"""Session state: the living note of a line of work in the session zone (``sesiones/``)."""

from __future__ import annotations

from episteme.session.actions import from_compact_text, restore, template
from episteme.session.capture import capture, end, track_ids
from episteme.session.gate import gate
from episteme.session.store import (
    FROM_COMPACT,
    IDS,
    SaveArgs,
    archive,
    current,
    has_active,
    latest,
    note_path,
    rotate,
    save,
    show,
)

__all__ = [
    "FROM_COMPACT",
    "IDS",
    "SaveArgs",
    "archive",
    "capture",
    "current",
    "end",
    "from_compact_text",
    "gate",
    "has_active",
    "latest",
    "note_path",
    "restore",
    "rotate",
    "save",
    "show",
    "template",
    "track_ids",
]
