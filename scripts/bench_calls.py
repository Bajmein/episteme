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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from episteme.engine import BATCH_MAX, Engine
from episteme.errors import EpistemeError
from episteme.filters import SearchFilters
from episteme.index import query_terms
from episteme.vault import INDEX_DIR

REPO = Path(__file__).resolve().parents[1]
BASELINE_CMD = "uvx --from git+https://github.com/Bajmein/episteme@v0.6.0 episteme"
FILTERS = ("path", "type", "tags", "status", "zone")
AB_TOOLS = ("search", "read", "context")
RUN_TIMEOUT = 900
BURST_GAP_SECONDS = 60
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100
AB_COLUMNS = (
    "Corrida", "Llamadas", "search", "read", "context", "search_any", "read_batch",
    "Caracteres", "Turnos", "Coste (USD)", "Nota",
)  # fmt: skip

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


def _is_model_lookup(row: sqlite3.Row, pid: int | None) -> bool:
    """Whether the row is a successful, non-hook search/read call (of ``pid`` if given)."""
    if row["hook_event"] is not None or not row["ok"]:
        return False
    if row["tool"] not in ("search", "read"):
        return False
    return pid is None or row["pid"] == pid


def _split_bursts(rows: list[sqlite3.Row], gap: float) -> list[list[sqlite3.Row]]:
    """Split the rows of one process wherever two calls are more than ``gap`` s apart."""
    bursts: list[list[sqlite3.Row]] = []
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


def find_bursts(
    calls: list[sqlite3.Row], gap: float = BURST_GAP_SECONDS, pid: int | None = None
) -> list[list[sqlite3.Row]]:
    """Runs of the model's successful search/read calls of one process, split at ``gap`` s."""
    by_pid: dict[int, list[sqlite3.Row]] = {}
    for row in calls:
        if _is_model_lookup(row, pid):
            by_pid.setdefault(row["pid"], []).append(row)
    return [burst for rows in by_pid.values() for burst in _split_bursts(rows, gap)]


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


@dataclass
class _BatchState:
    """What ``batch_calls`` knows while it walks the calls once."""

    groups: dict[str, list[dict[str, Any]]]
    notes: list[str]
    merged: set[str]
    notes_done: bool = False


def _search_groups(calls: list[Call]) -> dict[str, list[dict[str, Any]]]:
    """Single-word searches grouped by their filters and project."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for tool, args, project in calls:
        if tool == "search" and _single_word(args):
            groups.setdefault(_filter_key(args, project), []).append(args)
    return groups


def _whole_notes(calls: list[Call]) -> list[str]:
    """The notes read whole, without repeats, in call order."""
    whole = [args["note"] for tool, args, _ in calls if tool == "read" and _whole_read(args)]
    return list(dict.fromkeys(whole))


def _merge_search(members: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    """One ``match="any"`` search for the members, with the filters of ``args``."""
    queries = list(dict.fromkeys(m["query"] for m in members))
    joined = {k: args[k] for k in FILTERS if k in args}
    joined["query"] = " ".join(queries)
    joined["match"] = "any"
    limit = max(int(m.get("limit", SEARCH_LIMIT_DEFAULT)) for m in members)
    joined["limit"] = min(SEARCH_LIMIT_MAX, limit)
    return joined


def _read_batches(notes: list[str]) -> list[dict[str, Any]]:
    """The notes split into ``read(notes=[...])`` arguments of at most ``BATCH_MAX``."""
    return [{"notes": notes[i : i + BATCH_MAX]} for i in range(0, len(notes), BATCH_MAX)]


def _batch_one(call: Call, state: _BatchState) -> list[Call]:
    """The calls that replace ``call`` in the batched list (none if it was merged earlier)."""
    tool, args, project = call
    if tool == "search" and _single_word(args):
        key = _filter_key(args, project)
        members = state.groups[key]
        if len(members) < 2:
            return [call]
        if key in state.merged:
            return []
        state.merged.add(key)
        return [(tool, _merge_search(members, args), project)]
    if tool == "read" and _whole_read(args):
        if state.notes_done:
            return []
        state.notes_done = True
        return [("read", batch, project) for batch in _read_batches(state.notes)]
    return [call]


def batch_calls(calls: list[Call]) -> list[Call]:
    """The same lookups in fewer calls: OR searches and ``read(notes=[...])``."""
    state = _BatchState(_search_groups(calls), _whole_notes(calls), set())
    out: list[Call] = []
    for call in calls:
        out.extend(_batch_one(call, state))
    return out


def _call(engine: Engine, tool: str, args: dict[str, Any], project: str | None) -> dict[str, Any]:
    if tool == "search":
        return engine.search(
            args.get("query"),
            SearchFilters(
                path=args.get("path"),
                type=args.get("type"),
                tags=args.get("tags"),
                project=project,
                status=args.get("status"),
                zone=args.get("zone"),
            ),
            limit=int(args.get("limit", SEARCH_LIMIT_DEFAULT)),
            match=args.get("match", "all"),
        )
    if "notes" in args:
        return engine.read_many(args["notes"])
    note = args.get("note")  # a recorded call may lack it; the engine answers with its error
    return engine.read(note, args.get("heading"), args.get("lines"))  # ty: ignore[invalid-argument-type]


def _new_stats() -> dict[str, Any]:
    """Empty per-tool counters for ``run_calls``."""
    return {tool: {"calls": 0, "chars": 0, "ms": 0.0} for tool in ("search", "read")}


def _record(entry: dict[str, Any], res: dict[str, Any], start: float) -> None:
    """Add one answer to the counters of its tool."""
    entry["calls"] += 1
    entry["chars"] += len(json.dumps(res, ensure_ascii=False))
    entry["ms"] += (time.perf_counter() - start) * 1000


def _collect_paths(
    tool: str, res: dict[str, Any], search_paths: list[str], read_paths: list[str]
) -> list[str]:
    """Gather the paths of an answer; return the notes a batched read left pending."""
    if tool == "search":
        search_paths += [r["path"] for r in res["results"] + res.get("partial", [])]
        return []
    if "notes" not in res:
        read_paths.append(res["path"])
        return []
    read_paths += [n["path"] for n in res["notes"] if "path" in n]
    return res.get("pending") or []


def run_calls(engine: Engine, calls: list[Call]) -> dict[str, Any]:
    """Run the calls and count, per tool, calls, characters of the JSON answer and ms."""
    stats = _new_stats()
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
        _record(stats[tool], res, start)
        pending = _collect_paths(tool, res, search_paths, read_paths)
        if pending:
            queue.insert(0, ("read", {"notes": pending}, project))
    stats["errors"] = errors
    stats["search_paths"] = search_paths
    stats["read_paths"] = list(dict.fromkeys(read_paths))
    return stats


def _logged_totals(burst: list[sqlite3.Row]) -> dict[str, Any]:
    """Calls, characters and ms of the burst as logged, per tool."""
    return {
        tool: {
            "calls": sum(1 for r in burst if r["tool"] == tool),
            "chars": sum(r["chars"] or 0 for r in burst if r["tool"] == tool),
            "ms": sum(r["ms"] or 0 for r in burst if r["tool"] == tool),
        }
        for tool in ("search", "read")
    }


def _run_on_copy(
    vault: Path, calls: list[Call], batched: list[Call]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run both call lists on a temporary copy of the vault: (base, batch) stats."""
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
    return base, batch


def replay(
    vault: Path, pid: int | None = None, gap: float = BURST_GAP_SECONDS
) -> dict[str, Any] | None:
    """Replay the largest burst as logged and batched; None if the log has no burst."""
    bursts = find_bursts(load_calls(vault), gap, pid)
    if not bursts:
        return None
    burst = max(bursts, key=len)
    calls: list[Call] = [(row["tool"], _args(row), row["project"]) for row in burst]
    batched = batch_calls(calls)
    base, batch = _run_on_copy(vault, calls, batched)
    batch_found = set(batch["search_paths"])
    return {
        "pid": burst[0]["pid"],
        "start": burst[0]["at"],
        "end": burst[-1]["at"],
        "logged": _logged_totals(burst),
        "base": base,
        "batch": batch,
        "base_calls": calls,
        "batch_calls": batched,
        "read_notes": len(base["read_paths"]),
        "read_in_batch_search": sum(1 for p in base["read_paths"] if p in batch_found),
    }


def _total(stats: dict[str, Any], key: str) -> float:
    return stats["search"][key] + stats["read"][key]


def _replay_table(base: dict[str, Any], batch: dict[str, Any]) -> list[str]:
    """The markdown table of calls, characters and ms, base against batch."""
    out = [
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
    return out


def _shown_call(call: Call) -> str:
    """One call as a markdown bullet."""
    tool, args, project = call
    shown = dict(args) if project is None else {**args, "project": project}
    return f"- `{tool}` {json.dumps(shown, ensure_ascii=False)}"


def _replay_calls_section(result: dict[str, Any]) -> list[str]:
    """The ``--show`` listing of the base and batched calls."""
    out: list[str] = []
    for title, key in (("Llamadas base", "base_calls"), ("Llamadas lote", "batch_calls")):
        out += [f"## {title}", ""]
        out += [_shown_call(call) for call in result[key]]
        out.append("")
    return out


def _replay_notes_section(base: dict[str, Any], batch_found: set[str]) -> list[str]:
    """The ``--show`` listing of the notes read."""
    out = ["## Notas leídas", ""]
    out += [f"- {p}{'' if p in batch_found else ' (no sale en el lote)'}"
            for p in base["read_paths"]]  # fmt: skip
    out.append("")
    return out


def render_replay(result: dict[str, Any], show: bool) -> str:
    base, batch, logged = result["base"], result["batch"], result["logged"]
    out = [
        "# Replay de una ráfaga",
        "",
        f"Ráfaga del pid {result['pid']}, de {result['start']} a {result['end']}: "
        f"{int(_total(logged, 'calls'))} llamadas registradas "
        f"({int(_total(logged, 'chars'))} caracteres, {int(_total(logged, 'ms'))} ms).",
        "",
        *_replay_table(base, batch),
    ]
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
        out += _replay_calls_section(result)
        out += _replay_notes_section(base, batch_found)
    return "\n".join(out)


# -- agent A/B ---------------------------------------------------------------


def _zero_counts() -> dict[str, Any]:
    """The counters shared by a group of calls and a merged run."""
    return {
        "calls": {}, "total": 0, "search_any": 0, "read_batch": 0, "chars": 0, "ms": 0, "hooks": 0
    }  # fmt: skip


def _new_group(row: sqlite3.Row) -> dict[str, Any]:
    """An empty group for the server process of ``row``."""
    return {"pid": row["pid"], "first_id": row["id"], **_zero_counts()}


def _is_search_any(tool: str, args: dict[str, Any]) -> bool:
    return tool == "search" and args.get("match") == "any"


def _is_batch_read(tool: str, args: dict[str, Any]) -> bool:
    return tool == "read" and "notes" in args


def _tally(group: dict[str, Any], row: sqlite3.Row) -> None:
    """Add one logged call to its group."""
    if row["hook_event"] is not None:
        group["hooks"] += 1
        return
    tool = row["tool"]
    args = _args(row)
    group["calls"][tool] = group["calls"].get(tool, 0) + 1
    group["total"] += 1
    group["chars"] += row["chars"] or 0
    group["ms"] += row["ms"] or 0
    if _is_search_any(tool, args):
        group["search_any"] += 1
    if _is_batch_read(tool, args):
        group["read_batch"] += 1


def summarize(db: Path, after_id: int = 0) -> list[dict[str, Any]]:
    """The calls logged after ``after_id``, grouped by server process, oldest group first."""
    groups: dict[int, dict[str, Any]] = {}
    for row in _rows(db, "select * from calls where id > ? order by id", (after_id,)):
        if row["pid"] not in groups:
            groups[row["pid"]] = _new_group(row)
        _tally(groups[row["pid"]], row)
    return sorted(groups.values(), key=lambda g: g["first_id"])


def _max_id(db: Path) -> int:
    rows = _rows(db, "select coalesce(max(id), 0) as m from calls")
    return rows[0]["m"] if rows else 0


def _merge(groups: list[dict[str, Any]]) -> dict[str, Any]:
    run = _zero_counts()
    for group in groups:
        for tool, count in group["calls"].items():
            run["calls"][tool] = run["calls"].get(tool, 0) + count
        for key in ("total", "search_any", "read_batch", "chars", "ms", "hooks"):
            run[key] += group[key]
    return run


class _Variant(NamedTuple):
    """A server under test: its name and the command that starts it."""

    name: str
    command: list[str]


def _prepare_variant(
    vault: Path, out: Path, variant: _Variant, project: str
) -> tuple[Path, Path]:
    """Copy and index the vault for a variant and write its MCP config: (config, copy)."""
    name, command = variant
    copy = out / name / "vault"
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
    cfg = out / f"{name}.mcp.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"episteme": server}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="",
    )
    return cfg, copy


def _agent_command(claude_bin: str, prompt: str, config: Path, model: str | None) -> list[str]:
    allowed = [f"mcp__episteme__{tool}" for tool in AB_TOOLS]
    return [
        claude_bin, "-p", prompt,
        "--mcp-config", str(config),
        "--strict-mcp-config",
        "--allowedTools", *allowed,
        "--output-format", "json",
        *(["--model", model] if model else []),
    ]  # fmt: skip


def _run_agent(cmd: list[str], cwd: Path, out: Path, name: str) -> tuple[str, str]:
    """Run one headless agent: (stdout, note), with the note empty when it ended well."""
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
    except subprocess.TimeoutExpired:
        return "", f"sin respuesta en {RUN_TIMEOUT} s"
    note = ""
    if proc.returncode != 0:
        note = f"claude salió con código {proc.returncode}"
        (out / f"{name}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8", newline="")
    return proc.stdout or "", note


def _parse_answer(stdout: str) -> dict[str, Any]:
    try:
        answer = json.loads(stdout)
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}


@dataclass(frozen=True)
class AbOptions:
    """The knobs of ``run_ab`` besides the vault, project, prompt and output directory."""

    runs: int
    model: str | None = None
    claude_bin: str = "claude"
    baseline_cmd: str = BASELINE_CMD


def _measure_run(
    variant: str, n: int, cmd: list[str], cwd: Path, out: Path, db: Path
) -> dict[str, Any]:
    """Run one headless agent and read what it logged in ``db`` into a result dict."""
    before = _max_id(db)
    start = time.perf_counter()
    stdout, note = _run_agent(cmd, cwd, out, f"{variant}-{n}")
    run: dict[str, Any] = {"variant": variant, "n": n, "note": note}
    run["seconds"] = round(time.perf_counter() - start)
    (out / f"{variant}-{n}.json").write_text(stdout, encoding="utf-8", newline="")
    answer = _parse_answer(stdout)
    run["turns"] = answer.get("num_turns")
    run["cost"] = answer.get("total_cost_usd")
    run["answer_chars"] = len(answer.get("result") or "")
    run.update(_merge(summarize(db, before)))
    if run["total"] == 0 and not run["note"]:
        run["note"] = "sin llamadas registradas"
    return run


def run_ab(
    vault: Path, project: str, prompt: str, out: Path, options: AbOptions
) -> list[dict[str, Any]]:
    """Alternate ``options.runs`` headless agents per variant; one dict per run."""
    out.mkdir(parents=True, exist_ok=True)
    cwd = out / "cwd"
    cwd.mkdir(exist_ok=True)
    variants = [
        _Variant("base", shlex.split(options.baseline_cmd)),
        _Variant("new", ["uv", "run", "--directory", str(REPO), "episteme"]),
    ]
    prepared = {v.name: _prepare_variant(vault, out, v, project) for v in variants}
    results: list[dict[str, Any]] = []
    for n in range(1, options.runs + 1):
        for variant in variants:
            config, copy = prepared[variant.name]
            cmd = _agent_command(options.claude_bin, prompt, config, options.model)
            run = _measure_run(variant.name, n, cmd, cwd, out, activity_db(copy))
            results.append(run)
            print(
                f"{variant.name}-{n}: {run['total']} llamadas, {run['seconds']} s {run['note']}",
                file=sys.stderr,
            )
    return results


def _median(values: list[Any]) -> str:
    numbers = [v for v in values if isinstance(v, (int, float))]
    if not numbers:
        return "–"
    med = statistics.median(numbers)
    return f"{med:.2f}" if any(isinstance(v, float) for v in numbers) else f"{med:g}"


def _run_cells(run: dict[str, Any]) -> list[Any]:
    """The numeric cells of one run, in the order of ``AB_COLUMNS`` after the name."""
    calls = run["calls"]
    return [
        run["total"], calls.get("search", 0), calls.get("read", 0), calls.get("context", 0),
        run["search_any"], run["read_batch"], run["chars"],
        run["turns"], run["cost"],
    ]  # fmt: skip


def _fmt_cell(value: Any) -> Any:
    """A table cell: a dash for None, two decimals for floats."""
    if value is None:
        return "–"
    return f"{value:.2f}" if isinstance(value, float) else value


def _run_line(run: dict[str, Any]) -> str:
    """The table row of one run."""
    shown = [_fmt_cell(v) for v in _run_cells(run)]
    return (
        f"| {run['variant']}-{run['n']} | " + " | ".join(str(v) for v in shown)
        + f" | {run['note']} |"
    )  # fmt: skip


def _median_line(variant: str, rows: list[list[Any]]) -> str:
    """The table row with the median of each column of ``rows``."""
    columns = list(zip(*rows, strict=True))
    return f"| **mediana {variant}** | " + " | ".join(_median(list(c)) for c in columns) + " | |"


def render_ab(results: list[dict[str, Any]], out: Path) -> str:
    cols = "| " + " | ".join(AB_COLUMNS) + " |"
    lines = ["# A/B con agentes", "", cols, "|" + " --- |" * len(AB_COLUMNS)]
    lines += [_run_line(run) for run in results]
    medians: dict[str, float] = {}
    for variant in ("base", "new"):
        rows = [_run_cells(r) for r in results if r["variant"] == variant]
        if not rows:
            continue
        lines.append(_median_line(variant, rows))
        medians[variant] = statistics.median(row[0] for row in rows)
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


def _main_replay(vault: Path, args: argparse.Namespace) -> int:
    result = replay(vault, args.pid, args.gap)
    if result is None:
        print("no burst of search/read calls in the activity log of this vault.", file=sys.stderr)
        return 1
    _write(render_replay(result, args.show))
    return 0


def _main_ab(vault: Path, args: argparse.Namespace) -> int:
    prompt = args.prompt_file.expanduser().read_text(encoding="utf-8").strip()
    out = args.out or (
        Path.home() / ".cache" / "episteme-bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    out = out.expanduser().resolve()
    options = AbOptions(args.runs, args.model, args.claude_bin, args.baseline_cmd)
    results = run_ab(vault, args.project, prompt, out, options)
    _write(render_ab(results, out))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("replay", help="replay the largest logged burst, as it was and batched")
    rp.add_argument("--vault", required=True, type=Path)
    rp.add_argument("--pid", type=int, default=None, help="only bursts of this server process")
    rp.add_argument(
        "--gap", type=float, default=BURST_GAP_SECONDS, help="seconds of silence that end a burst"
    )
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
            return _main_replay(vault, args)
        return _main_ab(vault, args)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
