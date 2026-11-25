"""The /episteme:scaffold skill: its files, templates and the hooks it copies."""

from __future__ import annotations

import json
import os
import re
import runpy
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


def _hook_module() -> dict:
    return runpy.run_path(str(HOOKS / "python-serena.py"), run_name="python_serena_template")


def _call(tool: str, **tool_input: str) -> dict:
    return {"tool_name": tool, "tool_input": tool_input}


def _make_project_dirs(root: Path) -> None:
    for name in ("src", "tests", "scripts", "docs", "plugin", "plugin-docs", ".github"):
        (root / name).mkdir()


PYTHON_CALLS = [
    _call("mcp__serena__find_symbol", name_path="x"),
    _call("Read", file_path="/p/a.py"),
    _call("Edit", file_path="/p/a.pyi"),
    _call("MultiEdit", file_path="a.py"),
    _call("Write", file_path="a.py"),
    _call("NotebookEdit", file_path="a.py"),
    _call("Grep", pattern="x", type="py"),
    _call("Grep", pattern="x", glob="*.py"),
    _call("Grep", pattern="x", path="a.pyi"),
    _call("Grep", pattern="x", path="src/pkg"),
    _call("Bash", command="grep -rn x src/"),
    _call("Bash", command="grep -n x tests/test_a.py"),
    _call("Bash", command="grep -rn x --include=*.py ."),
    _call("Bash", command="rg -g '*.py' x"),
    _call("Bash", command="rg -t py x"),
    _call("Bash", command="rg --type=py x"),
    _call("Bash", command="grep -rn x src tests"),
    _call("Bash", command="grep -n x src/pkg/mod.py"),
    _call("Bash", command="cat > a.py <<'EOF'\nx\nEOF"),
]
OTHER_CALLS = [
    _call("Read", file_path="/p/README.md"),
    _call("Edit", file_path="/p/a.json"),
    _call("Grep", pattern="x", glob="*.md"),
    _call("Grep", pattern="x", path="docs"),
    _call("Grep", pattern="x"),
    _call("Bash", command="grep -n x README.md"),
    _call("Bash", command="curl -s https://example.com/a | grep x"),
    _call("Bash", command="ls docs"),
    _call("Bash", command="grep x notes.pyc"),
    _call("WebFetch", url="https://example.com/a.py"),
    _call(
        "Bash",
        command="/usr/bin/grep -rn 'CLAUDE.md' --include=*.md "
        "docs plugin plugin-docs tests src .github",
    ),
    _call(
        "Bash",
        command="/usr/bin/grep -rn 'CLAUDE\\.md' docs plugin plugin-docs tests src .github",
    ),
    _call("Bash", command="/usr/bin/grep -rln 'Al cambiar código\\|Cómo se trabaja' plugin tests"),
    _call(
        "Bash",
        command="cat > body.md <<'EOF'\nsee hooks/python-serena.py and src/\nEOF\n"
        "gh issue create -F body.md",
    ),
    _call("Bash", command='gh pr create --body "fix hooks/python-serena.py"'),
    _call("Bash", command="cat tests/fixtures/vault/a.md"),
    _call("Bash", command="grep -rnE 'a|include=\\*\\.py' '--include=*.md' docs"),
    _call("Bash", command="cat scripts/run.sh"),
]


@pytest.mark.parametrize("call", PYTHON_CALLS)
def test_python_serena_counts_python_calls(call: dict, tmp_path: Path) -> None:
    _make_project_dirs(tmp_path)
    assert _hook_module()["python_call"]({**call, "cwd": str(tmp_path)}) is True


@pytest.mark.parametrize("call", OTHER_CALLS)
def test_python_serena_ignores_other_calls(call: dict, tmp_path: Path) -> None:
    _make_project_dirs(tmp_path)
    assert _hook_module()["python_call"]({**call, "cwd": str(tmp_path)}) is False


def _fake_serena_hooks(tmp_path: Path) -> tuple[dict, Path]:
    """A PATH with a `serena-hooks` that records its stdin and exits 3."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "called.json"
    script = bin_dir / "serena-hooks"
    script.write_text(
        f"#!/bin/sh\ncat > '{marker}'\necho out-text\necho err-text >&2\nexit 3\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "CLAUDE_PROJECT_DIR": str(tmp_path)}
    return env, marker


@pytest.mark.skipif(sys.platform == "win32", reason="the fake serena-hooks is a sh script")
def test_remind_skips_serena_hooks_for_a_non_python_call(tmp_path: Path) -> None:
    env, marker = _fake_serena_hooks(tmp_path)
    event = json.dumps(_call("Bash", command="grep -n x README.md"))

    done = _run_hook("python-serena.py", "remind", stdin=event, env=env, cwd=tmp_path)

    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert not marker.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the fake serena-hooks is a sh script")
def test_remind_forwards_a_python_call_and_its_result(tmp_path: Path) -> None:
    env, marker = _fake_serena_hooks(tmp_path)
    event = _call("Bash", command="grep -rn x src/")

    done = _run_hook("python-serena.py", "remind", stdin=json.dumps(event), env=env, cwd=tmp_path)

    assert json.loads(marker.read_text(encoding="utf-8")) == event
    assert done.returncode == 3
    assert done.stdout.strip() == "out-text"
    assert done.stderr.strip() == "err-text"


def test_serena_python_settings_route_remind_through_the_hook() -> None:
    settings = json.loads(
        (TEMPLATES / "settings" / "serena-python.json").read_text(encoding="utf-8")
    )
    first = settings["hooks"]["PreToolUse"][0]

    assert first["matcher"] == ""
    assert first["hooks"][0]["command"] == (
        'python3 -I "$CLAUDE_PROJECT_DIR/.claude/hooks/python-serena.py" remind'
    )
