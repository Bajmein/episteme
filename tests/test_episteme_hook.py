"""The agy and Copilot CLI hook that calls episteme as a one-shot MCP client."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import TODAY

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "plugin" / "hooks" / "episteme-hook.py"
CONFIG = {"agy": ".agents/mcp_config.json", "copilot": ".github/mcp.json"}
LONG_PROMPT = "how do we configure serena with ty in this project?"


def _project(tmp_path: Path, vault: Path, client: str) -> Path:
    project = tmp_path / "repo"
    config = project / CONFIG[client]
    config.parent.mkdir(parents=True)
    server = {
        "command": sys.executable,
        "args": ["-m", "episteme", "--vault", str(vault), "--project", "fabrik"],
    }
    config.write_text(json.dumps({"mcpServers": {"episteme": server}}), encoding="utf-8")
    return project


def _run(client: str, event: str, payload: dict, project: Path) -> dict:
    env = {**os.environ, "EPISTEME_TODAY": TODAY, "COPILOT_PROJECT_DIR": str(project)}
    if client == "agy":
        env.pop("COPILOT_PROJECT_DIR")
    result = subprocess.run(  # nosec B603: fixed interpreter and script
        [sys.executable, "-I", str(SCRIPT), "--client", client, "--event", event],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _agy(project: Path, **fields: object) -> dict:
    return {"conversationId": "c1", "workspacePaths": [str(project)], **fields}


def _copilot(project: Path, **fields: object) -> dict:
    return {"sessionId": "s1", "cwd": str(project), **fields}


def test_agy_session_start_injects_the_welcome_as_a_nested_system_message(
    tmp_path: Path, vault: Path
) -> None:
    project = _project(tmp_path, vault, "agy")

    out = _run("agy", "SessionStart", _agy(project), project)

    text = out["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert text.startswith("episteme · welcome\n")


def test_copilot_session_start_returns_the_welcome_as_additional_context(
    tmp_path: Path, vault: Path
) -> None:
    project = _project(tmp_path, vault, "copilot")

    out = _run("copilot", "sessionStart", _copilot(project, source="new"), project)

    assert out["additionalContext"].startswith("episteme · welcome\n")


@pytest.mark.parametrize("prompt", [LONG_PROMPT, f"/plan {LONG_PROMPT}"])
def test_agy_first_invocation_of_a_long_message_injects_the_task_context(
    tmp_path: Path, vault: Path, prompt: str
) -> None:
    project = _project(tmp_path, vault, "agy")
    payload = _agy(project, lastUserInput=prompt, invocationNum=0)

    out = _run("agy", "PreInvocation", payload, project)

    text = out["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert text.startswith("episteme · task\n")
    assert "serena" in text.lower()


def test_copilot_long_prompt_returns_the_task_context(tmp_path: Path, vault: Path) -> None:
    project = _project(tmp_path, vault, "copilot")

    out = _run("copilot", "userPromptSubmitted", _copilot(project, prompt=LONG_PROMPT), project)

    assert out["additionalContext"].startswith("episteme · task\n")


@pytest.mark.parametrize(
    "fields",
    [
        {"lastUserInput": "sigue", "invocationNum": 0},
        {"lastUserInput": LONG_PROMPT, "invocationNum": 1},
        {"lastUserInput": "/plan", "invocationNum": 0},
    ],
)
def test_agy_short_or_later_invocations_inject_nothing(
    tmp_path: Path, vault: Path, fields: dict
) -> None:
    project = _project(tmp_path, vault, "agy")

    out = _run("agy", "PreInvocation", _agy(project, **fields), project)

    assert out == {}


@pytest.mark.parametrize("config", [None, "{not json", '{"mcpServers": {"other": {}}}'])
def test_missing_or_broken_config_returns_an_empty_object(
    tmp_path: Path, config: str | None
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    if config is not None:
        path = project / CONFIG["copilot"]
        path.parent.mkdir()
        path.write_text(config, encoding="utf-8")

    out = _run("copilot", "sessionStart", _copilot(project), project)

    assert out == {}
