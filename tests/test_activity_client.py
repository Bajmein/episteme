"""Activity log: the ``client`` column, the v1 -> v2 migration and the agy session in ``_meta``."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from episteme.activity import SCHEMA_VERSION, Activity
from episteme.server import caller_identity

pytestmark = pytest.mark.anyio

_V1 = """
create table calls (
    id integer primary key,
    at text, pid integer, session text, tool text, hook_event text, project text,
    args text, paths text, chars integer, ms integer, ok integer
);
"""


def _rows(db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("select * from calls order by id").fetchall()
    finally:
        conn.close()


def test_v1_db_keeps_rows_and_gains_client(tmp_path: Path) -> None:
    db = tmp_path / ".index" / "activity.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.executescript(_V1)
    conn.execute(
        "insert into calls (at, tool, ok) values (?, ?, ?)", ("2999-01-01T00:00", "read", 1)
    )
    conn.execute("pragma user_version = 1")
    conn.commit()
    conn.close()

    act = Activity(tmp_path)
    try:
        act.record("search", {}, "", 1, True, client="agy")
    finally:
        act.close()
    old, new = _rows(db)
    assert (old["tool"], old["client"]) == ("read", None)
    assert (new["tool"], new["client"]) == ("search", "agy")
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("pragma user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_session_argument_wins_over_meta_session(tmp_path: Path) -> None:
    act = Activity(tmp_path)
    try:
        act.record("read", {"session": "s1"}, "", 1, True, session="agy-conv")
        act.record("read", {}, "", 1, True, session="agy-conv")
    finally:
        act.close()
    assert [r["session"] for r in _rows(act.db_path)] == ["s1", "agy-conv"]


def _context(client_params: object, meta: object) -> SimpleNamespace:
    request = SimpleNamespace(session=SimpleNamespace(client_params=client_params), meta=meta)
    return SimpleNamespace(request_context=request)


def test_caller_identity_from_meta_without_client_params() -> None:
    meta = {
        "io.modelcontextprotocol/clientInfo": {"name": "antigravity", "version": "1"},
        "antigravity.google/root_conversation_id": "conv-1",
    }
    assert caller_identity(_context(None, meta)) == ("antigravity", "conv-1")


def test_caller_identity_prefers_initialize_client_info() -> None:
    params = SimpleNamespace(client_info=SimpleNamespace(name="claude-code"))
    meta = {"io.modelcontextprotocol/clientInfo": {"name": "other"}}
    assert caller_identity(_context(params, meta)) == ("claude-code", None)


class _NoRequest:
    @property
    def request_context(self) -> None:
        raise ValueError("Context is not available outside of a request")


@pytest.mark.parametrize("context", [None, _NoRequest(), SimpleNamespace(request_context=None)])
def test_caller_identity_is_defensive(context: object) -> None:
    assert caller_identity(context) == (None, None)


async def test_stdio_records_client_and_meta_session(vault: Path) -> None:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.types import Implementation

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "episteme", "--vault", str(vault), "--project", "fabrik"],
        env={**os.environ, "EPISTEME_TODAY": "2026-04-10"},
    )
    with open(os.devnull, "w") as errlog:
        async with (
            stdio_client(params, errlog=errlog) as (read, write),
            ClientSession(read, write, client_info=Implementation(name="agy-test", version="0"))
            as s,
        ):
            await s.initialize()
            await s.call_tool(
                "search",
                {"query": "x"},
                meta={"antigravity.google/root_conversation_id": "conv-9"},
            )
    row = _rows(vault / ".index" / "activity.db")[-1]
    assert (row["tool"], row["client"], row["session"]) == ("search", "agy-test", "conv-9")
