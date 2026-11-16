"""Measure how much link graph there really is between memories.

    uv run scripts/measure_links.py --vault <vault> [--zone memory] [--project <name>] \
        [--examples 15] [--days 30]

Read-only: walks the vault with ``Vault.iter_notes`` and ``parse``; it never opens or
creates the index and writes nothing in the vault. It counts the links of the active
memories by kind, how many memories have a ``related`` neighbour, how many are orphans, and
how much vocabulary the ``related`` neighbours of the same project (or ``_shared``) add: the
data to decide whether the hooks should suggest neighbours by ``related``.

It also reports what every wikilink (body and frontmatter) adds when walked both ways, the
``related`` pairs split by origin (both ends migrated from OMEGA, or not), a baseline (the
vocabulary overlap of every pair of memories of the same project) and, when the vault has
an activity log, how many memories read after a ``search`` were not in its results but
were linked to one of them.

Without an index a link target resolves by exact path (with or without ``.md``) or by a
base name that is unique in the vault; anything else counts as unresolved.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import chain, combinations, islice
from pathlib import Path
from statistics import median

from episteme.errors import INVALID_ARGUMENT, NOT_FOUND, EpistemeError
from episteme.index import STOPWORDS_ES
from episteme.markdown import Link, parse, tokens
from episteme.memory import similarity
from episteme.vault import INDEX_DIR, MEMORY, Vault

DEFAULT_EXAMPLES = 15
SHARED = "_shared"
# Below this Jaccard similarity two memories "use another vocabulary".
LOW_OVERLAP = 0.2
MAX_BUCKET = 3
RELATED = "related"
# ``source`` of a memory written by scripts/migrate_omega.py.
OMEGA_SOURCE = "omega:"
OMEGA, NATIVE = "omega", "nativo"
# Above this many same-project pairs the baseline takes one pair in every few.
BASELINE_MAX_PAIRS = 200_000
DEFAULT_DAYS = 30
RETURNED, FORWARD, BACKLINK, OTHER = "returned", "forward", "backlink", "other"
_ACTIVITY_SQL = (
    "select tool, args, paths, pid from calls"
    " where at >= ? and ok = 1 and tool in ('search', 'read') order by at, id"
)

Edge = tuple[str, str | None, str]  # (source, resolved target or None, kind)


@dataclass
class Memory:
    rel: str
    project: str
    active: bool
    words: set[str]
    links: list[Link] = field(default_factory=list)
    omega: bool = False


def _zone_prefix(vault: Vault, zone: str | None) -> str:
    if zone is None:
        z = vault.memory_zone
        if z is None:
            raise EpistemeError(
                INVALID_ARGUMENT,
                f"the vault has no zone with mode {MEMORY!r}. Pass --zone <zone path>.",
            )
        return z.path
    return zone.replace("\\", "/").strip("/")


def _in_zone(rel: str, zone: str) -> bool:
    return rel == zone or rel.startswith(zone + "/")


def _memory(rel: str, text: str) -> Memory:
    note = parse(text, rel)
    fm = note.frontmatter
    words = set(tokens(note.title + "\n" + note.search_text, min_len=2))
    return Memory(
        rel=rel,
        project=str(fm.get("project") or ""),
        active=fm.get("status") == "active",
        words=words - STOPWORDS_ES,
        links=list(note.links),
        omega=str(fm.get("source") or "").startswith(OMEGA_SOURCE),
    )


def _load(vault: Vault, zone: str) -> tuple[list[str], list[Memory]]:
    """Every note path of the vault and the memories of the zone."""
    paths: list[str] = []
    memories: list[Memory] = []
    for rel, _stat in vault.iter_notes():
        paths.append(rel)
        if not _in_zone(rel, zone):
            continue
        try:
            text = (vault.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"skipping {rel}: {e}", file=sys.stderr)
            continue
        memories.append(_memory(rel, text))
    return paths, memories


class Resolver:
    """Link target -> note path, without an index."""

    def __init__(self, paths: list[str]) -> None:
        self.exact = set(paths)
        by_base: dict[str, list[str]] = defaultdict(list)
        for p in paths:
            by_base[Path(p).stem].append(p)
        self.unique = {base: ps[0] for base, ps in by_base.items() if len(ps) == 1}

    def resolve(self, target: str) -> str | None:
        t = target.replace("\\", "/").strip().strip("/")
        for candidate in (t, t + ".md"):
            if t and candidate in self.exact:
                return candidate
        base = t.removesuffix(".md")
        return None if not base or "/" in base else self.unique.get(base)


def _edges(active: list[Memory], resolver: Resolver) -> list[Edge]:
    """One edge per link of an active memory."""
    return [
        (m.rel, resolver.resolve(link.target), link.kind)
        for m in active
        for link in m.links
        if link.target
    ]


def _is_related_pair(src: str, dst: str | None, kind: str) -> bool:
    return kind == RELATED and dst is not None and dst != src


def _related_neighbours(active: list[Memory], edges: list[Edge]) -> dict[str, set[str]]:
    """Active memory -> the active memories joined to it by ``related``, either way."""
    nb: dict[str, set[str]] = {m.rel: set() for m in active}
    for src, dst, kind in edges:
        if dst in nb and _is_related_pair(src, dst, kind):
            nb[src].add(dst)
            nb[dst].add(src)
    return nb


def _outgoing(edges: list[Edge], known: set[str] | None = None) -> dict[str, set[str]]:
    """Source -> resolved targets, any link kind; only targets in ``known`` when given."""
    out: dict[str, set[str]] = defaultdict(set)
    for src, dst, _kind in edges:
        if dst is not None and dst != src and (known is None or dst in known):
            out[src].add(dst)
    return out


def _incoming(out: dict[str, set[str]]) -> dict[str, set[str]]:
    back: dict[str, set[str]] = defaultdict(set)
    for src, dsts in out.items():
        for dst in dsts:
            back[dst].add(src)
    return back


def _reach(measured: list[Memory], active: list[Memory], edges: list[Edge]) -> dict[str, int]:
    """What every wikilink adds, and what only a backlink reaches, among active memories."""
    out = _outgoing(edges, {m.rel for m in active})
    back = _incoming(out)
    pairs = [(out.get(m.rel, set()), back.get(m.rel, set())) for m in measured]
    return {
        "with_any": sum(1 for o, b in pairs if o or b),
        "backlink_gain": sum(1 for o, b in pairs if b - o),
        "backlink_only": sum(1 for o, b in pairs if b and not o),
    }


def _overlap(scores: Iterable[float]) -> dict[str, float]:
    """How many pairs, how many with another vocabulary, and their median Jaccard."""
    values = list(scores)
    return {
        "pairs": len(values),
        "low": sum(1 for s in values if s < LOW_OVERLAP),
        "median": median(values) if values else 0.0,
    }


def _by_origin(pairs: list[tuple[float, Memory, Memory]]) -> dict[str, dict[str, float]]:
    """``related`` pairs split by origin: migrated when both ends came from OMEGA."""
    split: dict[str, list[float]] = {OMEGA: [], NATIVE: []}
    for score, a, b in pairs:
        split[OMEGA if a.omega and b.omega else NATIVE].append(score)
    return {origin: _overlap(scores) for origin, scores in split.items()}


def _baseline(measured: list[Memory]) -> dict[str, float]:
    """Overlap of the pairs of memories of the same project, linked or not."""
    by_project: dict[str, list[Memory]] = defaultdict(list)
    for m in measured:
        by_project[m.project].append(m)
    total = sum(len(g) * (len(g) - 1) // 2 for g in by_project.values())
    step = max(1, -(-total // BASELINE_MAX_PAIRS))
    every = chain.from_iterable(combinations(g, 2) for g in by_project.values())
    return _overlap(similarity(a.words, b.words) for a, b in islice(every, 0, None, step))


def _in_scope(a: Memory, b: Memory) -> bool:
    return b.project == a.project or b.project == SHARED


def _orphans(measured: list[Memory], edges: list[Edge]) -> list[Memory]:
    """Memories with no resolved link in either direction (edges from every memory)."""
    linked = {src for src, dst, _kind in edges if dst is not None}
    linked |= {dst for _src, dst, _kind in edges if dst is not None}
    return [m for m in measured if m.rel not in linked]


def _pair_stats(
    measured: list[Memory], by_rel: dict[str, Memory], nb: dict[str, set[str]]
) -> tuple[list[tuple[float, Memory, Memory]], Counter[int]]:
    """Distinct scoped neighbour pairs with their Jaccard, and neighbours-per-memory buckets."""
    pairs: dict[frozenset[str], tuple[float, Memory, Memory]] = {}
    buckets: Counter[int] = Counter()
    for m in measured:
        scoped = [by_rel[r] for r in sorted(nb[m.rel]) if _in_scope(m, by_rel[r])]
        buckets[min(len(scoped), MAX_BUCKET)] += 1
        for n in scoped:
            pairs.setdefault(frozenset((m.rel, n.rel)), (similarity(m.words, n.words), m, n))
    return list(pairs.values()), buckets


def _select(
    memories: list[Memory], zone: str | None, project: str | None
) -> tuple[list[Memory], list[Memory]]:
    """The active memories and the ones to measure (those of ``project`` when given)."""
    active = [m for m in memories if m.active]
    measured = [m for m in active if project is None or m.project == project]
    if measured:
        return active, measured
    raise EpistemeError(
        INVALID_ARGUMENT,
        f"no active memories found (zone {zone or 'default'}, project {project or 'any'}). "
        "Pass --zone with a memory folder or check --project.",
    )


def _link_counts(measured: list[Memory], edges: list[Edge]) -> tuple[Counter, Counter]:
    """Links by kind and unresolved links by kind, for the measured memories."""
    mine = {m.rel for m in measured}
    mine_edges = [e for e in edges if e[0] in mine]
    kinds = Counter(kind for _src, _dst, kind in mine_edges)
    unresolved = Counter(kind for _src, dst, kind in mine_edges if dst is None)
    return kinds, unresolved


def _json[T](text: str | None, default: T) -> T:
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _norm(path: str) -> str:
    path = path.replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def _asked(args: dict) -> list[str]:
    """Normalised note names a ``read`` asked for (``note`` and ``notes``)."""
    notes = args.get("notes")
    asked = [args.get("note"), *(notes if isinstance(notes, list) else [])]
    return [_norm(n) for n in asked if isinstance(n, str)]


def _read_paths(args: dict, paths: list[str]) -> list[str]:
    """Notes a ``read`` opened: path-like args, else as many leading result paths as names.

    ``paths`` is scraped from the result text, so it can also hold the notes it links to.
    """
    asked = _asked(args)
    if asked and all(n.endswith(".md") for n in asked):
        return list(dict.fromkeys(asked))
    return list(dict.fromkeys(paths[: len(asked) or len(paths)]))


def _activity_rows(vault_root: Path, days: int) -> list[tuple] | None:
    """The ``search`` and ``read`` calls of the last ``days`` days; None without a log."""
    db = vault_root / INDEX_DIR / "activity.db"
    if days <= 0 or not db.is_file():
        return None
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return conn.execute(_ACTIVITY_SQL, (since,)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise EpistemeError(NOT_FOUND, f"cannot read {db}: {e}. Pass --days 0 to skip it.") from e


def _how_reached(path: str, results: set[str], out: dict[str, set[str]]) -> str:
    """How a memory read after a search relates to what the search returned."""
    if path in results:
        return RETURNED
    if any(path in out.get(r, ()) for r in results):
        return FORWARD
    return BACKLINK if out.get(path, set()) & results else OTHER


def _replay(rows: list[tuple], out: dict[str, set[str]], zone: str) -> dict:
    """Classify each memory read after a search of the same process, once per search."""
    reads: Counter[str] = Counter()
    examples: list[tuple[str, str]] = []
    pending: dict[int | None, tuple[set[str], set[str]]] = {}  # pid -> (results, counted)
    searches = 0
    for tool, args, paths, pid in rows:
        found = [_norm(p) for p in _json(paths, [])]
        if tool == "search":
            searches += 1
            pending[pid] = (set(found), set())
            continue
        if pid not in pending:
            continue
        results, counted = pending[pid]
        opened = dict.fromkeys(_read_paths(_json(args, {}), found))
        fresh = [p for p in opened if _in_zone(p, zone) and p not in counted]
        counted.update(fresh)
        reached = [(_how_reached(p, results, out), p) for p in fresh]
        reads.update(how for how, _p in reached)
        examples += [r for r in reached if r[0] in (FORWARD, BACKLINK)]
    return {"searches": searches, "reads": reads, "examples": examples}


def measure(
    vault_root: Path, zone: str | None = None, project: str | None = None, days: int = DEFAULT_DAYS
) -> dict:
    """Link counts, neighbour buckets and vocabulary overlap of the active memories."""
    vault = Vault(Path(vault_root))
    prefix = _zone_prefix(vault, zone)
    paths, memories = _load(vault, prefix)
    active, measured = _select(memories, zone, project)
    resolver = Resolver(paths)
    edges = _edges(active, resolver)
    every_edge = _edges(memories, resolver)
    nb = _related_neighbours(active, edges)
    pairs, buckets = _pair_stats(measured, {m.rel: m for m in active}, nb)
    kinds, unresolved = _link_counts(measured, edges)
    rows = _activity_rows(vault.root, days)
    return {
        "active": len(measured),
        "kinds": kinds,
        "unresolved": unresolved,
        "with_related": sum(1 for m in measured if nb[m.rel]),
        "orphans": _orphans(measured, every_edge),
        "scoped": len(measured) - buckets[0],
        "buckets": buckets,
        "pairs": pairs,
        "low": [p for p in pairs if p[0] < LOW_OVERLAP],
        "reach": _reach(measured, active, edges),
        "linked": _overlap(s for s, _a, _b in pairs),
        "origins": _by_origin(pairs),
        "baseline": _baseline(measured),
        "activity": None if rows is None else _replay(rows, _outgoing(every_edge), prefix),
        "days": days,
    }


def _pct(part: int, total: int) -> str:
    return f"{part / total:.1%}" if total else "0.0%"


def _render_links(r: dict) -> list[str]:
    out = ["## Enlaces por tipo", "", "| tipo | enlaces | sin resolver |", "|---|---|---|"]
    out += [f"| {k} | {n} | {r['unresolved'][k]} |" for k, n in sorted(r["kinds"].items())]
    return out if r["kinds"] else [*out, "| (ninguno) | 0 | 0 |"]


def _render_graph(r: dict) -> list[str]:
    n = r["active"]
    out = [
        "",
        "## Memorias con vecinas",
        "",
        f"- Con al menos un `related` (saliente o entrante): {r['with_related']} "
        f"({_pct(r['with_related'], n)})",
        f"- Huérfanas (sin enlaces resueltos en ningún sentido): {len(r['orphans'])} "
        f"({_pct(len(r['orphans']), n)})",
        f"- Con vecinas `related` del mismo proyecto o `_shared`: {r['scoped']} "
        f"({_pct(r['scoped'], n)})",
        f"- Con al menos un wikilink de cualquier tipo (cuerpo o frontmatter, saliente o "
        f"entrante): {r['reach']['with_any']} ({_pct(r['reach']['with_any'], n)})",
        f"- Ganan vecinas al recorrer los backlinks: {r['reach']['backlink_gain']} "
        f"({_pct(r['reach']['backlink_gain'], n)}); de ellas, solo tienen enlaces "
        f"entrantes: {r['reach']['backlink_only']}",
        "",
        "Vecinas `related` activas del mismo proyecto o `_shared`, por memoria:",
        "",
        "| vecinas | memorias |",
        "|---|---|",
    ]
    for k in range(MAX_BUCKET + 1):
        label = str(k) if k < MAX_BUCKET else f"{k} o más"
        out.append(f"| {label} | {r['buckets'][k]} |")
    return out


def _overlap_row(label: str, o: dict[str, float]) -> str:
    low = _pct(int(o["low"]), int(o["pairs"]))
    return f"| {label} | {o['pairs']} | {low} | {o['median']:.2f} |"


def _render_decision(r: dict) -> list[str]:
    total, low = len(r["pairs"]), len(r["low"])
    return [
        "",
        "## Qué ganaría un hook",
        "",
        f"- Pares memoria-vecina: {total}",
        f"- Con vocabulario distinto (Jaccard < {LOW_OVERLAP}): {low} ({_pct(low, total)})",
        "",
        "Línea base: los mismos números para todos los pares de memorias del mismo proyecto, "
        "enlazados o no. Un par es «de OMEGA» cuando sus dos memorias vienen de la migración.",
        "",
        f"| pares | cuántos | Jaccard < {LOW_OVERLAP} | mediana |",
        "|---|---|---|---|",
        _overlap_row("enlazados por `related`", r["linked"]),
        _overlap_row("- de OMEGA", r["origins"][OMEGA]),
        _overlap_row("- nativos", r["origins"][NATIVE]),
        _overlap_row("línea base (mismo proyecto)", r["baseline"]),
    ]


def _render_activity(r: dict, examples: int) -> list[str]:
    out = ["", "## Búsquedas reales", ""]
    a = r["activity"]
    if a is None:
        return [*out, "- (sin registro de actividad: no hay `activity.db` o `--days 0`)"]
    reads = a["reads"]
    total = sum(reads.values())
    near = reads[FORWARD] + reads[BACKLINK]
    out += [
        f"- Búsquedas de los últimos {r['days']} días: {a['searches']}",
        f"- Memorias leídas después de una búsqueda, en el mismo proceso: {total}",
        f"- Estaban en el resultado: {reads[RETURNED]} ({_pct(reads[RETURNED], total)})",
        f"- No estaban, pero eran vecinas de un resultado: {near} ({_pct(near, total)}); "
        f"un resultado las enlaza: {reads[FORWARD]}, solo por backlink: {reads[BACKLINK]}",
        f"- Ni resultado ni vecinas: {reads[OTHER]} ({_pct(reads[OTHER], total)})",
    ]
    shown = list(dict.fromkeys(a["examples"]))[:examples]
    return [*out, "", *[f"- {how}: {path}" for how, path in shown]] if shown else out


def _pair_key(pair: tuple[float, Memory, Memory]) -> tuple[float, str, str]:
    return pair[0], pair[1].rel, pair[2].rel


def _render_examples(r: dict, examples: int) -> list[str]:
    out = ["", "## Ejemplos de pares (menor similitud primero)", ""]
    ranked = sorted(r["pairs"], key=_pair_key)[:examples]
    out += [f"- {s:.2f}: {a.rel} ↔ {b.rel}" for s, a, b in ranked] or ["- (sin pares)"]
    return out


def render(result: dict, examples: int) -> str:
    out = [
        "# Medición del grafo de enlaces",
        "",
        f"- Memorias activas: {result['active']}",
        "- Destinos: por ruta exacta (con o sin `.md`) o por nombre base único en el vault; "
        "lo demás cuenta como «sin resolver».",
        "",
    ]
    out += _render_links(result)
    out += _render_graph(result)
    out += _render_decision(result)
    out += _render_activity(result, examples)
    out += _render_examples(result, examples)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--zone", default=None, help="zone path (default: the memory zone)")
    ap.add_argument("--project", default=None, help="only measure this project's memories")
    ap.add_argument("--examples", type=int, default=DEFAULT_EXAMPLES)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="activity window; 0 skips it")
    args = ap.parse_args(argv)
    try:
        result = measure(args.vault, args.zone, args.project, args.days)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1
    sys.stdout.buffer.write(render(result, args.examples).encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
