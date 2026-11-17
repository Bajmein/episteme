"""``gate`` (PreCompact): block a manual /compact once when the session state is stale."""

from __future__ import annotations

from typing import TYPE_CHECKING

from episteme import checkpoint, prompting

if TYPE_CHECKING:
    from episteme.engine import Engine


def _blocks(st: prompting.SessionState) -> bool:
    """True when the session is long enough, the state stale and this /compact not yet blocked."""
    stale = st.prompts - st.state_saved_at
    return (
        st.prompts >= prompting.GATE_MIN_PROMPTS
        and stale >= prompting.GATE_STALE
        and st.gate_blocked_at != st.prompts
    )


def _can_block(engine: Engine, trigger: str | None) -> bool:
    """True for a manual /compact with ``block_manual_compact`` on."""
    return trigger == "manual" and engine.vault.config.session.block_manual_compact


def gate(
    engine: Engine,
    project: str,
    project_dir: str | None,
    trigger: str | None,
    session: str | None,
) -> str | None:
    """The reason to block this /compact, or None to let it through.

    Only a manual /compact with ``[session] block_manual_compact`` can be blocked, and only once
    per message: repeating /compact goes through. With ``[checkpoint] state_glob`` (deprecated)
    it first saves the checkpoint, as the PreCompact hook did.
    """
    if engine.vault.config.state_glob:
        checkpoint.save(engine, project_dir, project)
    if not session or not _can_block(engine, trigger):
        return None
    st = prompting.state(session)
    prompting.sync_state_saves(st)
    if not _blocks(st):
        return None
    st.gate_blocked_at = st.prompts
    stale = st.prompts - st.state_saved_at
    return (
        f"episteme: el estado de la sesión no se guarda desde hace {stale} mensajes. Pide «guarda "
        "el estado de la sesión» y vuelve a compactar, o repite /compact para compactar igual."
    )
