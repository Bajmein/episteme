from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

from episteme import memory

pytestmark = pytest.mark.anyio

GUARD = ".claude/hooks/serena_guard.py"


def hook_text(raw: str) -> str:
    """Text a hook call delivers: the plain string or the additionalContext of the JSON envelope."""
    if raw.startswith("{"):
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return raw


def test_repeat_within_window() -> None:
    memory._SURFACED.clear()
    assert memory.surface_repeated("s", "a.py", ["m1"], now=100.0) is False
    assert memory.surface_repeated("s", "a.py", ["m1"], now=200.0) is True


def test_changed_paths_not_repeated() -> None:
    memory._SURFACED.clear()
    assert memory.surface_repeated("s", "a.py", ["m1"], now=100.0) is False
    assert memory.surface_repeated("s", "a.py", ["m1", "m2"], now=110.0) is False


def test_shown_again_after_window() -> None:
    memory._SURFACED.clear()
    assert memory.surface_repeated("s", "a.py", ["m1"], now=100.0) is False
    later = 100.0 + memory.SURFACE_REPEAT_SECONDS
    assert memory.surface_repeated("s", "a.py", ["m1"], now=later) is False


def test_sessions_independent() -> None:
    memory._SURFACED.clear()
    assert memory.surface_repeated("s1", "a.py", ["m1"], now=100.0) is False
    assert memory.surface_repeated("s2", "a.py", ["m1"], now=101.0) is False
    assert memory.surface_repeated("s1", "a.py", ["m1"], now=102.0) is True


async def test_surface_hook_skips_repeat(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("remember", type="lesson", title="Nota del guard", body="x" * 50, files=[GUARD])
        args = {"file": GUARD, "hook_event": "PostToolUse"}
        first = await c.ok("surface", session="sess-1", **args)
        assert "Nota del guard" in hook_text(first)
        assert hook_text(await c.ok("surface", session="sess-1", **args)) == ""
        # no session: never suppressed
        assert "Nota del guard" in hook_text(await c.ok("surface", **args))
        assert "Nota del guard" in hook_text(await c.ok("surface", **args))
        # agent mode: always full JSON, even with session
        for _ in range(2):
            res = await c.ok("surface", file=GUARD, session="sess-1")
            assert [m["title"] for m in res["memories"]] == ["Nota del guard"]
