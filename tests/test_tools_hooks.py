"""context(welcome), surface and constraints through MCP (9, 10, 15, 16)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

GUARD = ".claude/hooks/serena_guard.py"
CONSTRAINT = "memory/fabrik/constraints/2026-10-10-serena-guard-cd.md"


async def test_case9_welcome_once_per_session(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        first = await c.ok("context", mode="welcome", session="s1")
        assert first["already_sent"] is False
        lines = first["text"].splitlines()
        assert lines[0] == "episteme · memoria de fabrik"
        assert lines[1] == "Recordatorios vencidos:"
        assert lines[2].startswith("- [2026-10-21] Correr las trigger queries")
        assert lines[3] == "Normas:"
        paths = [e["path"] for e in first["entries"]]
        norms = [e["path"] for e in first["entries"] if e["kind"] == "norm"]
        assert "memory/fabrik/decisions/2026-10-02-serena-ty.md" in norms
        assert paths[0] == "memory/fabrik/reminders/2026-10-18-revisar-trigger-queries.md"
        assert paths[1 : 1 + len(norms)] == norms
        assert "Memorias:" in lines
        assert "memory/_shared/perfil.md" in norms
        assert paths[1 + len(norms) :] == [
            CONSTRAINT,
            "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md",
        ]
        scores = [e["score"] for e in first["entries"] if e["kind"] == "memory"]
        assert scores == sorted(scores, reverse=True)
        assert "serena-pyright" not in first["text"]
        assert "— Serena pasa de `pyright` a `ty` 0.0.89" in first["text"]
        second = await c.ok("context", mode="welcome", session="s1")
        assert second == {"text": "", "entries": [], "already_sent": True}
        hook = await c.call("context", mode="welcome", session="s2", hook_event="UserPromptSubmit")
        assert hook[0] is False
        welcome = json.loads(hook[1])["hookSpecificOutput"]["additionalContext"]
        assert welcome.startswith("episteme · memoria de fabrik")
        again = await c.call("context", mode="welcome", session="s2", hook_event="UserPromptSubmit")
        assert again == (False, "")


async def test_welcome_before_due_date(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-19") as c:
        res = await c.ok("context")
        assert "Recordatorios vencidos" not in res["text"]


async def test_case10_surface_and_constraints(vault: Path) -> None:
    async with mcp_client(vault) as c:
        mem = await c.ok(
            "remember",
            type="lesson",
            title="serena_guard tarda con rutas largas",
            body="Probar con rutas de 200 caracteres.",
            files=[GUARD],
        )
        mention = await c.ok(
            "remember",
            type="insight",
            title="Guard de Serena revisado",
            body=f"Se revisó `{GUARD}` en el change 005.",
            priority=4,
        )
        surf = await c.ok("context", mode="surface", file=GUARD)
        got = [(m["path"], m["match"]) for m in surf["memories"]]
        assert got == [(mem["path"], "files"), (mention["path"], "mention")]
        assert CONSTRAINT not in {m["path"] for m in surf["memories"]}
        cons = await c.ok("context", mode="constraints", file=GUARD)
        assert [x["path"] for x in cons["constraints"]] == [CONSTRAINT]
        assert "no intentes expandir variables" in cons["constraints"][0]["body"]
        none = await c.ok("context", mode="constraints", file="src/data.py")
        assert none["constraints"] == []


async def test_case15_hook_output(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok("remember", type="lesson", title="Nota del guard", body="x" * 50, files=[GUARD])
        for mode, event in (("surface", "PostToolUse"), ("constraints", "PreToolUse")):
            is_error, text = await c.call("context", mode=mode, file=GUARD, hook_event=event)
            assert not is_error
            data = json.loads(text)
            assert list(data) == ["hookSpecificOutput"]
            out = data["hookSpecificOutput"]
            assert out["hookEventName"] == event
            assert 0 < len(out["additionalContext"]) <= 10_000
            assert "decision" not in data and "decision" not in out
            where = {"file": "nothing/here.py", "hook_event": event}
            assert await c.call("context", mode=mode, **where) == (False, "")
        text = await c.error("context", mode="surface", file=GUARD, hook_event="Stop")
        assert text.startswith("invalid_argument:")


async def test_case16_absolute_file_with_project_dir(vault: Path, tmp_path: Path) -> None:
    project = tmp_path / "proyecto"
    (project / ".claude/hooks").mkdir(parents=True)
    async with mcp_client(vault) as c:
        where = {"mode": "constraints", "project_dir": str(project)}
        res = await c.ok("context", file=str(project / GUARD), **where)
        assert res["file"] == GUARD
        assert [x["path"] for x in res["constraints"]] == [CONSTRAINT]
        res = await c.ok("context", file=str(project / "data.py"), **where)
        assert res["constraints"] == []


async def test_surface_relative_path_and_empty_file(vault: Path) -> None:
    async with mcp_client(vault) as c:
        mem = await c.ok(
            "remember", type="lesson", title="Nota del guard", body="x" * 50, files=[GUARD]
        )
        res = await c.ok("context", mode="surface", relative_path=GUARD)
        assert [m["path"] for m in res["memories"]] == [mem["path"]]
        cons = await c.ok("context", mode="constraints", file="", relative_path=GUARD)
        assert [x["path"] for x in cons["constraints"]] == [CONSTRAINT]
        for mode, event in (("surface", "PostToolUse"), ("constraints", "PreToolUse")):
            text = await c.error("context", mode=mode)
            assert text.startswith("invalid_argument:") and "file or relative_path" in text
            assert await c.call("context", mode=mode, file="", hook_event=event) == (False, "")


async def test_surface_excludes_session_and_reminder(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok(
            "remember",
            type="reminder",
            title="Recordar guard",
            body=f"Ver `{GUARD}`.",
            due="2026-10-25",
        )
        await c.ok("remember", type="session", title="Sesion guard", body=f"Toca `{GUARD}`.")
        res = await c.ok("context", mode="surface", file=GUARD)
        assert {m["type"] for m in res["memories"]}.isdisjoint({"session", "reminder"})


async def test_surface_basename_only_when_unambiguous(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok(
            "remember",
            type="insight",
            title="Sobre util",
            body="Cuidado con `util.py` al editar.",
            priority=4,
        )
        res = await c.ok("context", mode="surface", file="src/a/util.py")
        assert [m["match"] for m in res["memories"]] == ["mention"]
        await c.ok(
            "remember", type="lesson", title="Otro util", body="x" * 50, files=["src/b/util.py"]
        )
        res = await c.ok("context", mode="surface", file="src/a/util.py")
        assert res["memories"] == []


async def test_surface_and_constraints_skip_expired(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-19") as c:
        await c.ok(
            "remember",
            type="lesson",
            title="Vence pronto",
            body="x" * 50,
            files=["src/v.py"],
            valid_until="2026-10-30",
        )
        await c.ok(
            "remember",
            type="constraint",
            title="Regla vence",
            body="x" * 50,
            files=["src/v.py"],
            valid_until="2026-10-30",
        )
        assert len((await c.ok("context", mode="surface", file="src/v.py"))["memories"]) == 1
        assert len((await c.ok("context", mode="constraints", file="src/v.py"))["constraints"]) == 1
    async with mcp_client(vault, today="2026-11-05") as c:
        assert (await c.ok("context", mode="surface", file="src/v.py"))["memories"] == []
        assert (await c.ok("context", mode="constraints", file="src/v.py"))["constraints"] == []


PREVIOUS = "episteme · hay un estado de sesión de una sesión anterior"
STATE_BODY = "## Objetivo\n\nSeguir.\n\n## Siguiente paso\n\nNada.\n"


async def test_first_welcome_names_the_state_a_previous_session_left(
    vault: Path, tmp_path: Path
) -> None:
    here = tmp_path / "repo"
    here.mkdir()
    async with mcp_client(vault) as c:
        saved = await c.ok(
            "session", action="save", title="Hilo viejo", body=STATE_BODY, project_dir=str(here)
        )
    async with mcp_client(vault) as c:
        first = await c.ok("context", mode="welcome", session="s2", project_dir=str(here))
        again = await c.ok("context", mode="welcome", session="s2", project_dir=str(here))
        resent = await c.ok(
            "context",
            mode="welcome",
            session="s2",
            project_dir=str(here),
            hook_event="SessionStart",
            source="compact",
        )

    assert PREVIOUS in first["text"] and "«Hilo viejo»" in first["text"]
    assert f"`{saved['path']}`" in first["text"] and "/episteme:sesion retomar" in first["text"]
    assert "Seguir." not in first["text"]
    assert PREVIOUS not in again["text"]
    assert PREVIOUS not in resent


async def test_first_welcome_names_no_state_without_project_dir(
    vault: Path, tmp_path: Path
) -> None:
    async with mcp_client(vault) as c:
        await c.ok(
            "session", action="save", title="Hilo", body=STATE_BODY, project_dir=str(tmp_path)
        )
    async with mcp_client(vault) as c:
        first = await c.ok("context", mode="welcome", session="s2")

    assert PREVIOUS not in first["text"]


async def test_first_welcome_skips_a_state_saved_without_worktree(
    vault: Path, tmp_path: Path
) -> None:
    async with mcp_client(vault) as c:
        await c.ok("session", action="save", title="Sin worktree", body=STATE_BODY)
    async with mcp_client(vault) as c:
        first = await c.ok("context", mode="welcome", session="s2", project_dir=str(tmp_path))

    assert PREVIOUS not in first["text"]


async def test_first_welcome_skips_the_state_of_its_own_session(
    vault: Path, tmp_path: Path
) -> None:
    async with mcp_client(vault) as c:
        await c.ok(
            "session",
            action="save",
            title="Mío",
            body=STATE_BODY,
            session="s1",
            project_dir=str(tmp_path),
        )
    async with mcp_client(vault) as c:
        first = await c.ok("context", mode="welcome", session="s1", project_dir=str(tmp_path))

    assert PREVIOUS not in first["text"]


async def test_agent_save_takes_the_worktree_a_hook_passed(vault: Path, tmp_path: Path) -> None:
    async with mcp_client(vault) as c:
        await c.call(
            "context",
            mode="welcome",
            session="s1",
            project_dir=str(tmp_path),
            hook_event="UserPromptSubmit",
        )
        saved = await c.ok("session", action="save", title="Del agente", body=STATE_BODY)
        note = await c.ok("read", note=saved["path"], content=False)
    async with mcp_client(vault) as c:
        first = await c.ok("context", mode="welcome", session="s2", project_dir=str(tmp_path))

    assert note["frontmatter"]["worktree"] == tmp_path.resolve().as_posix()
    assert PREVIOUS in first["text"] and "«Del agente»" in first["text"]


async def test_first_welcome_says_nothing_without_a_previous_state(vault: Path) -> None:
    async with mcp_client(vault) as c:
        first = await c.ok("context", mode="welcome", session="s1")

    assert PREVIOUS not in first["text"]
