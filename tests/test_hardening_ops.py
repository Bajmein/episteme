"""Hardening of backups, the activity log and notes over the size limit."""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import sys
import tarfile
import time
from pathlib import Path

import pytest
from conftest import FIXTURES, mcp_client

from episteme import backup
from episteme.activity import Activity
from episteme.errors import StartupError
from episteme.vault import Vault, load_config

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions and symlinks")

# Built by concatenation so no scanner takes the test for a real credential.
FAKE_TOKEN = "gh" + "p_" + "a1B2c3D4e5" * 3 + "a1B2c3"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_backup_does_not_follow_a_symlinked_note(vault: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE-CONTENT", encoding="utf-8")
    (vault / "memory" / "link.md").symlink_to(outside)

    out = backup.run(Vault(vault), tmp_path / "bk", keep=3)

    assert out is not None
    with tarfile.open(out, "r:gz") as tar:
        blobs = [f.read() for m in tar.getmembers() if m.isfile() and (f := tar.extractfile(m))]
    assert b"OUTSIDE-CONTENT" not in b"".join(blobs)


@posix_only
def test_load_config_rejects_a_symlinked_config(tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    real = tmp_path / "real.toml"
    shutil.copy(FIXTURES / "vault" / "episteme.toml", real)
    (root / "episteme.toml").symlink_to(real)

    with pytest.raises(StartupError, match="not a symlink"):
        load_config(root)


def test_rotate_deletes_only_its_own_stale_temp_files(vault: Path, tmp_path: Path) -> None:
    dest = tmp_path / "bk"
    dest.mkdir()
    old = time.time() - 7200
    ours = dest / ".episteme-backup-abc.tmp"
    theirs = dest / ".tmp-abc.tmp"
    for f in (ours, theirs):
        f.write_text("x", encoding="utf-8")
        os.utime(f, (old, old))

    backup.run(Vault(vault), dest, keep=3)

    assert not ours.exists()
    assert theirs.exists()


@posix_only
def test_index_dir_and_activity_db_are_owner_only(tmp_path: Path) -> None:
    act = Activity(tmp_path)
    try:
        act.record("search", {"query": "x"}, "r", 1, True)
    finally:
        act.close()

    assert _mode(act.db_path.parent) == 0o700
    assert _mode(act.db_path) == 0o600


def test_activity_redacts_credentials_in_recorded_arguments(tmp_path: Path) -> None:
    act = Activity(tmp_path)
    try:
        act.record(
            "search",
            {"query": f"find {FAKE_TOKEN}", "tags": ["ok", FAKE_TOKEN], "project": FAKE_TOKEN},
            "r",
            1,
            True,
        )
    finally:
        act.close()

    conn = sqlite3.connect(act.db_path)
    try:
        dump = "".join(str(v) for row in conn.execute("select * from calls") for v in row)
    finally:
        conn.close()
    assert FAKE_TOKEN not in dump
    assert "[redacted: GitHub token]" in dump
    assert '"ok"' in dump


HUGE_LINE = "zorbhuge palabra\n"


@pytest.mark.anyio
async def test_revise_rejects_an_edit_over_2_mb_and_keeps_the_memory(vault: Path) -> None:
    async with mcp_client(vault) as c:
        made = await c.ok(
            "remember", type="decision", title="Memoria que no debe crecer",
            body="Texto corto con zorbkeep.",
        )  # fmt: skip
        before = (vault / made["path"]).read_bytes()

        err = await c.error(
            "revise", note=made["path"], action="edit", old="zorbkeep", new=HUGE_LINE * 170_000
        )
        hits = await c.ok("search", query="zorbkeep")
        note = await c.ok("read", note=made["path"])

    assert err.startswith(f"invalid_argument: {made['path']} would be ")
    assert "the limit is 2 MB. Shorten it or split it into several memories." in err
    assert (vault / made["path"]).read_bytes() == before
    assert [r["path"] for r in hits["results"]] == [made["path"]]
    assert "zorbkeep" in note["content"]


@pytest.mark.anyio
async def test_read_explains_a_note_over_2_mb(vault: Path) -> None:
    (vault / "plans").mkdir(exist_ok=True)
    (vault / "plans" / "huge.md").write_text("# Huge\n\n" + HUGE_LINE * 190_000, encoding="utf-8")

    async with mcp_client(vault) as c:
        err = await c.error("read", note="plans/huge.md")
        bare = await c.error("read", note="plans/huge")
        missing = await c.error("read", note="plans/nada.md")

    assert err.startswith("invalid_argument: plans/huge.md has ")
    assert err.endswith("over the 2 MB limit; episteme does not index it. Split the note.")
    assert bare == err
    assert missing.startswith("not_found: ")
