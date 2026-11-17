"""Consistency of the Claude Code plugin and marketplace shipped in the repo."""

from __future__ import annotations

import json
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
    assert folders == {"setup", "pausa", "mantencion", "reminder", "scaffold"}


@pytest.mark.parametrize("skill", ["setup", "pausa", "mantencion", "reminder", "scaffold"])
def test_skill_frontmatter_name_matches_folder(skill: str) -> None:
    meta = _frontmatter(SKILLS / skill / "SKILL.md")
    assert meta["name"] == skill
    assert isinstance(meta["description"], str)
    assert meta["description"].strip()


def test_setup_settings_has_hooks() -> None:
    settings = _json(SKILLS / "setup" / "settings.json")
    assert "hooks" in settings
