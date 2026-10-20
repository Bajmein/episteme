"""Output format per ``hook_event``: exactly what Claude Code expects from each event."""

from __future__ import annotations

import json

from episteme.errors import invalid
from episteme.markdown import clip_at_newline

PLAIN_EVENTS = ("UserPromptSubmit", "SessionStart")
JSON_EVENTS = ("PreToolUse", "PostToolUse")
SILENT_EVENTS = ("PreCompact",)
EVENTS = PLAIN_EVENTS + JSON_EVENTS + SILENT_EVENTS
CAP = 10_000


def check(event: str | None) -> None:
    if event is not None and event not in EVENTS:
        raise invalid(f'hook_event must be one of {", ".join(EVENTS)}, got "{event}".')


def render(event: str, text: str) -> str:
    """Plain text for prompt/session events, a hookSpecificOutput object for tool events.

    Nothing to say is an empty string. Never emits decision, permissionDecision or continue.
    """
    check(event)
    if event in SILENT_EVENTS or not text.strip():
        return ""
    text = clip_at_newline(text.strip("\n"), CAP)
    if event in PLAIN_EVENTS:
        return text
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
        ensure_ascii=False,
    )
