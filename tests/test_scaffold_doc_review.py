"""The doc-review hook of /episteme:scaffold, run as a subprocess over a throwaway git repo."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

HOOK = Path(__file__).parents[1] / "plugin/skills/scaffold/templates/hooks/doc-review.py"
START = date(2026, 11, 1)


class Repo:
    """A git repo whose commits are dated START + day."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir()
        self.git("init", "-q")

    def git(self, *args: str, day: int = 0) -> str:
        stamp = f"{(START + timedelta(days=day)).isoformat()}T12:00:00+00:00"
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        done = subprocess.run(
            ["git", "-c", "user.name=Ana", "-c", "user.email=ana@example.com", *args],
            cwd=self.path, env=env, check=True, capture_output=True, text=True, encoding="utf-8",
        )
        return done.stdout.strip()

    def commit(self, message: str, files: dict[str, str], day: int = 0) -> str:
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="")
        self.git("add", *files)
        self.git("commit", "-q", "-m", message, day=day)
        return self.git("rev-parse", "--short", "HEAD")

    def feats(self, count: int, day: int = 1) -> None:
        for n in range(count):
            self.commit(f"feat: change {n}", {"src/app.py": f"FEAT = {n}\n"}, day=day)


# @CodeScene(disable:"Excess Number of Function Arguments")
def run(repo: Path, today: int, *args: str, session: str = "s1", source: str = "startup",
        env_extra: dict | None = None, hook: Path = HOOK) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(repo),
        "DOC_REVIEW_TODAY": (START + timedelta(days=today)).isoformat(),
        "GIT_CONFIG_GLOBAL": os.devnull,
        **(env_extra or {}),
    }
    payload = json.dumps({"session_id": session, "source": source})
    return subprocess.run(
        [sys.executable, str(hook), *args], input=payload, env=env, cwd=repo,
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )


def output(done: subprocess.CompletedProcess[str]) -> dict:
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout.strip() else {}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")


def marked(repo: Repo, doc: str = "README.md") -> str:
    """A first commit, then the doc with a mark pointing at it (both on START)."""
    sha = repo.commit("chore: init", {"src/app.py": "VALUE = 0\n"})
    repo.commit("docs: add doc", {doc: f"<!-- doc-review: {START.isoformat()} {sha} -->\n# Doc\n"})
    return sha


def test_reads_the_mark_and_warns_after_8_days_and_5_feats(repo: Repo) -> None:
    sha = marked(repo)
    repo.feats(5)

    result = output(run(repo.path, 8))

    assert "README.md sin revisar: 8 días, 15 puntos (5 commits)" in result["systemMessage"]
    context = result["hookSpecificOutput"]["additionalContext"]
    assert f"(desde {sha})" in context
    assert "/episteme:scaffold auditar readme" in context
    assert "snooze README.md 7" in context


def test_without_a_mark_falls_back_to_the_last_commit_of_the_file(repo: Repo) -> None:
    sha = repo.commit("docs: readme", {"README.md": "# Doc\n"})
    repo.feats(5)

    context = output(run(repo.path, 8))["hookSpecificOutput"]["additionalContext"]

    assert f"(desde {sha})" in context


def test_an_unknown_sha_falls_back_to_since(repo: Repo) -> None:
    mark = f"<!-- doc-review: {START.isoformat()} deadbee -->\n"
    repo.commit("docs: readme", {"README.md": mark})
    repo.feats(5)

    context = output(run(repo.path, 8))["hookSpecificOutput"]["additionalContext"]

    assert f"(desde {START.isoformat()})" in context
    assert "15 puntos" in context


def test_points_by_type_and_markdown_only_commits_do_not_count(repo: Repo) -> None:
    marked(repo)
    marked_claude = repo.git("rev-parse", "--short", "HEAD")
    mark = f"<!-- doc-review: {START.isoformat()} {marked_claude} -->\n"
    repo.commit("docs: claude", {"CLAUDE.md": mark})
    repo.commit("feat: a", {"src/a.py": "A = 1\n"}, day=1)  # new file
    repo.commit("fix: b", {"src/app.py": "VALUE = 2\n"}, day=1)
    repo.commit("refactor: c", {"src/app.py": "VALUE = 3\n"}, day=1)
    repo.commit("wip c", {"src/app.py": "VALUE = 4\n"}, day=1)
    repo.commit("docs: only markdown", {"docs/x.md": "x\n"}, day=1)

    message = output(run(repo.path, 30))["systemMessage"]

    # README: feat 3 + fix 1 + refactor 0 + unknown 1. CLAUDE: feat 2 + new file 2 + 1 + 2 + 1.
    assert "README.md sin revisar: 30 días, 5 puntos (4 commits)" in message
    assert "CLAUDE.md sin revisar: 30 días, 8 puntos (4 commits)" in message


def test_a_new_tag_makes_the_doc_due_with_few_points(repo: Repo) -> None:
    marked(repo)
    repo.commit("fix: small", {"src/app.py": "VALUE = 9\n"}, day=1)
    repo.git("tag", "v1.0.0")

    message = output(run(repo.path, 1))["systemMessage"]

    assert "README.md sin revisar: 1 día, 11 puntos (1 commit, 1 tag)" in message


# @CodeScene(disable:"Excess Number of Function Arguments")
@pytest.mark.parametrize(
    ("days", "feats", "fixes", "due"),
    [
        (7, 5, 0, True),  # fast threshold: 7 days and 15 points
        (6, 5, 0, False),
        (7, 4, 2, False),  # 14 points
        (30, 0, 1, True),  # slow threshold: 30 days and 1 point
        (29, 0, 1, False),
    ],
)
def test_thresholds(repo: Repo, days: int, feats: int, fixes: int, due: bool) -> None:
    marked(repo)
    repo.feats(feats)
    for n in range(fixes):
        repo.commit(f"fix: {n}", {"src/app.py": f"FIX = {n}\n"}, day=1)

    result = output(run(repo.path, days))

    assert bool(result) is due


def test_zero_points_never_warns(repo: Repo) -> None:
    marked(repo)
    repo.commit("docs: more", {"docs/guide.md": "x\n"}, day=1)

    assert output(run(repo.path, 400)) == {}


def test_snooze_silences_until_the_date(repo: Repo) -> None:
    marked(repo)
    repo.feats(5)

    snoozed = run(repo.path, 8, "snooze", "README.md", "7")

    assert snoozed.returncode == 0
    assert output(run(repo.path, 14, session="s2")) == {}
    assert output(run(repo.path, 15, session="s3"))


def test_same_session_does_not_repeat(repo: Repo) -> None:
    marked(repo)
    repo.feats(5)

    first = output(run(repo.path, 8))
    second = output(run(repo.path, 8))
    compact = output(run(repo.path, 8, session="s9", source="compact"))

    assert first
    assert second == {}
    assert compact == {}


def test_not_a_git_repo_exits_silently(tmp_path: Path) -> None:
    done = run(tmp_path, 8, env_extra={"GIT_CEILING_DIRECTORIES": str(tmp_path.parent)})

    assert done.returncode == 0
    assert done.stdout == ""


def test_propose_mode_changes_the_instruction(repo: Repo, tmp_path: Path) -> None:
    hook = tmp_path / "doc-review.py"
    hook.write_text(
        HOOK.read_text(encoding="utf-8").replace('MODE = "auto"', 'MODE = "propose"', 1),
        encoding="utf-8", newline="",
    )
    marked(repo)
    repo.feats(5)

    context = output(run(repo.path, 8, hook=hook))["hookSpecificOutput"]["additionalContext"]

    assert "propón el diff y aplica solo lo aprobado" in context
    assert "corrige lo que contradiga" not in context


@pytest.mark.parametrize("args", [["snooze", "README.md"], ["snooze", "./README.md", "7"]])
def test_a_wrong_snooze_prints_the_usage(repo: Repo, args: list[str]) -> None:
    marked(repo)

    done = run(repo.path, 0, *args)

    assert done.returncode == 0
    assert done.stdout.startswith("uso: doc-review.py snooze")


def test_a_markdown_file_with_accents_does_not_count(repo: Repo) -> None:
    marked(repo)
    repo.commit("feat: docs", {"docs/instalación.md": "x\n"}, day=1)

    assert output(run(repo.path, 400)) == {}


def test_a_mark_outside_the_history_falls_back_to_since(repo: Repo) -> None:
    repo.commit("chore: init", {"src/app.py": "VALUE = 0\n"})
    repo.git("checkout", "-q", "-b", "side")
    side = repo.commit("feat: side", {"src/side.py": "S = 1\n"})
    repo.git("checkout", "-q", "-")
    mark = f"<!-- doc-review: {START.isoformat()} {side} -->\n"
    repo.commit("docs: readme", {"README.md": mark})
    repo.feats(5)

    context = output(run(repo.path, 8))["hookSpecificOutput"]["additionalContext"]

    assert f"(desde {START.isoformat()})" in context
