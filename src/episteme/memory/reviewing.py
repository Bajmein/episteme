"""Memory review: expired, stale, duplicate and contradictory memories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from episteme.errors import EpistemeError, invalid
from episteme.index import is_past
from episteme.markdown import (
    body_without_title,
)
from episteme.memory.schema import NoteFile, dedup_tokens, similarity, validate
from episteme.memory.scoring import days_since
from episteme.memory.writing import shared_reason
from episteme.vault import MEMORY, READ_ONLY, today

if TYPE_CHECKING:
    from datetime import date

    from episteme.engine import Engine

STALE_DAYS = 90
REVIEW_SIMILAR = 0.4  # wider than remember's 0.5: review only reports
# Two decisions that only share a hub file (server.py) are not about the same thing:
# below this token similarity the pair is noise, not a possible contradiction.
REVIEW_CONTRADICTION = 0.15
CONTRADICTION_MIN_SHARED_TAGS = 2
SIMILARITY_DIGITS = 3
STALE_EXEMPT_TYPES = ("preference", "constraint")
DECISION_TYPES = ("decision", "constraint")
NOT_SIMILAR_TYPES = ("session", "reminder")
CHECKPOINT_PREFIX = "checkpoint-"
ORPHAN_CANDIDATES = 3


def expired_memories(rows: list[Any], iso: str) -> list[Any]:
    """Active memories past valid_until (before ``iso``), checkpoints excluded."""
    return [
        r
        for r in rows
        if r["status"] == "active"
        and is_past(r["valid_until"], iso)
        and not (
            r["type"] == "session" and r["path"].rsplit("/", 1)[-1].startswith(CHECKPOINT_PREFIX)
        )
    ]


def _still_expired(nf: NoteFile, iso: str) -> bool:
    return nf.fm.get("status") == "active" and is_past(nf.fm.get("valid_until"), iso)


def archive_expired(engine: Engine) -> list[str]:
    """Archive every active memory past valid_until (all projects). Returns the paths."""
    iso = today().isoformat()
    rows = expired_memories(engine.index.memories("status = 'active'"), iso)
    archived = []
    for path in sorted(r["path"] for r in rows):
        try:
            nf = NoteFile(engine, path)
            # The index may be stale: only archive what the file itself still says is expired.
            if not _still_expired(nf, iso):
                continue
            nf.set_fields({"status": "archived"})
            nf.save()
        except (EpistemeError, OSError):
            continue
        archived.append(path)
    return archived


@dataclass(frozen=True)
class _Scope:
    """What a review looks at: path prefix, zone and project, plus each note's zone and mode."""

    zones: dict[str, tuple[str | None, str | None]]
    prefix: str | None
    zone: str | None
    project: str | None

    def _under_prefix(self, rel: str) -> bool:
        if self.prefix is None:
            return True
        return rel == self.prefix or rel.startswith(self.prefix + "/")

    def _in_zone(self, rel: str) -> bool:
        return self.zone is None or self.zones.get(rel, (None, None))[0] == self.zone

    def in_scope(self, rel: str) -> bool:
        return self._under_prefix(rel) and self._in_zone(rel)

    def is_read_only(self, rel: str) -> bool:
        # Notes outside every zone are read-only too (see vault.mode_for).
        return self.zones.get(rel, (None, READ_ONLY))[1] in (READ_ONLY, None)

    def in_project(self, r: Any) -> bool:
        # A memory with a missing or invalid project is matched by its folder, so that
        # the schema validation below reports it instead of the filter hiding it.
        if self.project in (None, "*") or r["project"] in (self.project, "_shared"):
            return True
        return r["path"].startswith((f"{r['zone']}/{self.project}/", f"{r['zone']}/_shared/"))


def _checked_zone(engine: Engine, zone: str | None) -> str | None:
    zone = zone.strip().strip("/") if zone else None
    if zone and zone not in {z.path for z in engine.vault.config.zones}:
        known = ", ".join(sorted(z.path for z in engine.vault.config.zones))
        raise invalid(f'unknown zone "{zone}". Use one of: {known}.')
    return zone


def _note_zones(engine: Engine) -> dict[str, tuple[str | None, str | None]]:
    return {
        r["path"]: (r["zone"], r["mode"])
        for r in engine.index.conn.execute("select path, zone, mode from notes")
    }


def _path_prefix(engine: Engine, path: str | None) -> str | None:
    if not path:
        return None
    engine.check_path(path.strip().rstrip("/") or "/")
    return path.strip().strip("/")


def _make_scope(engine: Engine, path: str | None, project: str | None, zone: str | None) -> _Scope:
    zone = _checked_zone(engine, zone)
    zones = _note_zones(engine)
    prefix = _path_prefix(engine, path)
    project = "*" if project == "*" else (project or engine.project)
    return _Scope(zones, prefix, zone, project)


def _is_stale(r: Any, days: int) -> bool:
    return bool(
        r["created"]
        and days > STALE_DAYS
        and not r["helpful"]
        and r["type"] not in STALE_EXEMPT_TYPES
    )


def _find_stale(active: list[Any], now: date) -> list[dict[str, Any]]:
    stale = []
    for r in active:
        days = days_since(r["created"], now)
        if _is_stale(r, days):
            stale.append({"path": r["path"], "title": r["title"], "days": days})
    return stale


def _find_expired(active: list[Any], iso: str) -> list[dict[str, Any]]:
    # Past valid_until, still active. Checkpoints are left out: checkpoint manages them.
    expired = [
        {
            "path": r["path"],
            "title": r["title"],
            "type": r["type"],
            "valid_until": r["valid_until"],
        }
        for r in expired_memories(active, iso)
    ]
    expired.sort(key=lambda e: (e["valid_until"], e["path"]))
    return expired


def _linked_pairs(engine: Engine) -> set[tuple[str, str]]:
    linked: set[tuple[str, str]] = set()
    for row in engine.index.conn.execute(
        "select src, dst_path from links where kind in ('supersedes', 'contradicts', 'related') "
        "and dst_path is not null"
    ):
        linked.add((row["src"], row["dst_path"]))
        linked.add((row["dst_path"], row["src"]))
    return linked


def _contradiction_reason(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """Why two decision memories may contradict (shared files or tags), else None."""
    files = set(_list_prop(a, "files")) & set(_list_prop(b, "files"))
    if files:
        return f"both cover files: {', '.join(sorted(files))}"
    tags = set(_list_prop(a, "tags")) & set(_list_prop(b, "tags"))
    if len(tags) >= CONTRADICTION_MIN_SHARED_TAGS:
        return f"share tags: {', '.join(sorted(tags))}"
    return None


def _find_contradictions(
    engine: Engine,
    active: list[Any],
    props: dict[str, dict[str, Any]],
    toks: dict[str, set[str]],
) -> list[dict[str, Any]]:
    linked = _linked_pairs(engine)
    contradictions = []
    decisions = [r for r in active if r["type"] in DECISION_TYPES]
    for i, a in enumerate(decisions):
        for b in decisions[i + 1 :]:
            if a["project"] != b["project"] or (a["path"], b["path"]) in linked:
                continue
            reason = _contradiction_reason(props[a["path"]], props[b["path"]])
            if not reason:
                continue
            sim = similarity(toks[a["path"]], toks[b["path"]])
            if sim < REVIEW_CONTRADICTION:
                continue
            contradictions.append(
                {
                    "a": a["path"],
                    "b": b["path"],
                    "reason": reason,
                    "similarity": round(sim, SIMILARITY_DIGITS),
                }
            )
    return contradictions


def _is_cut_title(r: Any) -> bool:
    title = (r["title"] or "").strip()
    first = (body_without_title(r["body"] or "").split("\n", 1)[0]).strip()
    return bool(title) and first.startswith(title) and len(first) > len(title)


def _find_cut_titles(mems: list[Any]) -> list[str]:
    return [r["path"] for r in mems if _is_cut_title(r)]


def _is_orphan(engine: Engine, path: str) -> bool:
    """True when the note links to no other note and nothing links to it."""
    out = [x for x in engine.index.outgoing(path) if x["dst_path"] not in (None, path)]
    return not out and not engine.index.backlinks(path)


def _by_rank(rows: list[Any]) -> list[Any]:
    """Rows by priority, then created, both descending; the path breaks ties."""
    by_path = sorted(rows, key=lambda r: r["path"])
    return sorted(
        by_path, key=lambda r: (r["priority"] or 0, str(r["created"] or "")), reverse=True
    )


def _can_link(r: Any, other: Any) -> bool:
    """True for another memory of the same project, or of _shared."""
    return other["path"] != r["path"] and other["project"] in (r["project"], "_shared")


def _files_and_tags(props: dict[str, Any]) -> tuple[set[str], set[str]]:
    return set(_list_prop(props, "files")), set(_list_prop(props, "tags"))


def _orphan_candidates(
    r: Any, pool: list[Any], props: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Up to ``ORPHAN_CANDIDATES`` memories of ``pool`` sharing a file or 2+ tags with ``r``."""
    my_files, my_tags = _files_and_tags(props.get(r["path"], {}))
    found: list[dict[str, Any]] = []
    for other in pool:
        if len(found) == ORPHAN_CANDIDATES:
            break
        if not _can_link(r, other):
            continue
        other_files, other_tags = _files_and_tags(props.get(other["path"], {}))
        reason = shared_reason(my_files, my_tags, other_files, other_tags)
        if reason:
            found.append({"path": other["path"], "title": other["title"], "reason": reason})
    return found


def _find_orphans(
    engine: Engine, active: list[Any], props: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Active memories with no links in or out, each with its candidates, linkable first."""
    pool = _by_rank([r for r in active if r["type"] not in NOT_SIMILAR_TYPES])
    orphans = [
        {"path": r["path"], "title": r["title"], "candidates": _orphan_candidates(r, pool, props)}
        for r in pool
        if _is_orphan(engine, r["path"])
    ]
    # Stable: within each half the rank order of pool holds.
    return sorted(orphans, key=lambda o: not o["candidates"])


def _find_broken_links(engine: Engine, scope: _Scope) -> list[dict[str, Any]]:
    return [
        {"path": r["src"], "target": _target(r), "line": r["line"]}
        for r in engine.index.conn.execute(
            "select * from links where dst_path is null or heading_missing = 1 order by src, line"
        )
        if scope.in_scope(r["src"])
    ]


def _frontmatter_error(r: Any, props: dict[str, dict[str, Any]]) -> str | None:
    """The schema error of a memory whose frontmatter parses, else None."""
    if r["mode"] != MEMORY or r["path"] not in props:
        return None
    try:
        validate(props[r["path"]])
    except EpistemeError as exc:
        return exc.message
    return None


def _find_invalid_frontmatter(
    engine: Engine, scope: _Scope, props: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    invalid_fm = []
    for r in engine.index.conn.execute("select path, mode, fm_valid, fm_error from notes"):
        if not scope.in_scope(r["path"]):
            continue
        if not r["fm_valid"]:
            invalid_fm.append({"path": r["path"], "error": r["fm_error"]})
            continue
        error = _frontmatter_error(r, props)
        if error is not None:
            invalid_fm.append({"path": r["path"], "error": error})
    return invalid_fm


def _find_flagged(mems: list[Any]) -> list[str]:
    return [r["path"] for r in mems if r["flagged"]]


def _path_of(item: Any) -> str:
    if isinstance(item, str):
        return item
    return item.get("path") or (item["paths"][0] if "paths" in item else item["a"])


def _in_scope_memories(engine: Engine, scope: _Scope) -> list[Any]:
    return [r for r in engine.index.memories() if scope.in_scope(r["path"]) and scope.in_project(r)]


def _collect_findings(engine: Engine, scope: _Scope, mems: list[Any]) -> dict[str, list[Any]]:
    now = today()
    props = {r["path"]: engine.index.props(r["path"]) for r in mems}
    active = [r for r in mems if r["status"] == "active"]
    toks = {
        r["path"]: dedup_tokens(r["title"] or "", body_without_title(r["body"] or ""))
        for r in active
    }
    return {
        "stale": _find_stale(active, now),
        "expired": _find_expired(active, now.isoformat()),
        "contradictions": _find_contradictions(engine, active, props, toks),
        "similar": _similar_groups([r for r in active if r["type"] not in NOT_SIMILAR_TYPES], toks),
        "cut_titles": _find_cut_titles(mems),
        "orphans": _find_orphans(engine, active, props),
        "broken_links": _find_broken_links(engine, scope),
        "invalid_frontmatter": _find_invalid_frontmatter(engine, scope, props),
        "flagged": _find_flagged(mems),
    }


def _partition(
    found: dict[str, list[Any]], scope: _Scope, read_only: bool
) -> dict[str, list[Any]]:
    return {
        k: [i for i in v if scope.is_read_only(_path_of(i)) == read_only] for k, v in found.items()
    }


def _report(parts: dict[str, list[Any]], limit: int) -> dict[str, Any]:
    totals = {k: len(v) for k, v in parts.items()}
    return {"totals": totals, **{k: v[:limit] for k, v in parts.items()}}


def review(
    engine: Engine, path: str | None, project: str | None, limit: int, zone: str | None = None
) -> dict[str, Any]:
    """Report memory problems without changing the vault; read-only zones come apart."""
    if limit < 1:
        raise invalid(f"limit must be positive, got {limit}.")
    scope = _make_scope(engine, path, project, zone)
    mems = _in_scope_memories(engine, scope)
    found = _collect_findings(engine, scope, mems)

    # Read-only zones are reported apart, with the same categories: they are not the
    # project's to fix, but nothing found there is dropped.
    out = _report(_partition(found, scope, False), limit)
    out["read_only"] = _report(_partition(found, scope, True), limit)
    return out


def _list_prop(props: dict[str, Any], key: str) -> list[str]:
    value = props.get(key)
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v is not None] if isinstance(value, list) else []


def _target(row: Any) -> str:
    target = row["dst_raw"] or ""
    if row["heading"]:
        target += f"#{row['heading']}"
    return target


def _find_root(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _similar_pairs(toks: list[set[str]]) -> list[tuple[int, int, float]]:
    pairs = []
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            sim = similarity(toks[i], toks[j])
            if sim >= REVIEW_SIMILAR:
                pairs.append((i, j, sim))
    return pairs


def _similar_groups(rows: list[Any], token_sets: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Connected components of memories whose dedup tokens reach REVIEW_SIMILAR."""
    pairs = _similar_pairs([token_sets[r["path"]] for r in rows])
    parent = list(range(len(rows)))
    for i, j, _ in pairs:
        parent[_find_root(parent, i)] = _find_root(parent, j)
    best: dict[int, float] = {}
    for i, _, sim in pairs:
        root = _find_root(parent, i)
        best[root] = max(best.get(root, 0.0), sim)
    members: dict[int, list[str]] = {}
    for i in {k for p in pairs for k in p[:2]}:
        members.setdefault(_find_root(parent, i), []).append(rows[i]["path"])
    groups: list[dict[str, Any]] = [
        {"paths": sorted(paths), "similarity": round(best[root], SIMILARITY_DIGITS)}
        for root, paths in members.items()
    ]
    groups.sort(key=lambda g: (-g["similarity"], g["paths"][0]))
    return groups
