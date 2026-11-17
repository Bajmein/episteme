"""The session tool through MCP: the state in sesiones/, its worktree, archive and rotation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml
from conftest import TODAY, mcp_client

from episteme.errors import StartupError
from episteme.vault import SESSION, Zone, load_config

pytestmark = pytest.mark.anyio

BODY = "## Objetivo\n\nProbar el estado.\n\n## Siguiente paso\n\nCorrer los tests.\n"
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


def _config(vault: Path, extra: str, drop_state_glob: bool = False) -> None:
    toml = vault / "episteme.toml"
    text = toml.read_text(encoding="utf-8")
    if drop_state_glob:
        text = text.split("[checkpoint]")[0]
    toml.write_text(text + "\n" + extra + "\n", encoding="utf-8")


def _worktree(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.mkdir()
    return str(path)


async def test_save_creates_the_state_in_sesiones_and_rewrites_it(vault: Path) -> None:
    async with mcp_client(vault) as c:
        first = await c.ok("session", action="save", title="Zona de sesión", body=BODY)
        second = await c.ok("session", action="save", body="# Zona de sesión\n\n" + BODY + "Más.")

    assert first["created"] is True and second["created"] is False
    assert first["path"] == second["path"]
    assert first["path"].startswith(f"sesiones/fabrik/{TODAY}-estado-")
    fm = _fm(vault / first["path"])
    assert fm["type"] == "session" and fm["status"] == "active"
    assert fm["tags"] == ["sesion/estado"] and fm["project"] == "fabrik"
    assert fm["task_title"] == "Zona de sesión" and fm["saved_by"] == "agent"
    assert str(fm["saved_at"]).startswith(TODAY)
    assert not {"kind", "priority", "helpful", "valid_until"} & set(fm)
    text = (vault / first["path"]).read_text(encoding="utf-8")
    assert text.count("# Zona de sesión") == 1 and "Más." in text
    assert "Hecho (con evidencia)" in first["missing_sections"]


async def test_save_with_note_rewrites_that_state(vault: Path) -> None:
    async with mcp_client(vault) as c:
        one = await c.ok("session", action="save", title="Uno", body=BODY)
        await c.ok("session", action="archive")
        two = await c.ok("session", action="save", title="Dos", body=BODY, origin="agent")
        with_note = await c.ok(
            "session", action="save", body=BODY + "Nota.", note=one["path"], origin="extractor"
        )
        shown = await c.ok("session", action="show")

    assert two["created"] is True and with_note["path"] == one["path"]
    assert _fm(vault / one["path"])["saved_by"] == "extractor"
    assert _fm(vault / one["path"])["status"] == "active"
    assert shown["path"] == one["path"] and "Nota." in shown["content"]


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"body": BODY}, "needs title"),
        ({"title": "T", "body": "  "}, "body is empty"),
        ({"title": "T", "body": f"key {FAKE_KEY}"}, "looks like a secret"),
        ({"title": "T", "body": BODY, "session": FAKE_KEY}, "session looks like a secret"),
        ({"title": "T", "body": BODY, "origin": "compact"}, "origin must be"),
        ({"title": "T", "body": BODY, "project": "../x"}, "not a valid project name"),
        ({"title": "T", "body": BODY, "note": "memory/fabrik/x.md"}, "not in a session zone"),
        ({"title": "T", "body": BODY, "note": "sesiones/fabrik/nope.md"}, "not_found"),
    ],
)
async def test_save_refuses_bad_arguments(vault: Path, arguments: dict, needle: str) -> None:
    async with mcp_client(vault) as c:
        text = await c.error("session", action="save", **arguments)

    assert needle in text, text
    assert not list((vault / "sesiones").rglob("*.md")) if (vault / "sesiones").exists() else True


async def test_show_after_restart_finds_the_newest_state_of_the_same_worktree(
    vault: Path, tmp_path: Path
) -> None:
    here, other = _worktree(tmp_path, "a"), _worktree(tmp_path, "b")
    async with mcp_client(vault) as c:
        mine = await c.ok("session", action="save", title="Mío", body=BODY, project_dir=here)
        await c.ok("session", action="save", title="Otro", body=BODY, project_dir=other)

    async with mcp_client(vault) as c:
        shown = await c.ok("session", action="show", project_dir=here)
        restored = await c.ok("session", action="restore", project_dir=here)
        saved = await c.ok("session", action="save", body=BODY + "Sigue.", project_dir=here)

    assert shown["found"] is True and shown["path"] == mine["path"]
    assert shown["task_title"] == "Mío" and "## Objetivo" in shown["content"]
    assert restored["source"] == "session" and restored["path"] == mine["path"]
    assert restored["content"].startswith("Estado de la sesión «Mío» (guardado ")
    assert saved["path"] == mine["path"]


async def test_save_without_project_dir_rewrites_the_state_restored_with_it(
    vault: Path, tmp_path: Path
) -> None:
    here, other = _worktree(tmp_path, "a"), _worktree(tmp_path, "b")
    async with mcp_client(vault) as c:
        mine = await c.ok("session", action="save", title="Mío", body=BODY, project_dir=here)
        theirs = await c.ok("session", action="save", title="Otro", body=BODY, project_dir=other)

    async with mcp_client(vault) as c:
        await c.ok("session", action="restore", project_dir=here)
        saved = await c.ok("session", action="save", body=BODY + "Sigue.")

    assert saved["path"] == mine["path"] != theirs["path"]
    assert "Sigue." not in (vault / theirs["path"]).read_text(encoding="utf-8")


async def test_save_refuses_a_state_of_another_project(vault: Path) -> None:
    async with mcp_client(vault) as c:
        theirs = await c.ok("session", action="save", title="Ajeno", body=BODY, project="otro")
        text = await c.error("session", action="save", body=BODY, note=theirs["path"])

    assert text.startswith("invalid_argument:") and 'project="otro"' in text


async def test_restore_hook_renders_the_state_with_a_notice(vault: Path) -> None:
    async with mcp_client(vault) as c:
        await c.ok("session", action="save", title="Hilo", body=BODY)
        text = await c.ok("session", action="restore", hook_event="SessionStart")

    out = json.loads(text)
    assert "Estado de la sesión «Hilo»" in out["hookSpecificOutput"]["additionalContext"]
    assert "estado de sesión recuperado: «Hilo»" in out["systemMessage"]


async def test_restore_falls_back_to_the_deprecated_checkpoint(
    vault: Path, project_dir: Path
) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="restore", project_dir=str(project_dir))

    assert res["found"] is True and res["source"] == "state"
    assert "deprecated" in res["deprecated"]


async def test_restore_without_state_or_state_glob_finds_nothing(vault: Path) -> None:
    _config(vault, "", drop_state_glob=True)
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="restore")

    assert res["found"] is False and res["source"] is None and "deprecated" not in res


async def test_checkpoint_is_marked_deprecated(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        tools = {t.name: t for t in (await c.session.list_tools()).tools}
        res = await c.ok("checkpoint", action="restore", project_dir=str(project_dir))

    assert (tools["checkpoint"].description or "").startswith("Deprecated: use session.")
    assert res["deprecated"].startswith("checkpoint and [checkpoint] state_glob are deprecated")


@pytest.mark.parametrize(("type_", "first"), [(None, "Objetivo"), ("decision", "Contexto")])
async def test_template_returns_the_skeleton(vault: Path, type_: str | None, first: str) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="template", **({"type": type_} if type_ else {}))

    assert res["sections"][0].startswith(first) and f"## {first}" in res["skeleton"]


async def test_template_and_action_refuse_unknown_values(vault: Path) -> None:
    async with mcp_client(vault) as c:
        bad_type = await c.error("session", action="template", type="nope")
        bad_action = await c.error("session", action="nope")

    assert bad_type.startswith("invalid_argument:") and "decision" in bad_type
    assert bad_action.startswith("invalid_argument:") and "archive" in bad_action


async def test_archive_keeps_the_file_and_show_ignores_it(vault: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("session", action="save", title="Hecho", body=BODY)
        archived = await c.ok("session", action="archive")
        again = await c.ok("session", action="archive", note=saved["path"])
        shown = await c.ok("session", action="show")
        nothing = await c.error("session", action="archive")

    assert archived == {"path": saved["path"], "changed": True}
    assert again["changed"] is False and shown["found"] is False
    assert _fm(vault / saved["path"])["status"] == "archived"
    assert "no current session state" in nothing


@pytest.mark.parametrize(
    ("extra", "archived"), [("", True), ("[session]\narchive_days = 10", False)]
)
async def test_first_welcome_archives_states_unsaved_for_archive_days(
    vault: Path, extra: str, archived: bool
) -> None:
    _config(vault, extra)
    async with mcp_client(vault, today="2026-10-01") as c:
        saved = await c.ok("session", action="save", title="Viejo", body=BODY)

    async with mcp_client(vault, today="2026-10-09") as c:
        await c.ok("context", mode="welcome", session="s1")
        shown = await c.ok("session", action="show")

    status = _fm(vault / saved["path"])["status"]
    assert status == ("archived" if archived else "active")
    assert shown["found"] is not archived


async def test_state_is_searchable_but_not_in_welcome_or_task_notes(vault: Path) -> None:
    body = BODY + "\nPalabra zumbadorrara aquí.\n"
    async with mcp_client(vault) as c:
        saved = await c.ok("session", action="save", title="Zumbadorrara", body=body)
        found = await c.ok("search", query="zumbadorrara")
        welcome = await c.ok("context", mode="welcome")
        task = await c.ok("context", mode="task", task="zumbadorrara")
        await c.ok("session", action="archive")
        archived = await c.ok("search", query="zumbadorrara")

    assert saved["path"] in json.dumps(found)
    assert saved["path"] not in json.dumps(welcome)
    assert saved["path"] not in json.dumps(task)
    assert saved["path"] not in json.dumps(archived)


async def test_revise_refuses_a_session_state(vault: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("session", action="save", title="Intocable", body=BODY)
        text = await c.error("revise", note=saved["path"], action="append", text="x")

    assert text == f"read_only_zone: {saved['path']} is in a session zone. Use session."


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_remember_refuses_a_memory_folder_linked_into_the_session_zone(
    vault: Path,
) -> None:
    (vault / "sesiones").mkdir()
    (vault / "memory/sym").symlink_to(vault / "sesiones", target_is_directory=True)

    async with mcp_client(vault) as c:
        text = await c.error(
            "remember", type="lesson", title="Una lección enlazada", body="x", project="sym"
        )

    assert text.startswith("read_only_zone:") and "session zone" in text, text
    assert not (vault / "sesiones/lessons").exists()


def test_session_zone_is_implicit(vault: Path) -> None:
    cfg = load_config(vault)

    assert Zone("sesiones", SESSION) in cfg.zones
    assert cfg.session.archive_days == 7 and cfg.session.nudge_every == 12
    assert cfg.session.extract is True and cfg.session.block_manual_compact is True


def test_declared_session_zone_replaces_the_implicit_one(vault: Path) -> None:
    _config(vault, '[zones."estado"]\nmode = "session"')

    zones = load_config(vault).zones

    assert Zone("estado", SESSION) in zones and not any(z.path == "sesiones" for z in zones)


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        ('[zones."sesiones"]\nmode = "read-write"', 'must have mode "session"'),
        ("[session]\narchive_days = 0", "archive_days must be an integer >= 1"),
        ("[session]\nextract = 1", "extract must be true or false"),
        ("[session]\nvalid_days = 14", 'unknown key "valid_days"'),
    ],
)
def test_bad_session_config_stops_startup(vault: Path, extra: str, needle: str) -> None:
    _config(vault, extra)

    with pytest.raises(StartupError, match=needle):
        load_config(vault)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_a_link_from_the_session_zone_to_a_memory_is_never_a_state(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-01") as c:
        memory = await c.ok(
            "remember", type="session", title="Pausa enlazada", body="Cuerpo de la pausa."
        )
    before = (vault / memory["path"]).read_text(encoding="utf-8")
    link = vault / "sesiones/fabrik/zz-link.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(vault / memory["path"])

    async with mcp_client(vault, today="2026-10-09") as c:
        await c.ok("context", mode="welcome", session="s1")
        shown = await c.ok("session", action="show")
        saved = await c.ok("session", action="save", title="Nuevo", body=BODY)
        archived = await c.error("session", action="archive", note="sesiones/fabrik/zz-link.md")

    assert shown["found"] is False
    assert saved["created"] is True and saved["path"] != "sesiones/fabrik/zz-link.md"
    assert "session zone" in archived
    assert (vault / memory["path"]).read_text(encoding="utf-8") == before
