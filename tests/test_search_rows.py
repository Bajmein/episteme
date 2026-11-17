"""search: richer rows, zone filter, project with _shared, hints, facets and partial matches."""

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio


async def test_memory_and_doc_rows(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", query="serena", limit=1)
        row = res["results"][0]
        assert row["path"] == "memory/fabrik/decisions/2026-10-02-serena-ty.md"
        assert {"zone", "type", "status", "project", "created", "priority"} <= set(row)
        assert row["zone"] == "memory" and row["project"] == "fabrik"
        assert "superseded_by" not in row

        res = await c.ok("search", query="context window", zone="docs/claude-code")
        doc = next(r for r in res["results"] if r["path"].endswith("context-window.md"))
        assert doc["zone"] == "docs/claude-code"
        assert "project" not in doc and "priority" not in doc
        assert {"type", "status", "created"} <= set(doc)


async def test_heading_of_the_match(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", query="best practices", zone="docs/claude-code")
        row = next(r for r in res["results"] if r["path"].endswith("README.index.md"))
        assert row["heading"] == "🗺️ Mapa Rápido por Objetivos"
        # the first match of a memory sits under its H1: no heading
        mem = await c.ok("search", query="serena", limit=1)
        assert "heading" not in mem["results"][0]


async def test_superseded_rows_carry_successor(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        old = await c.ok(
            "remember", type="lesson", title="Quasar cache is stale", body="quasarcache stale"
        )
        new = await c.ok(
            "remember",
            type="lesson",
            title="Quasar cache is fresh",
            body="quasarcache fresh",
            supersedes=old["path"],
            force=True,
        )
        res = await c.ok("search", query="quasarcache", status="any")
        rows = {r["path"]: r for r in res["results"]}
        assert rows[old["path"]]["status"] == "superseded"
        assert rows[old["path"]]["superseded_by"] == new["path"]
        assert "superseded_by" not in rows[new["path"]]
        default = await c.ok("search", query="quasarcache")
        assert [r["path"] for r in default["results"]] == [new["path"]]


async def test_zone_filter(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", zone="memory")
        assert res["total"] > 0
        assert {r["zone"] for r in res["results"]} == {"memory"}
        err = await c.error("search", query="serena", zone="nope")
        assert err.startswith("invalid_argument") and "docs/claude-code" in err
        err = await c.error("search")
        assert "tags, type, project or zone" in err


async def test_project_includes_shared(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        made = await c.ok(
            "remember",
            type="preference",
            title="Zorgblat shared habit",
            body="zorgblat everywhere",
            project="_shared",
        )
        res = await c.ok("search", query="zorgblat", project="fabrik")
        assert [r["path"] for r in res["results"]] == [made["path"]]
        res = await c.ok("search", query="zorgblat", project="_shared")
        assert res["total"] == 1


async def test_hints(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", type="decison")
        assert res["total"] == 0
        assert 'no note has type "decison". Types in the vault:' in res["hints"][0]
        assert "decision" in res["hints"][0]

        res = await c.ok("search", query="serena", project="fabrk")
        assert 'no note has project "fabrk". Projects in the vault: ' in res["hints"][0]
        assert "fabrik" in res["hints"][0]

        res = await c.ok("search", query="serena", status="activo")
        assert 'no note has status "activo"' in res["hints"][0]
        assert '"any" includes superseded and archived.' in res["hints"][0]

        res = await c.ok("search", query="serena", tags=["pieza/serenaa"])
        assert 'no note has tag "pieza/serenaa". Similar tags: pieza/serena,' in res["hints"][0]
        res = await c.ok("search", query="serena", tags=["qqqqqqqq"])
        assert res["hints"] == ['no note has tag "qqqqqqqq".']

        res = await c.ok("search", query="serena", path="memoria")
        assert res["hints"] == [
            'no note under "memoria". Zones: docs/claude-code, memory, plans, sesiones.'
        ]

        res = await c.ok("search", query="zzzxxyy")
        assert res["hints"][0].startswith("Nothing matches. search is literal")
        res = await c.ok("search", query="serena")
        assert "hints" not in res


async def test_facets(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", facets=True)
        assert res["results"] == []
        assert res["total"] == 50
        assert res["facets"]["zone"] == {"docs/claude-code": 45, "memory": 5}
        assert res["facets"]["project"] == {"fabrik": 4, "_shared": 1}
        assert len(res["facets"]["tags"]) <= 30
        assert res["facets"]["tags"]["claude-code"] == 44

        res = await c.ok("search", zone="memory", facets=True)
        assert res["total"] == 5
        assert res["facets"]["zone"] == {"memory": 5}
        assert "reference" not in res["facets"]["type"]
        assert res["facets"]["tags"]["persona"] == 1

        res = await c.ok("search", query="serena", facets=True)
        assert res["facets"]["project"] == {"fabrik": 2}


async def test_partial_matches(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", query="serena pyright")
        assert res["total"] == 1
        hit = res["results"][0]["path"]
        assert 1 <= len(res["partial"]) <= 5
        assert hit not in [r["path"] for r in res["partial"]]
        assert res["note"].startswith("Few notes have all the words")
        assert "match" not in res

        res = await c.ok("search", query="serena")
        assert "partial" not in res


async def test_match_any(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", query="serena pyright", match="any")
        assert res["total"] == 2
        assert "partial" not in res and "match" not in res and "note" not in res
        for row in res["results"]:
            assert row["matched"] and set(row["matched"]) <= {"serena", "pyright"}
        first = res["results"][0]
        assert first["path"] == "memory/fabrik/decisions/2026-10-02-serena-ty.md"
        assert first["matched"] == ["serena", "pyright"]

        res = await c.ok("search", query="serena pyright", match="any", facets=True)
        assert sum(res["facets"]["zone"].values()) == res["total"] == 2

        res = await c.ok("search", query="serena", match="all")
        assert all("matched" not in r for r in res["results"])
        res = await c.ok("search", zone="memory", match="any")
        assert res["total"] == 5 and all("matched" not in r for r in res["results"])

        err = await c.error("search", query="serena", match="bogus")
        assert err.startswith("invalid_argument: match must be")


async def test_matched_in_fallback_and_partial_rows(vault):
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("search", query="serena PreToolUse")
        assert res["match"] == "or"
        for row in res["results"]:
            assert row["matched"] and set(row["matched"]) <= {"serena", "pretooluse"}

        res = await c.ok("search", query="serena pyright")
        assert all("matched" not in r for r in res["results"])
        for row in res["partial"]:
            assert row["matched"] and set(row["matched"]) <= {"serena", "pyright"}
