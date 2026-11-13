"""Measure the tool calls of a burst of lookups, and what batching them saves.

    uv run scripts/bench_calls.py replay --vault <vault> [--pid N] [--gap 60] [--show]
    uv run scripts/bench_calls.py ab --vault <vault> --project <p> --prompt-file <file> \
        [--runs 5] [--out <dir>] [--model <m>] [--claude-bin claude] [--baseline-cmd "<cmd>"]

``replay`` takes the largest burst of ``search`` and ``read`` calls in the activity log and
runs it twice on a copy of the vault: as it was logged, and batched (single-word searches
with the same filters joined in one ``match="any"`` search; whole-note reads in
``read(notes=[...])``). ``ab`` runs a headless ``claude -p`` on the same prompt against two
servers, the baseline and this checkout, and counts the calls each run logs.

Read-only on the vault: ``activity.db`` is opened with ``mode=ro`` and the notes are copied
to a temporary directory (everything but dot entries). The index of the real vault is never
opened or created.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import statistics
import subprocess  # nosec B404
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from episteme.engine import BATCH_MAX, Engine
from episteme.errors import EpistemeError
from episteme.index import query_terms
from episteme.vault import INDEX_DIR

REPO = Path(__file__).resolve().parents[1]
BASELINE_CMD = "uvx --from git+ssh://git@github.com/Bajmein/episteme@v0.6.0 episteme"
FILTERS = ("path", "type", "tags", "status", "zone")
AB_TOOLS = ("search", "read", "context", "links")
RUN_TIMEOUT = 900

Call = tuple[str, dict[str, Any], str | None]


# -- shared ------------------------------------------------------------------


def activity_db(vault: Path) -> Path:
    return vault / INDEX_DIR / "activity.db"


def _rows(db: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    if not db.is_file():
        return []
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.DatabaseError:
        return []
    finally:
        conn.close()


def load_calls(vault: Path) -> list[sqlite3.Row]:
    """Every row of the vault's activity log, oldest first; empty if there is no log."""
    return _rows(activity_db(vault), "select * from calls order by id")


def copy_vault(src: Path, dst: Path) -> None:
    """Copy the notes and ``episteme.toml``, leaving out ``.index``, ``.git`` and the like."""
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(".*"))


def _args(row: sqlite3.Row) -> dict[str, Any]:
    try:
        args = json.loads(row["args"] or "{}")
    except ValueError:
        return {}
    return args if isinstance(args, dict) else {}


def _write(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()


# -- replay ------------------------------------------------------------------


def find_bursts(
    calls: list[sqlite3.Row], gap: float = 60, pid: int | None = None
) -> list[list[sqlite3.Row]]:
    """Runs of the model's successful search/read calls of one process, split at ``gap`` s."""
    by_pid: dict[int, list[sqlite3.Row]] = {}
    for row in calls:
        if row["hook_event"] is not None or not row["ok"]:
            continue
        if row["tool"] not in ("search", "read"):
            continue
        if pid is not None and row["pid"] != pid:
            continue
        by_pid.setdefault(row["pid"], []).append(row)
    bursts: list[list[sqlite3.Row]] = []
    for rows in by_pid.values():
        current: list[sqlite3.Row] = []
        last: datetime | None = None
        for row in rows:
            at = datetime.fromisoformat(row["at"])
            if last is not None and (at - last).total_seconds() > gap:
                bursts.append(current)
                current = []
            current.append(row)
            last = at
        if current:
            bursts.append(current)
    return bursts


def _single_word(args: dict[str, Any]) -> bool:
    query = args.get("query")
    return (
        isinstance(query, str)
        and args.get("match", "all") == "all"
        and len(query_terms(query)) == 1
    )


def _whole_read(args: dict[str, Any]) -> bool:
    return isinstance(args.get("note"), str) and not args.get("heading") and not args.get("lines")


def _filter_key(args: dict[str, Any], project: str | None) -> str:
    return json.dumps([[args.get(k) for k in FILTERS], project], ensure_ascii=False)


def batch_calls(calls: list[Call]) -> list[Call]:
    """The same lookups in fewer calls: OR searches and ``read(notes=[...])``."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for tool, args, project in calls:
        if tool == "search" and _single_word(args):
            groups.setdefault(_filter_key(args, project), []).append(args)
    whole = [args["note"] for tool, args, _ in calls if tool == "read" and _whole_read(args)]
    notes = list(dict.fromkeys(whole))
    out: list[Call] = []
    merged: set[str] = set()
    notes_done = False
    for tool, args, project in calls:
        if tool == "search" and _single_word(args):
            key = _filter_key(args, project)
            members = groups[key]
            if len(members) < 2:
                out.append((tool, args, project))
            elif key not in merged:
                merged.add(key)
                queries = list(dict.fromkeys(m["query"] for m in members))
                joined = {k: args[k] for k in FILTERS if k in args}
                joined["query"] = " ".join(queries)
                joined["match"] = "any"
                joined["limit"] = min(100, max(int(m.get("limit", 20)) for m in members))
                out.append((tool, joined, project))
        elif tool == "read" and _whole_read(args):
            if not notes_done:
                notes_done = True
                for i in range(0, len(notes), BATCH_MAX):
                    out.append(("read", {"notes": notes[i : i + BATCH_MAX]}, project))
        else:
            out.append((tool, args, project))
    return out


def _call(engine: Engine, tool: str, args: dict[str, Any], project: str | None) -> dict[str, Any]:
    if tool == "search":
        return engine.search(
            query=args.get("query"),
            path=args.get("path"),
            type=args.get("type"),
            tags=args.get("tags"),
            project=project,
            status=args.get("status"),
            limit=int(args.get("limit", 20)),
            zone=args.get("zone"),
            match=args.get("match", "all"),
        )
    if "notes" in args:
        return engine.read_many(args["notes"])
    note = args.get("note")  # a recorded call may lack it; the engine answers with its error
    return engine.read(note, args.get("heading"), args.get("lines"))  # ty: ignore[invalid-argument-type]


def run_calls(engine: Engine, calls: list[Call]) -> dict[str, Any]:
    """Run the calls and count, per tool, calls, characters of the JSON answer and ms."""
    stats: dict[str, Any] = {
        tool: {"calls": 0, "chars": 0, "ms": 0.0} for tool in ("search", "read")
    }
    search_paths: list[str] = []
    read_paths: list[str] = []
    errors = 0
    queue = list(calls)
    while queue:
        tool, args, project = queue.pop(0)
        start = time.perf_counter()
        try:
            with engine.session():
                res = _call(engine, tool, args, project)
        except EpistemeError:
            errors += 1
            continue
        entry = stats[tool]
        entry["calls"] += 1
        entry["chars"] += len(json.dumps(res, ensure_ascii=False))
        entry["ms"] += (time.perf_counter() - start) * 1000
        if tool == "search":
            search_paths += [r["path"] for r in res["results"] + res.get("partial", [])]
        elif "notes" in res:
            read_paths += [n["path"] for n in res["notes"] if "path" in n]
            if res.get("pending"):
                queue.insert(0, ("read", {"notes": res["pending"]}, project))
        else:
            read_paths.append(res["path"])
    stats["errors"] = errors
    stats["search_paths"] = search_paths
    stats["read_paths"] = list(dict.fromkeys(read_paths))
    return stats


def replay(vault: Path, pid: int | None = None, gap: float = 60) -> dict[str, Any] | None:
    """Replay the largest burst as logged and batched; None if the log has no burst."""
    bursts = find_bursts(load_calls(vault), gap, pid)
    if not bursts:
        return None
    burst = max(bursts, key=len)
    calls: list[Call] = [(row["tool"], _args(row), row["project"]) for row in burst]
    batched = batch_calls(calls)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "vault"
        copy_vault(vault, copy)
        engine = Engine(copy)
        try:
            engine.index.refresh()
            run_calls(engine, calls)  # warm-up: both measured passes read warm pages
            base = run_calls(engine, calls)
            batch = run_calls(engine, batched)
        finally:
            engine.index.close()
    batch_found = set(batch["search_paths"])
    return {
        "pid": burst[0]["pid"],
        "start": burst[0]["at"],
        "end": burst[-1]["at"],
        "logged": {
            tool: {
                "calls": sum(1 for r in burst if r["tool"] == tool),
                "chars": sum(r["chars"] or 0 for r in burst if r["tool"] == tool),
                "ms": sum(r["ms"] or 0 for r in burst if r["tool"] == tool),
            }
            for tool in ("search", "read")
        },
        "base": base,
        "batch": batch,
        "base_calls": calls,
        "batch_calls": batched,
        "read_notes": len(base["read_paths"]),
        "read_in_batch_search": sum(1 for p in base["read_paths"] if p in batch_found),
    }


def _total(stats: dict[str, Any], key: str) -> float:
    return stats["search"][key] + stats["read"][key]


def render_replay(result: dict[str, Any], show: bool) -> str:
    base, batch, logged = result["base"], result["batch"], result["logged"]
    out = [
        "# Replay de una ráfaga",
        "",
        f"Ráfaga del pid {result['pid']}, de {result['start']} a {result['end']}: "
        f"{int(_total(logged, 'calls'))} llamadas registradas "
        f"({int(_total(logged, 'chars'))} caracteres, {int(_total(logged, 'ms'))} ms).",
        "",
        "| Tool | Llamadas base | Llamadas lote | Caracteres base | Caracteres lote "
        "| ms base | ms lote |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tool in ("search", "read"):
        b, n = base[tool], batch[tool]
        out.append(
            f"| {tool} | {b['calls']} | {n['calls']} | {b['chars']} | {n['chars']} "
            f"| {b['ms']:.0f} | {n['ms']:.0f} |"
        )
    out.append(
        f"| total | {_total(base, 'calls')} | {_total(batch, 'calls')} "
        f"| {_total(base, 'chars')} | {_total(batch, 'chars')} "
        f"| {_total(base, 'ms'):.0f} | {_total(batch, 'ms'):.0f} |"
    )
    base_found, batch_found = set(base["search_paths"]), set(batch["search_paths"])
    out += [
        "",
        f"- Filas de `search`: {len(base['search_paths'])} en base "
        f"({len(base_found)} rutas únicas) y {len(batch['search_paths'])} en lote "
        f"({len(batch_found)} rutas únicas); {len(base_found & batch_found)} rutas de la base "
        "siguen en el lote.",
        f"- Notas leídas en la ráfaga: {result['read_notes']}; "
        f"{result['read_in_batch_search']} aparecen en los resultados del `search` por lote.",
        f"- Llamadas que fallaron al repetirlas: {base['errors']} en base, "
        f"{batch['errors']} en lote.",
        "",
    ]
    if show:
        for title, key in (("Llamadas base", "base_calls"), ("Llamadas lote", "batch_calls")):
            out += [f"## {title}", ""]
            for tool, args, project in result[key]:
                shown = dict(args) if project is None else {**args, "project": project}
                out.append(f"- `{tool}` {json.dumps(shown, ensure_ascii=False)}")
            out.append("")
        out += ["## Notas leídas", ""]
        out += [f"- {p}{'' if p in batch_found else ' (no sale en el lote)'}"
                for p in base["read_paths"]]  # fmt: skip
        out.append("")
    return "\n".join(out)


# -- agent A/B ---------------------------------------------------------------


def summarize(db: Path, after_id: int = 0) -> list[dict[str, Any]]:
    """The calls logged after ``after_id``, grouped by server process, oldest group first."""
    groups: dict[int, dict[str, Any]] = {}
    for row in _rows(db, "select * from calls where id > ? order by id", (after_id,)):
        group = groups.setdefault(
            row["pid"],
            {
                "pid": row["pid"],
                "first_id": row["id"],
                "calls": {},
                "total": 0,
                "search_any": 0,
                "read_batch": 0,
                "chars": 0,
                "ms": 0,
                "hooks": 0,
            },
        )
        if row["hook_event"] is not None:
            group["hooks"] += 1
            continue
        tool = row["tool"]
        args = _args(row)
        group["calls"][tool] = group["calls"].get(tool, 0) + 1
        group["total"] += 1
        group["chars"] += row["chars"] or 0
        group["ms"] += row["ms"] or 0
        if tool == "search" and args.get("match") == "any":
            group["search_any"] += 1
        if tool == "read" and "notes" in args:
            group["read_batch"] += 1
    return sorted(groups.values(), key=lambda g: g["first_id"])


def _max_id(db: Path) -> int:
    rows = _rows(db, "select coalesce(max(id), 0) as m from calls")
    return rows[0]["m"] if rows else 0


def _merge(groups: list[dict[str, Any]]) -> dict[str, Any]:
    run: dict[str, Any] = {
        "calls": {}, "total": 0, "search_any": 0, "read_batch": 0, "chars": 0, "ms": 0, "hooks": 0
    }  # fmt: skip
    for group in groups:
        for tool, count in group["calls"].items():
            run["calls"][tool] = run["calls"].get(tool, 0) + count
        for key in ("total", "search_any", "read_batch", "chars", "ms", "hooks"):
            run[key] += group[key]
    return run


def run_ab(
    vault: Path,
    project: str,
    prompt: str,
    runs: int,
    out: Path,
    model: str | None = None,
    claude_bin: str = "claude",
    baseline_cmd: str = BASELINE_CMD,
) -> list[dict[str, Any]]:
    """Alternate ``runs`` headless agents per variant; one dict per run."""
    out.mkdir(parents=True, exist_ok=True)
    cwd = out / "cwd"
    cwd.mkdir(exist_ok=True)
    commands = {
        "base": shlex.split(baseline_cmd),
        "new": ["uv", "run", "--directory", str(REPO), "episteme"],
    }
    configs: dict[str, Path] = {}
    copies: dict[str, Path] = {}
    for variant, command in commands.items():
        copy = out / variant / "vault"
        copy_vault(vault, copy)
        engine = Engine(copy)
        try:
            engine.index.refresh()
        finally:
            engine.index.close()
        server = {
            "command": command[0],
            "args": [*command[1:], "--vault", str(copy), "--project", project],
        }
        cfg = out / f"{variant}.mcp.json"
        cfg.write_text(
            json.dumps({"mcpServers": {"episteme": server}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="",
        )
        configs[variant], copies[variant] = cfg, copy
    allowed = [f"mcp__episteme__{tool}" for tool in AB_TOOLS]
    results: list[dict[str, Any]] = []
    for n in range(1, runs + 1):
        for variant in ("base", "new"):
            db = activity_db(copies[variant])
            before = _max_id(db)
            cmd = [
                claude_bin, "-p", prompt,
                "--mcp-config", str(configs[variant]),
                "--strict-mcp-config",
                "--allowedTools", *allowed,
                "--output-format", "json",
                *(["--model", model] if model else []),
            ]  # fmt: skip
            run: dict[str, Any] = {"variant": variant, "n": n, "note": ""}
            start = time.perf_counter()
            try:
                proc = subprocess.run(  # nosec B603
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=RUN_TIMEOUT,
                    env=os.environ,
                )
                stdout = proc.stdout or ""
                if proc.returncode != 0:
                    run["note"] = f"claude salió con código {proc.returncode}"
                    (out / f"{variant}-{n}.stderr.txt").write_text(
                        proc.stderr or "", encoding="utf-8", newline=""
                    )
            except subprocess.TimeoutExpired:
                stdout = ""
                run["note"] = f"sin respuesta en {RUN_TIMEOUT} s"
            run["seconds"] = round(time.perf_counter() - start)
            (out / f"{variant}-{n}.json").write_text(stdout, encoding="utf-8", newline="")
            try:
                answer = json.loads(stdout)
            except ValueError:
                answer = {}
            if not isinstance(answer, dict):
                answer = {}
            run["turns"] = answer.get("num_turns")
            run["cost"] = answer.get("total_cost_usd")
            run["answer_chars"] = len(answer.get("result") or "")
            run.update(_merge(summarize(db, before)))
            if run["total"] == 0 and not run["note"]:
                run["note"] = "sin llamadas registradas"
            results.append(run)
            print(
                f"{variant}-{n}: {run['total']} llamadas, {run['seconds']} s {run['note']}",
                file=sys.stderr,
            )
    return results


def _median(values: list[Any]) -> str:
    numbers = [v for v in values if isinstance(v, (int, float))]
    if not numbers:
        return "–"
    med = statistics.median(numbers)
    return f"{med:.2f}" if any(isinstance(v, float) for v in numbers) else f"{med:g}"


def render_ab(results: list[dict[str, Any]], out: Path) -> str:
    cols = (
        "| Corrida | Llamadas | search | read | context | links | search_any | read_batch "
        "| Caracteres | Turnos | Coste (USD) | Nota |"
    )
    lines = ["# A/B con agentes", "", cols, "|" + " --- |" * 12]

    def cells(run: dict[str, Any]) -> list[Any]:
        calls = run["calls"]
        return [
            run["total"], calls.get("search", 0), calls.get("read", 0), calls.get("context", 0),
            calls.get("links", 0), run["search_any"], run["read_batch"], run["chars"],
            run["turns"], run["cost"],
        ]  # fmt: skip

    for run in results:
        shown = ["–" if v is None else (f"{v:.2f}" if isinstance(v, float) else v)
                 for v in cells(run)]  # fmt: skip
        lines.append(
            f"| {run['variant']}-{run['n']} | " + " | ".join(str(v) for v in shown)
            + f" | {run['note']} |"
        )  # fmt: skip
    medians: dict[str, float] = {}
    for variant in ("base", "new"):
        rows = [cells(r) for r in results if r["variant"] == variant]
        if not rows:
            continue
        columns = list(zip(*rows, strict=True))
        lines.append(
            f"| **mediana {variant}** | " + " | ".join(_median(list(c)) for c in columns) + " | |"
        )
        medians[variant] = statistics.median(columns[0])
    lines.append("")
    if medians.get("base"):
        change = (medians.get("new", 0) - medians["base"]) / medians["base"]
        lines.append(
            f"Mediana de llamadas del modelo por corrida: {medians['base']:g} en base y "
            f"{medians.get('new', 0):g} en new ({change:+.0%})."
        )
    lines += ["", f"Respuestas y configuración: {out}", ""]
    return "\n".join(lines)


# -- command line ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("replay", help="replay the largest logged burst, as it was and batched")
    rp.add_argument("--vault", required=True, type=Path)
    rp.add_argument("--pid", type=int, default=None, help="only bursts of this server process")
    rp.add_argument("--gap", type=float, default=60, help="seconds of silence that end a burst")
    rp.add_argument("--show", action="store_true", help="print the queries and paths (private)")
    ab = sub.add_parser("ab", help="run headless agents against the baseline and this checkout")
    ab.add_argument("--vault", required=True, type=Path)
    ab.add_argument("--project", required=True)
    ab.add_argument("--prompt-file", required=True, type=Path)
    ab.add_argument("--runs", type=int, default=5, help="runs per variant")
    ab.add_argument("--out", type=Path, default=None)
    ab.add_argument("--model", default=None)
    ab.add_argument("--claude-bin", default="claude")
    ab.add_argument("--baseline-cmd", default=BASELINE_CMD)
    args = ap.parse_args(argv)
    vault = args.vault.expanduser().resolve()
    if not (vault / "episteme.toml").is_file():
        print(f"{vault} is not a vault: it has no episteme.toml.", file=sys.stderr)
        return 1
    try:
        if args.command == "replay":
            result = replay(vault, args.pid, args.gap)
            if result is None:
                print(
                    "no burst of search/read calls in the activity log of this vault.",
                    file=sys.stderr,
                )
                return 1
            _write(render_replay(result, args.show))
            return 0
        prompt = args.prompt_file.expanduser().read_text(encoding="utf-8").strip()
        out = args.out or (
            Path.home() / ".cache" / "episteme-bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
        )
        out = out.expanduser().resolve()
        results = run_ab(
            vault, args.project, prompt, args.runs, out,
            args.model, args.claude_bin, args.baseline_cmd,
        )  # fmt: skip
        _write(render_ab(results, out))
        return 0
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
