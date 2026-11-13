"""Memory schema: constants, validation, key order, similarity and NoteFile."""

from __future__ import annotations

import datetime as dt
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.errors import INVALID_SCHEMA, EpistemeError, invalid
from episteme.index import STOPWORDS_ES, as_date
from episteme.markdown import (
    dump_frontmatter,
    load_frontmatter,
    split_frontmatter,
    tokens,
)
from episteme.vault import MEMORY

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
PRIORITY_MIN = 1
PRIORITY_MAX = 5
DEFAULT_PRIORITY = 3
HIGH_PRIORITY = 4  # decisions and constraints
DEDUP_MIN_TOKEN = 3


def kind_for(type_: str) -> str:
    if type_ == "session":
        return "episodic"
    if type_ in ("lesson", "error", "constraint"):
        return "procedural"
    return "semantic"


def default_priority(type_: str) -> int:
    return HIGH_PRIORITY if type_ in ("decision", "constraint") else DEFAULT_PRIORITY


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
    if (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or not PRIORITY_MIN <= priority <= PRIORITY_MAX
    ):
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
    toks = tokens(f"{title}\n{body}", min_len=DEDUP_MIN_TOKEN)
    return {t for t in toks if t not in STOPWORDS_ES}


def wikilink(engine: Engine, rel: str) -> str:
    """``[[name]]`` when the bare name resolves back to ``rel``, else ``[[path]]``."""
    stem = PurePosixPath(rel).name.removesuffix(".md")
    target = stem if engine.index.resolver().resolve_quiet(stem) == rel else rel[:-3]
    return f"[[{target}]]"




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


STOPWORDS_EN = frozenset(
    """a an the and or of to in on at for with by from is are was be as it its this that into
    about vs via not""".split()
)
