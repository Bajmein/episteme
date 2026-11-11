"""read: outline on demand, outline-only mode and range."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

NOTE = "docs/outline-note.md"
BODY = "\n".join(
    [
        "---",
        "title: Outline note",
        "---",
        "# Top",
        "intro",
        "## A",
        "a text",
        "### A1",
        "a1 text",
        "## B",
        "b text",
        "",
    ]
)


@pytest.fixture
def note_vault(vault: Path) -> Path:
    (vault / NOTE).write_text(BODY, encoding="utf-8", newline="")
    return vault


async def test_whole_note_outline_has_end(note_vault: Path) -> None:
    async with mcp_client(note_vault) as c:
        res = await c.ok("read", note=NOTE)
        ends = {o["text"]: (o["line"], o["end"]) for o in res["outline"]}
        assert ends["Top"] == (4, 11)
        assert ends["A"] == (6, 9)
        assert ends["A1"] == (8, 9)
        assert ends["B"] == (10, 11)
        assert "range" not in res


async def test_lines_and_heading_omit_outline_and_give_range(note_vault: Path) -> None:
    async with mcp_client(note_vault) as c:
        res = await c.ok("read", note=NOTE, lines="5-6")
        assert "outline" not in res
        assert res["range"] == "5-6"
        res = await c.ok("read", note=NOTE, heading="A")
        assert "outline" not in res
        assert res["range"] == "6-9"
        assert res["content"].startswith("## A")


async def test_outline_true_forces_outline(note_vault: Path) -> None:
    async with mcp_client(note_vault) as c:
        res = await c.ok("read", note=NOTE, lines="5-6", outline=True)
        assert len(res["outline"]) == 4
        res = await c.ok("read", note=NOTE, outline=False)
        assert "outline" not in res
        assert "intro" in res["content"]


async def test_content_false_returns_only_outline(note_vault: Path) -> None:
    async with mcp_client(note_vault) as c:
        res = await c.ok("read", note=NOTE, content=False)
        assert res["content"] == ""
        assert res["truncated"] is False
        assert res["frontmatter"]["title"] == "Outline note"
        assert len(res["outline"]) == 4


@pytest.mark.parametrize(
    "args",
    [{"heading": "A"}, {"lines": "1-2"}, {"outline": False}],
)
async def test_content_false_conflicts(note_vault: Path, args: dict) -> None:
    async with mcp_client(note_vault) as c:
        err = await c.error("read", note=NOTE, content=False, **args)
        assert err.startswith("invalid_argument:")
        assert "content=false returns only the outline" in err
