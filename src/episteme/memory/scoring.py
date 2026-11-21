"""Scoring helpers shared by the welcome and the task context."""

from __future__ import annotations

import datetime as dt
import math
from typing import TYPE_CHECKING, Any

from episteme.hookmode import clean_line
from episteme.markdown import memory_description

if TYPE_CHECKING:
    pass


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
    sentence = clean_line(memory_description(row["description"], row["body"]))
    tail = f" — {sentence}" if sentence else ""
    title = clean_line(row["title"])
    return f"- [{row['type']} p{row['priority']}] {title} ({row['path']}){tail}"


def _neg_date(value: str | None) -> int:
    """Sort key for 'most recent first'."""
    try:
        return -dt.date.fromisoformat(value or "").toordinal()
    except ValueError:
        return 0
