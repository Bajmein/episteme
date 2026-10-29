"""hookmode.py and file matching (case 16 at module level)."""

from __future__ import annotations

import json
import ntpath
import os
import sys

import pytest

from episteme import hookmode
from episteme.errors import EpistemeError
from episteme.memory import file_matches, project_relative


def test_render_per_event() -> None:
    assert hookmode.render("UserPromptSubmit", "hello") == "hello"
    assert hookmode.render("SessionStart", "hello") == "hello"
    out = json.loads(hookmode.render("PreToolUse", "warn"))
    expected = {"hookEventName": "PreToolUse", "additionalContext": "warn"}
    assert out == {"hookSpecificOutput": expected}
    assert hookmode.render("PreCompact", "anything") == ""
    for event in hookmode.EVENTS:
        assert hookmode.render(event, "") == ""
    with pytest.raises(EpistemeError) as err:
        hookmode.check("Stop")
    assert err.value.code == "invalid_argument"


def test_render_caps_at_newline() -> None:
    text = "\n".join("x" * 99 for _ in range(300))
    plain = hookmode.render("UserPromptSubmit", text)
    assert len(plain) <= 10_000 and plain.endswith("x")
    ctx = json.loads(hookmode.render("PostToolUse", text))["hookSpecificOutput"]
    assert len(ctx["additionalContext"]) <= 10_000


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths")
def test_project_relative_posix() -> None:
    entry = ".claude/hooks/serena_guard.py"
    abs_file = "/tmp/proyecto/.claude/hooks/serena_guard.py"
    rel = project_relative(abs_file, "/tmp/proyecto")
    assert rel == entry
    assert file_matches(abs_file, rel, entry)


def test_project_relative_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "path", ntpath)
    file, proj = r"C:\Users\ana\proj\src\app.py", r"C:\Users\ana\proj"
    assert project_relative(file, proj) == "src/app.py"
    assert project_relative(file, r"c:\users\ana\proj") == "src/app.py"
    assert project_relative(r"C:\Users\ana\other\a.py", proj) == "C:/Users/ana/other/a.py"
    rel = project_relative(file, proj)
    assert file_matches(file, rel, "src/*.py")


def test_file_matching() -> None:
    assert file_matches("/x/.claude/hooks/a.py", "/x/.claude/hooks/a.py", ".claude/hooks/a.py")
    assert not file_matches("data.py", "data.py", "a.py")
    assert not file_matches("/p/src/data.py", "src/data.py", "a.py")
    assert file_matches("/p/src/a.py", "src/a.py", "a.py")
    assert file_matches("/p/src/x.py", "src/x.py", "src/*.py")
    assert not file_matches("/p/lib/x.py", "lib/x.py", "src/*.py")
    assert project_relative("./src/a.py", None) == "src/a.py"
