"""Schema of a docs suite: the notes of a ``docs`` zone and its ``README.index.md`` manifest."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from episteme.errors import INVALID_SCHEMA, EpistemeError

MANIFEST = "README.index.md"
INDEX_TYPE = "index"
NOTE_TYPES = ("reference", "guide", "concept", "how-to", INDEX_TYPE)
STATUSES = ("stable", "deprecated")
REQUIRED = ("title", "type", "status", "lang", "created", "updated", "tags")
DATE_KEYS = ("created", "updated")
SUITE_KEYS = ("upstream", "include", "context7", "synced")
# The order of the keys of a note created by docs_write; the rest go after, as given.
KEY_ORDER = (
    "title",
    "description",
    "summary",
    "aliases",
    "tags",
    "type",
    "category",
    "status",
    "lang",
    "source",
    "created",
    "updated",
    "up",
    "related",
)
LANG_RE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?")
CONTEXT7_RE = re.compile(r"/[\w.-]+(?:/[\w.-]+)+")
URL_SCHEMES = ("https://", "http://")


def is_url(value: Any) -> bool:
    """An ``http(s)`` URL with a host and no whitespace."""
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    scheme = next((s for s in URL_SCHEMES if value.lower().startswith(s)), None)
    return scheme is not None and len(value) > len(scheme) and value[len(scheme)] != "/"


def as_day(value: Any) -> dt.date | None:
    """A ``date`` (not a datetime) or a ``YYYY-MM-DD`` string as a date, else None."""
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) == len("YYYY-MM-DD"):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _enum_error(fm: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str | None:
    if fm.get(key) in allowed:
        return None
    return f"{key} must be one of {', '.join(allowed)}"


def _date_errors(fm: dict[str, Any]) -> list[str]:
    return [f"{k} must be a YYYY-MM-DD date" for k in DATE_KEYS if as_day(fm.get(k)) is None]


def note_errors(fm: dict[str, Any]) -> list[str]:
    """What is wrong with the frontmatter of a suite note; empty when it is valid."""
    missing = [k for k in REQUIRED if k not in fm]
    if missing:
        return [f"missing {', '.join(missing)}"]
    errors = [
        "title must be non-empty text" if not _is_text(fm["title"]) else None,
        _enum_error(fm, "type", NOTE_TYPES),
        _enum_error(fm, "status", STATUSES),
        "lang must be a short code (en, es)" if not _lang_ok(fm["lang"]) else None,
        "tags must be a list" if not isinstance(fm["tags"], list) else None,
        _source_error(fm),
    ]
    return [e for e in errors if e] + _date_errors(fm)


def _lang_ok(value: Any) -> bool:
    return isinstance(value, str) and LANG_RE.fullmatch(value) is not None


def _source_error(fm: dict[str, Any]) -> str | None:
    source = fm.get("source")
    if source is None and fm.get("type") == INDEX_TYPE:
        return None
    if not is_url(source):
        return "source must be an http(s) URL (only type: index can go without one)"
    return None


def _url_list_error(suite: dict[str, Any], key: str) -> str | None:
    value = suite.get(key)
    if isinstance(value, list) and all(is_url(v) for v in value):
        return None
    return f"suite.{key} must be a list of http(s) URLs"


def _is_context7_id(value: Any) -> bool:
    return isinstance(value, str) and CONTEXT7_RE.fullmatch(value) is not None


def _context7_error(value: Any) -> str | None:
    if value is None or _is_context7_id(value):
        return None
    return "suite.context7 must be a Context7 ID such as /astral-sh/uv, or null"


def suite_errors(suite: Any) -> list[str]:
    """What is wrong with the ``suite`` key of a manifest; empty when it is valid."""
    if not isinstance(suite, dict):
        return ["suite must be a mapping with upstream, include, context7 and synced"]
    unknown = [str(k) for k in suite if k not in SUITE_KEYS]
    missing = [k for k in SUITE_KEYS if k not in suite]
    errors = [
        f"suite has unknown keys: {', '.join(unknown)}" if unknown else None,
        f"suite is missing {', '.join(missing)}" if missing else None,
        _url_list_error(suite, "upstream"),
        _url_list_error(suite, "include"),
        _context7_error(suite.get("context7")),
    ]
    synced = suite.get("synced")
    if synced is not None and as_day(synced) is None:
        errors.append("suite.synced must be a YYYY-MM-DD date or null")
    return [e for e in errors if e]


def manifest_errors(fm: dict[str, Any]) -> list[str]:
    """What is wrong with the frontmatter of ``README.index.md``; empty when it is valid."""
    errors = note_errors(fm)
    if fm.get("type") != INDEX_TYPE:
        errors.append("type must be index")
    return errors + suite_errors(fm.get("suite"))


def validate(fm: dict[str, Any], rel: str, manifest: bool) -> None:
    """Raise ``invalid_schema`` when ``fm`` is not a valid note (or manifest) of a suite."""
    errors = manifest_errors(fm) if manifest else note_errors(fm)
    if errors:
        raise EpistemeError(
            INVALID_SCHEMA,
            f"{rel}: {'; '.join(errors)}. Fix fields and call docs_write again.",
        )


def ordered(fm: dict[str, Any]) -> dict[str, Any]:
    """``fm`` with the known keys first, in ``KEY_ORDER``."""
    head = {k: fm[k] for k in KEY_ORDER if k in fm}
    return head | {k: v for k, v in fm.items() if k not in head}
