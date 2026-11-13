"""Output format per ``hook_event``: a hookSpecificOutput JSON object, or nothing for PreCompact."""

from __future__ import annotations

import json
import os
from typing import Any

from episteme.errors import invalid
from episteme.markdown import clip_at_newline

CONTEXT_EVENTS = ("UserPromptSubmit", "SessionStart", "PreToolUse", "PostToolUse")
SILENT_EVENTS = ("PreCompact",)
EVENTS = CONTEXT_EVENTS + SILENT_EVENTS
NOTICE_EVENTS = ("SessionStart",)
NOTICE_STYLE = "\x1b[1;32m"
NOTICE_RESET = "\x1b[0m"
CAP = 10_000
CUT_MARK = f"\n[episteme: output cut at {CAP:,} characters]"


def check(event: str | None) -> None:
    if event is not None and event not in EVENTS:
        raise invalid(f'hook_event must be one of {", ".join(EVENTS)}, got "{event}".')


def paint(text: str) -> str:
    """``text`` in bold green for the terminal; plain when ``NO_COLOR`` is set."""
    if os.environ.get("NO_COLOR"):
        return text
    return f"{NOTICE_STYLE}{text}{NOTICE_RESET}"


def render(event: str, text: str, notice: str = "") -> str:
    """A hookSpecificOutput JSON object with additionalContext for every context event.

    Plain text is not used: Claude Code 2.1.322 drops it for ``mcp_tool`` hooks.

    ``notice`` is a one-line message for the person, not the model: it goes out as a coloured
    ``systemMessage``, only on ``SessionStart`` (Claude Code shows it as "SessionStart:<source>
    says: ..."), with or without text.

    Nothing to say is an empty string. Never emits decision, permissionDecision or continue.
    """
    check(event)
    if event in SILENT_EVENTS:
        return ""
    notice = notice.strip() if event in NOTICE_EVENTS else ""
    out: dict[str, Any] = {}
    if notice:
        out["systemMessage"] = paint(notice)
    if text.strip():
        text = text.strip("\n")
        if len(text) > CAP:
            text = clip_at_newline(text, CAP - len(CUT_MARK)) + CUT_MARK
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": text}
    return json.dumps(out, ensure_ascii=False) if out else ""
