"""Server instructions: triggers for reading and saving, within the MCP size limit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio


async def test_instructions_carry_triggers_and_fit(vault: Path) -> None:
    async with mcp_client(vault) as c:
        text = c.session.initialize_result.instructions
        assert text.startswith("episteme is the project memory")
        assert len(text) <= 2000
        for needle in ('context(mode="task"', "search is literal", "Save without being asked"):
            assert needle in text


async def test_instructions_name_any_agent_memory(vault: Path) -> None:
    async with mcp_client(vault) as c:
        text = c.session.initialize_result.instructions

    assert "auto memory" not in text
    assert "AGENTS.md" in text and "GEMINI.md" in text


async def test_instructions_recommend_description_link_and_read_links(vault: Path) -> None:
    async with mcp_client(vault) as c:
        text = c.session.initialize_result.instructions
        names = {t.name for t in (await c.session.list_tools()).tools}

    assert "description=" in text and "link=true" in text
    assert 'read(note, links="out"' in text
    for removed in ("surface(", "constraints(", "docs_status", "docs_write"):
        assert removed not in text
    assert not names & {"surface", "constraints", "links", "docs_status", "docs_write"}


@pytest.mark.parametrize(
    ("name", "replacement"),
    [("surface", 'context(mode="surface")'), ("docs_write", 'docs(action="write")')],
)
async def test_removed_tool_answers_not_found(vault: Path, name: str, replacement: str) -> None:
    async with mcp_client(vault) as c:
        message = await c.error(name, file="a.py")

    assert message == (
        f'not_found: tool "{name}" was removed. Use {replacement} instead, '
        "and re-run /episteme:setup to update hooks and permissions."
    )


async def test_removed_tool_in_hook_mode_adds_context_without_blocking(vault: Path) -> None:
    async with mcp_client(vault) as c:
        text = await c.ok("surface", hook_event="PostToolUse", file="a.py")

    out = json.loads(text)
    assert set(out) == {"hookSpecificOutput"}
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PostToolUse"
    assert 'context(mode="surface")' in specific["additionalContext"]
    assert "/episteme:setup" in specific["additionalContext"]


async def test_removed_tool_with_silent_event_says_nothing(vault: Path) -> None:
    async with mcp_client(vault) as c:
        assert await c.ok("links", hook_event="SessionEnd") == ""
