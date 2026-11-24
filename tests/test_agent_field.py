"""The ``agent`` front matter field: set by the server from the MCP client name."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Implementation

from episteme import memory
from episteme.engine import Engine

_BODY = "Use uv for every dependency change in this project, never pip install."
_REMEMBER = {"type": "lesson", "title": "Agent field", "body": _BODY}


async def _call(vault: Path, name: str, args: dict[str, object], client: str) -> str:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "episteme", "--vault", str(vault), "--project", "fabrik"],
        env={**os.environ, "EPISTEME_TODAY": "2026-04-10"},
    )
    with open(os.devnull, "w") as errlog:
        async with (
            stdio_client(params, errlog=errlog) as (read, write),
            ClientSession(read, write, client_info=Implementation(name=client, version="1")) as s,
        ):
            await s.initialize()
            result = await s.call_tool(name, args)
    return "".join(getattr(c, "text", "") for c in result.content)


@pytest.mark.anyio
async def test_remember_writes_the_client_name_as_agent(vault: Path) -> None:
    out = await _call(vault, "remember", _REMEMBER, "agent-test")

    text = (vault / json.loads(out)["path"]).read_text(encoding="utf-8")
    head = text.split("---")[1].splitlines()
    keys = [ln.split(":")[0] for ln in head if ln and ln[0].isalpha()]

    assert "agent: agent-test" in head
    assert keys.index("agent") < keys.index("helpful")


@pytest.mark.anyio
async def test_revise_set_rejects_agent(vault: Path) -> None:
    out = await _call(vault, "remember", _REMEMBER, "agent-test")

    err = await _call(
        vault,
        "revise",
        {"note": json.loads(out)["path"], "action": "set", "fields": {"agent": "x"}},
        "agent-test",
    )

    assert "agent is set by the server" in err


def test_direct_remember_without_agent_omits_the_field(vault: Path) -> None:
    engine = Engine(vault, "fabrik")

    with engine.session():
        res = memory.remember(engine, "lesson", "No agent here", _BODY)

    assert "agent:" not in (vault / res["path"]).read_text(encoding="utf-8")


def test_remember_trims_agent_to_64_characters(vault: Path) -> None:
    engine = Engine(vault, "fabrik")

    with engine.session():
        res = memory.remember(engine, "lesson", "Long agent", _BODY, agent="a" * 100)

    assert f"agent: {'a' * 64}\n" in (vault / res["path"]).read_text(encoding="utf-8")


def test_remember_collapses_whitespace_in_agent(vault: Path) -> None:
    engine = Engine(vault, "fabrik")

    with engine.session():
        res = memory.remember(engine, "lesson", "Odd agent", _BODY, agent="foo\nbar")

    assert "agent: foo bar\n" in (vault / res["path"]).read_text(encoding="utf-8")
