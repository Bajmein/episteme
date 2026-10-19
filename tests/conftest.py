"""Shared fixtures: a writable copy of the test vault and an MCP stdio client."""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = "2026-10-19"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A copy of tests/fixtures/vault; the fixture itself is never written."""
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURES / "vault", dst)
    return dst


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    dst = tmp_path / "project"
    shutil.copytree(FIXTURES / "project", dst)
    return dst


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Client:
    """Thin wrapper over ClientSession that decodes tool results."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def call(self, name: str, **arguments: Any) -> tuple[bool, str]:
        result = await self.session.call_tool(name, arguments)
        text = "".join(getattr(block, "text", "") for block in result.content)
        return bool(result.is_error), text

    async def ok(self, name: str, **arguments: Any) -> Any:
        is_error, text = await self.call(name, **arguments)
        assert not is_error, text
        return json.loads(text) if text and "hook_event" not in arguments else text

    async def error(self, name: str, **arguments: Any) -> str:
        is_error, text = await self.call(name, **arguments)
        assert is_error, text
        return text


@asynccontextmanager
async def mcp_client(
    vault: Path, project: str | None = "fabrik", today: str = TODAY
) -> AsyncIterator[Client]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    args = ["-m", "episteme_mcp", "--vault", str(vault)]
    if project:
        args += ["--project", project]
    params = StdioServerParameters(
        command=sys.executable,
        args=args,
        env={"EPISTEME_TODAY": today, "PYTHONPATH": os.environ.get("PYTHONPATH", "")},
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield Client(session)
