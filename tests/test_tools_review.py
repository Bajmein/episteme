"""review and context(mode="task") through MCP (cases 14 and 18 plus overdue reminders)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

README = "docs/claude-code/README.index.md"


async def test_tool_list_is_complete(vault: Path) -> None:
    from test_tools_read import TOOLS

    async with mcp_client(vault) as c:
        tools = {t.name: t for t in (await c.session.list_tools()).tools}
        assert set(tools) == TOOLS
        read_only = {n for n, t in tools.items() if t.annotations and t.annotations.read_only_hint}
        assert read_only == {
            "search", "read", "links", "review", "context", "surface", "constraints"
        }  # fmt: skip
        assert all(t.description for t in tools.values())
        info = c.session.initialize_result
        assert info.instructions.startswith("episteme is the project memory")


async def test_case14_review_reports_invalid_frontmatter(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("review")
        bad = {x["path"]: x["error"] for x in res["invalid_frontmatter"]}
        assert README in bad and "mapping values" in bad[README]
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
        assert [s["path"] for s in res["stale"]] == [
            "memory/fabrik/insights/2026-01-01-vieja.md"
        ]
        assert res["stale"][0]["days"] == 291
        pair = res["contradictions"][0]
        assert {pair["a"], pair["b"]} == {
            "memory/fabrik/decisions/2026-10-02-serena-ty.md",
            "memory/fabrik/decisions/2026-10-19-serena-sin-lsp-para-markdown.md",
        }
        assert ".serena/project.yml" in pair["reason"]
        assert "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md" in res["orphans"]
        assert "memory/fabrik/decisions/2026-10-02-serena-ty.md" not in res["orphans"]
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
        hook = await c.call(
            "context", mode="task", task="serena", hook_event="UserPromptSubmit"
        )
        assert hook[0] is False and hook[1].startswith("episteme · contexto para: serena")


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
