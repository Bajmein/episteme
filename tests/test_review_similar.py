"""review: similar groups, cut titles, similarity on contradictions and project="*"."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import mcp_client

pytestmark = pytest.mark.anyio

T = "Desplegar staging"
BODY = "Siempre desplegar la aplicación staging usando el pipeline compartido nuevo."




def write(vault: Path, rel: str, typ: str, project: str, title: str, body: str) -> str:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: {typ}\nproject: {project}\npriority: 3\nstatus: active\n"
        f"created: 2026-10-20\n---\n# {title}\n\n{body}\n",
        encoding="utf-8",
        newline="",
    )
    return rel


def make_group(vault: Path) -> list[str]:
    a = write(vault, "memory/fabrik/lessons/2026-10-20-a.md", "lesson", "fabrik", T, BODY)
    b = write(vault, "memory/fabrik/insights/2026-10-20-b.md", "insight", "fabrik", T, BODY + " X")
    c = write(vault, "memory/_shared/lessons/2026-10-20-c.md", "lesson", "_shared", T, BODY)
    return sorted([a, b, c])


async def test_similar_group_and_scope(vault: Path) -> None:
    paths = make_group(vault)
    other = write(vault, "memory/other/lessons/2026-10-20-o.md", "lesson", "other", T, BODY)
    async with mcp_client(vault, today="2026-10-22") as c:
        out = await c.ok("review", zone="memory")
        assert out["totals"]["similar"] == 1
        assert out["similar"][0]["paths"] == paths
        assert out["similar"][0]["similarity"] >= 0.4
        assert other not in out["similar"][0]["paths"]
        out = await c.ok("review", project="fabrik", zone="memory")
        assert out["similar"][0]["paths"] == paths
        out = await c.ok("review", project="*", zone="memory")
        assert out["similar"][0]["paths"] == sorted([*paths, other])
        assert out["totals"]["similar"] == 1


async def test_cut_titles_and_totals(vault: Path) -> None:
    rel = write(
        vault, "memory/fabrik/lessons/2026-10-20-cut.md", "lesson", "fabrik",
        "Usar el pipeline", "Usar el pipeline compartido para todo lo demás.",
    )  # fmt: skip
    async with mcp_client(vault, today="2026-10-22") as c:
        out = await c.ok("review", zone="memory")
        assert rel in out["cut_titles"]
        assert out["totals"]["cut_titles"] == len(out["cut_titles"])
        assert "similar" in out["read_only"]["totals"]
        assert "cut_titles" in out["read_only"]["totals"]


async def test_contradictions_carry_similarity(vault: Path) -> None:
    for n in ("x", "y"):
        path = vault / f"memory/fabrik/decisions/2026-10-20-{n}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntype: decision\nproject: fabrik\npriority: 4\nstatus: active\n"
            "created: 2026-10-20\nfiles: [src/shared.py]\n---\n"
            f"# Decisión {n}\n\nCambiar el módulo compartido {n}.\n",
            encoding="utf-8",
            newline="",
        )
    async with mcp_client(vault, today="2026-10-22") as c:
        out = await c.ok("review", zone="memory")
        mine = [x for x in out["contradictions"] if "decisions/2026-10-20-x" in x["a"] + x["b"]]
        assert mine and isinstance(mine[0]["similarity"], float)
        assert round(mine[0]["similarity"], 3) == mine[0]["similarity"]


async def test_contradictions_need_similar_text(vault: Path) -> None:
    """Sharing a hub file is not enough: unrelated decisions are not paired."""
    bodies = {
        "hub-a": ("Bienvenida en UserPromptSubmit", "El hook reenvía avisos tras compactar."),
        "hub-b": ("Respaldo rotado del vault", "Un tar comprimido guarda las notas cada periodo."),
    }
    for name, (title, body) in bodies.items():
        path = vault / f"memory/fabrik/decisions/2026-10-20-{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntype: decision\nproject: fabrik\npriority: 4\nstatus: active\n"
            "created: 2026-10-20\nfiles: [src/hub.py]\n---\n"
            f"# {title}\n\n{body}\n",
            encoding="utf-8",
            newline="",
        )
    async with mcp_client(vault, today="2026-10-22") as c:
        out = await c.ok("review", zone="memory")
        assert not [x for x in out["contradictions"] if "2026-10-20-hub-" in x["a"] + x["b"]]
        assert all(x["similarity"] >= 0.15 for x in out["contradictions"])
