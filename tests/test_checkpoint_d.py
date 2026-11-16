"""checkpoint: saved-checkpoint notice, worktree filter and the hook output cut mark."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import FIXTURES, mcp_client

from episteme.hookmode import CAP, CUT_MARK, render

pytestmark = pytest.mark.anyio

NOTICE = (
    "Saved checkpoint from 2026-10-19, not the live state: check it against the working "
    "tree and do not redo listed steps without a current request."
)


def _second_project(tmp_path: Path) -> Path:
    dst = tmp_path / "other"
    shutil.copytree(FIXTURES / "project", dst)
    return dst


def test_render_marks_the_cut() -> None:
    text = "\n".join(f"line {i:05d} " + "x" * 40 for i in range(400))
    assert len(text) > CAP
    out = json.loads(render("SessionStart", text))["hookSpecificOutput"]["additionalContext"]
    assert out.endswith(CUT_MARK) and len(out) <= CAP
    assert CUT_MARK.strip() == "[episteme: output cut at 10,000 characters]"
    short = json.loads(render("SessionStart", "hola"))["hookSpecificOutput"]["additionalContext"]
    assert short == "hola"


async def test_saved_checkpoint_has_notice_and_worktree(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("checkpoint", action="save", project_dir=str(project_dir))
        fm = yaml.safe_load((vault / saved["path"]).read_text().split("---\n")[1])
        assert fm["worktree"] == Path(os.path.realpath(project_dir)).as_posix()
        res = await c.ok("checkpoint", action="restore")
        assert res["source"] == "checkpoint"
        assert res["content"].startswith(NOTICE + "\n\n# Checkpoint · 001 · demo")
        hook = await c.call("checkpoint", action="restore", hook_event="SessionStart")
        ctx = json.loads(hook[1])["hookSpecificOutput"]["additionalContext"]
        assert ctx.startswith(NOTICE)


async def test_live_state_has_no_notice(vault: Path, project_dir: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("checkpoint", action="restore", project_dir=str(project_dir))
        assert res["source"] == "state" and "Saved checkpoint" not in res["content"]


async def test_restore_filters_by_worktree(vault: Path, project_dir: Path, tmp_path: Path) -> None:
    other = _second_project(tmp_path)
    shutil.rmtree(other / ".fabrik")  # no live state there: only the fallback applies
    async with mcp_client(vault) as c:
        saved = await c.ok("checkpoint", action="save", project_dir=str(project_dir))
        res = await c.ok("checkpoint", action="restore", project_dir=str(other))
        assert res["found"] is False
        res = await c.ok("checkpoint", action="restore")  # no project_dir: as before
        assert res["path"] == saved["path"]
        # A checkpoint without the field (older version) still matches any worktree.
        note = vault / saved["path"]
        lines = [x for x in note.read_text().splitlines(keepends=True) if "worktree:" not in x]
        note.write_text("".join(lines))
    async with mcp_client(vault) as c:
        res = await c.ok("checkpoint", action="restore", project_dir=str(other))
        assert res["found"] is True and res["path"] == saved["path"]


async def test_hook_cut_mark_end_to_end(vault: Path, project_dir: Path) -> None:
    state = project_dir / ".fabrik/core/001-demo/estado.md"
    big = "\n".join(f"- paso {i} " + "y" * 60 for i in range(300))
    state.write_text(state.read_text().replace("## Trampas", f"## Trampas\n{big}"))
    async with mcp_client(vault) as c:
        hook = await c.call(
            "checkpoint", action="restore", project_dir=str(project_dir), hook_event="SessionStart"
        )
    ctx = json.loads(hook[1])["hookSpecificOutput"]["additionalContext"]
    assert hook[0] is False and len(ctx) <= CAP and ctx.endswith(CUT_MARK)


async def test_other_worktree_state_does_not_archive_checkpoint(
    vault: Path, project_dir: Path, tmp_path: Path
) -> None:
    other = _second_project(tmp_path)
    state = other / ".fabrik/core/001-demo/estado.md"
    state.write_text(state.read_text().replace("001 · demo", "009 · otra"))
    async with mcp_client(vault) as c:
        saved = await c.ok("checkpoint", action="save", project_dir=str(project_dir))
        res = await c.ok("checkpoint", action="restore", project_dir=str(other))
        assert res["source"] == "state"
        res = await c.ok("checkpoint", action="restore")
        assert res["found"] is True and res["path"] == saved["path"]


async def test_restore_notice_has_no_control_characters(vault: Path, project_dir: Path) -> None:
    state = next(project_dir.rglob("estado.md"))
    text = state.read_text(encoding="utf-8")
    hostile = '"001 \\e]0;pwn\\a\\e[2J demo"'.replace("\\e", "\\x1b").replace("\\a", "\\x07")
    patched = text.replace("task_title: 001 · demo", f"task_title: {hostile}")
    assert patched != text
    state.write_text(patched, encoding="utf-8", newline="")

    async with mcp_client(vault) as c:
        hook = await c.call(
            "checkpoint",
            action="restore",
            project_dir=str(project_dir),
            hook_event="SessionStart",
        )

    notice = json.loads(hook[1])["systemMessage"]
    assert "\x1b]0;" not in notice and "\x07" not in notice and "\x1b[2J" not in notice
    assert "pwn" in notice
