"""Conversions of frontmatter values for the index."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any


def as_date(value: Any) -> str | None:
    """A frontmatter date (date, datetime or ISO string) as ``YYYY-MM-DD``."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            return None
    return None


def is_past(value: Any, iso: str) -> bool:
    """Whether a frontmatter date falls before ``iso`` (``YYYY-MM-DD``).

    A missing or unreadable date never does, so it never makes a note expire.
    """
    date = as_date(value)
    return date is not None and date < iso


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _json_default(value: Any) -> Any:
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return str(value)


def _str_keys(value: Any) -> Any:
    """Copy ``value`` with every mapping key as a string, which JSON requires."""
    if isinstance(value, dict):
        return {str(k): _str_keys(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_str_keys(v) for v in value]
    return value


def to_json(value: Any) -> str:
    return json.dumps(_str_keys(value), ensure_ascii=False, default=_json_default)


def jsonable(value: Any) -> Any:
    return json.loads(to_json(value))
