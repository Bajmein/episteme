"""Automatic maintenance on the first welcome of a session (stdio) and Store-driven run()."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import mcp_client
from test_review_expired import write

from episteme import maintenance

pytestmark = pytest.mark.anyio

TODAY = "2026-10-22"
OLD = "memory/fabrik/lessons/2026-10-20-vencida.md"
NOTICE = "mantención pendiente en fabrik"
ARCHIVED = "memorias vencidas archivadas"


def seed(vault: Path) -> None:
    write(vault, OLD, "lesson", "Vencida", "2026-10-21")


def config(vault: Path, extra: str) -> None:
    toml = vault / "episteme.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + "\n" + extra + "\n", encoding="utf-8", newline=""
    )


async def welcome(c, session: str) -> str:
    return (await c.ok("context", mode="welcome", session=session))["text"]


async def test_archive_expired(vault: Path) -> None:
    seed(vault)
    config(vault, "[maintenance]\narchive_expired = true")
    async with mcp_client(vault, today=TODAY) as c:
        text = await welcome(c, "s1")
        assert ARCHIVED in text and OLD in text
        assert ARCHIVED not in await welcome(c, "s2")
        out = await c.ok("review", project="fabrik", zone="memory")
        assert out["expired"] == []


async def test_default_notifies_once_per_day(vault: Path) -> None:
    seed(vault)
    async with mcp_client(vault, today=TODAY) as c:
        assert NOTICE in await welcome(c, "s1")
        assert NOTICE not in await welcome(c, "s2")
        out = await c.ok("review", project="fabrik", zone="memory")
        assert [e["path"] for e in out["expired"]] == [OLD]
    async with mcp_client(vault, today="2026-10-23") as c:
        assert NOTICE in await welcome(c, "s3")


async def test_backup(vault: Path, tmp_path: Path) -> None:
    dest = tmp_path / "bk"
    config(vault, f"[backup]\ndir = '{dest}'")
    async with mcp_client(vault, today=TODAY) as c:
        await welcome(c, "s1")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not list(dest.glob("episteme-*.tar.gz")):
            await asyncio.sleep(0.1)
        assert list(dest.glob("episteme-*.tar.gz"))


async def test_no_session_no_maintenance(vault: Path) -> None:
    seed(vault)
    async with mcp_client(vault, today=TODAY) as c:
        out = await c.ok("context", mode="welcome")
        assert NOTICE not in out["text"]
    assert not (vault / ".index" / "maintenance.db").exists()


class FakeStore:
    def __init__(self) -> None:
        self.restored: list[str] = []
        self.logged: list[tuple[str, list[str]]] = []

    def claim(self, task: str, every_days: int) -> str:
        return "2026-01-01"

    def restore(self, task: str, previous: str) -> None:
        self.restored.append(task)

    def log(self, task: str, paths: list[str], detail: str = "") -> None:
        self.logged.append((task, paths))


def fake_engine(archive: bool = True) -> SimpleNamespace:
    cfg = SimpleNamespace(archive_expired=archive, notify=False, every_days=1)
    return SimpleNamespace(vault=SimpleNamespace(config=SimpleNamespace(maintenance=cfg)))


def test_run_caps_listed_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from episteme import memory

    paths = [f"memory/p/{n}.md" for n in range(8)]
    monkeypatch.setattr(memory, "archive_expired", lambda engine: paths)
    store = FakeStore()
    line = maintenance.run(fake_engine(), store, "p")
    assert "8 memorias vencidas" in line
    assert "memory/p/4.md +3 más" in line and "memory/p/5.md" not in line
    assert store.logged == [("archive_expired", paths)]


def test_run_restores_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from episteme import memory

    def boom(engine):
        raise RuntimeError("x")

    monkeypatch.setattr(memory, "archive_expired", boom)
    store = FakeStore()
    assert maintenance.run(fake_engine(), store, "p") == ""
    assert store.restored == ["archive_expired"]
