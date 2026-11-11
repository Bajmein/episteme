"""Activity log: unit tests of Activity and stdio integration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import mcp_client

from episteme.activity import Activity, extract_paths

pytestmark = pytest.mark.anyio


def rows(db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("select * from calls order by id").fetchall()
    finally:
        conn.close()


def test_creates_file_on_first_record(tmp_path: Path) -> None:
    act = Activity(tmp_path)
    try:
        assert not act.db_path.exists()
        act.record("search", {"query": "x", "session": "s1", "hook_event": "Stop"}, "abc", 3, True)
    finally:
        act.close()
    (row,) = rows(act.db_path)
    assert row["tool"] == "search"
    assert row["session"] == "s1"
    assert row["hook_event"] == "Stop"
    assert (row["chars"], row["ms"], row["ok"]) == (3, 3, 1)


def test_args_whitelist(tmp_path: Path) -> None:
    act = Activity(tmp_path)
    try:
        act.record(
            "remember",
            {
                "title": "t" * 500,
                "body": "secret",
                "text": "s",
                "old": "o",
                "new": "n",
                "prompt": "p",
                "fields": {"a": 1},
                "limit": 5,
            },
            "",
            1,
            True,
        )
    finally:
        act.close()
    args = json.loads(rows(act.db_path)[0]["args"])
    assert args == {"title": "t" * 200, "limit": 5}


def test_extract_paths_json_and_text() -> None:
    data = {"hits": [{"path": "a.md"}, {"x": {"path": "b.md"}}], "paths": ["c.md", "a.md"]}
    assert set(extract_paths(json.dumps(data))) == {"a.md", "b.md", "c.md"}
    assert len(extract_paths(json.dumps(data))) == 3
    assert extract_paths("- Title (memory/x.md) and (docs/y.md) (not a path)") == [
        "memory/x.md",
        "docs/y.md",
    ]
    assert len(extract_paths(" ".join(f"(n{i}.md)" for i in range(50)))) == 30


def test_never_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    act = Activity(blocker)  # .index cannot be created under a file
    try:
        act.record("search", {}, "x", 1, True)
        act.record("search", None, None, 1, True)  # type: ignore[arg-type]
    finally:
        act.close()


def test_disabled_by_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPISTEME_ACTIVITY", "0")
    act = Activity(tmp_path)
    try:
        act.record("search", {}, "x", 1, True)
    finally:
        act.close()
    assert not act.db_path.exists()


async def test_integration_logs_calls(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("search", query="settings")
        res = await c.ok("read", note="settings-reference")
        await c.ok("remember", type="lesson", title="Nota de actividad", body="x" * 50)
        assert (await c.call("read", note="no-such-note-zzz"))[0]
    got = rows(vault / ".index" / "activity.db")
    assert [r["tool"] for r in got] == ["search", "read", "remember", "read"]
    assert [r["ok"] for r in got] == [1, 1, 1, 0]
    assert res["path"] in json.loads(got[1]["paths"])
    assert "x" * 50 not in got[2]["args"]
