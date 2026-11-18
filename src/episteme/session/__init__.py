"""Session state: the living note of a line of work in the session zone (``sesiones/``)."""

from __future__ import annotations

from episteme.session.actions import DEPRECATED, restore, template
from episteme.session.capture import capture, end
from episteme.session.gate import gate
from episteme.session.store import (
    SaveArgs,
    archive,
    current,
    has_active,
    note_path,
    rotate,
    save,
    show,
)

__all__ = [
    "DEPRECATED",
    "SaveArgs",
    "archive",
    "capture",
    "current",
    "end",
    "gate",
    "has_active",
    "note_path",
    "restore",
    "rotate",
    "save",
    "show",
    "template",
]
