"""Output format per ``hook_event``: a hookSpecificOutput JSON object, plain compaction
instructions for PreCompact, or nothing for the silent events (PostCompact, SessionEnd)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from episteme.errors import invalid
from episteme.markdown import clip_at_newline

CONTEXT_EVENTS = ("UserPromptSubmit", "SessionStart", "PreToolUse", "PostToolUse")
SILENT_EVENTS = ("PreCompact", "PostCompact", "SessionEnd")
EVENTS = CONTEXT_EVENTS + SILENT_EVENTS
NOTICE_EVENTS = ("SessionStart",)
NOTICE_STYLE = "\x1b[1;32m"
NOTICE_RESET = "\x1b[0m"
CAP = 10_000
LINE_MAX = 120
NOTICE_MAX = 600
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff\u061c]")
_BREAKS = re.compile(r"[\t\r\n]+")
# Whole escape sequences, so their parameters do not stay behind as text: CSI (ESC [ or
# 0x9b, e.g. "\x1b[2J"), OSC, DCS, SOS, PM and APC strings up to BEL or ST, and the
# two-character ESC sequences.
_ESCAPES = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
    r"|(?:\x1b[\]PX^_]|[\x90\x98\x9d-\x9f])[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"
    r"|\x1b[ -/]*[0-~]"
)
CUT_MARK = f"\n[episteme: output cut at {CAP:,} characters]"


def check(event: str | None) -> None:
    if event is not None and event not in EVENTS:
        raise invalid(f'hook_event must be one of {", ".join(EVENTS)}, got "{event}".')


def clean_line(text: object, limit: int = LINE_MAX) -> str:
    """One printable line: escape sequences and control characters dropped, cut at ``limit``.

    Titles and task names come from notes and project files, so they must not reach the
    person's terminal with escape sequences.
    """
    line = _CONTROL.sub("", _ESCAPES.sub("", _BREAKS.sub(" ", str(text))))
    return line if len(line) <= limit else line[: limit - 1] + "…"


def clean_block(text: object, limit: int) -> str:
    """Several printable lines: each one cleaned with ``clean_line``, empty ones dropped.

    The whole block is cut at ``limit`` with ``…``. Used for notices that list several items,
    one per line, so they keep their line breaks without letting control characters through.
    """
    lines = (clean_line(line, LINE_MAX) for line in str(text).splitlines())
    block = "\n".join(line for line in lines if line.strip())
    return block if len(block) <= limit else block[: limit - 1] + "…"


def paint(text: str) -> str:
    """``text`` in bold green for the terminal; plain when ``NO_COLOR`` is set."""
    if os.environ.get("NO_COLOR"):
        return text
    return f"{NOTICE_STYLE}{text}{NOTICE_RESET}"


def render_instructions(text: str) -> str:
    """Plain text for ``PreCompact``: Claude Code adds it to the compaction instructions.

    Each line is cleaned like ``clean_line`` (no escape sequences or control characters) but
    not shortened, and the whole is cut at ``CAP`` like ``render``. It never starts with
    ``{``, which Claude Code would parse as JSON. Nothing to say is an empty string.
    """
    lines = (clean_line(line, len(line) + 1).rstrip() for line in str(text).splitlines())
    text = "\n".join(lines).strip("\n")
    if not text.strip():
        return ""
    if text.startswith("{"):
        text = f"episteme · {text}"
    if len(text) > CAP:
        text = clip_at_newline(text, CAP - len(CUT_MARK)) + CUT_MARK
    return text


def render(event: str, text: str, notice: str = "") -> str:
    """A hookSpecificOutput JSON object with additionalContext for every context event.

    Plain text is not used: Claude Code 2.1.322 drops it for ``mcp_tool`` hooks.

    ``notice`` is a short message for the person, not the model, one item per line: it goes
    out as a coloured ``systemMessage`` (each line cleaned, at most ``NOTICE_MAX`` characters),
    only on ``SessionStart`` (Claude Code shows it as "SessionStart:<source>
    says: ..."), with or without text.

    Nothing to say is an empty string. Never emits decision, permissionDecision or continue.
    """
    check(event)
    if event in SILENT_EVENTS:
        return ""
    notice = notice.strip() if event in NOTICE_EVENTS else ""
    out: dict[str, Any] = {}
    if notice:
        out["systemMessage"] = paint(clean_block(notice, NOTICE_MAX))
    if text.strip():
        text = text.strip("\n")
        if len(text) > CAP:
            text = clip_at_newline(text, CAP - len(CUT_MARK)) + CUT_MARK
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": text}
    return json.dumps(out, ensure_ascii=False) if out else ""
