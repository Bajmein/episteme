"""Writing memories: slugs and ``remember``."""

from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import TYPE_CHECKING, Any, NamedTuple

from episteme.errors import invalid
from episteme.index import STOPWORDS_ES
from episteme.markdown import (
    body_without_title,
    compose,
    fold,
)
from episteme.memory.files import _as_list, _files_of
from episteme.memory.revising import _reject_tool_zone
from episteme.memory.schema import (
    DUPLICATE,
    FOLDERS,
    SHARED,
    SIMILAR,
    STOPWORDS_EN,
    TYPES,
    NoteFile,
    _date_arg,
    check_files,
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
from episteme.memory.templates import template_hint
from episteme.vault import MEMORY, today

if TYPE_CHECKING:
    from episteme.engine import Engine

BODY_MAX_CHARS = 100_000
SLUG_WORDS = 5
SLUG_CHARS = 40
MAX_CANDIDATES = 5
MAX_AUTO_LINKS = 3  # how many candidates ``remember(link=True)`` writes into ``related``
MIN_SHARED_TAGS = 2
_SLUG_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z0-9]+")
_SLUG_OK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SLUG_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _join_slug(words: list[str]) -> str:
    picked: list[str] = []
    for word in words:
        if len(picked) == SLUG_WORDS:
            break
        if len("-".join([*picked, word])) <= SLUG_CHARS:
            picked.append(word)
            continue
        if not picked:
            picked.append(word[:SLUG_CHARS].strip("-"))
        break
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


def _active_memories(engine: Engine, project: str) -> list[Any]:
    """Active memories of the project and of the shared zone (all of them for ``SHARED``)."""
    if project == SHARED:
        return engine.index.memories("status = 'active'")
    return engine.index.memories("status = 'active' and project in (?, ?)", (project, SHARED))


def shared_reason(
    my_files: set[str], my_tags: set[str], other_files: set[str], other_tags: set[str]
) -> str | None:
    """Why two memories are worth linking (a shared file or 2+ shared tags), or ``None``."""
    shared_files = sorted(my_files & other_files)
    if shared_files:
        return f"shares file {shared_files[0]}"
    shared_tags = sorted(my_tags & other_tags)
    if len(shared_tags) >= MIN_SHARED_TAGS:
        return f"shares tags {', '.join(shared_tags)}"
    return None


def _match_reason(
    engine: Engine,
    row: Any,
    my_files: set[str],
    my_tags: set[str],
    files: dict[str, list[str]],
) -> str | None:
    """Why a memory is worth linking (a shared file or 2+ shared tags), or ``None``."""
    other_files = set(files.get(row["path"], []))
    if my_files & other_files:
        return shared_reason(my_files, my_tags, other_files, set())
    raw_tags = engine.index.props(row["path"]).get("tags")
    return shared_reason(my_files, my_tags, other_files, set(_as_list(raw_tags)))


def _top_candidates(found: list[tuple[Any, ...]]) -> list[dict[str, str]]:
    """The best ``MAX_CANDIDATES``: priority, then newest, then path (stable sorts)."""
    found.sort(key=lambda f: f[2])
    found.sort(key=lambda f: f[1], reverse=True)
    found.sort(key=lambda f: f[0], reverse=True)
    return [{"path": p, "title": t, "reason": r} for _, _, p, t, r in found[:MAX_CANDIDATES]]


def _link_candidates(
    engine: Engine, project: str, fm: dict[str, Any], skip: set[str]
) -> list[dict[str, str]]:
    """Up to 5 active memories sharing a ``files`` value or 2+ tags with the new one."""
    my_files = set(fm.get("files") or [])
    my_tags = set(fm.get("tags") or [])
    if not my_files and len(my_tags) < MIN_SHARED_TAGS:
        return []
    files = _files_of(engine)
    found: list[tuple[Any, ...]] = []
    for row in _active_memories(engine, project):
        if row["path"] in skip:
            continue
        reason = _match_reason(engine, row, my_files, my_tags, files)
        if reason is None:
            continue
        found.append(
            (row["priority"] or 0, row["created"] or "", row["path"], row["title"], reason)
        )
    return _top_candidates(found)


class _Links(NamedTuple):
    related: list[str]
    old_rel: str | None
    old_note: NoteFile | None


def _memory_zone(engine: Engine) -> Any:
    """The vault's memory zone, or an error if it has none."""
    zone = engine.vault.memory_zone
    if zone is None:
        raise invalid('the vault has no zone with mode = "memory". Declare one in episteme.toml.')
    return zone


def _check_type(type: str) -> None:
    if type not in TYPES:
        raise schema_error(f"type must be one of {', '.join(TYPES)}, got {type!r}.")


def _clean_title(title: str) -> str:
    """The title with its whitespace collapsed; an error if it is empty."""
    title = " ".join((title or "").split())
    if not title:
        raise invalid("title is empty. Pass a short title.")
    return title


def _check_body(body: str) -> None:
    if not (body or "").strip():
        raise invalid("body is empty. Describe the memory and name the files or tools involved.")
    if len(body) > BODY_MAX_CHARS:
        raise invalid(
            f"body has {len(body)} characters, the limit is {BODY_MAX_CHARS}. "
            "Shorten it or split it into several memories."
        )


def _reject_all_secrets(fields: tuple[tuple[str, Any], ...]) -> None:
    for field, value in fields:
        _reject_secrets(field, value)


def _check_args(
    engine: Engine,
    type: str,
    title: str,
    body: str,
    secret_fields: tuple[tuple[str, Any], ...],
) -> tuple[Any, str]:
    """Validate the arguments and return the memory zone and the cleaned title."""
    zone = _memory_zone(engine)
    _check_type(type)
    title = _clean_title(title)
    _check_body(body)
    _reject_all_secrets((("title", title), ("body", body), *secret_fields))
    return zone, title


def _resolve_links(engine: Engine, related: list[str] | None, supersedes: str | None) -> _Links:
    """Resolve ``related`` to wikilinks and mark the superseded memory (not yet saved)."""
    related_links = [wikilink(engine, engine.resolve_note(r)) for r in related or []]
    if not supersedes:
        return _Links(related_links, None, None)
    old_rel = engine.resolve_note(supersedes)
    if engine.vault.check_writable(old_rel) != MEMORY:
        raise invalid(f"{old_rel} is not a memory, so it cannot be superseded.")
    old_note = NoteFile(engine, old_rel)
    old_note.set_fields({"status": "superseded"})
    validate(old_note.fm)
    return _Links(related_links, old_rel, old_note)


def _clean_body(body: str) -> str:
    """The body without its leading ``# title`` line, which ``remember`` writes itself."""
    text_body = body.strip()
    if text_body.split("\n", 1)[0].strip().startswith("# "):
        return body_without_title(text_body)
    return text_body


def _similar_item(row: Any, score: float) -> dict[str, Any]:
    return {
        "path": row["path"],
        "title": row["title"],
        "similarity": round(score, 3),
        "type": row["type"],
        "project": row["project"],
    }


def _blocks(row: Any, score: float, project: str, type: str) -> bool:
    """Whether a close memory is a duplicate that blocks the save."""
    return score >= DUPLICATE and row["project"] == project and row["type"] == type


def _better_blocker(item: dict[str, Any], blocking: dict[str, Any] | None) -> bool:
    """Whether ``item`` is closer than the current blocker (ties go to the first path)."""
    if blocking is None:
        return True
    return (-item["similarity"], item["path"]) < (-blocking["similarity"], blocking["path"])


def _find_similar(
    engine: Engine, project: str, type: str, title: str, text_body: str, old_rel: str | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Memories close to the new one, and the closest duplicate that blocks the save."""
    mine = dedup_tokens(title, text_body)
    similar: list[dict[str, Any]] = []
    blocking: dict[str, Any] | None = None
    for row in _active_memories(engine, project):
        if row["path"] == old_rel:
            continue
        theirs = dedup_tokens(row["title"] or "", body_without_title(row["body"]))
        score = similarity(mine, theirs)
        if score < SIMILAR:
            continue
        item = _similar_item(row, score)
        similar.append(item)
        if _blocks(row, score, project, type) and _better_blocker(item, blocking):
            blocking = item
    similar.sort(key=lambda s: (-s["similarity"], s["path"]))
    return similar, blocking


def _duplicate_reply(similar: list[dict[str, Any]], blocking: dict[str, Any]) -> dict[str, Any]:
    """The answer when a near-duplicate blocks the save: nothing is written."""
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


KEYWORDS_HINT = (
    "No keywords. Add the other words people use for this (synonyms, abbreviations, "
    'full names) with revise(action="set", fields={"keywords": [...]}): '
    "search matches whole words."
)


def _needs_keywords_hint(fm: dict[str, Any]) -> bool:
    """True for a memory saved without keywords, unless it is a session or a reminder."""
    return not fm.get("keywords") and fm.get("type") not in ("session", "reminder")


LINKS_HINT = (
    'No links. Link it to the memories it builds on or belongs with: revise(action="set", '
    'fields={"related": ["[[name]]"]}). Pick from link_candidates, or search for them.'
)


def _needs_links_hint(fm: dict[str, Any], body: str) -> bool:
    """True for a memory with no related, no supersedes and no wikilink in the body."""
    if fm.get("type") in ("session", "reminder"):
        return False
    return not fm.get("related") and not fm.get("supersedes") and "[[" not in body


def _body_hints(fm: dict[str, Any], text_body: str) -> dict[str, str]:
    """Hints about the body: no links at all, or sections of the type's template missing."""
    hints: dict[str, str] = {}
    if _needs_links_hint(fm, text_body):
        hints["links_hint"] = LINKS_HINT
    template = template_hint(fm["type"], text_body)
    if template:
        hints["template_hint"] = template
    return hints


def _extras(engine: Engine, fm: dict[str, Any], candidates: list[dict[str, str]]) -> dict[str, Any]:
    """Hints for the caller: tags no other note has and memories worth linking."""
    extras: dict[str, Any] = {}
    new_tags = _new_tags(engine, fm.get("tags") or [])
    if new_tags:
        extras["new_tags"] = new_tags
    if candidates:
        extras["link_candidates"] = candidates
    if _needs_keywords_hint(fm):
        extras["keywords_hint"] = KEYWORDS_HINT
    return extras


def _numbered_rel(folder: str, base: str, n: int) -> str:
    """Path of the n-th try for a file name: ``base.md``, ``base-2.md``, ``base-3.md``..."""
    return f"{folder}/{base}.md" if n == 1 else f"{folder}/{base}-{n}.md"


def _first_free_rel(engine: Engine, folder: str, base: str) -> str:
    """Path of the first numbered name that does not exist yet."""
    n = 1
    while engine.vault.resolve(_numbered_rel(folder, base, n)).exists():
        n += 1
    return _numbered_rel(folder, base, n)


def _create_numbered(engine: Engine, folder: str, base: str, content: str) -> str:
    """Create the file under the first numbered name nobody took meanwhile."""
    n = 1
    while True:
        rel = _numbered_rel(folder, base, n)
        if not engine.vault.resolve(rel).exists() and engine.vault.create_exclusive(rel, content):
            return rel
        n += 1


def _write_new(engine: Engine, folder: str, base: str, content: str, dry_run: bool) -> str:
    """Create the file under the first free numbered name (only look for it if ``dry_run``)."""
    if dry_run:
        return _first_free_rel(engine, folder, base)
    return _create_numbered(engine, folder, base, content)


def _frontmatter(engine: Engine, raw: dict[str, Any], links: _Links) -> dict[str, Any]:
    """Normalise the raw fields of a new memory, then put them in key order and validate."""
    priority = raw["priority"]
    fm = ordered(
        {
            **raw,
            "kind": kind_for(raw["type"]),
            "priority": priority if priority is not None else default_priority(raw["type"]),
            "valid_until": _date_arg("valid_until", raw["valid_until"]),
            "tags": [t.strip().lstrip("#") for t in raw["tags"] or []],
            "keywords": [k.strip() if isinstance(k, str) else k for k in raw["keywords"] or []],
            "files": list(raw["files"] or []),
            "supersedes": wikilink(engine, links.old_rel) if links.old_rel else None,
            "related": links.related,
            "due": _date_arg("due", raw["due"]),
        }
    )
    validate(fm)
    return fm


def _skip_paths(engine: Engine, related: list[str] | None, links: _Links) -> set[str]:
    """Paths that are already linked and so are not suggested as link candidates."""
    skip = {engine.resolve_note(r) for r in related or []}
    if links.old_rel:
        skip.add(links.old_rel)
    return skip


def _persist(
    engine: Engine,
    folder: str,
    base: str,
    content: str,
    links: _Links,
    dry_run: bool,
) -> str:
    """Write the memory, index it and save the superseded one (never on a dry run)."""
    mode = engine.vault.check_writable(f"{folder}/{base}.md")
    _reject_tool_zone(f"{folder}/{base}.md", mode)  # a symlinked folder into a docs zone
    rel = _write_new(engine, folder, base, content, dry_run)
    if dry_run:
        return rel
    engine.index.reindex(rel)
    if links.old_note is not None:
        links.old_note.save()
    return rel


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
    link: bool = False,
) -> dict[str, Any]:
    """Create a memory. ``created``, ``helpful`` and ``dry_run`` are for the OMEGA migration.

    With ``link=True`` the best link candidates (up to ``MAX_AUTO_LINKS``) go into the new
    memory's ``related`` and the reply lists them under ``linked``.
    """
    project = engine.need_project(project)
    check_files(files)
    secret_fields = (
        ("keywords", keywords),
        ("source", source),
        ("tags", tags),
        ("files", files),
        ("project", project),
    )
    zone, title = _check_args(engine, type, title, body, secret_fields)

    slug = _check_slug(slug) if slug is not None else memory_slug(title, project, type)
    links = _resolve_links(engine, related, supersedes)

    created = created or today()
    raw = {
        "type": type,
        "project": project,
        "priority": priority,
        "status": status,
        "created": created,
        "valid_until": valid_until,
        "tags": tags,
        "keywords": keywords,
        "files": files,
        "source": source,
        "helpful": helpful,
        "due": due,
    }
    fm = _frontmatter(engine, raw, links)

    text_body = _clean_body(body)
    similar, blocking = _find_similar(engine, project, type, title, text_body, links.old_rel)
    if blocking is not None and not force:
        return _duplicate_reply(similar, blocking)
    candidates = _link_candidates(engine, project, fm, _skip_paths(engine, related, links))
    linkable = link and type not in ("session", "reminder")
    linked = [c["path"] for c in candidates[:MAX_AUTO_LINKS]] if linkable else []
    if linked:
        links = links._replace(related=[*links.related, *(wikilink(engine, p) for p in linked)])
        fm = _frontmatter(engine, raw, links)
        candidates = candidates[len(linked) :]
    extras = _extras(engine, fm, candidates)
    extras.update(_body_hints(fm, text_body))
    if link:
        extras["linked"] = linked

    content = compose(fm, f"# {title}\n\n{text_body}\n")
    folder = f"{zone.path}/{project}/{FOLDERS[type]}"
    base = f"{created.isoformat()}-{slug}"
    rel = _persist(engine, folder, base, content, links, dry_run)
    if dry_run:
        return {"created": True, "path": rel, "similar": similar, "dry_run": True, **extras}
    return {"created": True, "path": rel, "similar": similar, **extras}
