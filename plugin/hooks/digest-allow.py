"""PreToolUse (Bash) hook: let the extractor run its transcript script without a prompt.

The ``episteme:extractor`` agent runs in the background and cannot ask for permission, so
its one shell command, ``transcript_digest.py`` of the ``sesion`` skill, has to be
approved beforehand. A permission rule cannot follow the plugin: its path changes with each
version, and a ``*`` in a Bash rule also matches spaces, which would let text the extractor
read from the transcript run another script. This hook approves only that exact command:
inside the extractor, the script of this very plugin version (``CLAUDE_PLUGIN_ROOT``), a
single-quoted ``.jsonl`` transcript, an optional ISO ``--since`` and ``--max-chars``.

Anything else gets no output, so Claude Code decides as usual. A hook ``allow`` never
skips a deny or ask rule. It never denies or blocks.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

AGENT = "episteme:extractor"
PREFIX = "uv run --no-project --python 3.14 python -I "
SCRIPT = "skills/sesion/scripts/transcript_digest.py"
ARGS = re.compile(
    r"'[^'\n]+\.jsonl'"
    r"(?: --since \d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r" --max-chars \d{1,7}"
)
REASON = "episteme: script del extractor (transcript_digest.py) de esta versión del plugin"


def _script(root: str) -> str:
    """The script path as the agent writes it: the plugin root with ``/`` separators."""
    return root.replace("\\", "/").rstrip("/") + "/" + SCRIPT


def _extractor_bash(data: dict[str, Any]) -> bool:
    """True when the call is a Bash command of the extractor agent."""
    return data.get("tool_name") == "Bash" and data.get("agent_type") == AGENT


def _command(data: dict[str, Any]) -> str:
    """The Bash command of the call, or ``""`` when there is none."""
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else ""


def allowed(data: dict[str, Any], root: str) -> bool:
    """True only for the extractor's own digest command of the plugin at ``root``."""
    if not root or not _extractor_bash(data):
        return False
    head = PREFIX + _script(root) + " "
    command = _command(data)
    if not command.startswith(head):
        return False
    return ARGS.fullmatch(command[len(head) :]) is not None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    if isinstance(data, dict) and allowed(data, os.environ.get("CLAUDE_PLUGIN_ROOT", "")):
        decision = {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                    "permissionDecisionReason": REASON}
        sys.stdout.write(json.dumps({"hookSpecificOutput": decision}))


if __name__ == "__main__":
    main()
