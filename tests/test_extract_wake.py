"""The plugin's wake hook after /compact or /clear (plugin/hooks/extract-wake.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugin"
SCRIPT = PLUGIN / "hooks" / "extract-wake.py"
RESTORE = {
    "type": "mcp_tool",
    "server": "episteme",
    "tool": "session",
    "input": {"action": "restore", "source": "${source}"},
}
TRANSCRIPT = "/home/u/.claude/projects/-repo/abc.jsonl"


def _settings(path: Path, hook: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"matcher": "compact|clear", "hooks": [hook]}
    path.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")


def _run(tmp_path: Path, payload: object) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "config")}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run(  # nosec B603: fixed interpreter and script
        [sys.executable, "-I", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _event(project: Path, source: str = "clear", transcript: str = TRANSCRIPT) -> dict:
    return {
        "hook_event_name": "SessionStart",
        "source": source,
        "transcript_path": transcript,
        "cwd": str(project),
    }


@pytest.mark.parametrize(
    "where", [".claude/settings.local.json", ".claude/settings.json", "config/settings.json"]
)
def test_wakes_after_clear_when_the_restore_hook_is_set(tmp_path: Path, where: str) -> None:
    project = tmp_path / "repo"
    base = tmp_path if where.startswith("config") else project
    _settings(base / where, RESTORE)

    done = _run(tmp_path, _event(project))

    assert done.returncode == 2
    assert "despertar tras /clear" in done.stderr and "episteme:extractor" in done.stderr


@pytest.mark.parametrize(
    ("source", "transcript"), [("startup", TRANSCRIPT), ("resume", TRANSCRIPT), ("compact", "")]
)
def test_stays_silent_outside_a_compaction_or_clear_with_transcript(
    tmp_path: Path, source: str, transcript: str
) -> None:
    project = tmp_path / "repo"
    _settings(project / ".claude/settings.local.json", RESTORE)

    done = _run(tmp_path, _event(project, source, transcript))

    assert done.returncode == 0 and done.stderr == ""


@pytest.mark.parametrize(
    "hook",
    [
        {**RESTORE, "server": "otro"},
        {**RESTORE, "tool": "context"},
        {**RESTORE, "input": {"action": "capture"}},
        {"type": "command", "command": "episteme session restore"},
    ],
)
def test_stays_silent_in_a_project_without_the_restore_hook(tmp_path: Path, hook: dict) -> None:
    project = tmp_path / "repo"
    _settings(project / ".claude/settings.local.json", hook)

    done = _run(tmp_path, _event(project))

    assert done.returncode == 0 and done.stderr == ""


@pytest.mark.parametrize("payload", ["no es json", [1, 2]])
def test_stays_silent_on_bad_input(tmp_path: Path, payload: object) -> None:
    done = _run(tmp_path, payload)

    assert done.returncode == 0 and done.stderr == ""


def test_plugin_registers_the_wake_hook_as_async_rewake() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    (entry,) = hooks["hooks"]["SessionStart"]
    (hook,) = entry["hooks"]
    assert entry["matcher"] == "compact|clear"
    assert hook["type"] == "command" and hook["asyncRewake"] is True
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/extract-wake.py" in hook["command"]
