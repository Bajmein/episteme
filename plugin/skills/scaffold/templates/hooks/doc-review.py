#!/usr/bin/env python3
"""SessionStart hook: ask Claude to review README.md and CLAUDE.md when git activity piles up.

Module doc-review of /episteme:scaffold. Each document carries a review mark on its first line,
`<!-- doc-review: YYYY-MM-DD <sha> -->`, written only by a full review. The hook weighs the
commits since that mark by Conventional Commits type and, once a document is due, asks Claude to
review it when the current task is done. One notice per session; `compact` and `clear` repeat
nothing.

    python3 .claude/hooks/doc-review.py                     SessionStart (JSON on stdin)
    python3 .claude/hooks/doc-review.py snooze README.md 7  silence one document for 7 days

Standard library only. Any error exits 0 without output: the hook never breaks the session.
State lives in `$(git rev-parse --git-path doc-review.json)`: never versioned, one per worktree.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

# "auto": Claude fixes what contradicts the repo, moves the mark and reports the diff.
# "propose": Claude shows the diff and applies only what the person approves.
MODE = "auto"
DOCS = ["README.md", "CLAUDE.md"]
FAST_DAYS = 7  # a lot of activity in little time...
FAST_POINTS = 15
SLOW_DAYS = 30  # ...or a little, but sustained
SLOW_POINTS = 1
UNKNOWN_TYPE_POINTS = 1
GIT_TIMEOUT = 5
SKIPPED_SOURCES = {"compact", "clear"}
SESSIONS_KEPT = 20  # recent session ids that already got the notice
HOOK_PATH = '"$CLAUDE_PROJECT_DIR/.claude/hooks/doc-review.py"'
USAGE = "uso: doc-review.py snooze <documento> <días>"
STATE_FILE = "doc-review.json"
TAG_DATE = "%(creatordate:short)"
MARK = re.compile(r"^<!-- doc-review: (\d{4}-\d{2}-\d{2}) ([0-9a-f]{7,40}) -->$")
COMMIT_TYPE = re.compile(r"^(\w+)(?:\([^)]*\))?!?:")
STRUCTURAL = frozenset("ADR")  # added, deleted or renamed files (--name-status)


class Weights(NamedTuple):
    types: dict[str, int]
    file: int
    tag: int


WEIGHTS = {
    "README.md": Weights(
        {"feat": 3, "fix": 1, "refactor": 0, "perf": 0, "ci": 0, "build": 0, "chore": 0}, 0, 10
    ),
    "CLAUDE.md": Weights(
        {"feat": 2, "fix": 1, "refactor": 2, "perf": 2, "ci": 2, "build": 2, "chore": 2}, 2, 10
    ),
}
PARTS = {"README.md": "readme", "CLAUDE.md": "claude"}


@dataclass(frozen=True)
class Baseline:
    day: date
    sha: str | None  # None: the sha is not in HEAD's history (rebase, squash); use --since


@dataclass(frozen=True)
class Commit:
    kind: str
    changes: tuple[tuple[str, str], ...]  # (status letter, path)


@dataclass(frozen=True)
class Status:
    doc: str
    since: str
    days: int
    points: int
    commits: int
    tags: int

    @property
    def due(self) -> bool:
        if self.points <= 0:
            return False
        fast = self.days >= FAST_DAYS and self.points >= FAST_POINTS
        slow = self.days >= SLOW_DAYS and self.points >= SLOW_POINTS
        return self.tags > 0 or fast or slow


def git(root: Path, *args: str) -> str | None:
    """The command's stdout, or None if git fails or is missing."""
    try:
        # fixed argv, no shell.
        done = subprocess.run(  # nosec B603 B607
            ["git", "-c", "core.quotePath=false", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def today() -> date:
    override = os.environ.get("DOC_REVIEW_TODAY")
    return date.fromisoformat(override) if override else date.today()


def project_root(payload: dict) -> Path | None:
    start = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    out = git(Path(start), "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None


def read_mark(path: Path) -> tuple[date, str] | None:
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    found = MARK.match(first.strip())
    if found is None:
        return None
    try:
        return date.fromisoformat(found[1]), found[2]
    except ValueError:
        return None


def in_history(root: Path, sha: str) -> bool:
    """The sha exists and is an ancestor of HEAD (a squashed branch commit is not)."""
    return git(root, "merge-base", "--is-ancestor", sha, "HEAD") is not None


def baseline(root: Path, doc: str) -> Baseline | None:
    """The mark, or the last commit that touched the document when there is none."""
    mark = read_mark(root / doc)
    if mark is not None:
        day, sha = mark
        return Baseline(day, sha if in_history(root, sha) else None)
    out = (git(root, "log", "-1", "--format=%H %cs", "--", doc) or "").split()
    if len(out) != 2:
        return None
    return Baseline(date.fromisoformat(out[1]), out[0])


def range_args(base: Baseline) -> list[str]:
    if base.sha:
        return [f"{base.sha}..HEAD"]
    return [f"--since={base.day.isoformat()}T00:00:00", "HEAD"]


def parse_commit(record: str) -> Commit:
    lines = record.strip("\n").splitlines()
    found = COMMIT_TYPE.match(lines[0]) if lines else None
    split = (line.split("\t") for line in lines[1:])
    changes = tuple((parts[0][:1], parts[-1]) for parts in split if len(parts) > 1)
    return Commit(found[1].lower() if found else "", changes)


def commits(root: Path, base: Baseline) -> list[Commit]:
    out = git(root, "log", "--no-merges", "--format=%x1e%s", "--name-status", *range_args(base))
    return [parse_commit(record) for record in (out or "").split("\x1e") if record.strip()]


def counts(commit: Commit) -> bool:
    """A commit counts unless it only touches Markdown (or nothing)."""
    return any(not path.endswith(".md") for _, path in commit.changes)


def commit_points(commit: Commit, weights: Weights) -> int:
    structural = sum(1 for status, _ in commit.changes if status in STRUCTURAL)
    return weights.types.get(commit.kind, UNKNOWN_TYPE_POINTS) + structural * weights.file


def new_tags(root: Path, base: Baseline) -> int:
    if base.sha:
        out = git(root, "tag", "--merged", "HEAD", "--no-merged", base.sha)
        return len((out or "").split())
    out = git(root, "for-each-ref", "refs/tags", "--merged", "HEAD", f"--format={TAG_DATE}")
    since = base.day.isoformat()
    return sum(1 for day in (out or "").split() if day > since)  # same day: before the review


def status(root: Path, doc: str, now: date) -> Status | None:
    base = baseline(root, doc)
    if base is None:
        return None
    weights = WEIGHTS.get(doc, WEIGHTS["README.md"])
    counted = [commit for commit in commits(root, base) if counts(commit)]
    tags = new_tags(root, base)
    points = sum(commit_points(commit, weights) for commit in counted) + tags * weights.tag
    since = base.sha[:7] if base.sha else base.day.isoformat()
    return Status(doc, since, (now - base.day).days, points, len(counted), tags)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def notice(item: Status) -> str:
    detail = plural(item.commits, "commit")
    if item.tags:
        detail += ", " + plural(item.tags, "tag")
    return (
        f"episteme · {item.doc} sin revisar: {plural(item.days, 'día')}, {item.points} puntos "
        f"({detail}). "
        "Claude lo revisará al cerrar la tarea."
    )


def instruction(item: Status) -> str:
    part = PARTS.get(item.doc, item.doc)
    if MODE == "propose":
        action = (
            "propón el diff y aplica solo lo aprobado; actualiza la línea doc-review al terminar."
        )
    else:
        action = (
            "corrige lo que contradiga al repo, actualiza la línea doc-review y di qué cambiaste "
            "(sin commit)."
        )
    return "\n".join([
        f"doc-review: {item.doc} lleva {plural(item.days, 'día')} y {item.points} puntos de "
        f"actividad sin revisar (desde {item.since}).",
        "No interrumpas la tarea en curso. Al cerrarla, revísalo con "
        f"/episteme:scaffold auditar {part}:",
        action,
        f"Si la persona pide posponerlo: python3 {HOOK_PATH} snooze {item.doc} 7",
    ])


def state_path(root: Path) -> Path | None:
    out = git(root, "rev-parse", "--git-path", STATE_FILE)
    return root / out.strip() if out else None


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def snoozed(state: dict, doc: str, now: date) -> bool:
    until = (state.get("snoozed") or {}).get(doc)
    return isinstance(until, str) and until > now.isoformat()


def due_docs(root: Path, state: dict, now: date) -> list[Status]:
    found = []
    for doc in DOCS:
        if snoozed(state, doc, now):
            continue
        item = status(root, doc, now)
        if item is not None and item.due:
            found.append(item)
    return found


def notify(payload: dict) -> None:
    if payload.get("source") in SKIPPED_SOURCES:
        return
    root = project_root(payload)
    path = state_path(root) if root else None
    if root is None or path is None:
        return
    state = load_state(path)
    session = payload.get("session_id") or ""
    seen = [s for s in state.get("sessions") or [] if isinstance(s, str)]
    if session and session in seen:
        return
    items = due_docs(root, state, today())
    save_state(path, {**state, "sessions": [*seen, session][-SESSIONS_KEPT:]})
    if not items:
        return
    print(
        json.dumps({
            "systemMessage": "\n".join(notice(item) for item in items),
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n\n".join(instruction(item) for item in items),
            },
        })
    )


def snooze(args: list[str]) -> None:
    if len(args) != 2 or args[0] not in DOCS or not args[1].isdigit():
        print(f"{USAGE} (documentos: {', '.join(DOCS)})")
        return
    doc, days = args[0], int(args[1])
    root = project_root({})
    path = state_path(root) if root else None
    if path is None:
        return
    state = load_state(path)
    until = (today() + timedelta(days=days)).isoformat()
    save_state(path, {**state, "snoozed": {**(state.get("snoozed") or {}), doc: until}})
    print(f"doc-review: {doc} pospuesto hasta {until}.")


def read_payload() -> dict:
    text = sys.stdin.read()
    data = json.loads(text) if text.strip() else {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str]) -> None:
    if argv[1:2] == ["snooze"]:
        snooze(argv[2:])
        return
    try:
        notify(read_payload())
    # a hook must never break the session.
    except Exception:  # nosec B110
        pass


if __name__ == "__main__":
    main(sys.argv)
