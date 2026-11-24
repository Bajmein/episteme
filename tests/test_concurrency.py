"""Two server processes writing the same vault at once."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
import yaml
from conftest import mcp_client

ROUNDS = 5

REMEMBER_WRITER = """
import anyio, sys
sys.path.insert(0, {tests!r})
from pathlib import Path
from conftest import mcp_client

async def main():
    async with mcp_client(Path({vault!r})) as c:
        for _ in range({rounds}):
            await c.ok("remember", type="insight", title="Shared concurrent note",
                         body="Same body written by two processes at once about quokkas")

anyio.run(main)
"""

FEEDBACK_WRITER = """
import anyio, sys
sys.path.insert(0, {tests!r})
from pathlib import Path
from conftest import mcp_client

async def main():
    async with mcp_client(Path({vault!r})) as c:
        for _ in range({rounds}):
            await c.ok("revise", note={note!r}, action="feedback", value="helpful")

anyio.run(main)
"""


def _run_two(script: str, **fmt: object) -> None:
    tests = str(Path(__file__).parent)
    procs = [
        subprocess.Popen([sys.executable, "-c", script.format(tests=tests, rounds=ROUNDS, **fmt)])
        for _ in range(2)
    ]
    assert all(p.wait(timeout=180) == 0 for p in procs)


def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_concurrent_remember_without_force_loses_nothing(vault: Path) -> None:
    _run_two(REMEMBER_WRITER, vault=str(vault))

    files = [
        p
        for p in (vault / "memory/fabrik").rglob("*.md")
        if "shared-concurrent-note" in p.name
    ]
    assert files
    for path in files:
        assert _front_matter(path)["type"] == "insight"
    conn = sqlite3.connect(vault / ".index/index.db")
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"
    if len(files) > 1:

        async def check() -> None:
            async with mcp_client(vault) as c:
                res = await c.ok("review", project="fabrik")
                listed = {p for group in res["similar"] for p in group["paths"]}
                assert {p.relative_to(vault).as_posix() for p in files} <= listed

        anyio.run(check)


def test_concurrent_feedback_keeps_every_increment(vault: Path) -> None:
    async def create() -> str:
        async with mcp_client(vault) as c:
            res = await c.ok("remember", type="insight", title="Counter note", body="Counts votes")
            return res["path"]

    path = anyio.run(create)

    _run_two(FEEDBACK_WRITER, vault=str(vault), note=path)

    assert _front_matter(vault / path)["helpful"] == 2 * ROUNDS


def test_write_lock_does_not_unlock_when_the_lock_was_never_taken(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from episteme import vault as vault_module

    unlocked: list[bool] = []
    monkeypatch.setattr(vault_module, "_lock_file", lambda fh: False)  # Windows timeout
    monkeypatch.setattr(vault_module, "_unlock_file", lambda fh: unlocked.append(True))

    with vault_module.Vault(vault).write_lock():
        pass

    assert unlocked == []
