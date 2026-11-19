"""Consistency of the Claude Code plugin and marketplace shipped in the repo."""

from __future__ import annotations

import json
import runpy
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugin"
SKILLS = PLUGIN / "skills"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    block = text.split("---\n", 2)[1]
    return yaml.safe_load(block)


def test_plugin_version_matches_package() -> None:
    manifest = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["name"] == "episteme"
    assert manifest["version"] == pyproject["project"]["version"]


def test_marketplace_points_to_plugin_dir_without_version() -> None:
    marketplace = _json(ROOT / ".claude-plugin" / "marketplace.json")
    assert marketplace["name"] == "episteme"
    [entry] = marketplace["plugins"]
    assert entry["name"] == "episteme"
    assert entry["source"] == "./plugin"
    assert "version" not in entry


def test_skill_folders() -> None:
    folders = {p.name for p in SKILLS.iterdir() if p.is_dir()}
    assert folders == {"setup", "sesion", "mantencion", "reminder", "scaffold", "docs"}


@pytest.mark.parametrize(
    "skill", ["setup", "sesion", "mantencion", "reminder", "scaffold", "docs"]
)
def test_skill_frontmatter_name_matches_folder(skill: str) -> None:
    meta = _frontmatter(SKILLS / skill / "SKILL.md")
    assert meta["name"] == skill
    assert isinstance(meta["description"], str)
    assert meta["description"].strip()


def test_setup_settings_has_hooks() -> None:
    settings = _json(SKILLS / "setup" / "settings.json")
    assert "hooks" in settings


def test_docs_check_body_hash_matches_episteme() -> None:
    from episteme.docs import body_hash

    script = runpy.run_path(str(SKILLS / "docs" / "scripts" / "docs_check.py"))

    for text in ("# A\r\n\r\nb\r\n", "\n\n# A\n", "> ## Documentation Index\n"):
        assert script["body_hash"](text) == body_hash(text)


def test_setup_allows_docs_status_but_not_docs_write() -> None:
    allow = _json(SKILLS / "setup" / "settings.json")["permissions"]["allow"]

    assert "mcp__episteme__docs_status" in allow
    assert "mcp__episteme__docs_write" not in allow


def test_extractor_agent_frontmatter() -> None:
    meta = _frontmatter(PLUGIN / "agents" / "extractor.md")

    assert meta["name"] == "extractor" and meta["model"] == "sonnet"
    assert meta["effort"] == "low" and meta["background"] is True
    assert "mcp__episteme__session" in meta["tools"]
    assert "transcript_digest.py" in (PLUGIN / "agents" / "extractor.md").read_text(
        encoding="utf-8"
    )


def _hook(settings: dict, event: str) -> list[dict]:
    return [h for entry in settings["hooks"][event] for h in entry["hooks"]]


def test_setup_hooks_drive_the_session_state_without_checkpoint() -> None:
    settings = _json(SKILLS / "setup" / "settings.json")

    [gate] = _hook(settings, "PreCompact")
    [capture] = _hook(settings, "PostCompact")
    [end] = _hook(settings, "SessionEnd")
    restore, plan_restore, welcome = _hook(settings, "SessionStart")
    assert gate["input"]["action"] == "gate" and gate["input"]["trigger"] == "${trigger}"
    assert capture["input"]["summary"] == "${compact_summary}"
    assert end["input"]["transcript"] == "${transcript_path}"
    assert settings["hooks"]["SessionEnd"][0]["matcher"] == "clear"
    assert restore["input"]["action"] == "restore" and restore["input"]["source"] == "${source}"
    assert plan_restore["tool"] == "plan" and plan_restore["input"]["action"] == "restore"
    assert welcome["tool"] == "context"
    tools = {h["tool"] for event in settings["hooks"] for h in _hook(settings, event)}
    assert "checkpoint" not in tools


def test_setup_copies_the_plan_on_exit_plan_mode_and_restores_it() -> None:
    settings = _json(SKILLS / "setup" / "settings.json")
    entries = {e.get("matcher"): e["hooks"] for e in settings["hooks"]["PreToolUse"]}

    [save] = entries["ExitPlanMode"]
    [constraints] = entries["Edit|Write|mcp__serena__.*"]
    restore = _hook(settings, "SessionStart")[1]
    assert save["type"] == "mcp_tool" and save["tool"] == "plan"
    assert save["input"] == {
        "action": "save",
        "plan": "${tool_input.plan}",
        "plan_path": "${tool_input.planFilePath}",
        "session": "${session_id}",
        "project_dir": "${cwd}",
        "hook_event": "${hook_event_name}",
    }
    assert constraints["tool"] == "constraints"
    assert restore["input"] == {
        "action": "restore",
        "source": "${source}",
        "project_dir": "${cwd}",
        "session": "${session_id}",
        "hook_event": "${hook_event_name}",
    }
    assert settings["hooks"]["SessionStart"][0]["matcher"] == "compact|clear"
    assert "mcp__episteme__plan" in settings["permissions"]["allow"]


def test_setup_allows_session_and_only_the_digest_script() -> None:
    allow = _json(SKILLS / "setup" / "settings.json")["permissions"]["allow"]
    bash = [rule for rule in allow if rule.startswith("Bash(")]

    assert "mcp__episteme__session" in allow and "mcp__episteme__remember" not in allow
    assert bash == ["Bash(uv run --no-project --python 3.14 python -I <SESION_SCRIPT> *)"]
    before_path = bash[0].split("<SESION_SCRIPT>")[0]
    assert "*" not in before_path


def test_setup_writes_the_absolute_script_path_and_asks_to_rerun_it() -> None:
    text = (SKILLS / "setup" / "SKILL.md").read_text(encoding="utf-8")

    assert "<SESION_SCRIPT>" in text
    assert "${CLAUDE_SKILL_DIR}/../sesion/scripts/transcript_digest.py" in text
    assert "volver a correr `/episteme:setup`" in text
