"""Measure how much link graph there really is between memories.

    uv run scripts/measure_links.py --vault <vault> [--zone memory] [--project <name>] \
        [--examples 15]

Read-only: walks the vault with ``Vault.iter_notes`` and ``parse``; it never opens or
creates the index and writes nothing in the vault. It counts the links of the active
memories by kind, how many memories have a ``related`` neighbour, how many are orphans, and
how much vocabulary the ``related`` neighbours of the same project (or ``_shared``) add: the
data to decide whether the hooks should suggest neighbours by ``related``.

Without an index a link target resolves by exact path (with or without ``.md``) or by a
base name that is unique in the vault; anything else counts as unresolved.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from episteme.errors import INVALID_ARGUMENT, EpistemeError
from episteme.index import STOPWORDS_ES
from episteme.markdown import Link, parse, tokens
from episteme.memory import similarity
from episteme.vault import MEMORY, Vault

DEFAULT_EXAMPLES = 15
SHARED = "_shared"
# Below this Jaccard similarity two memories "use another vocabulary".
LOW_OVERLAP = 0.2
MAX_BUCKET = 3
RELATED = "related"

Edge = tuple[str, str | None, str]  # (source, resolved target or None, kind)


@dataclass
class Memory:
    rel: str
    project: str
    active: bool
    words: set[str]
    links: list[Link] = field(default_factory=list)


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


def measure(vault_root: Path, zone: str | None = None, project: str | None = None) -> dict:
    """Link counts, neighbour buckets and vocabulary overlap of the active memories."""
    vault = Vault(Path(vault_root))
    paths, memories = _load(vault, _zone_prefix(vault, zone))
    active, measured = _select(memories, zone, project)
    resolver = Resolver(paths)
    edges = _edges(active, resolver)
    nb = _related_neighbours(active, edges)
    pairs, buckets = _pair_stats(measured, {m.rel: m for m in active}, nb)
    kinds, unresolved = _link_counts(measured, edges)
    return {
        "active": len(measured),
        "kinds": kinds,
        "unresolved": unresolved,
        "with_related": sum(1 for m in measured if nb[m.rel]),
        "orphans": _orphans(measured, _edges(memories, resolver)),
        "scoped": len(measured) - buckets[0],
        "buckets": buckets,
        "pairs": pairs,
        "low": [p for p in pairs if p[0] < LOW_OVERLAP],
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
        f"- De ellas, con vecinas del mismo proyecto o `_shared`: {r['scoped']} "
        f"({_pct(r['scoped'], n)})",
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


def _render_decision(r: dict) -> list[str]:
    total, low = len(r["pairs"]), len(r["low"])
    return [
        "",
        "## Qué ganaría un hook",
        "",
        f"- Pares memoria-vecina: {total}",
        f"- Con vocabulario distinto (Jaccard < {LOW_OVERLAP}): {low} ({_pct(low, total)})",
    ]


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
    out += _render_examples(result, examples)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--zone", default=None, help="zone path (default: the memory zone)")
    ap.add_argument("--project", default=None, help="only measure this project's memories")
    ap.add_argument("--examples", type=int, default=DEFAULT_EXAMPLES)
    args = ap.parse_args(argv)
    try:
        result = measure(args.vault, args.zone, args.project)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1
    sys.stdout.buffer.write(render(result, args.examples).encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
