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
    for event in ("UserPromptSubmit", "SessionStart", "PreToolUse"):
        out = json.loads(hookmode.render(event, "warn"))
        expected = {"hookEventName": event, "additionalContext": "warn"}
        assert out == {"hookSpecificOutput": expected}
    assert hookmode.render("PreCompact", "anything") == ""
    for event in hookmode.EVENTS:
        assert hookmode.render(event, "") == ""
    with pytest.raises(EpistemeError) as err:
        hookmode.check("Stop")
    assert err.value.code == "invalid_argument"


def test_context_events_emit_single_json_object() -> None:
    for event in hookmode.CONTEXT_EVENTS:
        out = json.loads(hookmode.render(event, "hello"))
        assert list(out) == ["hookSpecificOutput"]
        assert out["hookSpecificOutput"]["hookEventName"] == event


def test_render_caps_at_newline() -> None:
    text = "\n".join("x" * 99 for _ in range(300))
    raw = hookmode.render("UserPromptSubmit", text)
    plain = json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    assert len(plain) <= 10_000 and plain.endswith(hookmode.CUT_MARK)
    assert plain.removesuffix(hookmode.CUT_MARK).endswith("x")
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


def test_notice_is_a_coloured_system_message_on_session_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    out = json.loads(hookmode.render("SessionStart", "ctx", "recuperado"))
    assert out["systemMessage"] == "\x1b[1;32mrecuperado\x1b[0m"
    assert out["hookSpecificOutput"]["additionalContext"] == "ctx"
    assert json.loads(hookmode.render("SessionStart", "", "solo aviso")) == {
        "systemMessage": "\x1b[1;32msolo aviso\x1b[0m"
    }
    for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
        assert "systemMessage" not in json.loads(hookmode.render(event, "ctx", "aviso"))
        assert hookmode.render(event, "", "aviso") == ""
    assert hookmode.render("PreCompact", "ctx", "aviso") == ""
    monkeypatch.setenv("NO_COLOR", "1")
    assert json.loads(hookmode.render("SessionStart", "", "plano"))["systemMessage"] == "plano"


def test_notice_drops_control_characters_from_note_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    hostile = "tarea\x1b]0;pwn\x07\x1b[2J\x9b31m\nsegunda\x00línea"

    out = json.loads(hookmode.render("SessionStart", "", f"retomada: {hostile}"))

    assert out["systemMessage"] == "retomada: tarea]0;pwn[2J31m\nsegunda" + "línea"
    assert not hookmode._CONTROL.search(out["systemMessage"].replace("\n", ""))


def test_notice_keeps_its_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    notice = "episteme · archivadas 2\n\n  \nepisteme · revisión pendiente\x1b[2J"

    out = json.loads(hookmode.render("SessionStart", "", notice))

    assert out["systemMessage"] == "episteme · archivadas 2\nepisteme · revisión pendiente[2J"
    assert "\x1b" not in out["systemMessage"]


def test_notice_is_painted_line_by_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)

    out = json.loads(hookmode.render("SessionStart", "", "a\nb\x1b[2J"))

    assert out["systemMessage"] == hookmode.paint("a\nb[2J")


def test_clean_block_cuts_the_whole_block() -> None:
    block = hookmode.clean_block("\n".join(["x" * 100] * 10), 250)

    assert len(block) == 250
    assert block.endswith("…")
    assert block.count("\n") == 2


def test_clean_line_drops_bidi_marks() -> None:
    assert hookmode.clean_line("a\u061cb\u202ec\u2066d") == "abcd"


def test_clean_line_cuts_long_text() -> None:
    cleaned = hookmode.clean_line("x" * 500)

    assert len(cleaned) == hookmode.LINE_MAX
    assert cleaned.endswith("…")
