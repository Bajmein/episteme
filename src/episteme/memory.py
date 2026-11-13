"""Memory: schema, remember, revise, review, welcome and surface."""

from __future__ import annotations

import datetime as dt
import difflib
import fnmatch
import json
import math
import os
import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.errors import INVALID_SCHEMA, NOT_FOUND, EpistemeError, invalid
from episteme.index import STOPWORDS_ES, as_date, as_int
from episteme.markdown import (
    body_without_title,
    clip,
    compose,
    dump_frontmatter,
    find_section,
    first_sentence,
    fold,
    load_frontmatter,
    parse,
    split_frontmatter,
    tokens,
)
from episteme.vault import MEMORY, READ_ONLY, today

if TYPE_CHECKING:
    from episteme.engine import Engine

FOLDERS = {
    "decision": "decisions",
    "lesson": "lessons",
    "error": "errors",
    "constraint": "constraints",
    "preference": "preferences",
    "session": "sessions",
    "reminder": "reminders",
    "insight": "insights",
}
TYPES = tuple(FOLDERS)
STATUSES = ("active", "superseded", "speculative", "archived")
KEY_ORDER = (
    "type",
    "kind",
    "project",
    "priority",
    "status",
    "created",
    "valid_until",
    "tags",
    "keywords",
    "files",
    "supersedes",
    "related",
    "contradicts",
    "source",
    "helpful",
    "due",
    "flagged",
)
OMIT_WHEN_EMPTY = {
    "valid_until",
    "due",
    "source",
    "supersedes",
    "related",
    "contradicts",
    "tags",
    "keywords",
    "files",
}
DUPLICATE = 0.8
SHARED = "_shared"
KEYWORD_CHARS = 60
KEYWORDS_MAX = 12
SIMILAR = 0.5
MIN_CONTEXT_SCORE = 0.25  # task context: memories and notes below this are left out
ACTIONS = ("edit", "append", "set", "supersede", "feedback", "archive", "dismiss")
MEMORY_ACTIONS = ("supersede", "feedback", "archive", "dismiss")
UPCOMING_DAYS = 7
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"(?<![A-Za-z0-9_-])(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_-])gh[pousr]_[A-Za-z0-9]{36}")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_-])github_pat_[A-Za-z0-9_]{22,}")),
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")),
    ("API key", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9]{32,}")),
    ("Stripe live key", re.compile(r"(?<![A-Za-z0-9_-])sk_live_[A-Za-z0-9]{16,}")),
    ("npm token", re.compile(r"(?<![A-Za-z0-9_-])npm_[A-Za-z0-9]{36}")),
    ("Hugging Face token", re.compile(r"(?<![A-Za-z0-9_-])hf_[A-Za-z0-9]{30,}")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9_-])xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}")),
    (
        "JWT",
        re.compile(
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{7,}\.eyJ[A-Za-z0-9_-]{7,}\.[A-Za-z0-9_-]{10,}"
        ),
    ),
)
_URL_CREDENTIALS = re.compile(r"://[^\s/:@]+:([^\s/@]{6,})@")
_PLACEHOLDER_PASSWORDS = {
    "pass",
    "password",
    "passwd",
    "clave",
    "secret",
    "changeme",
    "example",
    "redacted",
    "your_password",
    "your-password",
    "yourpassword",
    "contraseña",
    "tu_clave",
}


def _is_placeholder(password: str) -> bool:
    return (
        password[0] in "<${[%*"
        or set(password) <= {"*", "x", "X", "."}
        or password.lower() in _PLACEHOLDER_PASSWORDS
    )


def find_secrets(text: str) -> str | None:
    """Name of the first credential type found in ``text`` (never the value), else None."""
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return name
    for m in _URL_CREDENTIALS.finditer(text):
        if not _is_placeholder(m.group(1)):
            return "password in URL"
    return None


def _reject_secrets(field: str, value: Any) -> None:
    values = value if isinstance(value, list) else [value]
    for item in values:
        found = find_secrets(item) if isinstance(item, str) else None
        if found:
            raise invalid(
                f"{field} looks like a secret ({found}). "
                "Remove it and say where it is stored instead."
            )


def kind_for(type_: str) -> str:
    if type_ == "session":
        return "episodic"
    if type_ in ("lesson", "error", "constraint"):
        return "procedural"
    return "semantic"


def default_priority(type_: str) -> int:
    return 4 if type_ in ("decision", "constraint") else 3


def schema_error(message: str) -> EpistemeError:
    return EpistemeError(INVALID_SCHEMA, message)


def _is_date(value: Any) -> bool:
    return isinstance(value, dt.date) or (
        isinstance(value, str) and as_date(value) is not None and len(value.strip()) == 10
    )


def validate(fm: dict[str, Any]) -> None:
    """Check a memory's frontmatter; raise ``invalid_schema`` naming the field."""
    type_ = fm.get("type")
    if type_ not in TYPES:
        raise schema_error(f"type must be one of {', '.join(TYPES)}, got {type_!r}.")
    project = fm.get("project")
    if not isinstance(project, str) or not project.strip():
        raise schema_error("project is required.")
    if "/" in project or "\\" in project or project in (".", ".."):
        raise schema_error(f'project must be a plain name without "/" or "..", got {project!r}.')
    priority = fm.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
        raise schema_error(f"priority must be 1-5, got {priority!r}.")
    if fm.get("status") not in STATUSES:
        raise schema_error(
            f"status must be one of {', '.join(STATUSES)}, got {fm.get('status')!r}."
        )
    if not _is_date(fm.get("created")):
        raise schema_error(f"created must be a date YYYY-MM-DD, got {fm.get('created')!r}.")
    for key in ("due", "valid_until"):
        if fm.get(key) is not None and not _is_date(fm[key]):
            raise schema_error(f"{key} must be a date YYYY-MM-DD, got {fm[key]!r}.")
    if type_ == "reminder" and fm.get("due") is None:
        raise schema_error("reminder needs due (YYYY-MM-DD).")
    for key in ("files", "tags", "keywords"):
        value = fm.get(key)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(v, str) for v in value)
        ):
            raise schema_error(f"{key} must be a list of strings.")
    keywords = fm.get("keywords") or []
    if any(not k.strip() or len(k) > KEYWORD_CHARS for k in keywords):
        raise schema_error(
            f"keywords must be non-empty strings of at most {KEYWORD_CHARS} characters."
        )
    if len(keywords) > KEYWORDS_MAX:
        raise schema_error(f"keywords has {len(keywords)} items; the limit is {KEYWORDS_MAX}.")
    for tag in fm.get("tags") or []:
        if not tag or any(c in tag for c in ": #\t"):
            raise schema_error(
                f'tag "{tag}" has ":", "#" or spaces. Nest tags with "/", e.g. dominio/auth.'
            )
    helpful = fm.get("helpful")
    if helpful is not None and (
        isinstance(helpful, bool) or not isinstance(helpful, int) or helpful < 0
    ):
        raise schema_error(f"helpful must be an integer >= 0, got {helpful!r}.")
    if fm.get("flagged") is not None and not isinstance(fm["flagged"], bool):
        raise schema_error("flagged must be true or false.")


def ordered(fm: dict[str, Any]) -> dict[str, Any]:
    """Schema key order; empty optional keys dropped; unknown keys kept at the end."""
    out: dict[str, Any] = {}
    for key in KEY_ORDER:
        if key not in fm:
            continue
        value = fm[key]
        if key in OMIT_WHEN_EMPTY and value in (None, "", []):
            continue
        if key == "flagged" and value is False:
            continue
        out[key] = value
    for key, value in fm.items():
        if key not in out and key not in KEY_ORDER:
            out[key] = value
    return out


def _date_arg(name: str, value: str | None) -> dt.date | None:
    if value is None or value == "":
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except (ValueError, AttributeError) as exc:
        raise schema_error(f"{name} must be a date YYYY-MM-DD, got {value!r}.") from exc


def similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_tokens(title: str, body: str) -> set[str]:
    toks = tokens(f"{title}\n{body}", min_len=3)
    return {t for t in toks if t not in STOPWORDS_ES}


def wikilink(engine: Engine, rel: str) -> str:
    """``[[name]]`` when the bare name resolves back to ``rel``, else ``[[path]]``."""
    stem = PurePosixPath(rel).name.removesuffix(".md")
    target = stem if engine.index.resolver().resolve_quiet(stem) == rel else rel[:-3]
    return f"[[{target}]]"


# -- writing notes -------------------------------------------------------


class NoteFile:
    """A note split into raw frontmatter and body, so a body edit keeps the YAML byte-exact."""

    def __init__(self, engine: Engine, rel: str) -> None:
        self.engine = engine
        self.rel = rel
        text = engine.vault.resolve(rel).read_text(encoding="utf-8")
        text = text.replace("\r\n", "\n")
        lines = text.split("\n")
        raw, fm_end = split_frontmatter(lines)
        self.fm_end = fm_end
        self.head = "\n".join(lines[:fm_end]) + "\n" if fm_end else ""
        self.body = "\n".join(lines[fm_end:])
        self.fm, self.fm_valid, self.fm_error = load_frontmatter(raw)
        self.fm_changed = False

    def set_fields(self, fields: dict[str, Any]) -> list[str]:
        if not self.fm_valid:
            raise invalid(
                f"{self.rel} has invalid frontmatter ({self.fm_error}). Fix the YAML by hand first."
            )
        changed = []
        for key, value in fields.items():
            if value is None:
                if key in self.fm:
                    del self.fm[key]
                    changed.append(key)
            elif self.fm.get(key) != value:
                self.fm[key] = value
                changed.append(key)
        self.fm_changed = self.fm_changed or bool(changed)
        return changed

    def text(self) -> str:
        if self.fm_changed:
            fm = ordered(self.fm) if self.engine.vault.mode_for(self.rel) == MEMORY else self.fm
            head = dump_frontmatter(fm) if fm else ""
        else:
            head = self.head
        return head + self.body

    def save(self) -> None:
        if self.engine.vault.mode_for(self.rel) == MEMORY:
            validate(self.fm)
        self.engine.vault.write_atomic(self.rel, self.text())
        self.engine.index.reindex(self.rel)


# -- remember ------------------------------------------------------------

STOPWORDS_EN = frozenset(
    """a an the and or of to in on at for with by from is are was be as it its this that into
    about vs via not""".split()
)
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
        rows = engine.index.memories("status = 'active' and project in (?, ?)", (project, SHARED))
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


# -- revise --------------------------------------------------------------


def revise(
    engine: Engine,
    note: str,
    action: str,
    old: str | None = None,
    new: str | None = None,
    text: str | None = None,
    heading: str | None = None,
    fields: dict[str, Any] | None = None,
    by: str | None = None,
    value: str | None = None,
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise invalid(f"action must be one of {', '.join(ACTIONS)}, got {action!r}.")
    rel = engine.resolve_note(note)
    mode = engine.vault.check_writable(rel)
    if action in MEMORY_ACTIONS and mode != MEMORY:
        raise invalid(f'action "{action}" only applies to memories, and {rel} is not one.')
    nf = NoteFile(engine, rel)
    result: dict[str, Any] = {"path": rel, "action": action, "changed": []}

    if action == "edit":
        if not old or new is None:
            raise invalid("edit needs old (text to replace) and new.")
        if find_secrets(new) != find_secrets(old):  # editing around an old false positive is fine
            _reject_secrets("new", new)
        count = nf.body.count(old)
        if count != 1:
            raise invalid(
                f"old appears {count} times in {rel}; it must appear exactly once. "
                "Include more surrounding text."
            )
        nf.body = nf.body.replace(old, new, 1)
        result["changed"] = ["body"]
    elif action == "append":
        if not text:
            raise invalid("append needs text.")
        _reject_secrets("text", text)
        nf.body = _append(nf, text, heading)
        result["changed"] = ["body"]
    elif action == "set":
        if not fields:
            raise invalid('set needs fields, e.g. {"priority": 5}.')
        for key, value_ in fields.items():
            _reject_secrets(f"fields.{key}", value_)
        fields = {k: _coerce(k, v) for k, v in fields.items()}
        result["changed"] = nf.set_fields(fields)
        if mode == MEMORY and {"type", "project"} & set(result["changed"]):
            if "type" in result["changed"] and nf.fm.get("type") in TYPES:
                result["changed"] += nf.set_fields({"kind": kind_for(nf.fm["type"])})
            moved = _move_memory(engine, nf)
            if moved != rel:
                result["path"] = moved
                result["moved_from"] = rel
                return result
    elif action == "supersede":
        if not by:
            raise invalid("supersede needs by (the note that replaces this one).")
        by_rel = engine.resolve_note(by)
        if by_rel == rel:
            raise invalid("a note cannot supersede itself.")
        if engine.vault.check_writable(by_rel) != MEMORY:
            raise invalid(f"{by_rel} is not a memory. Create the replacement with remember.")
        newer = NoteFile(engine, by_rel)
        link = wikilink(engine, rel)
        current = newer.fm.get("supersedes")
        if current and current != link:
            current = current if isinstance(current, list) else [current]
            link_value: Any = current + ([link] if link not in current else [])
        else:
            link_value = link
        result["changed"] = nf.set_fields({"status": "superseded"})
        newer.set_fields({"supersedes": link_value})
        validate(nf.fm)
        validate(newer.fm)
        nf.save()
        newer.save()
        result["by"] = by_rel
        return result
    elif action == "feedback":
        if value not in ("helpful", "unhelpful", "outdated"):
            raise invalid('feedback value must be "helpful", "unhelpful" or "outdated".')
        current = nf.fm.get("helpful")
        helpful = as_int(current) or 0
        if value == "helpful":
            result["changed"] = nf.set_fields({"helpful": helpful + 1})
        elif value == "unhelpful":
            result["changed"] = nf.set_fields({"helpful": max(0, helpful - 1)})
        else:
            result["changed"] = nf.set_fields({"flagged": True})
    elif action == "archive":
        result["changed"] = nf.set_fields({"status": "archived"})
    elif action == "dismiss":
        if nf.fm.get("type") != "reminder":
            raise invalid(f"dismiss only applies to reminders, and {rel} is not one.")
        result["changed"] = nf.set_fields({"status": "archived"})

    nf.save()
    return result


def _move_memory(engine: Engine, nf: NoteFile) -> str:
    """Save a memory whose type or project changed in ``<zone>/<project>/<type folder>/``.

    The file name stays, so ``[[name]]`` links keep resolving. Links written as a path would
    break, so they block the move, and so does a file with the same name in the new folder.
    """
    validate(nf.fm)
    zone = engine.vault.memory_zone
    assert zone is not None  # nf is in a memory zone
    name = PurePosixPath(nf.rel).name
    new_rel = f"{zone.path}/{nf.fm['project']}/{FOLDERS[nf.fm['type']]}/{name}"
    if new_rel == nf.rel:
        return nf.rel  # revise saves it in place
    by_path = sorted(
        {
            r["src"]
            for r in engine.index.conn.execute(
                "select src, dst_raw from links where dst_path = ? and src != ?",
                (nf.rel, nf.rel),
            )
            if "/" in (r["dst_raw"] or "")
        }
    )
    if by_path:
        raise invalid(
            f"{', '.join(by_path)} link to {nf.rel} by path, and moving it to {new_rel} would "
            f"break them. Change those links to [[{name.removesuffix('.md')}]] first."
        )
    engine.vault.check_writable(new_rel)
    if not engine.vault.create_exclusive(new_rel, nf.text()):
        raise invalid(
            f"{new_rel} already exists, so {nf.rel} cannot move there. "
            "Supersede one of them, or rename one in Obsidian."
        )
    engine.vault.remove(nf.rel)
    engine.index.reindex(nf.rel)
    engine.index.reindex(new_rel)
    return new_rel


def _coerce(key: str, value: Any) -> Any:
    """Dates given as strings in ``set`` are stored as YAML dates."""
    if key in ("created", "due", "valid_until") and isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return value
    return value


def _append(nf: NoteFile, text: str, heading: str | None) -> str:
    addition = text.strip("\n")
    lines = nf.body.rstrip("\n").split("\n") if nf.body.strip() else []
    if heading is None:
        return "\n".join(lines + ([""] if lines else []) + [addition]) + "\n"
    parsed = parse(nf.head + nf.body, nf.rel)
    rng = find_section(parsed, heading)
    if rng is None:
        names = ", ".join(f'"{h.text}"' for h in parsed.headings)
        raise EpistemeError(
            NOT_FOUND, f'no heading "{heading}" in {nf.rel}. Headings are: {names or "none"}.'
        )
    start, end = rng[0] - nf.fm_end, min(rng[1] - nf.fm_end, len(lines))
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    tail = lines[end:]
    insert = ["", addition] + ([""] if tail else [])
    return "\n".join(lines[:last] + insert + tail) + "\n"


# -- scoring helpers (welcome, task context) -----------------------------


def days_since(created: str | None, now: dt.date) -> int:
    if not created:
        return 0
    try:
        return max(0, (now - dt.date.fromisoformat(created)).days)
    except ValueError:
        return 0


def recency(created: str | None, now: dt.date) -> float:
    return math.exp(-days_since(created, now) / 30)


def welcome_score(row: Any, now: dt.date) -> float:
    priority = row["priority"] or 1
    helpful = row["helpful"] or 0
    return (
        0.45 * (priority - 1) / 4
        + 0.35 * recency(row["created"], now)
        + 0.20 * min(helpful, 10) / 10
    )


def entry_line(row: Any) -> str:
    sentence = first_sentence(row["body"] or "")
    tail = f" — {sentence}" if sentence else ""
    return f"- [{row['type']} p{row['priority']}] {row['title']} ({row['path']}){tail}"


SHARED_MAX = 3  # welcome: most `_shared` memories listed ahead of the project's own


def welcome(
    engine: Engine, project: str | None, upcoming_days: int = UPCOMING_DAYS
) -> tuple[str, list[dict[str, Any]]]:
    """The welcome text (4000 chars max).

    Sections, in order: overdue reminders, "Normas" (every active priority-5 memory, whatever
    its age), "Vencen pronto" (reminders due within ``upcoming_days``) and "Memorias" (the
    10 best by score, without the norms already listed). At most ``SHARED_MAX`` of those are
    ``_shared`` ones (when the project is not ``_shared``); the extra ``_shared`` memories only
    fill the slots left once the others are listed.
    """
    project = engine.need_project(project)
    now = today()
    iso = now.isoformat()
    soon = (now + dt.timedelta(days=upcoming_days)).isoformat()
    rows = engine.index.memories("project in (?, '_shared') and status = 'active'", (project,))
    reminders = sorted(
        (r for r in rows if r["type"] == "reminder" and r["due"]),
        key=lambda r: (r["due"], r["path"]),
    )
    overdue = [r for r in reminders if r["due"] <= iso]
    upcoming = [r for r in reminders if iso < r["due"] <= soon]
    candidates = [
        r
        for r in rows
        if r["type"] not in ("session", "reminder")
        and not (r["valid_until"] and r["valid_until"] < iso)
    ]
    norms = sorted(
        (r for r in candidates if r["priority"] == 5),
        key=lambda r: (_neg_date(r["created"]), r["path"]),
    )
    scored = sorted(
        ((welcome_score(r, now), r) for r in candidates if r["priority"] != 5),
        key=lambda x: (-x[0], _neg_date(x[1]["created"]), x[1]["path"]),
    )
    header = f"episteme · memoria de {project}"
    lines = [header]
    entries: list[dict[str, Any]] = []
    budget = 4000 - len(header) - 1
    ranked = 0

    def add(line: str, section: str | None, ranked_entry: bool = False) -> bool:
        nonlocal budget, ranked
        extra = len(line) + 1 + (len(section) + 1 if section else 0)
        if (ranked_entry and ranked >= 10) or extra > budget:
            return False
        if section:
            lines.append(section)
        lines.append(line)
        budget -= extra
        ranked += ranked_entry
        return True

    def reminder_lines(rows_: list[Any], section: str) -> None:
        first = True
        for r in rows_:
            line = f"- [{r['due']}] {r['title']} ({r['path']})"
            if not add(line, section if first else None):
                break
            first = False
            entries.append({"path": r["path"], "score": None, "kind": "reminder"})

    reminder_lines(overdue, "Recordatorios vencidos:")
    first = True
    for r in norms:
        if not add(entry_line(r), "Normas:" if first else None):
            break
        first = False
        entries.append({"path": r["path"], "score": None, "kind": "norm"})
    reminder_lines(upcoming, f"Vencen pronto ({upcoming_days} días):")
    first = True
    shared_used = 0
    spill: list[tuple[float, Any]] = []
    full = False
    for score, r in scored:
        if project != "_shared" and r["project"] == "_shared":
            if shared_used >= SHARED_MAX:
                spill.append((score, r))
                continue
            shared_used += 1
        if not add(entry_line(r), "Memorias:" if first else None, True):
            full = True
            break
        first = False
        entries.append({"path": r["path"], "score": round(score, 4), "kind": "memory"})
    for score, r in [] if full else spill:
        if not add(entry_line(r), "Memorias:" if first else None, True):
            break
        first = False
        entries.append({"path": r["path"], "score": round(score, 4), "kind": "memory"})
    if not entries:
        return "", []
    return "\n".join(lines), entries


def _neg_date(value: str | None) -> int:
    """Sort key for 'most recent first'."""
    try:
        return -dt.date.fromisoformat(value or "").toordinal()
    except ValueError:
        return 0


# -- files: surface and constraints -------------------------------------


def project_relative(file: str, project_dir: str | None) -> str:
    """The project-relative form of ``file`` when ``project_dir`` contains it."""
    f = file.replace("\\", "/")
    if project_dir and os.path.isabs(f):
        for base, target in (
            (os.path.normpath(project_dir), os.path.normpath(f)),
            (os.path.realpath(project_dir), os.path.realpath(f)),
        ):
            # normcase: on Windows separators are "\" and the drive letter's case varies.
            if os.path.normcase(target).startswith(os.path.normcase(os.path.join(base, ""))):
                return os.path.relpath(target, base).replace("\\", "/")
    return f.removeprefix("./")


def file_matches(file: str, rel: str, entry: str) -> bool:
    """Match a ``files`` entry against a file (see «Casado de file con files»)."""
    entry = entry.strip().replace("\\", "/").removeprefix("./")
    if not entry:
        return False
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatchcase(rel, entry)
    file = file.replace("\\", "/")
    return rel == entry or file.endswith("/" + entry) or rel.endswith("/" + entry)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [f for f in value if isinstance(f, str)] if isinstance(value, list) else []


def _files_of(engine: Engine) -> dict[str, list[str]]:
    """The ``files`` entries of every note that has them, in one query: ``{path: [entry]}``."""
    return {
        r["path"]: _as_list(json.loads(r["value"]))
        for r in engine.index.conn.execute("select path, value from props where key = 'files'")
    }


def _hook_file(
    file: str, relative_path: str | None, project_dir: str | None
) -> tuple[str, str] | None:
    """The file a hook is about: ``file`` or, for Serena edits, ``relative_path``; None if both
    are empty."""
    chosen = (file or "").strip() or (relative_path or "").strip()
    return (chosen, project_relative(chosen, project_dir)) if chosen else None


def _name_is_unambiguous(rel: str, name: str, files: dict[str, list[str]]) -> bool:
    """True when no other known path in the project shares the base name ``name``."""
    if name == rel:
        return False
    for entries in files.values():
        for e in entries:
            e = e.strip().replace("\\", "/").removeprefix("./")
            if e and not any(c in e for c in "*?[") and e != rel and PurePosixPath(e).name == name:
                if not rel.endswith("/" + e) and not e.endswith("/" + rel):
                    return False
    return True


def _by_priority(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda r: (-(r["priority"] or 0), _neg_date(r["created"]), r["path"]))


SURFACE_REPEAT_SECONDS = 1800
_SURFACED: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {}


def surface_repeated(session: str, rel: str, paths: list[str], now: float | None = None) -> bool:
    """True if the same set of paths was already surfaced for (session, rel) within the window."""
    if now is None:
        import time

        now = time.monotonic()
    key = (session, rel)
    shown = tuple(sorted(paths))
    prev = _SURFACED.get(key)
    if prev is not None and prev[1] == shown and now - prev[0] < SURFACE_REPEAT_SECONDS:
        return True
    _SURFACED[key] = (now, shown)
    if len(_SURFACED) > 500:
        for k in [k for k, (t, _) in _SURFACED.items() if now - t >= SURFACE_REPEAT_SECONDS]:
            del _SURFACED[k]
    return False


def surface_forget(session: str) -> None:
    """Drop what was surfaced to a session: after compact or clear its context lost it."""
    for key in [k for k in _SURFACED if k[0] == session]:
        del _SURFACED[key]


def surface(
    engine: Engine,
    file: str,
    project_dir: str | None,
    project: str | None,
    limit: int,
    relative_path: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if not (1 <= limit <= 50):
        raise invalid(f"limit must be 1-50, got {limit}.")
    project = engine.need_project(project)
    target = _hook_file(file, relative_path, project_dir)
    if target is None:
        return "", {"file": "", "memories": []}
    file, rel = target
    rows = engine.index.memories(
        "project in (?, '_shared') and status = 'active'"
        " and type not in ('constraint', 'session', 'reminder')"
        " and (valid_until is null or valid_until >= ?)",
        (project, today().isoformat()),
    )
    files = _files_of(engine)
    by_files = _by_priority(
        [r for r in rows if any(file_matches(file, rel, e) for e in files.get(r["path"], []))]
    )
    seen = {r["path"] for r in by_files}
    name = PurePosixPath(rel).name
    query = f'"{rel}"' + (f' "{name}"' if _name_is_unambiguous(rel, name, files) else "")
    hits, _ = engine.index.search(
        query,
        any_term=True,
        mode=MEMORY,
        project=[project, "_shared"],
        limit=1000,
        snippets=False,
    )
    hit_paths = {h.path for h in hits}
    by_mention = _by_priority([r for r in rows if r["path"] in hit_paths and r["path"] not in seen])
    chosen = [(r, "files") for r in by_files] + [(r, "mention") for r in by_mention]
    chosen = chosen[:limit]
    text = ""
    if chosen:
        text = "\n".join([f"Memories about {rel}:"] + [entry_line(r) for r, _ in chosen])
    data = {
        "file": rel,
        "memories": [
            {
                "path": r["path"],
                "title": r["title"],
                "type": r["type"],
                "priority": r["priority"],
                "match": match,
            }
            for r, match in chosen
        ],
    }
    return text, data


def constraints(
    engine: Engine,
    file: str,
    project_dir: str | None,
    project: str | None,
    relative_path: str | None = None,
) -> tuple[str, dict[str, Any]]:
    project = engine.need_project(project)
    target = _hook_file(file, relative_path, project_dir)
    if target is None:
        return "", {"file": "", "constraints": []}
    file, rel = target
    rows = engine.index.memories(
        "project in (?, '_shared') and status = 'active' and type = 'constraint'"
        " and (valid_until is null or valid_until >= ?)",
        (project, today().isoformat()),
    )
    files = _files_of(engine)
    found = _by_priority(
        [r for r in rows if any(file_matches(file, rel, e) for e in files.get(r["path"], []))]
    )
    items = [
        {
            "path": r["path"],
            "title": r["title"],
            "priority": r["priority"],
            "body": clip(body_without_title(r["body"] or ""), 600),
        }
        for r in found
    ]
    text = ""
    if items:
        parts = [f"Constraints that apply to {rel}:"]
        for item in items:
            parts.append(f"- {item['title']} ({item['path']})")
            parts.append(item["body"])
        text = "\n".join(parts)
    return text, {"file": rel, "constraints": items}


# -- task context --------------------------------------------------------


MIN_RELEVANCE = 0.25  # task context: a memory's score relative to the best hit
LINKED_MAX = 3  # task context: memories listed under "Memorias enlazadas:"


def _matched(engine: Engine, path: str, terms: list[list[str]]) -> int:
    """How many distinct ``terms`` occur in the title or text of ``path`` (at least 1)."""
    from episteme.index import _term_regex

    row = engine.index.note(path)
    text = ""
    if row is not None:
        tags = [t["tag"] for t in engine.index.conn.execute(
            "select tag from tags where path = ?", (path,)
        )]  # fmt: skip
        text = fold("\n".join([row["title"], row["search_text"], *tags]))
    return max(1, sum(1 for t in terms if _term_regex(t).search(text)))


def task_context(
    engine: Engine, task: str, project: str | None, budget_tokens: int
) -> tuple[str, list[dict[str, Any]]]:
    """A context pack for ``task``: relevant memories, linked memories, then related notes.

    English stopwords are dropped from ``task`` first (Spanish ones by the search). With N
    remaining terms a hit must match ``need`` of them (2 if N >= 3, else 1). A memory is listed
    if it is a constraint with ``files``, or if its score relative to the best hit is at least
    ``MIN_RELEVANCE``, it matches ``need`` terms and ``0.5*relevance + 0.3*priority +
    0.2*recency`` is at least ``MIN_CONTEXT_SCORE``. "Memorias enlazadas:" adds up to
    ``LINKED_MAX`` active memories one ``related`` link away from the first five listed. Notes
    need relevance >= 0.5 (relative to the best note) and ``need`` terms; their score is
    ``0.5*relevance``; at most 5.
    """
    from episteme.index import query_terms

    if budget_tokens < 1:
        raise invalid(f"budget_tokens must be positive, got {budget_tokens}.")
    project = engine.need_project(project)
    now = today()
    kept = [w for w in task.split() if fold(w).strip(".,;:!?()[]\"'") not in STOPWORDS_EN]
    query = " ".join(kept) if kept else task
    terms = query_terms(query, drop_stopwords=True)
    need = 2 if len(terms) >= 3 else 1
    hits, _ = engine.index.search(
        query,
        any_term=True,
        drop_stopwords=True,
        mode=MEMORY,
        project=[project, "_shared"],
        status="active",
        limit=200,
        snippets=False,
    )
    rows = {h.path: row for h in hits if (row := engine.index.note(h.path)) is not None}
    hits = [h for h in hits if h.path in rows]
    hi = max((h.score for h in hits), default=0.0)
    scored = []
    files = _files_of(engine)
    for h in hits:
        row = rows[h.path]
        relevance = h.score / hi if hi > 0 else 1.0
        score = (
            0.5 * relevance
            + 0.3 * ((row["priority"] or 1) - 1) / 4
            + 0.2 * recency(row["created"], now)
        )
        pinned = row["type"] == "constraint" and bool(files.get(h.path))
        if pinned or (
            relevance >= MIN_RELEVANCE
            and _matched(engine, h.path, terms) >= need
            and score >= MIN_CONTEXT_SCORE
        ):
            scored.append((pinned, score, row))
    scored.sort(key=lambda x: (not x[0], -x[1], x[2]["path"]))

    budget = budget_tokens * 4
    header = f"episteme · contexto para: {' '.join(task.split())}"
    parts = [header]
    used = len(header)
    entries: list[dict[str, Any]] = []
    chosen: list[str] = []
    for _, score, row in scored:
        excerpt = clip(" ".join(body_without_title(row["body"] or "").split()), 300)
        block = f"- [{row['type']} p{row['priority']}] {row['title']} ({row['path']})\n  {excerpt}"
        if used + len(block) + 1 > budget:
            continue
        parts.append(block)
        used += len(block) + 1
        entries.append({"path": row["path"], "score": round(score, 4), "kind": "memory"})
        chosen.append(row["path"])

    listed = set(chosen)
    iso = now.isoformat()
    linked: list[Any] = []
    for path in chosen[:5]:
        near = [x["dst_path"] for x in engine.index.outgoing(path) if x["kind"] == "related"]
        near += [x["src"] for x in engine.index.backlinks(path) if x["kind"] == "related"]
        for other in near:
            if other is None or other in listed:
                continue
            r = engine.index.note(other)
            if (
                r is None
                or r["mode"] != MEMORY
                or r["status"] != "active"
                or r["project"] not in (project, "_shared")
                or (r["valid_until"] and r["valid_until"] < iso)
            ):
                continue
            listed.add(other)
            linked.append(r)
    first = True
    for r in linked[:LINKED_MAX]:
        line = f"- [{r['type']} p{r['priority']}] {r['title']} ({r['path']})"
        extra = len(line) + 1 + (len("Memorias enlazadas:") + 1 if first else 0)
        if used + extra > budget:
            break
        if first:
            parts.append("Memorias enlazadas:")
            first = False
        parts.append(line)
        used += extra
        entries.append({"path": r["path"], "score": None, "kind": "linked"})

    found, _ = engine.index.search(
        query, any_term=True, drop_stopwords=True, limit=50, snippets=False
    )
    found = [n for n in found if engine.vault.mode_for(n.path) != MEMORY]
    nhi = max((n.score for n in found), default=0.0)
    notes = []
    for n in found:
        relevance = n.score / nhi if nhi > 0 else 1.0
        if relevance >= 0.5 and _matched(engine, n.path, terms) >= need:
            n.score = round(0.5 * relevance, 4)
            notes.append(n)
    notes = notes[:5]
    first = True
    for n in notes:
        line = f"- {n.path} — {n.title}"
        extra = len(line) + 1 + (len("Notas relacionadas:") + 1 if first else 0)
        if used + extra > budget:
            break
        if first:
            parts.append("Notas relacionadas:")
            first = False
        parts.append(line)
        used += extra
        entries.append({"path": n.path, "score": n.score, "kind": "note"})
    if not entries:
        return "", []
    return "\n".join(parts), entries


# -- review --------------------------------------------------------------

STALE_DAYS = 90
REVIEW_SIMILAR = 0.4  # wider than remember's 0.5: review only reports


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
            if reason:
                contradictions.append(
                    {
                        "a": a["path"],
                        "b": b["path"],
                        "reason": reason,
                        "similarity": round(similarity(toks[a["path"]], toks[b["path"]]), 3),
                    }
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
    groups = [
        {"paths": sorted(paths), "similarity": round(best[root], 3)}
        for root, paths in members.items()
    ]
    groups.sort(key=lambda g: (-g["similarity"], g["paths"][0]))
    return groups
