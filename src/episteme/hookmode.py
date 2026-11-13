"""Output format per ``hook_event``: a hookSpecificOutput JSON object, or nothing for PreCompact."""

from __future__ import annotations

import json

from episteme.errors import invalid
from episteme.markdown import clip_at_newline

CONTEXT_EVENTS = ("UserPromptSubmit", "SessionStart", "PreToolUse", "PostToolUse")
SILENT_EVENTS = ("PreCompact",)
EVENTS = CONTEXT_EVENTS + SILENT_EVENTS
CAP = 10_000
CUT_MARK = "\n[episteme: output cut at 10,000 characters]"


def check(event: str | None) -> None:
    if event is not None and event not in EVENTS:
        raise invalid(f'hook_event must be one of {", ".join(EVENTS)}, got "{event}".')


def render(event: str, text: str) -> str:
    """A hookSpecificOutput JSON object with additionalContext for every context event.

    Plain text is not used: Claude Code 2.1.322 drops it for ``mcp_tool`` hooks.

    Nothing to say is an empty string. Never emits decision, permissionDecision or continue.
    """
    check(event)
    if event in SILENT_EVENTS or not text.strip():
        return ""
    text = text.strip("\n")
    if len(text) > CAP:
        text = clip_at_newline(text, CAP - len(CUT_MARK)) + CUT_MARK
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
        ensure_ascii=False,
    )
