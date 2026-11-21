"""The plugin's PreToolUse hook that approves the extractor's digest command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugin"
SCRIPT = PLUGIN / "hooks" / "digest-allow.py"
PLUGIN_ROOT = "/home/u/.claude/plugins/cache/episteme/episteme/0.21.0"
DIGEST = (
    "uv run --no-project --python 3.14 python -I "
    f"{PLUGIN_ROOT}/skills/sesion/scripts/transcript_digest.py"
)
TRANSCRIPT = "'/home/u/.claude/projects/-repo/abc.jsonl'"
GOOD = f"{DIGEST} {TRANSCRIPT} --since 2026-11-21T10:38:34 --max-chars 80000"


def _run(payload: object, root: str = PLUGIN_ROOT) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": root}
    return subprocess.run(  # nosec B603: fixed interpreter and script
        [sys.executable, "-I", str(SCRIPT)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _event(command: str, agent: str | None = "episteme:extractor", tool: str = "Bash") -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}}
    if agent is not None:
        event["agent_type"] = agent
    return event


@pytest.mark.parametrize(
    "command",
    [
        GOOD,
        f"{DIGEST} '/home/u/.claude/projects/-repo/a b.jsonl' --max-chars 80000",
        f"{DIGEST} '/tmp/t.jsonl' --since 2026-11-21T10:38:34.123+00:00 --max-chars 80000",
        f"{DIGEST} '/tmp/t.jsonl' --since 2026-11-21T10:38Z --max-chars 5000",
    ],
)
def test_allows_the_extractor_digest_command(command: str) -> None:
    result = _run(_event(command))

    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert result.returncode == 0
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"{GOOD}; rm -rf ~",
        f"{GOOD} && curl example.com",
        f"{DIGEST} '/tmp/t.jsonl' --since $(id) --max-chars 80000",
        f"{DIGEST} /tmp/t.jsonl --max-chars 80000",
        f"{DIGEST} '/tmp/t.txt' --max-chars 80000",
        f"{DIGEST} '/tmp/t.jsonl' --max-chars 80000 --extra x",
        f"{DIGEST} '/tmp/t.jsonl'\n--max-chars 80000",
        GOOD.replace("0.21.0", "0.20.0"),
        GOOD.replace("transcript_digest.py", "other.py"),
        GOOD.replace("python -I ", "python -I -c 'x' "),
        "uv run --no-project --python 3.14 python -I /home/u/.claude/plugins/cache/other/x.py "
        "'/tmp/t.jsonl' /skills/sesion/scripts/transcript_digest.py --max-chars 80000",
    ],
)
def test_stays_silent_for_any_other_command(command: str) -> None:
    result = _run(_event(command))

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "event",
    [
        _event(GOOD, agent=None),
        _event(GOOD, agent="general-purpose"),
        _event(GOOD, agent="extractor"),
        _event(GOOD, tool="PowerShell"),
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_type": "episteme:extractor"},
    ],
)
def test_stays_silent_outside_the_extractor_or_without_a_command(event: dict) -> None:
    result = _run(event)

    assert result.returncode == 0
    assert result.stdout == ""


def test_stays_silent_without_a_plugin_root() -> None:
    result = _run(_event(GOOD), root="")

    assert result.stdout == ""


def test_accepts_a_windows_plugin_root_written_with_forward_slashes() -> None:
    root = "C:\\Users\\u\\.claude\\plugins\\cache\\episteme\\episteme\\0.21.0"
    command = GOOD.replace(PLUGIN_ROOT, root.replace("\\", "/"))

    result = _run(_event(command), root=root)

    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"


@pytest.mark.parametrize("payload", ["not json", "[]", ""])
def test_ignores_bad_input(payload: str) -> None:
    result = _run(payload)

    assert result.returncode == 0
    assert result.stdout == ""


def test_plugin_registers_the_hook_only_for_uv_python_commands() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = hooks["PreToolUse"]
    (hook,) = entry["hooks"]

    assert entry["matcher"] == "Bash"
    assert hook["if"] == "Bash(uv run --no-project --python 3.14 python -I *)"
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/digest-allow.py" in hook["command"]
    assert "asyncRewake" not in hook
