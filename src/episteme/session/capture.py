"""What the hooks leave in the session state: ``capture`` (PostCompact) and ``end`` (SessionEnd).

``capture`` saves the ``<estado-sesion>`` block that ``gate`` asked the compaction summary
for as the state (or, without one, the summary into a section of it); ``end`` only remembers,
in the process, the transcript that a ``/clear`` closed. Neither reads the transcript.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from episteme import hookmode
from episteme.markdown import compose
from episteme.memory import redact_secrets
from episteme.plans import current_slug
from episteme.session import store
from episteme.vault import today
from episteme.worktree import resolve_project_dir

if TYPE_CHECKING:
    from episteme.engine import Engine

COMPACT_HEADING = "## Resumen de compactación"
COMPACT_ORIGIN = "compact"
PATH_MAX = 4096  # characters of a transcript path kept from a hook

# The <analysis> block Claude Code puts before the summary (V1, 16-11-2026). Anchored at the
# start and lazy up to the first closing tag: one pass over the text.
_ANALYSIS = re.compile(r"\A\s*<analysis>.*?</analysis>\s*", re.DOTALL)
_HEADING = re.compile(r"^(#{1,4})(?=\s)", re.MULTILINE)
_SECTION = re.compile(rf"^{re.escape(COMPACT_HEADING)}[ \t]*$", re.MULTILINE)
_NEXT_SECTION = re.compile(r"^#{1,2}\s", re.MULTILINE)
# The state block gate asks the summary for; the last one wins.
_STATE_BLOCK = re.compile(r"<estado-sesion>(.*?)</estado-sesion>", re.DOTALL)
_SESSION_ID = re.compile(r"[\w-]{1,128}")
# A hook variable Claude Code did not substitute, e.g. "${compact_summary}" on an older version.
_PLACEHOLDER = re.compile(r"\$\{\w+\}")
# Characters a transcript path may not hold: it goes into a shell command the extractor runs
# inside single quotes (Claude Code builds it from the project folder and a session uuid).
_UNSAFE_PATH = re.compile(r"[\x00-\x1f'\"`$;|&<>]")


def clean_summary(summary: str | None) -> str:
    """The compaction summary without its leading <analysis> block, credentials redacted."""
    if _PLACEHOLDER.fullmatch((summary or "").strip()):
        return ""
    text = _ANALYSIS.sub("", summary or "", count=1)
    return redact_secrets(text).strip()


def _section(text: str) -> str:
    """The summary as a section; its headings go two levels down so they stay inside it."""
    return f"{COMPACT_HEADING}\n\n{_HEADING.sub(r'##\1', text)}\n"


def with_summary(body: str, section: str) -> str:
    """``body`` with its compaction section replaced by ``section``, or with it appended."""
    found = _SECTION.search(body)
    if found is None:
        return f"{body.rstrip()}\n\n{section}"
    after = _NEXT_SECTION.search(body, found.end())
    tail = body[after.start() :] if after else ""
    return body[: found.start()] + section + (f"\n{tail}" if tail else "")


def without_summary(body: str) -> str:
    """``body`` without its compaction section (the summary is already in the context)."""
    found = _SECTION.search(body)
    if found is None:
        return body
    after = _NEXT_SECTION.search(body, found.end())
    tail = body[after.start() :] if after else ""
    return (body[: found.start()].rstrip() + (f"\n\n{tail}" if tail else "")).strip()


def state_block(summary: str | None) -> tuple[str | None, str] | None:
    """The last ``<estado-sesion>`` block of the summary as (title or None, body), or None.

    The title is its leading ``# `` line; credentials in it are redacted (generated text).
    """
    blocks = _STATE_BLOCK.findall(clean_summary(summary))
    if not blocks:
        return None
    text = redact_secrets(blocks[-1]).strip()
    title: str | None = None
    first, _, rest = text.partition("\n")
    if first.startswith("# "):
        title = " ".join(first[2:].split()) or None
        text = rest.strip()
    return (title, text) if text else None


def track_ids(hook_event: str | None, session: str | None, transcript: str | None = None) -> None:
    """Keep the session id and transcript path a hook passed, for the state this session uses.

    Agent calls (no ``hook_event``) and SessionEnd (its transcript is the one closing) change
    nothing.
    """
    if not hook_event or hook_event == "SessionEnd":
        return
    found = {"session": session_id(session), "transcript": transcript_path(transcript)}
    store.IDS.update({key: value for key, value in found.items() if value})


def session_id(value: str | None) -> str | None:
    """A session id from a hook, kept only when it looks like one (letters, digits, - and _)."""
    value = (value or "").strip()
    return value if _SESSION_ID.fullmatch(value) else None


# @CodeScene(disable:"Excess Number of Function Arguments")
def _new_state(
    engine: Engine, project: str, project_dir: str | None, section: str, sid: str | None
) -> str:
    """Create «Sesión <date>» holding only the summary; it has no ``saved_at`` yet."""
    title = f"Sesión {today().isoformat()}"
    worktree = resolve_project_dir(project_dir).as_posix() if project_dir else None
    fresh = {"project": project, "task_title": title, "worktree": worktree}
    meta = store._meta({}, fresh, store.SaveArgs(title, None, session_id=sid))
    del meta["saved_at"]
    meta.update(saved_by=COMPACT_ORIGIN, compacted_at=store.now())
    return store._store(engine, None, fresh, compose(meta, f"# {title}\n\n{section}"))


# @CodeScene(disable:"Excess Number of Function Arguments")
def capture(
    engine: Engine,
    project: str,
    project_dir: str | None,
    summary: str | None,
    sid: str | None,
) -> dict[str, Any]:
    """Save the compaction summary in the current state (or a new one); {"path", "created"}.

    With an ``<estado-sesion>`` block (what gate asks for), the block becomes the whole state
    and ``saved_at`` moves. Without one, the summary goes to the «Resumen de compactación»
    section and ``saved_at`` does not move: it still says when the agent or the extractor last
    wrote the state, which is where the extraction starts; ``compacted_at`` says when. The
    summary is generated text, so a credential in it is redacted, never refused.
    """
    store.folder(engine, project)
    block = state_block(summary)
    if block is not None:
        return _capture_block(engine, (project, project_dir), block, session_id(sid))
    text = clean_summary(summary)
    if not text:
        return {"path": None, "created": False}
    section = _section(text)
    rel = store.current(engine, project, project_dir)
    created = rel is None
    if rel is None:
        rel = _new_state(engine, project, project_dir, section, session_id(sid))
    else:
        meta, body = store._read(engine, rel)
        meta.update(saved_by=COMPACT_ORIGIN, compacted_at=store.now())
        store._write(engine, rel, meta, with_summary(body, section))
    store._remember_current(store._key(project, project_dir), rel)
    return {"path": rel, "created": created}


def _capture_block(
    engine: Engine,
    where: tuple[str, str | None],
    block: tuple[str | None, str],
    sid: str | None,
) -> dict[str, Any]:
    """Save the summary block as the whole state: the current one (keeping its title), or new.

    ``saved_at`` moves (the block is the state as of this compaction) and extraction is not
    needed after it.
    """
    project, project_dir = where
    block_title, body = block
    rel = store.current(engine, project, project_dir)
    old: dict[str, Any] = store._read(engine, rel)[0] if rel else {}
    title = (
        str(old.get("task_title") or "").strip() or block_title or f"Sesión {today().isoformat()}"
    )
    worktree = resolve_project_dir(project_dir).as_posix() if project_dir else None
    fresh = {
        "project": project,
        "task_title": title,
        "worktree": worktree,
        "plan": current_slug(engine, project, project_dir),
    }
    meta = store._meta(old, fresh, store.SaveArgs(title, body, session_id=sid))
    meta.update(saved_by=COMPACT_ORIGIN, compacted_at=store.now())
    saved = store._store(engine, rel, fresh, compose(meta, f"# {title}\n\n{body}\n"))
    store._remember_current(store._key(project, project_dir), saved)
    store.mark_from_compact(saved)
    return {"path": saved, "created": rel is None}


def transcript_path(transcript: str | None) -> str | None:
    """A transcript path from a hook, when it is a ``.jsonl`` with no shell metacharacters."""
    raw = (transcript or "").strip()
    return raw if _is_safe_path(raw) else None


def _is_safe_path(raw: str) -> bool:
    """A ``.jsonl`` that ``clean_line`` leaves as is (no control, bidi or line-separator
    characters) and with no shell metacharacters."""
    fits = raw.endswith(".jsonl") and hookmode.clean_line(raw, PATH_MAX) == raw
    return fits and _UNSAFE_PATH.search(raw) is None


def end(transcript: str | None, reason: str | None = None) -> dict[str, Any]:
    """Remember the transcript a /clear closed, for the next restore; never writes the vault."""
    path = transcript_path(transcript)
    if path is None or reason not in (None, "", "clear"):
        return {"transcript": False}
    store.LAST_TRANSCRIPT[:] = [path]
    return {"transcript": True}


def take_transcript(source: str | None, transcript: str | None) -> str | None:
    """The transcript to extract from: this one after compact, the one ``end`` kept after clear.

    The one kept by ``end`` is handed out once.
    """
    if source == "compact":
        return transcript_path(transcript)
    if source == "clear" and store.LAST_TRANSCRIPT:
        return store.LAST_TRANSCRIPT.pop()
    return None
