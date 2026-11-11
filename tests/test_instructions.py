"""Server instructions: triggers for reading and saving, within the MCP size limit."""

from __future__ import annotations

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
