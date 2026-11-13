"""Welcome: the 160-char reserve and the "no caben aquí" line."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import mcp_client

from episteme import memory
from episteme.engine import Engine

pytestmark = pytest.mark.anyio

NOTICE = "no caben aquí: "


@pytest.fixture
def engine(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-19")
    eng = Engine(vault, "fabrik")
    eng.index.refresh()
    return eng


def _norms(engine: Engine, n: int) -> None:
    for i in range(n):
        memory.remember(
            engine, "decision", f"Norma de relleno número {i} {'z' * i}",
            f"Regla {i} {'larga ' * 30}.", priority=5, force=True,
        )  # fmt: skip


def test_no_notice_when_everything_fits(engine: Engine) -> None:
    text, _ = memory.welcome(engine, "fabrik")
    assert NOTICE not in text
    assert len(text) <= 4000


def test_notice_when_norms_do_not_fit(engine: Engine) -> None:
    _norms(engine, 30)
    text, entries = memory.welcome(engine, "fabrik")
    shown = sum(e["kind"] == "norm" for e in entries)
    last = text.splitlines()[-1]
    assert len(text) <= 4000
    assert last.startswith(f"(+{shown_missing(engine, shown)} normas no caben aquí: ")
    assert "recordatorios" not in last
    assert last.endswith('search(project="fabrik", zone="memory", type="reminder") o review)')
    assert all(e["kind"] != "memory" for e in entries)  # normal memories are not mentioned


def shown_missing(engine: Engine, shown: int) -> int:
    rows = engine.index.memories("project in (?, '_shared') and status = 'active'", ("fabrik",))
    total = sum(1 for r in rows if r["priority"] == 5 and r["type"] not in ("session", "reminder"))
    return total - shown


def test_notice_counts_overdue_reminders(engine: Engine) -> None:
    _norms(engine, 30)
    for i in range(8):
        memory.remember(
            engine, "reminder", f"Recordatorio vencido {i} {'y' * 60}", "Hacer algo.",
            due="2026-10-01", force=True,
        )  # fmt: skip
    text, entries = memory.welcome(engine, "fabrik")
    assert len(text) <= 4000
    # overdue reminders come first, so they are listed and the norms are the ones left out
    assert any(e["kind"] == "reminder" for e in entries)
    assert "normas" in text.splitlines()[-1]


async def test_welcome_notice_over_mcp(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        for i in range(30):
            await c.ok(
                "remember", type="decision", title=f"Norma e2e número {i} {'q' * i}",
                body=f"Regla {i} {'larga ' * 30}.", priority=5, force=True,
            )  # fmt: skip
        res = await c.ok("context", mode="welcome", session="e2e")
        lines = res["text"].splitlines()
        assert len(res["text"]) <= 4000
        assert lines[-1].startswith("(+")
        assert " normas no caben aquí: search(project=" in lines[-1]
