"""The session tool's read actions: restore and template."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.memory import TEMPLATES
from episteme.session import store
from episteme.session.capture import take_transcript

if TYPE_CHECKING:
    from episteme.engine import Engine

# The saved_at that session writes (store.now()); anything else, e.g. edited by hand, never
# reaches the extractor's command line.
_SAVED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
SINCE_ALL = "inicio"

def restore_text(title: str, saved_at: str | None, content: str) -> str:
    """The state as context: a line that says what it is, then its body."""
    head = (
        f"Estado de la sesión «{title}» (guardado {saved_at or '?'}; compruébalo contra el "
        "repo antes de repetir pasos):"
    )
    return f"{head}\n\n{content}".strip()


def extraction_order(project: str, transcript: str, state: dict[str, Any]) -> str:
    """The line that asks the agent to launch the extractor on ``transcript``."""
    managed = state.get("source") == "session"
    mark = state.get("extracted_until") or state.get("saved_at")
    saved = str(mark or "") if managed else ""
    since = saved if _SAVED_AT.fullmatch(saved) else SINCE_ALL
    target = state["path"] if managed else "nuevo"
    return (
        "episteme · extracción pendiente: lanza en segundo plano el agente episteme:extractor "
        f"con este encargo y sigue sin esperarlo: desde={since} estado={target} "
        f"proyecto={project} transcript={transcript}"
    )


def _state(engine: Engine, project: str, project_dir: str | None) -> dict[str, Any]:
    """The state in use as context, made current; else the empty result."""
    data = store.show(engine, project, project_dir)
    if data["found"]:
        store.mark_current(engine, project, project_dir, data["path"])
        text = restore_text(data["task_title"], data["saved_at"], data["content"])
        return {**data, "content": text, "source": "session"}
    return {**data, "source": None}


# @CodeScene(disable:"Excess Number of Function Arguments")
def restore(
    engine: Engine,
    project: str,
    project_dir: str | None,
    source: str | None = None,
    transcript: str | None = None,
) -> dict[str, Any]:
    """The state in use as context, made current; else the empty result.

    Returns {"found", "path", "task_title", "saved_at", "content", "source"}; source is
    "session", or None when there is no state. After a
    compact or clear (``source``) with ``[session] extract`` and a known transcript, it adds
    "extract": the order to launch the extractor.
    """
    data = _state(engine, project, project_dir)
    path = take_transcript(source, transcript)
    if path is None or not engine.vault.config.session.extract:
        return data
    return {**data, "extract": extraction_order(project, path, data)}


def template(type: str | None) -> dict[str, Any]:
    """The body skeleton of a memory type (``session`` by default) and its sections."""
    name = type or store.STATE_TYPE
    found = TEMPLATES.get(name)
    if found is None:
        raise invalid(f'type must be one of {", ".join(TEMPLATES)}, got "{name}".')
    return {"type": name, "sections": list(found.sections), "skeleton": found.skeleton}
