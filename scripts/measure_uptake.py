"""Measure whether the memories episteme delivers get read, from the activity log.

    uv run scripts/measure_uptake.py --vault <vault> [--project <p>] [--days 30] \
        [--min-deliveries 3] [--old-days 90]

Read-only: opens ``<vault>/.index/activity.db`` with ``mode=ro`` and reads the ``created``
date of each memory from the notes; it never opens or creates the index and writes nothing.

Per memory (``memory/...``) it counts, over the last ``--days`` days:

- deliveries by hook (rows with ``hook_event``, ``ok=1``): ``context`` (the welcome and the
  task recall; a row does not tell them apart, so they are counted together, and ``welcome``
  is the subset with ``args.mode=welcome``), ``surface`` and ``constraints``;
- agent reads (``tool=read`` without ``hook_event``; path in ``args.note``, ``args.notes`` or
  ``paths``), and how many happened in the same session after a delivery of that memory;
- appearances in agent ``search`` calls (without ``hook_event``).

The summary answers: (a) share of deliveries followed by a read, (b) memories delivered N times
and never read, (c) old memories with and without reads, (d) sessions that read but never called
``remember``/``revise``, (e) agent searches with no results, by query.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from episteme.errors import NOT_FOUND, EpistemeError
from episteme.markdown import parse
from episteme.vault import INDEX_DIR, Vault

DELIVERY_TOOLS = ("context", "surface", "constraints")
WRITE_TOOLS = ("remember", "revise")
TOP_EMPTY = 20


def _json(text: str | None, default):
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _norm(path: str) -> str:
    path = path.replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def _open_ro(vault_root: Path) -> sqlite3.Connection:
    db = Path(vault_root) / INDEX_DIR / "activity.db"
    if not db.is_file():
        raise EpistemeError(
            NOT_FOUND, f"no activity log at {db}. Use the vault for a while, or check --vault."
        )
    return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)


def _created(vault: Vault, zone: str) -> dict[str, date]:
    """Memory path -> ``created`` date, from the notes' frontmatter."""
    out: dict[str, date] = {}
    for rel, _stat in vault.iter_notes():
        if not rel.startswith(zone + "/"):
            continue
        try:
            fm = parse((vault.root / rel).read_text(encoding="utf-8"), rel).frontmatter
        except (OSError, UnicodeDecodeError):
            continue
        c = fm.get("created")
        if isinstance(c, datetime):
            c = c.date()
        elif isinstance(c, str):
            try:
                c = date.fromisoformat(c[:10])
            except ValueError:
                c = None
        if isinstance(c, date):
            out[rel] = c
    return out


def _read_paths(args: dict, paths: list[str]) -> list[str]:
    found: list[str] = []
    note = args.get("note")
    if isinstance(note, str):
        found.append(note)
    notes = args.get("notes")
    if isinstance(notes, list):
        found += [n for n in notes if isinstance(n, str)]
    found += paths
    return list(dict.fromkeys(_norm(p) for p in found))


def measure(
    vault_root: Path,
    project: str | None = None,
    days: int = 30,
    min_deliveries: int = 3,
    old_days: int = 90,
    now: datetime | None = None,
) -> dict:
    """Per-memory counters and the figures of the five summary sections."""
    vault = Vault(Path(vault_root))
    zone_obj = vault.memory_zone
    zone = zone_obj.path if zone_obj else "memory"
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    conn = _open_ro(vault.root)
    try:
        sql = (
            "select session, tool, hook_event, args, paths, ok from calls where at >= ?"
            + (" and project = ?" if project else "")
            + " order by at, id"
        )
        rows = conn.execute(sql, (since, project) if project else (since,)).fetchall()
    finally:
        conn.close()

    def is_mem(p: str) -> bool:
        return p.startswith(zone + "/")

    stats: dict[str, Counter] = defaultdict(Counter)
    first_delivery: dict[tuple[str, str], int] = {}  # (session, path) -> row index
    reads_at: dict[tuple[str, str], list[int]] = defaultdict(list)
    deliveries: list[tuple[str | None, str, int]] = []
    sessions_read: set[str] = set()
    sessions_wrote: set[str] = set()
    empty: Counter = Counter()

    for i, (session, tool, hook, args_s, paths_s, ok) in enumerate(rows):
        args = _json(args_s, {})
        paths = [_norm(p) for p in _json(paths_s, []) if isinstance(p, str)]
        if tool in WRITE_TOOLS and session:
            sessions_wrote.add(session)
        if not ok:
            continue
        if hook and tool in DELIVERY_TOOLS:
            for p in dict.fromkeys(p for p in paths if is_mem(p)):
                stats[p][tool] += 1
                if tool == "context" and args.get("mode") == "welcome":
                    stats[p]["welcome"] += 1
                deliveries.append((session, p, i))
                if session:
                    first_delivery.setdefault((session, p), i)
        elif tool == "read" and not hook:
            mems = [p for p in _read_paths(args, paths) if is_mem(p)]
            for p in mems:
                stats[p]["reads"] += 1
                if session:
                    reads_at[(session, p)].append(i)
            if mems and session:
                sessions_read.add(session)
        elif tool == "search" and not hook:
            for p in dict.fromkeys(p for p in paths if is_mem(p)):
                stats[p]["searches"] += 1
            if not paths:
                key = (
                    str(args.get("query", "")),
                    str(args.get("match", "")),
                    str(args.get("zone", "")),
                )
                empty[key] += 1

    followed = 0
    for session, p, i in deliveries:
        if session and any(j > i for j in reads_at.get((session, p), ())):
            followed += 1
    for (session, p), idxs in reads_at.items():
        first = first_delivery.get((session, p))
        if first is not None:
            stats[p]["reads_after"] += sum(1 for j in idxs if j > first)

    def n_delivered(p: str) -> int:
        return sum(stats[p][t] for t in DELIVERY_TOOLS)

    never_read = sorted(
        (p for p in stats if n_delivered(p) >= min_deliveries and not stats[p]["reads"]),
        key=lambda p: (-n_delivered(p), p),
    )
    created = _created(vault, zone)
    cutoff = now.date() - timedelta(days=old_days)
    old = [p for p, c in created.items() if c < cutoff]
    old_read = [p for p in old if stats[p]["reads"]]
    return {
        "days": days,
        "project": project,
        "rows": len(rows),
        "stats": stats,
        "deliveries": len(deliveries),
        "followed": followed,
        "min_deliveries": min_deliveries,
        "never_read": [(p, n_delivered(p)) for p in never_read],
        "old_days": old_days,
        "old_total": len(old),
        "old_read": sorted(old_read),
        "old_unread": sorted(set(old) - set(old_read)),
        "sessions_read": len(sessions_read),
        "sessions_no_write": sorted(sessions_read - sessions_wrote),
        "empty": sorted(empty.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_EMPTY],
        "empty_total": sum(empty.values()),
    }


def render(r: dict) -> str:
    scope = f"proyecto {r['project']}" if r["project"] else "todos los proyectos"
    out = [
        "# Medición de uso de las memorias",
        "",
        f"- Ventana: últimos {r['days']} días ({scope}); {r['rows']} llamadas",
        "- `context` junta la bienvenida y el recall (una fila no los distingue); "
        "`welcome` es el subconjunto con `mode=welcome`",
        "",
        "## Por memoria",
        "",
        "| memoria | context | welcome | surface | constraints | lecturas | tras entrega "
        "| en search |",
        "|---|---|---|---|---|---|---|---|",
    ]
    stats = r["stats"]

    def order(p: str) -> tuple[int, str]:
        s = stats[p]
        return (-(s["context"] + s["surface"] + s["constraints"] + s["reads"]), p)

    for p in sorted(stats, key=order):
        s = stats[p]
        out.append(
            f"| {p} | {s['context']} | {s['welcome']} | {s['surface']} | {s['constraints']} "
            f"| {s['reads']} | {s['reads_after']} | {s['searches']} |"
        )
    if not stats:
        out.append("| (sin actividad sobre memorias) | | | | | | | |")
    d, f = r["deliveries"], r["followed"]
    pct = f"{f / d:.1%}" if d else "n/a"
    out += [
        "",
        "## Resumen",
        "",
        "### (a) Entregas seguidas de lectura",
        "",
        f"{f} de {d} entregas ({pct}) tienen una lectura de esa memoria después, en la misma "
        "sesión. Las entregas sin sesión no se pueden emparejar y cuentan como no seguidas.",
        "",
        f"### (b) Entregadas {r['min_deliveries']} veces o más y nunca leídas",
        "",
    ]
    out += [f"- {p} ({n} entregas)" for p, n in r["never_read"]] or ["- (ninguna)"]
    out += [
        "",
        f"### (c) Memorias de más de {r['old_days']} días",
        "",
        f"{r['old_total']} memorias: {len(r['old_read'])} con lectura, "
        f"{len(r['old_unread'])} sin lectura en la ventana.",
        "",
    ]
    out += [f"- sin lectura: {p}" for p in r["old_unread"]]
    out += [
        "",
        "### (d) Sesiones con lecturas y sin remember/revise",
        "",
        f"{len(r['sessions_no_write'])} de {r['sessions_read']} sesiones con lecturas de "
        "memorias.",
        "",
        f"### (e) Búsquedas del agente sin resultados ({r['empty_total']})",
        "",
    ]
    out += [
        f"- {n}x `{q}` (match={m or '-'}, zone={z or '-'})" for (q, m, z), n in r["empty"]
    ] or ["- (ninguna)"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--project", default=None, help="only calls of this project")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-deliveries", type=int, default=3)
    ap.add_argument("--old-days", type=int, default=90)
    args = ap.parse_args(argv)
    try:
        result = measure(args.vault, args.project, args.days, args.min_deliveries, args.old_days)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1
    sys.stdout.buffer.write(render(result).encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
