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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from episteme.errors import NOT_FOUND, EpistemeError
from episteme.markdown import parse
from episteme.vault import INDEX_DIR, Vault

DELIVERY_TOOLS = ("context", "surface", "constraints")
WRITE_TOOLS = ("remember", "revise")
TOP_EMPTY = 20
DEFAULT_DAYS = 30
DEFAULT_MIN_DELIVERIES = 3
DEFAULT_OLD_DAYS = 90

_ROWS_SQL = (
    "select session, tool, hook_event, args, paths, ok, project from calls"
    " where at >= ? order by at, id"
)


class Row(NamedTuple):
    """One row of the ``calls`` table, in the column order of ``_ROWS_SQL``."""

    session: str | None
    tool: str
    hook: str | None
    args: str | None
    paths: str | None
    ok: int
    project: str | None


@dataclass
class _Scan:
    """What one pass over the rows collects; mutated only by the ``_record_*`` helpers."""

    zone: str
    stats: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    first_delivery: dict[tuple[str, str], int] = field(default_factory=dict)  # -> row index
    reads_at: dict[tuple[str, str], list[int]] = field(default_factory=lambda: defaultdict(list))
    deliveries: list[tuple[str | None, str, int]] = field(default_factory=list)
    sessions_read: set[str] = field(default_factory=set)
    sessions_wrote: set[str] = field(default_factory=set)
    empty: Counter = field(default_factory=Counter)


class _Call(NamedTuple):
    """One decoded row: its position, JSON args and normalised result paths."""

    row: Row
    index: int
    args: dict
    paths: list[str]


def _json[T](text: str | None, default: T) -> T:
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
    try:
        return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise EpistemeError(NOT_FOUND, f"cannot open {db} read-only: {e}. Check --vault.") from e


def _created_date(raw: object) -> date | None:
    """A frontmatter ``created`` value as a date, or None if it is not one."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _note_created(vault: Vault, rel: str) -> date | None:
    """The ``created`` date of one note, or None if unreadable or missing."""
    try:
        fm = parse((vault.root / rel).read_text(encoding="utf-8"), rel).frontmatter
    except (OSError, UnicodeDecodeError):
        return None
    return _created_date(fm.get("created"))


def _created(vault: Vault, zone: str) -> dict[str, date]:
    """Memory path -> ``created`` date, from the notes' frontmatter."""
    out: dict[str, date] = {}
    for rel, _stat in vault.iter_notes():
        if not rel.startswith(zone + "/"):
            continue
        created = _note_created(vault, rel)
        if created is not None:
            out[rel] = created
    return out


def _asked_notes(args: dict) -> list[str]:
    """Normalised note names the call asked for (``note`` and ``notes`` args)."""
    asked: list[str] = []
    note = args.get("note")
    if isinstance(note, str):
        asked.append(note)
    notes = args.get("notes")
    if isinstance(notes, list):
        asked += [n for n in notes if isinstance(n, str)]
    return [_norm(n) for n in asked]


def _read_paths(args: dict, paths: list[str]) -> list[str]:
    """Notes the agent asked for: path-like args, else the leading result paths.

    ``paths`` is scraped from the result text, so it can also hold linked notes; when the
    request used bare names, only as many leading paths as names are trusted.
    """
    asked = _asked_notes(args)
    if asked and all(n.endswith(".md") for n in asked):
        return list(dict.fromkeys(asked))
    return list(dict.fromkeys(paths[: len(asked) or len(paths)]))


def _load_rows(vault_root: Path, since: str, project: str | None) -> list[Row]:
    conn = _open_ro(vault_root)
    try:
        rows = [Row(*r) for r in conn.execute(_ROWS_SQL, (since,)).fetchall()]
    finally:
        conn.close()
    if project:
        # Agent calls often carry no project: keep every call of a session that has one.
        mine = {r.session for r in rows if r.project == project and r.session}
        rows = [r for r in rows if r.project == project or (r.session and r.session in mine)]
    return rows


def _in_zone(scan: _Scan, paths: list[str]) -> list[str]:
    """The distinct paths that live in the memory zone, in order."""
    return [p for p in dict.fromkeys(paths) if p.startswith(scan.zone + "/")]


def _record_delivery(scan: _Scan, call: _Call) -> None:
    row, i = call.row, call.index
    for p in _in_zone(scan, call.paths):
        scan.stats[p][row.tool] += 1
        if row.tool == "context" and call.args.get("mode") == "welcome":
            scan.stats[p]["welcome"] += 1
        scan.deliveries.append((row.session, p, i))
        if row.session:
            scan.first_delivery.setdefault((row.session, p), i)


def _record_read(scan: _Scan, call: _Call) -> None:
    session = call.row.session
    mems = [p for p in _read_paths(call.args, call.paths) if p.startswith(scan.zone + "/")]
    for p in mems:
        scan.stats[p]["reads"] += 1
        if session:
            scan.reads_at[(session, p)].append(call.index)
    if mems and session:
        scan.sessions_read.add(session)


def _record_search(scan: _Scan, call: _Call) -> None:
    for p in _in_zone(scan, call.paths):
        scan.stats[p]["searches"] += 1
    if not call.paths:
        args = call.args
        key = (str(args.get("query", "")), str(args.get("match", "")), str(args.get("zone", "")))
        scan.empty[key] += 1


def _decode(row: Row, index: int) -> _Call:
    """Parse the JSON columns of a row into a ``_Call``."""
    args = _json(row.args, {})
    paths = [_norm(p) for p in _json(row.paths, []) if isinstance(p, str)]
    return _Call(row, index, args, paths)


def _note_write(scan: _Scan, row: Row) -> None:
    """Remember the sessions that called ``remember`` or ``revise``."""
    if row.tool in WRITE_TOOLS and row.session:
        scan.sessions_wrote.add(row.session)


def _dispatch(scan: _Scan, call: _Call) -> None:
    """Route one successful call to the recorder for its kind."""
    row = call.row
    if row.hook and row.tool in DELIVERY_TOOLS:
        _record_delivery(scan, call)
    elif row.tool == "read" and not row.hook:
        _record_read(scan, call)
    elif row.tool == "search" and not row.hook:
        _record_search(scan, call)


def _scan_rows(rows: list[Row], zone: str) -> _Scan:
    scan = _Scan(zone)
    for i, row in enumerate(rows):
        if not row.ok:
            continue
        _note_write(scan, row)
        _dispatch(scan, _decode(row, i))
    return scan


def _followed_deliveries(scan: _Scan) -> int:
    """Deliveries with a read of the same memory later in the same session."""
    return sum(
        1
        for session, p, i in scan.deliveries
        if session and any(j > i for j in scan.reads_at.get((session, p), ()))
    )


def _fill_reads_after(scan: _Scan) -> None:
    """Count, per memory, the reads after its first delivery in the same session."""
    for (session, p), idxs in scan.reads_at.items():
        first = scan.first_delivery.get((session, p))
        if first is not None:
            scan.stats[p]["reads_after"] += sum(1 for j in idxs if j > first)


def _count_followed(scan: _Scan) -> int:
    """Followed deliveries; also fills reads_after."""
    followed = _followed_deliveries(scan)
    _fill_reads_after(scan)
    return followed


def _since(now: datetime, days: int) -> str:
    """ISO timestamp of the start of the window."""
    return (now - timedelta(days=days)).isoformat(timespec="seconds")


def _n_delivered(stats: dict[str, Counter], p: str) -> int:
    """Deliveries of one memory by every delivery tool."""
    return sum(stats[p][t] for t in DELIVERY_TOOLS)


def _never_read(stats: dict[str, Counter], min_deliveries: int) -> list[str]:
    """Memories delivered ``min_deliveries`` times or more and never read, most first."""
    return sorted(
        (p for p in stats if _n_delivered(stats, p) >= min_deliveries and not stats[p]["reads"]),
        key=lambda p: (-_n_delivered(stats, p), p),
    )


def _old_memories(vault: Vault, zone: str, now: datetime, old_days: int) -> list[str]:
    """Memories created before the ``old_days`` cutoff."""
    cutoff = now.date() - timedelta(days=old_days)
    return [p for p, c in _created(vault, zone).items() if c < cutoff]


def measure(
    vault_root: Path,
    project: str | None = None,
    days: int = DEFAULT_DAYS,
    min_deliveries: int = DEFAULT_MIN_DELIVERIES,
    old_days: int = DEFAULT_OLD_DAYS,
    now: datetime | None = None,
) -> dict:
    """Per-memory counters and the figures of the five summary sections."""
    vault = Vault(Path(vault_root))
    zone_obj = vault.memory_zone
    zone = zone_obj.path if zone_obj else "memory"
    now = now or datetime.now(UTC)
    since = _since(now, days)
    rows = _load_rows(vault.root, since, project)
    scan = _scan_rows(rows, zone)
    followed = _count_followed(scan)
    stats = scan.stats
    old = _old_memories(vault, zone, now, old_days)
    old_read = [p for p in old if p in stats and stats[p]["reads"]]
    return {
        "days": days,
        "project": project,
        "rows": len(rows),
        "stats": stats,
        "deliveries": len(scan.deliveries),
        "followed": followed,
        "min_deliveries": min_deliveries,
        "never_read": [(p, _n_delivered(stats, p)) for p in _never_read(stats, min_deliveries)],
        "old_days": old_days,
        "old_total": len(old),
        "old_read": sorted(old_read),
        "old_unread": sorted(set(old) - set(old_read)),
        "sessions_read": len(scan.sessions_read),
        "sessions_no_write": sorted(scan.sessions_read - scan.sessions_wrote),
        "empty": sorted(scan.empty.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_EMPTY],
        "empty_total": sum(scan.empty.values()),
    }


def _render_table(r: dict) -> list[str]:
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
    return out


def _render_followed_and_never_read(r: dict) -> list[str]:
    d, f = r["deliveries"], r["followed"]
    pct = f"{f / d:.1%}" if d else "n/a"
    out = [
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
    return out + ([f"- {p} ({n} entregas)" for p, n in r["never_read"]] or ["- (ninguna)"])


def _render_old_and_sessions(r: dict) -> list[str]:
    out = [
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
    ]
    return out


def _render_empty(r: dict) -> list[str]:
    out = ["", f"### (e) Búsquedas del agente sin resultados ({r['empty_total']})", ""]
    return out + (
        [f"- {n}x `{q}` (match={m or '-'}, zone={z or '-'})" for (q, m, z), n in r["empty"]]
        or ["- (ninguna)"]
    )


def render(r: dict) -> str:
    out = _render_table(r)
    out += _render_followed_and_never_read(r)
    out += _render_old_and_sessions(r)
    out += _render_empty(r)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--project", default=None, help="only calls of this project")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--min-deliveries", type=int, default=DEFAULT_MIN_DELIVERIES)
    ap.add_argument("--old-days", type=int, default=DEFAULT_OLD_DAYS)
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
