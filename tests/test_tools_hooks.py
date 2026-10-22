"""context(welcome), surface, constraints and checkpoint through MCP (9, 10, 11, 15, 16, 19)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
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
        assert lines[3] == "Memorias:"
        paths = [e["path"] for e in first["entries"]]
        assert paths == [
            "memory/fabrik/reminders/2026-10-18-revisar-trigger-queries.md",
            "memory/fabrik/decisions/2026-10-02-serena-ty.md",
            "memory/_shared/perfil.md",
            CONSTRAINT,
            "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md",
        ]
        scores = [e["score"] for e in first["entries"][1:]]
        assert scores == sorted(scores, reverse=True)
        assert "serena-pyright" not in first["text"]
        assert "— Serena pasa de `pyright` a `ty` 0.0.89" in first["text"]
        second = await c.ok("context", mode="welcome", session="s1")
        assert second == {"text": "", "entries": [], "already_sent": True}
        hook = await c.call(
            "context", mode="welcome", session="s2", hook_event="UserPromptSubmit"
        )
        assert hook[0] is False and hook[1].startswith("episteme · memoria de fabrik")
        again = await c.call(
            "context", mode="welcome", session="s2", hook_event="UserPromptSubmit"
        )
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
        )
        surf = await c.ok("surface", file=GUARD)
        got = [(m["path"], m["match"]) for m in surf["memories"]]
        assert got == [(mem["path"], "files"), (mention["path"], "mention")]
        assert CONSTRAINT not in {m["path"] for m in surf["memories"]}
        cons = await c.ok("constraints", file=GUARD)
        assert [x["path"] for x in cons["constraints"]] == [CONSTRAINT]
        assert "no intentes expandir variables" in cons["constraints"][0]["body"]
        none = await c.ok("constraints", file="src/data.py")
        assert none["constraints"] == []


async def test_case15_hook_output(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok(
            "remember", type="lesson", title="Nota del guard", body="x" * 50, files=[GUARD]
        )
        for tool, event in (("surface", "PostToolUse"), ("constraints", "PreToolUse")):
            is_error, text = await c.call(tool, file=GUARD, hook_event=event)
            assert not is_error
            data = json.loads(text)
            assert list(data) == ["hookSpecificOutput"]
            out = data["hookSpecificOutput"]
            assert out["hookEventName"] == event
            assert 0 < len(out["additionalContext"]) <= 10_000
            assert "decision" not in data and "decision" not in out
            assert await c.call(tool, file="nothing/here.py", hook_event=event) == (False, "")
        text = await c.error("surface", file=GUARD, hook_event="Stop")
        assert text.startswith("invalid_argument:")


async def test_case16_absolute_file_with_project_dir(vault: Path, tmp_path: Path) -> None:
    project = tmp_path / "proyecto"
    (project / ".claude/hooks").mkdir(parents=True)
    async with mcp_client(vault) as c:
        res = await c.ok(
            "constraints", file=str(project / GUARD), project_dir=str(project)
        )
        assert res["file"] == GUARD
        assert [x["path"] for x in res["constraints"]] == [CONSTRAINT]
        res = await c.ok("constraints", file=str(project / "data.py"), project_dir=str(project))
        assert res["constraints"] == []


async def test_case11_checkpoint_save_and_restore(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("checkpoint", action="save", project_dir=str(project_dir))
        assert saved == {
            "saved": True,
            "path": "memory/fabrik/sessions/checkpoint-001-demo.md",
            "task_title": "001 · demo",
        }
        text = (vault / saved["path"]).read_text()
        fm = yaml.safe_load(text.split("---\n")[1])
        assert fm["type"] == "session" and str(fm["valid_until"]) == "2026-10-26"
        assert fm["task_title"] == "001 · demo"
        for section in ("## Plan", "## Progreso", "## Decisiones", "## Trampas"):
            assert section in text
        assert "## Siguientes pasos" in text
        assert "Bitácora" not in text and "salida larga de pytest" not in text

        restored = await c.ok("checkpoint", action="restore")
        assert restored["found"] is True and restored["path"] == saved["path"]
        assert restored["source"] == "checkpoint"
        assert "Tests de error" in restored["content"]
        assert "Bitácora" not in restored["content"]
        hook = await c.call(
            "checkpoint", action="restore", project_dir=str(project_dir), hook_event="SessionStart"
        )
        assert hook[0] is False and "## Plan" in hook[1]

        state = project_dir / ".fabrik/core/001-demo/estado.md"
        state.write_text(state.read_text().replace("estado: activo", "estado: cerrado"))
        res = await c.ok("checkpoint", action="save", project_dir=str(project_dir))
        assert res == {"saved": False, "path": None, "task_title": None}


async def test_restore_ignores_expired(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok("checkpoint", action="save", project_dir=str(project_dir))
    async with mcp_client(vault, today="2026-11-30") as c:
        res = await c.ok("checkpoint", action="restore")
        assert res["found"] is False


async def test_case19_precompact_is_silent(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.call(
            "checkpoint", action="save", project_dir=str(project_dir), hook_event="PreCompact"
        )
        assert res == (False, "")
        assert (vault / "memory/fabrik/sessions/checkpoint-001-demo.md").exists()


async def test_checkpoint_without_state_glob(vault: Path, project_dir: Path) -> None:
    toml = vault / "episteme.toml"
    toml.write_text(toml.read_text().split("[checkpoint]")[0])
    async with mcp_client(vault) as c:
        text = await c.error("checkpoint", action="save", project_dir=str(project_dir))
        assert text.startswith("invalid_argument:") and "state_glob" in text


def _change(project: Path, name: str, estado: str = "activo", etapa: str = "build") -> Path:
    folder = project / ".fabrik/core" / name
    folder.mkdir(parents=True)
    (folder / "estado.md").write_text(
        f"---\ntask_title: {name}\nestado: {estado}\netapa: {etapa}\n---\n"
        f"# Estado · {name}\n\n## Progreso\n- trabajo de {name}\n\n"
        "## Siguientes pasos\n1. seguir\n"
    )
    return folder


def _branch(project: Path, ref: str) -> None:
    (project / ".git").mkdir()
    (project / ".git/HEAD").write_text(f"ref: refs/heads/{ref}\n")


async def test_restore_live_state_of_branch(vault: Path, project_dir: Path) -> None:
    other = _change(project_dir, "002-otro")
    (other / "tasks.md").write_text("- [x] T1 a\n- [~] T2 b\n- [ ] T3 c\n")
    _branch(project_dir, "feat/002-otro")
    async with mcp_client(vault) as c:
        res = await c.ok("checkpoint", action="restore", project_dir=str(project_dir))
        assert res["source"] == "state" and res["task_title"] == "002-otro"
        assert res["path"] == ".fabrik/core/002-otro/estado.md"
        first = res["content"].splitlines()[0]
        assert first == (
            "Flujo fabrik: change 002-otro (core), etapa build, "
            "tasks 1/3, en curso T2, siguiente T3"
        )
        assert "trabajo de 002-otro" in res["content"] and "001" not in res["content"]


async def test_restore_newest_when_branch_is_not_a_change(vault: Path, project_dir: Path) -> None:
    other = _change(project_dir, "002-otro")
    old = project_dir / ".fabrik/core/001-demo/estado.md"
    os.utime(old, (1, 1))
    _branch(project_dir, "main")
    async with mcp_client(vault) as c:
        res = await c.ok("checkpoint", action="restore", project_dir=str(project_dir))
        assert res["task_title"] == "002-otro" and other.is_dir()
        assert "tasks" not in res["content"].splitlines()[0]


async def test_restore_by_task_title(vault: Path, project_dir: Path) -> None:
    _change(project_dir, "002-otro")
    _branch(project_dir, "feat/001-demo")
    async with mcp_client(vault) as c:
        res = await c.ok(
            "checkpoint", action="restore", project_dir=str(project_dir), task_title="002-otro"
        )
        assert res["task_title"] == "002-otro" and res["source"] == "state"
        res = await c.ok(
            "checkpoint", action="restore", project_dir=str(project_dir), task_title="nope"
        )
        assert res["found"] is False


async def test_restore_falls_back_then_archives_stale(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("checkpoint", action="save", project_dir=str(project_dir))
        state = project_dir / ".fabrik/core/001-demo/estado.md"
        state.write_text(state.read_text().replace("estado: activo", "estado: cerrado"))
        # No active state: the saved checkpoint is the fallback.
        res = await c.ok("checkpoint", action="restore", project_dir=str(project_dir))
        assert res["source"] == "checkpoint" and res["path"] == saved["path"]
        # Another task becomes active: the stale checkpoint is archived, not restored again.
        _change(project_dir, "002-otro")
        res = await c.ok("checkpoint", action="restore", project_dir=str(project_dir))
        assert res["task_title"] == "002-otro"
        assert "status: archived" in (vault / saved["path"]).read_text()
        res = await c.ok("checkpoint", action="restore")
        assert res["found"] is False
