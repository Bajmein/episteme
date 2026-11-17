"""The /episteme:scaffold skill: its files, templates and the hooks it copies."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "plugin" / "skills" / "scaffold"
TEMPLATES = SKILL / "templates"
HOOKS = TEMPLATES / "hooks"
EPISTEME_LINE = "Vault `episteme`:"

FILES = [
    "SKILL.md",
    "referencia/auditoria.md",
    "referencia/stacks.md",
    "templates/README.md",
    "templates/CLAUDE.md",
    "templates/CLAUDE.local.md",
    "templates/CHANGELOG.md",
    "templates/gitignore",
    "templates/github/CONTRIBUTING.md",
    "templates/github/ESTILO.md",
    "templates/github/pull_request_template.md",
    "templates/github/gitmessage",
    "templates/rules/regla.md",
    "templates/rules/docs.md",
    "templates/rules/python/style.md",
    "templates/rules/python/testing.md",
    "templates/rules/python/security.md",
    "templates/rules/python/serena.md",
    "templates/hooks/session-brief.py",
    "templates/hooks/python-serena.py",
    "templates/hooks/doc-review.py",
    "templates/serena/project.yml",
    "templates/serena/ty-lsp.sh",
    "templates/settings/serena-python.json",
    "templates/settings/session-brief.json",
    "templates/settings/doc-review.json",
]
# Real paths and names must not leak into the templates: only /home/ana/ is a neutral example.
PERSONAL = re.compile(r"/home/(?!ana/)|/Users/|C:\\Users|kenno|Bajmein", re.IGNORECASE)


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(
        ["git", "-c", "user.name=Ana", "-c", "user.email=ana@example.com", *args],
        cwd=cwd, env=env, check=True, capture_output=True,
    )


# @CodeScene(disable:"Excess Number of Function Arguments")
def _run_hook(name: str, *args: str, stdin: str = "", env: dict | None = None,
              cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / name), *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
        env=env or dict(os.environ), cwd=cwd, timeout=60, check=False,
    )


@pytest.fixture
def python_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "core.py").write_text(
        '"""Core of the package."""\n', encoding="utf-8", newline=""
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Sin publicar]\n\n- Something new.\n", encoding="utf-8", newline=""
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feat: first")
    return repo


def test_every_file_of_the_skill_exists() -> None:
    missing = [name for name in FILES if not (SKILL / name).is_file()]
    assert missing == []


def test_claude_template_carries_the_same_episteme_line_as_setup() -> None:
    setup = (ROOT / "plugin" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    template = (TEMPLATES / "CLAUDE.md").read_text(encoding="utf-8")

    [quoted] = [ln[2:] for ln in setup.splitlines() if ln.startswith(f"> {EPISTEME_LINE}")]
    [listed] = [ln[2:] for ln in template.splitlines() if ln.startswith(f"- {EPISTEME_LINE}")]

    assert listed == quoted


@pytest.mark.parametrize("name", FILES)
def test_no_real_paths_or_names_in_the_skill(name: str) -> None:
    text = (SKILL / name).read_text(encoding="utf-8")
    assert PERSONAL.search(text) is None


@pytest.mark.parametrize("name", ["serena-python", "session-brief", "doc-review"])
def test_module_settings_are_json_with_hooks(name: str) -> None:
    settings = json.loads((TEMPLATES / "settings" / f"{name}.json").read_text(encoding="utf-8"))
    assert settings["hooks"]


def test_gitignore_has_a_block_per_stack() -> None:
    reference = (SKILL / "referencia" / "stacks.md").read_text(encoding="utf-8")
    stacks = set(re.findall(r"# stack: ([\w-]+)", reference))
    gitignore = (TEMPLATES / "gitignore").read_text(encoding="utf-8")

    assert stacks >= {"python-uv", "node", "php", "wordpress"}
    assert all(f"# stack: {stack}\n" in gitignore for stack in stacks)


def test_review_mark_on_line_one_of_readme_and_claude_templates() -> None:
    for name in ("README.md", "CLAUDE.md"):
        first = (TEMPLATES / name).read_text(encoding="utf-8").splitlines()[0]
        assert first == "<!-- doc-review: {{fecha}} {{sha}} -->"


def test_session_brief_returns_context_on_a_python_repo(python_repo: Path) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(python_repo), "NO_COLOR": "1"}

    done = _run_hook("session-brief.py", stdin='{"source": "startup"}', env=env)

    assert done.returncode == 0
    context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "`pkg/core.py`: Core of the package." in context
    assert "Something new." in context


@pytest.mark.skipif(sys.platform == "win32", reason="builds a PATH of symlinks")
def test_session_brief_works_without_gh(python_repo: Path, tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(git)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(python_repo), "PATH": str(bin_dir)}

    done = _run_hook("session-brief.py", stdin="{}", env=env)

    assert done.returncode == 0
    output = json.loads(done.stdout)
    assert "Rama:" in output["hookSpecificOutput"]["additionalContext"]
    assert "gh" not in output["systemMessage"]


@pytest.mark.parametrize("stdin", ["", "{}"])
def test_python_serena_with_an_empty_event_is_silent(stdin: str, tmp_path: Path) -> None:
    done = _run_hook("python-serena.py", "pre", stdin=stdin, cwd=tmp_path)

    assert done.returncode == 0
    assert done.stdout == ""


@pytest.mark.parametrize("hook", ["session-brief.py", "doc-review.py"])
def test_hooks_start_with_no_input(hook: str, tmp_path: Path) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}

    done = _run_hook(hook, env=env, cwd=tmp_path)

    assert done.returncode == 0
