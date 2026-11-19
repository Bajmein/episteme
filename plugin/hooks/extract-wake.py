"""SessionStart (compact|clear) hook: wake Claude so it launches the extractor right away.

After /compact or /clear the model takes no turn on its own, so the extraction order that
``session restore`` puts in the context would wait for the next user message. Run as an
``asyncRewake`` command hook, this script exits 2 and Claude Code wakes the model with the
stderr text as a system reminder.

It does not read the vault. It only wakes the model when the event is a compaction or a
/clear with a transcript, and the project (or the user) has episteme's ``session`` restore
hook, the one that adds the extraction order: elsewhere it stays silent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SOURCES = ("compact", "clear")
WAKE = 2
MESSAGE = (
    "episteme · despertar tras /{source}: si el contexto de SessionStart trae "
    "«extracción pendiente», lanza ahora en segundo plano el agente episteme:extractor "
    "con ese encargo tal cual y termina el turno con una línea. Si no lo trae, no hagas nada."
)


def _settings_files(project_dir: str) -> list[Path]:
    """The settings files whose hooks Claude Code merges: project, local and user."""
    project = Path(project_dir) / ".claude"
    config = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    user = Path(config) / "settings.json"
    return [project / "settings.local.json", project / "settings.json", user]


def _is_restore_hook(hook: Any) -> bool:
    """True for episteme's ``session`` restore hook (a ``mcp_tool`` hook)."""
    if not isinstance(hook, dict) or hook.get("type") != "mcp_tool":
        return False
    tool_input = hook.get("input")
    return (
        str(hook.get("server", "")).endswith("episteme")
        and hook.get("tool") == "session"
        and isinstance(tool_input, dict)
        and tool_input.get("action") == "restore"
    )


def _has_restore_hook(path: Path) -> bool:
    """True when the settings at ``path`` declare episteme's restore hook on SessionStart."""
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        entries = settings["hooks"]["SessionStart"]
        return any(_is_restore_hook(h) for entry in entries for h in entry.get("hooks", []))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def should_wake(data: dict[str, Any]) -> bool:
    """True after a compaction or /clear with a transcript, in a project wired to episteme."""
    if data.get("source") not in SOURCES or not data.get("transcript_path"):
        return False
    project_dir = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    return bool(project_dir) and any(_has_restore_hook(p) for p in _settings_files(project_dir))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    if isinstance(data, dict) and should_wake(data):
        sys.stderr.write(MESSAGE.format(source=data["source"]))
        sys.exit(WAKE)


if __name__ == "__main__":
    main()
