"""The session tool's read actions: restore (with the deprecated checkpoint fallback) and
template."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from episteme import checkpoint
from episteme.errors import invalid
from episteme.memory import TEMPLATES
from episteme.session import store

if TYPE_CHECKING:
    from episteme.engine import Engine

DEPRECATED = (
    "checkpoint and [checkpoint] state_glob are deprecated and will be removed in the next "
    "minor release; use session."
)


def restore_text(title: str, saved_at: str | None, content: str) -> str:
    """The state as context: a line that says what it is, then its body."""
    head = (
        f"Estado de la sesión «{title}» (guardado {saved_at or '?'}; compruébalo contra el "
        "repo antes de repetir pasos):"
    )
    return f"{head}\n\n{content}".strip()


def _fallback(engine: Engine, project: str, project_dir: str | None) -> dict[str, Any]:
    """The deprecated checkpoint restore, used when there is no managed state."""
    data = checkpoint.restore(engine, project, project_dir)
    return {**data, "saved_at": None, "deprecated": DEPRECATED}


def restore(engine: Engine, project: str, project_dir: str | None) -> dict[str, Any]:
    """The state in use as context, made current; else the checkpoint (deprecated), if any.

    Returns {"found", "path", "task_title", "saved_at", "content", "source"}; source is
    "session", "state" or "checkpoint" (the last two add "deprecated"), or None.
    """
    data = store.show(engine, project, project_dir)
    if data["found"]:
        store.mark_current(engine, project, project_dir, data["path"])
        text = restore_text(data["task_title"], data["saved_at"], data["content"])
        return {**data, "content": text, "source": "session"}
    if engine.vault.config.state_glob:
        return _fallback(engine, project, project_dir)
    return {**data, "source": None}


def template(type: str | None) -> dict[str, Any]:
    """The body skeleton of a memory type (``session`` by default) and its sections."""
    name = type or store.STATE_TYPE
    found = TEMPLATES.get(name)
    if found is None:
        raise invalid(f'type must be one of {", ".join(TEMPLATES)}, got "{name}".')
    return {"type": name, "sections": list(found.sections), "skeleton": found.skeleton}
