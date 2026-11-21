"""review and context(mode="task") through MCP (cases 14 and 18 plus overdue reminders)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

README = "docs/claude-code/README.index.md"


async def test_tool_list_is_complete(vault: Path) -> None:
    from test_tools_read import DOCS_TOOLS, TOOLS

    async with mcp_client(vault) as c:
        tools = {t.name: t for t in (await c.session.list_tools()).tools}
        assert set(tools) == TOOLS - DOCS_TOOLS
        read_only = {n for n, t in tools.items() if t.annotations and t.annotations.read_only_hint}
        assert read_only == {"search", "read", "links", "review", "surface", "constraints"}
        assert all(t.description for t in tools.values())
        info = c.session.initialize_result
        assert info.instructions.startswith("episteme is the project memory")
        assert "episteme-docs" not in info.instructions


async def test_docs_zone_adds_docs_tools_and_instructions(vault: Path) -> None:
    from test_tools_read import TOOLS

    with (vault / "episteme.toml").open("a", encoding="utf-8") as fh:
        fh.write('\n[zones."docs/mise"]\nmode = "docs"\n')
    async with mcp_client(vault) as c:
        tools = {t.name: t for t in (await c.session.list_tools()).tools}
        assert set(tools) == TOOLS
        assert tools["docs_status"].annotations.read_only_hint is True
        text = c.session.initialize_result.instructions
        assert "/episteme-docs:docs" in text
        assert len(text) <= 2000


async def test_case14_review_reports_invalid_frontmatter(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("review")
        bad = {x["path"]: x["error"] for x in res["read_only"]["invalid_frontmatter"]}
        assert README in bad and "mapping values" in bad[README]
        assert res["read_only"]["totals"]["invalid_frontmatter"] == len(bad)
        assert README not in {x["path"] for x in res["invalid_frontmatter"]}
        assert res["broken_links"] == []
        hits = await c.ok("search", query="Mapa Rápido por Objetivos")
        assert hits["results"][0]["path"] == README


async def test_review_categories(vault: Path) -> None:
    (vault / "plans").mkdir()
    (vault / "plans/p.md").write_text("# P\n\n[[nowhere]] and [[hooks-reference#No such]]\n")
    old = vault / "memory/fabrik/insights/2026-01-01-vieja.md"
    old.parent.mkdir(parents=True)
    old.write_text(
        "---\ntype: insight\nproject: fabrik\npriority: 3\nstatus: active\n"
        "created: 2026-01-01\nhelpful: 0\n---\n# Vieja\n\ntexto\n"
    )
    bad = vault / "memory/fabrik/insights/2026-10-01-mala.md"
    bad.write_text(
        "---\ntype: insight\nproject: fabrik\npriority: 7\nstatus: active\n"
        "created: 2026-10-01\n---\n# Mala\n\n[[perfil]]\n"
    )
    async with mcp_client(vault) as c:
        await c.ok(
            "remember",
            type="decision",
            title="Serena sin LSP para Markdown",
            body="Serena no arranca LSP para Markdown en `.serena/project.yml`.",
            files=[".serena/project.yml"],
        )
        await c.ok(
            "revise",
            note="2026-10-14-omega-rss-limit",
            action="feedback",
            value="outdated",
        )
        res = await c.ok("review", project="fabrik")
        assert [s["path"] for s in res["stale"]] == ["memory/fabrik/insights/2026-01-01-vieja.md"]
        assert res["stale"][0]["days"] == 291
        pair = res["contradictions"][0]
        assert {pair["a"], pair["b"]} == {
            "memory/fabrik/decisions/2026-10-02-serena-ty.md",
            "memory/fabrik/decisions/2026-10-19-serena-lsp-markdown.md",
        }
        assert ".serena/project.yml" in pair["reason"]
        orphans = [o["path"] for o in res["orphans"]]
        assert "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md" in orphans
        assert "memory/fabrik/decisions/2026-10-02-serena-ty.md" not in orphans
        assert {(b["path"], b["target"]) for b in res["broken_links"]} == {
            ("plans/p.md", "nowhere"),
            ("plans/p.md", "hooks-reference#No such"),
        }
        errors = {x["path"]: x["error"] for x in res["invalid_frontmatter"]}
        assert "priority" in errors["memory/fabrik/insights/2026-10-01-mala.md"]
        assert res["flagged"] == ["memory/fabrik/lessons/2026-10-14-omega-rss-limit.md"]
        scoped = await c.ok("review", path="plans")
        assert scoped["orphans"] == [] and len(scoped["broken_links"]) == 2
        assert (await c.error("review", path="../x")).startswith("outside_vault:")
        # related between two decisions says they were compared: not a contradiction.
        new = await c.ok(
            "remember",
            type="decision",
            title="Serena con pyright desactivado",
            body="En `.serena/project.yml` no se activa pyright.",
            files=[".serena/project.yml"],
            related=["2026-10-02-serena-ty"],
        )
        pairs = [{p["a"], p["b"]} for p in (await c.ok("review"))["contradictions"]]
        assert {new["path"], "memory/fabrik/decisions/2026-10-02-serena-ty.md"} not in pairs
        assert {new["path"], "memory/fabrik/decisions/2026-10-19-serena-lsp-markdown.md"} in pairs


def _orphan(vault: Path, slug: str, tags: str = "[]", status: str = "active") -> str:
    rel = f"memory/orph/insights/{slug}.md"
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: insight\nproject: orph\npriority: 3\nstatus: {status}\n"
        f"created: 2026-10-10\ntags: {tags}\n---\n# {slug}\n\ntexto {slug}\n",
        encoding="utf-8",
        newline="",
    )
    return rel


async def test_review_orphans_carry_candidates_linkable_first(vault: Path) -> None:
    lone = _orphan(vault, "lone")
    a = _orphan(vault, "alpha", "[tema/x, tema/y]")
    b = _orphan(vault, "beta", "[tema/x, tema/y, tema/z]")
    gone = _orphan(vault, "gone", "[tema/x, tema/y]", status="archived")

    async with mcp_client(vault) as c:
        res = await c.ok("review", project="orph")

    by_path = {o["path"]: o for o in res["orphans"]}
    assert gone not in by_path
    assert by_path[a]["candidates"] == [
        {"path": b, "title": "beta", "reason": "shares tags tema/x, tema/y"}
    ]
    assert [x["path"] for x in by_path[b]["candidates"]] == [a]
    assert by_path[lone]["candidates"] == []
    order = [o["path"] for o in res["orphans"]]
    assert order.index(a) < order.index(lone) and order.index(b) < order.index(lone)


async def test_flagged_clears_with_set_null(vault: Path) -> None:
    note = "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md"
    async with mcp_client(vault) as c:
        await c.ok("revise", note=note, action="feedback", value="outdated")
        assert note in (await c.ok("review", project="fabrik"))["flagged"]

        await c.ok("revise", note=note, action="set", fields={"flagged": None})

        assert note not in (await c.ok("review", project="fabrik"))["flagged"]


async def test_task_context(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("context", mode="task", task="cambiar serena_guard y el hook de cd")
        kinds = [e["kind"] for e in res["entries"]]
        assert res["entries"][0]["path"] == (
            "memory/fabrik/constraints/2026-10-10-serena-guard-cd.md"
        )
        assert "note" in kinds and kinds.index("note") > kinds.index("memory")
        assert "Notas relacionadas:" in res["text"]
        assert "serena-pyright" not in res["text"]
        small = await c.ok("context", mode="task", task="serena", budget_tokens=60)
        assert len(small["text"]) <= 240
        text = await c.error("context", mode="task")
        assert text.startswith("invalid_argument:")
        hook = await c.call("context", mode="task", task="serena", hook_event="UserPromptSubmit")
        assert hook[0] is False
        out = json.loads(hook[1])["hookSpecificOutput"]
        assert out["hookEventName"] == "UserPromptSubmit"
        assert out["additionalContext"].startswith("episteme · contexto para: serena")


async def test_overdue_reminders_order(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-25") as c:
        await c.ok("remember", type="reminder", title="Antes", body="Algo.", due="2026-10-20")
        await c.ok("remember", type="reminder", title="Futuro", body="Otro.", due="2026-12-01")
        res = await c.ok("context")
        reminders = [e["path"] for e in res["entries"] if e["kind"] == "reminder"]
        assert reminders == [
            "memory/fabrik/reminders/2026-10-25-antes.md",
            "memory/fabrik/reminders/2026-10-18-revisar-trigger-queries.md",
        ]
        assert "Futuro" not in res["text"]


async def test_review_totals_and_zone_filter(vault: Path) -> None:
    (vault / "plans").mkdir(exist_ok=True)
    for i in range(3):
        (vault / f"plans/p{i}.md").write_text(f"# P{i}\n\n[[missing-{i}]]\n")
    async with mcp_client(vault) as c:
        res = await c.ok("review", limit=2)
        assert len(res["broken_links"]) == 2
        assert res["totals"]["broken_links"] == 3
        assert res["read_only"]["totals"]["invalid_frontmatter"] >= 1
        # Same categories as the project's own, so nothing found in a read-only zone is lost.
        assert set(res["read_only"]["totals"]) == set(res["totals"])
        assert set(res["read_only"]) == {"totals", *res["totals"]}
        plans = await c.ok("review", zone="plans")
        assert plans["totals"]["broken_links"] == 3
        assert plans["read_only"]["totals"]["invalid_frontmatter"] == 0
        docs = await c.ok("review", zone="docs/claude-code")
        assert docs["totals"]["broken_links"] == 0
        assert docs["read_only"]["invalid_frontmatter"]
        assert (await c.error("review", zone="nope")).startswith("invalid_argument:")


async def test_same_folder_preferred_for_repeated_names(vault: Path) -> None:
    (vault / "plans/a").mkdir(parents=True)
    (vault / "plans/b").mkdir()
    (vault / "plans/a/dup.md").write_text("# Dup A\n")
    (vault / "plans/b/dup.md").write_text("# Dup B\n")
    (vault / "plans/a/src.md").write_text("# Src\n\n[[dup]]\n")
    (vault / "plans/other.md").write_text("# Other\n\n[[dup]]\n")
    async with mcp_client(vault) as c:
        res = await c.ok("review", zone="plans")
        assert {(b["path"], b["target"]) for b in res["broken_links"]} == {
            ("plans/other.md", "dup")
        }
