"""read(notes=[...]): several notes in one call, per-note errors and the output cap."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

A = "memory/fabrik/decisions/2026-10-02-serena-ty.md"
B = "docs/claude-code/context-window.md"


def _big(vault: Path, count: int, size: int = 19_000) -> list[str]:
    (vault / "plans").mkdir(exist_ok=True)
    paths = []
    for n in range(count):
        rel = f"plans/big-{n}.md"
        line = f"palabra{n} " * 9 + "\n"
        body = f"# Big {n}\n\n" + line * (size // len(line))
        (vault / rel).write_text(body, encoding="utf-8", newline="")
        paths.append(rel)
    return paths


async def test_reads_several_notes(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("read", notes=[A, B])
        assert [n["path"] for n in res["notes"]] == [A, B]
        assert "pending" not in res and "note" not in res
        for item in res["notes"]:
            assert item["content"] and "outline" not in item
            assert {"frontmatter", "fm_valid", "truncated", "total_lines"} <= set(item)

        res = await c.ok("read", notes=[A, B], outline=True)
        assert all(item["outline"] for item in res["notes"])

        res = await c.ok("read", notes=[A, B], content=False)
        assert all(item["content"] == "" and item["outline"] for item in res["notes"])


async def test_a_note_that_fails_is_reported(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("read", notes=[A, "no-such-note-zzz", B])
        assert [n.get("path") for n in res["notes"]] == [A, None, B]
        bad = res["notes"][1]
        assert set(bad) == {"note", "error"} and bad["note"] == "no-such-note-zzz"
        assert bad["error"].startswith("not_found:")


async def test_same_note_twice_comes_once(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("read", notes=[A, "2026-10-02-serena-ty", A])
        assert [n["path"] for n in res["notes"]] == [A]


async def test_invalid_arguments(vault: Path) -> None:
    async with mcp_client(vault) as c:
        for kwargs in (
            {"note": A, "notes": [B]},
            {},
            {"notes": []},
            {"notes": [A] * 21},
            {"notes": [A], "heading": "Decisión"},
            {"notes": [A], "lines": "1-3"},
            {"notes": [A], "content": False, "outline": False},
        ):
            err = await c.error("read", **kwargs)
            assert err.startswith("invalid_argument:"), (kwargs, err)


async def test_output_cap_leaves_the_rest_pending(vault: Path) -> None:
    big = _big(vault, 3)
    async with mcp_client(vault) as c:
        res = await c.ok("read", notes=[*big, A])
        assert [n["path"] for n in res["notes"]] == big[:2]
        assert res["pending"] == [big[2], A]
        assert res["note"].startswith("Output limit reached")
        assert len(json.dumps(res, ensure_ascii=False)) < 60_000

        res = await c.ok("read", notes=res["pending"])
        assert [n["path"] for n in res["notes"]] == [big[2], A]
        assert "pending" not in res


async def test_activity_logs_notes_and_match(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok("read", notes=[A, B])
        await c.ok("search", query="serena pyright", match="any")
    conn = sqlite3.connect(vault / ".index" / "activity.db")
    conn.row_factory = sqlite3.Row
    try:
        got = conn.execute("select * from calls order by id").fetchall()
    finally:
        conn.close()
    assert [r["tool"] for r in got] == ["read", "search"]
    assert json.loads(got[0]["args"])["notes"] == [A, B]
    assert json.loads(got[0]["paths"])[:2] == [A, B]
    assert json.loads(got[1]["args"])["match"] == "any"
