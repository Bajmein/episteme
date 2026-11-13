"""Writing memories: slugs and ``remember``."""

from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.index import STOPWORDS_ES
from episteme.markdown import (
    body_without_title,
    compose,
    fold,
)
from episteme.memory.files import _as_list, _files_of
from episteme.memory.schema import (
    DUPLICATE,
    FOLDERS,
    SHARED,
    SIMILAR,
    STOPWORDS_EN,
    TYPES,
    NoteFile,
    _date_arg,
    dedup_tokens,
    default_priority,
    kind_for,
    ordered,
    schema_error,
    similarity,
    validate,
    wikilink,
)
from episteme.memory.secrets import _reject_secrets
from episteme.vault import MEMORY, today

if TYPE_CHECKING:
    from episteme.engine import Engine

SLUG_WORDS = 5
SLUG_CHARS = 40
_SLUG_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z0-9]+")
_SLUG_OK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SLUG_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _join_slug(words: list[str]) -> str:
    picked: list[str] = []
    for word in words:
        if len(picked) == SLUG_WORDS:
            break
        if len("-".join([*picked, word])) > SLUG_CHARS:
            if not picked:
                picked.append(word[:SLUG_CHARS].strip("-"))
            break
        picked.append(word)
    return "-".join(picked)


def memory_slug(title: str, project: str, type: str) -> str:
    """Short file-name slug: up to 5 useful words, 40 characters, never cut mid-word."""
    found = [re.sub(r"[.,]", "-", t) for t in _SLUG_TOKEN.findall(fold(title))]
    in_path = {*re.findall(r"[a-z0-9]+", fold(project)), type, FOLDERS.get(type, type)}
    skip = STOPWORDS_ES | STOPWORDS_EN | in_path
    useful = [t for t in found if t not in skip and not (len(t) == 1 and t.isalpha())]
    return _join_slug(useful) or _join_slug(found) or "note"


def _check_slug(slug: str) -> str:
    if not (_SLUG_OK.fullmatch(slug) and len(slug) <= SLUG_CHARS and not _SLUG_DATE.match(slug)):
        raise invalid(
            f'slug "{slug}" is not valid. Use 1-{SLUG_CHARS} lowercase ASCII letters, digits '
            "and single hyphens, without the date, e.g. checkpoint-fuera-de-change."
        )
    return slug


def _new_tags(engine: Engine, tags: list[str]) -> list[dict[str, Any]]:
    """Tags no other note has, each with up to 3 close existing spellings."""
    existing = {r["tag"] for r in engine.index.conn.execute("select distinct tag from tags")}
    return [
        {"tag": t, "similar": difflib.get_close_matches(t, sorted(existing), n=3, cutoff=0.75)}
        for t in dict.fromkeys(tags)
        if t not in existing
    ]


def _link_candidates(
    engine: Engine, project: str, fm: dict[str, Any], skip: set[str]
) -> list[dict[str, str]]:
    """Up to 5 active memories sharing a ``files`` value or 2+ tags with the new one."""
    my_files = set(fm.get("files") or [])
    my_tags = set(fm.get("tags") or [])
    if not my_files and len(my_tags) < 2:
        return []
    if project == SHARED:
        rows = engine.index.memories("status = 'active'")
    else:
        rows = engine.index.memories(
            "status = 'active' and project in (?, ?)", (project, SHARED)
        )
    files = _files_of(engine)
    found = []
    for row in rows:
        if row["path"] in skip:
            continue
        shared_files = sorted(my_files & set(files.get(row["path"], [])))
        raw_tags = engine.index.props(row["path"]).get("tags")
        shared_tags = sorted(my_tags & set(_as_list(raw_tags)))
        if shared_files:
            reason = f"shares file {shared_files[0]}"
        elif len(shared_tags) >= 2:
            reason = f"shares tags {', '.join(shared_tags)}"
        else:
            continue
        found.append(
            (row["priority"] or 0, row["created"] or "", row["path"], row["title"], reason)
        )
    found.sort(key=lambda f: f[2])
    found.sort(key=lambda f: f[1], reverse=True)
    found.sort(key=lambda f: f[0], reverse=True)
    return [{"path": p, "title": t, "reason": r} for _, _, p, t, r in found[:5]]


def remember(
    engine: Engine,
    type: str,
    title: str,
    body: str,
    project: str | None = None,
    priority: int | None = None,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    related: list[str] | None = None,
    supersedes: str | None = None,
    source: str | None = None,
    due: str | None = None,
    valid_until: str | None = None,
    status: str = "active",
    force: bool = False,
    *,
    created: dt.date | None = None,
    helpful: int = 0,
    dry_run: bool = False,
    slug: str | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Create a memory. ``created``, ``helpful`` and ``dry_run`` are for the OMEGA migration."""
    project = engine.need_project(project)
    zone = engine.vault.memory_zone
    if zone is None:
        raise invalid('the vault has no zone with mode = "memory". Declare one in episteme.toml.')
    if type not in TYPES:
        raise schema_error(f"type must be one of {', '.join(TYPES)}, got {type!r}.")
    title = " ".join((title or "").split())
    if not title:
        raise invalid("title is empty. Pass a short title.")
    if not (body or "").strip():
        raise invalid("body is empty. Describe the memory and name the files or tools involved.")

    for field, value in (
        ("title", title),
        ("body", body),
        ("keywords", keywords),
        ("source", source),
        ("tags", tags),
        ("files", files),
    ):
        _reject_secrets(field, value)

    slug = _check_slug(slug) if slug is not None else memory_slug(title, project, type)
    related_links = [wikilink(engine, engine.resolve_note(r)) for r in related or []]
    old_rel = None
    old_note = None
    if supersedes:
        old_rel = engine.resolve_note(supersedes)
        if engine.vault.check_writable(old_rel) != MEMORY:
            raise invalid(f"{old_rel} is not a memory, so it cannot be superseded.")
        old_note = NoteFile(engine, old_rel)
        old_note.set_fields({"status": "superseded"})
        validate(old_note.fm)

    created = created or today()
    fm = ordered(
        {
            "type": type,
            "kind": kind_for(type),
            "project": project,
            "priority": priority if priority is not None else default_priority(type),
            "status": status,
            "created": created,
            "valid_until": _date_arg("valid_until", valid_until),
            "tags": [t.strip().lstrip("#") for t in tags or []],
            "keywords": [k.strip() if isinstance(k, str) else k for k in keywords or []],
            "files": list(files or []),
            "supersedes": wikilink(engine, old_rel) if old_rel else None,
            "related": related_links,
            "source": source,
            "helpful": helpful,
            "due": _date_arg("due", due),
        }
    )
    validate(fm)

    text_body = body.strip()
    first = text_body.split("\n", 1)[0].strip()
    if first.startswith("# "):
        text_body = body_without_title(text_body)
    mine = dedup_tokens(title, text_body)
    similar = []
    blocking = None
    if project == SHARED:
        rows = engine.index.memories("status = 'active'")
    else:
        rows = engine.index.memories(
            "status = 'active' and project in (?, ?)", (project, SHARED)
        )
    for row in rows:
        if row["path"] == old_rel:
            continue
        theirs = dedup_tokens(row["title"] or "", body_without_title(row["body"]))
        score = similarity(mine, theirs)
        if score >= SIMILAR:
            item = {
                "path": row["path"],
                "title": row["title"],
                "similarity": round(score, 3),
                "type": row["type"],
                "project": row["project"],
            }
            similar.append(item)
            if score >= DUPLICATE and row["project"] == project and row["type"] == type:
                if blocking is None or (-item["similarity"], item["path"]) < (
                    -blocking["similarity"],
                    blocking["path"],
                ):
                    blocking = item
    similar.sort(key=lambda s: (-s["similarity"], s["path"]))
    if blocking is not None and not force:
        similar.remove(blocking)
        similar.insert(0, blocking)
        hint = (
            f"Already saved as {blocking['path']}. If it happened again, "
            f'revise(note="{blocking["path"]}", action="feedback", value="helpful"). '
            "If it changed, call remember again with "
            f'supersedes="{blocking["path"]}". '
            "Use force=true only for a genuinely different memory."
        )
        return {"created": False, "path": None, "similar": similar, "hint": hint}
    extras: dict[str, Any] = {}
    new_tags = _new_tags(engine, fm.get("tags") or [])
    if new_tags:
        extras["new_tags"] = new_tags
    skip = {engine.resolve_note(r) for r in related or []}
    if old_rel:
        skip.add(old_rel)
    candidates = _link_candidates(engine, project, fm, skip)
    if candidates:
        extras["link_candidates"] = candidates

    content = compose(fm, f"# {title}\n\n{text_body}\n")
    folder = f"{zone.path}/{project}/{FOLDERS[type]}"
    base = f"{created.isoformat()}-{slug}"
    engine.vault.check_writable(f"{folder}/{base}.md")
    n = 1
    if dry_run:
        while engine.vault.resolve(f"{folder}/{base}{'' if n == 1 else f'-{n}'}.md").exists():
            n += 1
        path = f"{folder}/{base}{'' if n == 1 else f'-{n}'}.md"
        return {"created": True, "path": path, "similar": similar, "dry_run": True, **extras}
    while True:
        rel = f"{folder}/{base}.md" if n == 1 else f"{folder}/{base}-{n}.md"
        if not engine.vault.resolve(rel).exists() and engine.vault.create_exclusive(rel, content):
            break
        n += 1
    engine.index.reindex(rel)

    if old_note is not None:
        old_note.save()
    return {"created": True, "path": rel, "similar": similar, **extras}
