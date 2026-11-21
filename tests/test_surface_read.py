from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

GUARD = ".claude/hooks/serena_guard.py"


def hook_text(raw: str) -> str:
    """Text a hook call delivers: the plain string or the additionalContext of the JSON envelope."""
    if raw.startswith("{"):
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return raw


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


async def test_surface_after_compaction_skips_what_the_resent_welcome_brought(
    vault: Path,
) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("remember", type="lesson", title="Nota del guard", body="x" * 50, files=[GUARD])
        args = {"file": GUARD, "hook_event": "PostToolUse", "session": "sess-2"}
        assert "Nota del guard" in hook_text(await c.ok("surface", **args))
        assert hook_text(await c.ok("surface", **args)) == ""
        # compact|clear resends the welcome: what it brings is not surfaced again
        welcome = await c.ok("context", mode="welcome", session="sess-2", hook_event="SessionStart")
        assert "Nota del guard" in hook_text(welcome)
        assert hook_text(await c.ok("surface", **args)) == ""
