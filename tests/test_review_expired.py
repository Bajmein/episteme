"""review: the expired group (active memories past valid_until, checkpoints excluded)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio


def write(
    vault: Path, rel: str, typ: str, title: str, valid_until: str, status: str = "active"
) -> str:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: {typ}\nproject: fabrik\npriority: 3\nstatus: {status}\n"
        f"created: 2026-10-20\nvalid_until: {valid_until}\n---\n# {title}\n\nCuerpo de {title}.\n",
        encoding="utf-8",
        newline="",
    )
    return rel


async def test_expired_group(vault: Path) -> None:
    old = write(
        vault, "memory/fabrik/lessons/2026-10-20-vencida.md", "lesson", "Vencida", "2026-10-21"
    )
    write(vault, "memory/fabrik/lessons/2026-10-20-vigente.md", "lesson", "Vigente", "2026-10-22")
    write(
        vault, "memory/fabrik/sessions/checkpoint-viejo.md", "session", "Checkpoint", "2026-10-01"
    )
    write(
        vault,
        "memory/fabrik/lessons/2026-10-20-arch.md",
        "lesson",
        "Archivada",
        "2026-10-01",
        "archived",
    )
    async with mcp_client(vault, today="2026-10-22") as c:
        out = await c.ok("review", project="fabrik", zone="memory")
        assert out["expired"] == [
            {"path": old, "title": "Vencida", "type": "lesson", "valid_until": "2026-10-21"}
        ]
        assert out["totals"]["expired"] == 1
        assert "expired" in out["read_only"]["totals"]


async def test_expired_boundary_and_plain_session(vault: Path) -> None:
    write(vault, "memory/fabrik/lessons/2026-10-20-hoy.md", "lesson", "Hoy", "2026-10-22")
    sess = write(
        vault, "memory/fabrik/sessions/2026-10-20-nota.md", "session", "Nota", "2026-10-21"
    )
    async with mcp_client(vault, today="2026-10-22") as c:
        out = await c.ok("review", project="*", zone="memory")
        assert [e["path"] for e in out["expired"]] == [sess]
