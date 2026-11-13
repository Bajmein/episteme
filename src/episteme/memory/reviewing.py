"""Memory review: expired, stale, duplicate and contradictory memories."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from episteme.errors import EpistemeError, invalid
from episteme.markdown import (
    body_without_title,
)
from episteme.memory.schema import NoteFile, dedup_tokens, similarity, validate
from episteme.memory.scoring import days_since
from episteme.vault import MEMORY, READ_ONLY, today

if TYPE_CHECKING:
    from episteme.engine import Engine

STALE_DAYS = 90
REVIEW_SIMILAR = 0.4  # wider than remember's 0.5: review only reports
# Two decisions that only share a hub file (server.py) are not about the same thing:
# below this token similarity the pair is noise, not a possible contradiction.
REVIEW_CONTRADICTION = 0.15


def expired_memories(rows: list[Any], iso: str) -> list[Any]:
    """Active memories past valid_until (before ``iso``), checkpoints excluded."""
    return [
        r
        for r in rows
        if r["status"] == "active"
        and r["valid_until"]
        and r["valid_until"] < iso
        and not (r["type"] == "session" and r["path"].rsplit("/", 1)[-1].startswith("checkpoint-"))
    ]


def archive_expired(engine: Engine) -> list[str]:
    """Archive every active memory past valid_until (all projects). Returns the paths."""
    iso = today().isoformat()
    rows = expired_memories(engine.index.memories("status = 'active'"), iso)
    archived = []
    for path in sorted(r["path"] for r in rows):
        try:
            nf = NoteFile(engine, path)
            # The index may be stale: only archive what the file itself still says is expired.
            if nf.fm.get("status") != "active" or str(nf.fm.get("valid_until") or "") >= iso:
                continue
            nf.set_fields({"status": "archived"})
            nf.save()
        except (EpistemeError, OSError):
            continue
        archived.append(path)
    return archived


def review(
    engine: Engine, path: str | None, project: str | None, limit: int, zone: str | None = None
) -> dict[str, Any]:
    if limit < 1:
        raise invalid(f"limit must be positive, got {limit}.")
    zone = zone.strip().strip("/") if zone else None
    if zone and zone not in {z.path for z in engine.vault.config.zones}:
        known = ", ".join(sorted(z.path for z in engine.vault.config.zones))
        raise invalid(f'unknown zone "{zone}". Use one of: {known}.')
    zones = {
        r["path"]: (r["zone"], r["mode"])
        for r in engine.index.conn.execute("select path, zone, mode from notes")
    }
    prefix = None
    if path:
        engine.check_path(path.strip().rstrip("/") or "/")
        prefix = path.strip().strip("/")
    project = "*" if project == "*" else (project or engine.project)

    def in_scope(rel: str) -> bool:
        if prefix is not None and rel != prefix and not rel.startswith(prefix + "/"):
            return False
        return zone is None or zones.get(rel, (None, None))[0] == zone

    def is_read_only(rel: str) -> bool:
        # Notes outside every zone are read-only too (see vault.mode_for).
        return zones.get(rel, (None, READ_ONLY))[1] in (READ_ONLY, None)

    def in_project(r: Any) -> bool:
        # A memory with a missing or invalid project is matched by its folder, so that
        # the schema validation below reports it instead of the filter hiding it.
        if project in (None, "*") or r["project"] in (project, "_shared"):
            return True
        return r["path"].startswith((f"{r['zone']}/{project}/", f"{r['zone']}/_shared/"))

    now = today()
    mems = [r for r in engine.index.memories() if in_scope(r["path"]) and in_project(r)]
    props = {r["path"]: engine.index.props(r["path"]) for r in mems}
    active = [r for r in mems if r["status"] == "active"]

    stale = []
    for r in active:
        days = days_since(r["created"], now)
        if (
            r["created"]
            and days > STALE_DAYS
            and not r["helpful"]
            and r["type"] not in ("preference", "constraint")
        ):
            stale.append({"path": r["path"], "title": r["title"], "days": days})

    # Past valid_until, still active. Checkpoints are left out: checkpoint manages them.
    iso = now.isoformat()
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

    linked: set[tuple[str, str]] = set()
    for row in engine.index.conn.execute(
        "select src, dst_path from links where kind in ('supersedes', 'contradicts', 'related') "
        "and dst_path is not null"
    ):
        linked.add((row["src"], row["dst_path"]))
        linked.add((row["dst_path"], row["src"]))
    toks = {
        r["path"]: dedup_tokens(r["title"] or "", body_without_title(r["body"] or ""))
        for r in active
    }
    contradictions = []
    decisions = [r for r in active if r["type"] in ("decision", "constraint")]
    for i, a in enumerate(decisions):
        for b in decisions[i + 1 :]:
            if a["project"] != b["project"] or (a["path"], b["path"]) in linked:
                continue
            files_a = set(_list_prop(props[a["path"]], "files"))
            files_b = set(_list_prop(props[b["path"]], "files"))
            tags_a = set(_list_prop(props[a["path"]], "tags"))
            tags_b = set(_list_prop(props[b["path"]], "tags"))
            reason = None
            if files_a & files_b:
                reason = f"both cover files: {', '.join(sorted(files_a & files_b))}"
            elif len(tags_a & tags_b) >= 2:
                reason = f"share tags: {', '.join(sorted(tags_a & tags_b))}"
            if not reason:
                continue
            sim = similarity(toks[a["path"]], toks[b["path"]])
            if sim < REVIEW_CONTRADICTION:
                continue
            contradictions.append(
                {"a": a["path"], "b": b["path"], "reason": reason, "similarity": round(sim, 3)}
            )

    similar = _similar_groups(
        [r for r in active if r["type"] not in ("session", "reminder")], toks
    )

    cut_titles = []
    for r in mems:
        title = (r["title"] or "").strip()
        first = (body_without_title(r["body"] or "").split("\n", 1)[0]).strip()
        if title and first.startswith(title) and len(first) > len(title):
            cut_titles.append(r["path"])

    orphans = []
    for r in mems:
        out = [
            x for x in engine.index.outgoing(r["path"]) if x["dst_path"] not in (None, r["path"])
        ]
        if not out and not engine.index.backlinks(r["path"]):
            orphans.append(r["path"])

    broken = [
        {"path": r["src"], "target": _target(r), "line": r["line"]}
        for r in engine.index.conn.execute(
            "select * from links where dst_path is null or heading_missing = 1 order by src, line"
        )
        if in_scope(r["src"])
    ]

    invalid_fm = []
    for r in engine.index.conn.execute("select path, mode, fm_valid, fm_error from notes"):
        if not in_scope(r["path"]):
            continue
        if not r["fm_valid"]:
            invalid_fm.append({"path": r["path"], "error": r["fm_error"]})
        elif r["mode"] == MEMORY and r["path"] in props:
            try:
                validate(props[r["path"]])
            except EpistemeError as exc:
                invalid_fm.append({"path": r["path"], "error": exc.message})

    flagged = [r["path"] for r in mems if r["flagged"]]
    found: dict[str, list[Any]] = {
        "stale": stale,
        "expired": expired,
        "contradictions": contradictions,
        "similar": similar,
        "cut_titles": cut_titles,
        "orphans": orphans,
        "broken_links": broken,
        "invalid_frontmatter": invalid_fm,
        "flagged": flagged,
    }

    def path_of(item: Any) -> str:
        if isinstance(item, str):
            return item
        return item.get("path") or (item["paths"][0] if "paths" in item else item["a"])

    # Read-only zones are reported apart, with the same categories: they are not the
    # project's to fix, but nothing found there is dropped.
    own = {k: [i for i in v if not is_read_only(path_of(i))] for k, v in found.items()}
    apart = {k: [i for i in v if is_read_only(path_of(i))] for k, v in found.items()}
    out: dict[str, Any] = {"totals": {k: len(v) for k, v in own.items()}}
    out.update({k: v[:limit] for k, v in own.items()})
    out["read_only"] = {
        "totals": {k: len(v) for k, v in apart.items()},
        **{k: v[:limit] for k, v in apart.items()},
    }
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


def _similar_groups(rows: list[Any], token_sets: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Connected components of memories whose dedup tokens reach REVIEW_SIMILAR."""
    toks = [token_sets[r["path"]] for r in rows]
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    best: dict[int, float] = {}
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sim = similarity(toks[i], toks[j])
            if sim >= REVIEW_SIMILAR:
                pairs.append((i, j, sim))
                parent[find(i)] = find(j)
    for i, _, sim in pairs:
        root = find(i)
        best[root] = max(best.get(root, 0.0), sim)
    members: dict[int, list[str]] = {}
    for i in {k for p in pairs for k in p[:2]}:
        members.setdefault(find(i), []).append(rows[i]["path"])
    groups: list[dict[str, Any]] = [
        {"paths": sorted(paths), "similarity": round(best[root], 3)}
        for root, paths in members.items()
    ]
    groups.sort(key=lambda g: (-g["similarity"], g["paths"][0]))
    return groups
