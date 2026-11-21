"""``gate`` (PreCompact): instructions that make the compaction summary end with the state.

Claude Code adds what a PreCompact hook prints to the instructions of the compaction summary.
The summary then carries the session state between ``<estado-sesion>`` and
``</estado-sesion>``, and ``capture`` (PostCompact) saves that block as the state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from episteme.markdown import body_without_title
from episteme.memory import TEMPLATES
from episteme.session import store

if TYPE_CHECKING:
    from episteme.engine import Engine

BLOCK_OPEN = "<estado-sesion>"
BLOCK_CLOSE = "</estado-sesion>"
EXTRACTOR_ORIGIN = "extractor"
# Characters of an extractor-saved body put in the instructions; longer, only its path goes.
STATE_IN_INSTRUCTIONS_MAX = 7000

TASK = (
    f"Cierra el resumen con el estado de la sesión al día, entre `{BLOCK_OPEN}` y "
    f"`{BLOCK_CLOSE}`: primera línea `# <la tarea en pocas palabras>` y luego estas secciones "
    "`##`, en este orden, con «Nada.» en las vacías:"
)
RULES = (
    "Parte del último estado que aparezca en la conversación y súmale lo nuevo; corrige lo que "
    "la conversación contradiga. Sin secretos (di dónde están). Las personas, por su apellido."
)
EXTRACTED_HEAD = "Estado guardado por el extractor (más nuevo que la conversación):"


def _sections() -> str:
    return "\n".join(f"## {name}" for name in TEMPLATES[store.STATE_TYPE].sections)


def _extracted_state(engine: Engine, project: str, project_dir: str | None) -> str:
    """The state in use when the extractor saved it last (not in the conversation), else ``""``.

    A long body goes as its path, so the person does not see it whole on every compaction.
    """
    rel = store.current(engine, project, project_dir)
    if rel is None:
        return ""
    meta, body = store._read(engine, rel)
    if meta.get("saved_by") != EXTRACTOR_ORIGIN:
        return ""
    content = body_without_title(body.strip()).strip()
    if len(content) >= STATE_IN_INSTRUCTIONS_MAX:
        return f"{EXTRACTED_HEAD} `{rel}` (léelo con read si hace falta)."
    return f"{EXTRACTED_HEAD}\n\n{content}"


def gate(engine: Engine, project: str, project_dir: str | None) -> str | None:
    """The compaction instructions, or None with ``[session] compact_state`` off."""
    if not engine.vault.config.session.compact_state:
        return None
    parts = [TASK, _sections(), RULES, _extracted_state(engine, project, project_dir)]
    return "\n\n".join(p for p in parts if p)
