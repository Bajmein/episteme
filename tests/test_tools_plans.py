"""The plan tool through MCP: copies in planes/, the ExitPlanMode hook, restore and rotation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml
from conftest import TODAY, mcp_client

from episteme.memory import REDACTED
from episteme.plans.store import CUT_MARK, PLAN_MAX

pytestmark = pytest.mark.anyio

PLAN = "# Plan azul\n\n## Pasos\n\n1. Escribir el tool.\n2. Correr los tests.\n"
PATH_A = "/home/u/.claude/plans/plan-azul.md"
PATH_B = "/home/u/.claude/plans/plan-rojo.md"
BODY = "## Objetivo\n\nProbar el enlace.\n\n## Siguiente paso\n\nCorrer los tests.\n"
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


def _worktree(tmp_path: Path, name: str = "repo") -> str:
    path = tmp_path / name
    path.mkdir(exist_ok=True)
    return str(path)


async def _hook_save(c, plan: str, plan_path: str, project_dir: str | None = None) -> str:
    extra = {"project_dir": project_dir} if project_dir else {}
    return await c.ok(
        "plan",
        action="save",
        plan=plan,
        plan_path=plan_path,
        session="sess-1",
        hook_event="PreToolUse",
        **extra,
    )


async def _clear(c, project_dir: str | None = None) -> str:
    extra = {"project_dir": project_dir} if project_dir else {}
    return await c.ok(
        "plan", action="restore", source="clear", hook_event="SessionStart", **extra
    )


def _context(text: str) -> str:
    return json.loads(text)["hookSpecificOutput"]["additionalContext"]


async def test_save_creates_the_copy_and_overwrites_it_by_slug(
    vault: Path, tmp_path: Path
) -> None:
    here = _worktree(tmp_path)
    async with mcp_client(vault) as c:
        first = await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_A, project_dir=here)
        second = await c.ok(
            "plan", action="save", plan=PLAN + "3. Abrir el PR.\n", plan_path=PATH_A
        )

    assert first["path"] == second["path"] == "planes/fabrik/plan-azul.md"
    assert first["created"] is True and second["created"] is False
    assert first["slug"] == "plan-azul" and first["title"] == "Plan azul"
    fm = _fm(vault / first["path"])
    assert fm["type"] == "plan" and fm["status"] == "active" and fm["tags"] == ["sesion/plan"]
    assert fm["project"] == "fabrik" and fm["slug"] == "plan-azul" and fm["title"] == "Plan azul"
    assert str(fm["saved_at"]).startswith(TODAY) and fm["source_path"] == PATH_A
    assert fm["worktree"] == Path(os.path.realpath(here)).as_posix()
    assert "Abrir el PR" in (vault / first["path"]).read_text(encoding="utf-8")


async def test_hook_save_answers_nothing_and_keeps_the_copy(vault: Path) -> None:
    async with mcp_client(vault) as c:
        out = await _hook_save(c, PLAN, PATH_A)

    assert out == ""
    fm = _fm(vault / "planes/fabrik/plan-azul.md")
    assert fm["session_id"] == "sess-1"


@pytest.mark.parametrize(
    "arguments",
    [
        {"plan": "", "plan_path": PATH_A},
        {"plan": PLAN, "plan_path": ""},
        {"plan": PLAN, "plan_path": PATH_A, "project_dir": "relative/dir"},
        {"plan": PLAN, "plan_path": PATH_A, "project": "../x"},
    ],
)
async def test_hook_save_answers_nothing_on_an_error(vault: Path, arguments: dict) -> None:
    async with mcp_client(vault) as c:
        out = await c.ok("plan", action="save", hook_event="PreToolUse", **arguments)
        agent = await c.error("plan", action="save", **arguments)

    assert out == ""
    assert agent.startswith("invalid_argument:"), agent
    assert not (vault / "planes").exists() or not list((vault / "planes").rglob("*.md"))


@pytest.mark.parametrize(
    "arguments",
    [
        {"plan": "${tool_input.plan}", "plan_path": PATH_A},
        {"plan": PLAN, "plan_path": "${tool_input.planFilePath}"},
    ],
)
async def test_an_unsubstituted_placeholder_saves_nothing(vault: Path, arguments: dict) -> None:
    async with mcp_client(vault) as c:
        hook = await c.ok("plan", action="save", hook_event="PreToolUse", **arguments)
        agent = await c.ok("plan", action="save", **arguments)

    assert hook == "" and agent == {"path": None, "saved": False}
    assert not (vault / "planes").exists()


async def test_save_redacts_credentials_in_text_title_and_path(vault: Path) -> None:
    plan = f"# Clave {FAKE_KEY}\n\nUsar {FAKE_KEY} en el despliegue.\n"
    async with mcp_client(vault) as c:
        saved = await c.ok(
            "plan", action="save", plan=plan, plan_path=f"/tmp/{FAKE_KEY}/plan-clave.md"
        )

    text = (vault / saved["path"]).read_text(encoding="utf-8")
    assert FAKE_KEY not in text and text.count(REDACTED) == 4
    assert FAKE_KEY not in json.dumps(saved)


async def test_save_cuts_a_long_plan_at_a_line_break(vault: Path) -> None:
    plan = "# Largo\n\n" + "una línea del plan bastante larga\n" * 8000
    async with mcp_client(vault) as c:
        saved = await c.ok("plan", action="save", plan=plan, plan_path=PATH_A)
        shown = await c.ok("plan", action="show", slug="plan-azul")

    assert len(plan) > PLAN_MAX
    assert shown["content"].endswith(CUT_MARK.strip())
    assert len(shown["content"]) <= PLAN_MAX
    assert saved["saved"] is True


@pytest.mark.parametrize(
    ("plan_path", "hashed"),
    [
        ("/x/plan con espacios.md", True),
        ("C:\\Users\\u\\.claude\\plans\\plan-win.md", False),
        ("/x/.oculto.md", True),
    ],
)
async def test_slug_is_the_basename_or_a_hash(vault: Path, plan_path: str, hashed: bool) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("plan", action="save", plan=PLAN, plan_path=plan_path)

    slug = saved["slug"]
    if hashed:
        assert len(slug) == 12 and all(ch in "0123456789abcdef" for ch in slug)
    else:
        assert slug == "plan-win"
    assert saved["path"] == f"planes/fabrik/{slug}.md"


async def test_restore_after_clear_points_to_the_plan(vault: Path, tmp_path: Path) -> None:
    here = _worktree(tmp_path)
    async with mcp_client(vault) as c:
        await _hook_save(c, PLAN, PATH_A, here)
        cleared = await _clear(c, here)
        compact = await c.ok(
            "plan", action="restore", source="compact", project_dir=here, hook_event="SessionStart"
        )

    text = _context(cleared)
    assert text.startswith("Plan de esta tarea en episteme: `planes/fabrik/plan-azul.md` — ")
    assert f"Plan azul (guardado {TODAY} " in text and "Léelo con read" in text
    assert "systemMessage" not in json.loads(cleared)
    assert compact == ""


async def test_restore_without_plans_says_nothing(vault: Path) -> None:
    async with mcp_client(vault) as c:
        out = await _clear(c)
        agent = await c.ok("plan", action="restore", source="clear")

    assert out == "" and agent["found"] is False


async def test_restore_prefers_current_then_the_linked_plan_then_the_newest(
    vault: Path, tmp_path: Path
) -> None:
    here = _worktree(tmp_path)
    async with mcp_client(vault, today="2026-10-01") as c:
        await _hook_save(c, PLAN, PATH_A, here)
    async with mcp_client(vault, today="2026-10-02") as c:
        await _hook_save(c, "# Plan rojo\n\nOtro.\n", PATH_B, here)

    async with mcp_client(vault, today="2026-10-03") as c:
        newest = await c.ok("plan", action="restore", source="clear", project_dir=here)
        await c.ok("session", action="save", title="T", body=BODY, plan="plan-azul")
    async with mcp_client(vault, today="2026-10-03") as c:
        linked = await c.ok("plan", action="restore", source="clear", project_dir=here)
    async with mcp_client(vault, today="2026-10-03") as c:
        await _hook_save(c, "# Plan rojo\n\nOtra vez.\n", PATH_B, here)
        current = await c.ok("plan", action="restore", source="clear", project_dir=here)

    assert newest["path"] == "planes/fabrik/plan-rojo.md"
    assert linked["path"] == "planes/fabrik/plan-azul.md"
    assert current["path"] == "planes/fabrik/plan-rojo.md"


async def test_session_save_keeps_and_takes_the_plan(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_A)
        taken = await c.ok("session", action="save", title="Con plan", body=BODY)
        first = _fm(vault / taken["path"])["plan"]
        await c.ok("session", action="save", body=BODY, plan="plan-otro")
        await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_B)
        await c.ok("session", action="save", body=BODY)
        bad = await c.error("session", action="save", body=BODY, plan="../x")

    assert first == "plan-azul"
    assert _fm(vault / taken["path"])["plan"] == "plan-otro"
    assert bad.startswith("invalid_argument:") and "plan slug" in bad


async def test_show_lists_active_plans_and_archive_hides_them(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-01") as c:
        await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_A)
    async with mcp_client(vault, today="2026-10-02") as c:
        await c.ok("plan", action="save", plan="# Plan rojo\n\nOtro.\n", plan_path=PATH_B)
        listed = await c.ok("plan", action="show")
        one = await c.ok("plan", action="show", slug="plan-azul")
        archived = await c.ok("plan", action="archive", slug="plan-azul")
        again = await c.ok("plan", action="archive", slug="plan-azul")
        after = await c.ok("plan", action="show")
        missing = await c.error("plan", action="show", slug="nope")
        no_slug = await c.error("plan", action="archive")
        bad = await c.error("plan", action="show", slug="../x")

    assert [p["slug"] for p in listed["plans"]] == ["plan-rojo", "plan-azul"]
    assert one["title"] == "Plan azul" and "Escribir el tool" in one["content"]
    assert archived == {"path": "planes/fabrik/plan-azul.md", "changed": True}
    assert again["changed"] is False
    assert [p["slug"] for p in after["plans"]] == ["plan-rojo"]
    assert missing.startswith("not_found:") and no_slug.startswith("invalid_argument:")
    assert bad.startswith("invalid_argument:")


async def test_revise_and_remember_refuse_the_plan_zone(vault: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_A)
        revised = await c.error("revise", note=saved["path"], action="append", text="x")

    assert revised == f"read_only_zone: {saved['path']} is in a plan zone. Use plan."


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_remember_refuses_a_memory_folder_linked_into_the_plan_zone(vault: Path) -> None:
    (vault / "planes").mkdir()
    (vault / "memory/sym").symlink_to(vault / "planes", target_is_directory=True)

    async with mcp_client(vault) as c:
        text = await c.error(
            "remember", type="lesson", title="Una lección enlazada", body="x", project="sym"
        )

    assert text.startswith("read_only_zone:") and "plan zone" in text, text


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_save_refuses_a_plan_folder_linked_out_of_the_zone(vault: Path) -> None:
    (vault / "planes").mkdir()
    (vault / "planes/fabrik").symlink_to(vault / "memory/fabrik", target_is_directory=True)

    async with mcp_client(vault) as c:
        hook = await _hook_save(c, PLAN, PATH_A)
        agent = await c.error("plan", action="save", plan=PLAN, plan_path=PATH_A)

    assert hook == ""
    assert agent.startswith("invalid_argument:") and "plan zone" in agent
    assert not (vault / "memory/fabrik/plan-azul.md").exists()


async def test_plan_is_searchable_but_not_in_welcome_or_task_notes(vault: Path) -> None:
    plan = PLAN + "\nPalabra zumbadorrara aquí.\n"
    async with mcp_client(vault) as c:
        saved = await c.ok("plan", action="save", plan=plan, plan_path=PATH_A)
        found = await c.ok("search", query="zumbadorrara")
        welcome = await c.ok("context", mode="welcome")
        task = await c.ok("context", mode="task", task="zumbadorrara")
        await c.ok("plan", action="archive", slug="plan-azul")
        archived = await c.ok("search", query="zumbadorrara")
        anyway = await c.ok("search", query="zumbadorrara", status="any")

    assert saved["path"] in json.dumps(found)
    assert saved["path"] not in json.dumps(welcome)
    assert saved["path"] not in json.dumps(task)
    assert saved["path"] not in json.dumps(archived)
    assert saved["path"] in json.dumps(anyway)


@pytest.mark.parametrize(
    ("extra", "old_archived"), [("", True), ("[plans]\narchive_days = 10", False)]
)
async def test_first_welcome_archives_old_plans_but_not_the_linked_one(
    vault: Path, extra: str, old_archived: bool
) -> None:
    toml = vault / "episteme.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + "\n" + extra + "\n", encoding="utf-8")
    async with mcp_client(vault, today="2026-10-01") as c:
        await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_A)
        await c.ok("plan", action="save", plan="# Plan rojo\n\nOtro.\n", plan_path=PATH_B)
    async with mcp_client(vault, today="2026-10-08") as c:
        await c.ok("session", action="save", title="Sigue", body=BODY, plan="plan-rojo")

    async with mcp_client(vault, today="2026-10-09") as c:
        await c.ok("context", mode="welcome", session="s1")

    old = _fm(vault / "planes/fabrik/plan-azul.md")["status"]
    linked = _fm(vault / "planes/fabrik/plan-rojo.md")["status"]
    assert old == ("archived" if old_archived else "active")
    assert linked == "active"


async def test_session_save_does_not_link_an_archived_current_plan(vault: Path) -> None:
    async with mcp_client(vault) as c, mcp_client(vault) as other:
        await c.ok("plan", action="save", plan=PLAN, plan_path=PATH_A)
        await other.ok("plan", action="archive", slug="plan-azul")
        saved = await c.ok("session", action="save", title="Sin plan", body=BODY)

    assert "plan" not in _fm(vault / saved["path"])
