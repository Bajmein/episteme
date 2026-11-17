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
    assert folders == {"setup", "pausa", "mantencion", "reminder", "scaffold", "docs"}


@pytest.mark.parametrize(
    "skill", ["setup", "pausa", "mantencion", "reminder", "scaffold", "docs"]
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
