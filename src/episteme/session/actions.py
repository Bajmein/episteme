"""The session tool's read actions: restore and template."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.memory import TEMPLATES
from episteme.session import store
from episteme.session.capture import take_transcript, transcript_path, without_summary

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


def from_compact_text(title: str, path: str) -> str:
    """The one line a restore after compaction gives when the summary block is the state."""
    return (
        f"Estado de la sesión «{title}» guardado en `{path}` desde el resumen de compactación "
        "(su contenido es el bloque del resumen)."
    )


def _state(engine: Engine, project: str, project_dir: str | None, explicit: bool) -> dict[str, Any]:
    """The state in use, made current; else the empty result.

    An explicit restore (the agent's, not a hook's) without a state in use takes the newest
    active state of the worktree, whichever session saved it.
    """
    data = store.show(engine, project, project_dir)
    if not data["found"] and explicit:
        newest = store.latest(engine, project, project_dir)
        if newest is not None:
            store.mark_current(engine, project, project_dir, newest)
            data = store.show(engine, project, project_dir)
    if data["found"]:
        store.mark_current(engine, project, project_dir, data["path"])
        return {**data, "source": "session"}
    return {**data, "source": None}


def _as_context(data: dict[str, Any], source: str | None) -> dict[str, Any]:
    """``data`` with its content as context; after compaction, without the summary in it."""
    if not data["found"]:
        return data
    content = without_summary(data["content"]) if source == "compact" else data["content"]
    return {**data, "content": restore_text(data["task_title"], data["saved_at"], content)}


def _resume_transcript(data: dict[str, Any]) -> str | None:
    """The transcript of the session that saved this state, when it is not this one."""
    path = transcript_path(data.get("transcript"))
    if path is None or path == store.IDS.get("transcript"):
        return None
    return path


# @CodeScene(disable:"Excess Number of Function Arguments")
def restore(
    engine: Engine,
    project: str,
    project_dir: str | None,
    hook: tuple[str | None, str | None] = (None, None),
    explicit: bool = False,
) -> dict[str, Any]:
    """The state in use as context, made current; else the empty result.

    ``hook`` is the (source, transcript) a SessionStart hook passes. Returns {"found", "path",
    "task_title", "saved_at", "content", "source"}; source is "session", or None when there is
    no state. After a compaction whose summary block capture saved, content is one line. After
    another compact or a clear with ``[session] extract`` and a known transcript, it adds
    "extract": the order to launch the extractor; so does an ``explicit`` restore of a state
    saved by another session whose transcript it kept.
    """
    source, transcript = hook
    data = _state(engine, project, project_dir, explicit)
    if source == "compact" and store.take_from_compact(data.get("path")):
        return {**data, "content": from_compact_text(data["task_title"], data["path"])}
    data = _as_context(data, source)
    path = _resume_transcript(data) if explicit else take_transcript(source, transcript)
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
