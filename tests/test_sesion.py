"""Session state: write nudge per session, delivered registry and surface per memory (stdio)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

from episteme import prompting
from episteme.prompting import SessionState

pytestmark = pytest.mark.anyio

GUARD = ".claude/hooks/serena_guard.py"
OTHER = ".claude/hooks/other_guard.py"
NUDGE = "aún no se ha guardado ninguna memoria"


def hook_text(raw: str) -> str:
    if raw.startswith("{"):
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return raw


def test_nudge_compares_session_writes() -> None:
    st = SessionState(baseline=prompting.WRITES, prompts=8)
    assert NUDGE in prompting.nudge(st)
    st = SessionState(baseline=prompting.WRITES, prompts=8)
    prompting.WRITES += 1
    assert prompting.nudge(st) == ""


async def test_nudge_ignores_writes_outside_the_session(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("context", mode="welcome", session="nud")
        # a memory appears on disk (another session or a person): not this session's write
        note = vault / "memory" / "fabrik" / "2026-10-22-externa.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\ntype: decision\ncreated: 2026-10-22\nstatus: active\npriority: 3\n---\n"
            "# Externa\n\nCuerpo.\n",
            encoding="utf-8",
            newline="",
        )
        for n in range(2, 9):
            r = await c.ok("context", mode="welcome", session="nud")
            assert (NUDGE in r["text"]) == (n == 8)


async def test_nudge_off_after_session_remember(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("context", mode="welcome", session="nud2")
        await c.ok("remember", type="decision", title="Cosa decidida", body="Cuerpo largo " * 5)
        for _ in range(2, 10):
            r = await c.ok("context", mode="welcome", session="nud2")
            assert NUDGE not in r["text"]


async def test_blocked_duplicate_does_not_count(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        args = {"type": "decision", "title": "Zorbflux dicta el formato", "body": "Sin más " * 5}
        await c.ok("remember", **args)
        await c.ok("context", mode="welcome", session="dup")
        dup = await c.ok("remember", **args)
        assert dup["created"] is False
        for n in range(2, 9):
            r = await c.ok("context", mode="welcome", session="dup")
            assert (NUDGE in r["text"]) == (n == 8)


async def test_surface_not_repeated_across_files(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok(
            "remember", type="lesson", title="Nota compartida", body="x" * 50, files=[GUARD, OTHER]
        )
        await c.ok("remember", type="lesson", title="Nota solo otra", body="y" * 50, files=[OTHER])
        a = {"hook_event": "PostToolUse", "session": "sf"}
        first = hook_text(await c.ok("surface", file=GUARD, **a))
        assert "Nota compartida" in first
        second = hook_text(await c.ok("surface", file=OTHER, **a))
        assert "Nota compartida" not in second
        assert "Nota solo otra" in second
        assert "(+1 ya mostradas)" in second
        # same file again: nothing new
        assert hook_text(await c.ok("surface", file=OTHER, **a)) == ""
        # another session sees everything
        other = hook_text(await c.ok("surface", file=OTHER, hook_event="PostToolUse", session="s2"))
        assert "Nota compartida" in other and "ya mostradas" not in other


async def test_recall_skips_what_welcome_delivered(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        made = await c.ok(
            "remember",
            type="decision",
            title="Zorbflux dicta el formato",
            body="Sin más.",
            priority=5,
        )
        first = await c.ok("context", mode="welcome", session="rw")
        assert made["path"] in first["text"]
        r = await c.ok("context", mode="welcome", session="rw", prompt="sobre zorbflux")
        assert made["path"] not in r["text"]


async def test_welcome_after_compact_or_clear_brings_the_session_trail(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("context", mode="welcome", session="antes")
        made = await c.ok(
            "remember",
            type="insight",
            title="Rastro zeta de la sesión",
            body="Algo aprendido antes de compactar. " * 3,
            project="otro",  # not in fabrik's welcome, so only the trail can bring it back
        )
        first = await c.ok("context", mode="welcome", session="antes")
        assert first["already_sent"] and "De esta sesión" not in first["text"]
        # /clear: a new session id, same server process
        raw = await c.ok(
            "context", mode="welcome", session="despues", hook_event="SessionStart", source="clear"
        )
        out = json.loads(raw)
        text = out["hookSpecificOutput"]["additionalContext"]
        assert "De esta sesión, antes de compactar o limpiar" in text
        assert f"({made['path']}) · escrita" in text
        assert "contexto recuperado tras /clear" in out["systemMessage"]
        assert "de esta sesión" in out["systemMessage"]
        # the first prompt after it does not repeat the welcome nor the notice
        nxt = await c.ok(
            "context", mode="welcome", session="despues", hook_event="UserPromptSubmit"
        )
        assert "systemMessage" not in nxt and "De esta sesión" not in nxt


def test_recovered_notice_wording() -> None:
    assert prompting.recovered_notice("compact", 12, 2) == (
        "episteme · contexto recuperado tras compactar: 12 memorias del proyecto y 2 de esta sesión"
    )
    assert prompting.recovered_notice("${source}", 0, 1).endswith(
        "tras compactar o limpiar: 1 memorias de esta sesión"
    )
    assert "no había memorias" in prompting.recovered_notice(None, 0, 0)
