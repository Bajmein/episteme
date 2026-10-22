"""search, read and links through a real MCP stdio client (cases 1, 2, 4, 5, 6, 17)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

TOOLS = {
    "search",
    "read",
    "links",
    "remember",
    "revise",
    "review",
    "context",
    "surface",
    "constraints",
    "checkpoint",
}


async def test_read_tools_are_annotated(vault: Path) -> None:
    async with mcp_client(vault) as c:
        tools = {t.name: t for t in (await c.session.list_tools()).tools}
        for name in ("search", "read", "links"):
            assert tools[name].annotations.read_only_hint is True
            assert tools[name].description


async def test_case1_search_and_read_heading(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("search", query="PreToolUse", path="docs/claude-code")
        paths = [r["path"] for r in res["results"]]
        assert "docs/claude-code/hooks-reference.md" in paths[:3]
        hit = res["results"][paths.index("docs/claude-code/hooks-reference.md")]
        assert hit["line"] > 1 and "**PreToolUse**" in hit["snippet"]
        assert res["total"] >= len(paths)
        section = await c.ok("read", note=hit["path"], heading="PreToolUse")
        assert section["content"].startswith("### PreToolUse")
        assert "### PermissionRequest" not in section["content"]
        assert "#### PreToolUse input" in section["content"]
        assert section["truncated"] is False


async def test_case2_ambiguous_name(vault: Path) -> None:
    async with mcp_client(vault) as c:
        text = await c.error("read", note="best-practices")
        assert text.startswith("ambiguous:")
        assert "docs/claude-code/best-practices.md" in text
        assert "docs/claude-code/agent-skill-open-standard-doc-reference/best-practices.md" in text


async def test_case4_paths_leaving_the_vault(vault: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("# secret\n")
    os.symlink(outside, vault / "escape")
    async with mcp_client(vault) as c:
        for bad in ("../outside/secret", "/etc/passwd", "escape/secret.md", "escape/secret"):
            for tool, args in (
                ("read", {"note": bad}),
                ("links", {"note": bad}),
                ("search", {"query": "secret", "path": bad}),
            ):
                text = await c.error(tool, **args)
                assert text.startswith("outside_vault:"), (tool, bad, text)


async def test_case5_search_without_accents(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("search", query="configuracion")
        assert res["total"] > 0
        assert any("onfiguración" in r["snippet"] for r in res["results"])


async def test_case6_backlinks(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("links", note="hooks-reference")
        assert res["path"] == "docs/claude-code/hooks-reference.md"
        assert "docs/claude-code/README.index.md" in {b["path"] for b in res["backlinks"]}
        kinds = {o["kind"] for o in res["outgoing"]}
        assert {"body", "up", "related"} <= kinds
        deep = await c.ok("links", note="hooks-reference", direction="out", depth=2)
        assert deep["backlinks"] == []
        assert {"path": "docs/claude-code/README.index.md", "distance": 1} in deep["reachable"]


async def test_case17_read_truncates_large_notes(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("read", note="settings-reference")
        assert res["truncated"] is True
        assert len(res["content"]) <= 20_000
        assert "more lines" in res["content"].splitlines()[-1]
        assert res["total_lines"] > 1000
        part = await c.ok("read", note="settings-reference", lines="10-12")
        assert part["content"].count("\n") == 2


async def test_read_errors(vault: Path) -> None:
    async with mcp_client(vault) as c:
        assert (await c.error("read", note="nope-nothing")).startswith("not_found:")
        text = await c.error("read", note="hooks-reference", heading="No such heading")
        assert text.startswith("not_found:") and "PreToolUse" in text
        text = await c.error("read", note="hooks-reference", heading="x", lines="1-2")
        assert text.startswith("invalid_argument:")
        assert (await c.error("search", query="x", limit=500)).startswith("invalid_argument:")
        text = await c.error("search", query="x", limit="many")
        assert text.startswith("invalid_argument:")
        assert (await c.error("links", note="hooks-reference", depth=9)).startswith(
            "invalid_argument:"
        )


async def test_search_filters_and_superseded(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("search", query="serena")
        paths = {r["path"] for r in res["results"]}
        assert "memory/fabrik/decisions/2026-10-02-serena-ty.md" in paths
        assert "memory/fabrik/decisions/2026-09-12-serena-pyright.md" not in paths
        res = await c.ok("search", query="serena", status="superseded")
        assert [r["path"] for r in res["results"]] == [
            "memory/fabrik/decisions/2026-09-12-serena-pyright.md"
        ]
        res = await c.ok("search", query="serena", status="any", type="decision")
        assert res["total"] == 2
        res = await c.ok("search", query="serena", tags=["pieza"], project="fabrik", limit=1)
        assert res["total"] >= 2 and len(res["results"]) == 1


async def test_search_without_query_by_tags_or_type(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("search", tags=["pieza"], project="fabrik")
        assert res["total"] >= 2 and "match" not in res
        res = await c.ok("search", type="decision", project="fabrik")
        assert res["total"] >= 1
        assert (await c.ok("search", tags=["pieza:serena"]))["total"] == (
            await c.ok("search", tags=["pieza/serena"])
        )["total"]
        err = await c.error("search")
        assert err.startswith("invalid_argument:")


async def test_search_or_fallback_and_prefix(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("search", query="zzzinexistente qqqnada")
        assert res["total"] == 0 and "match" not in res
        res = await c.ok("search", query="serena PreToolUse")
        assert res["results"] and res["match"] == "or" and "OR" in res["note"]
        res = await c.ok("search", query="pretool*")
        assert any("hooks-reference" in r["path"] for r in res["results"])
        assert (await c.ok("search", query="pretool"))["total"] == 0
