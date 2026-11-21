"""remember and revise through MCP (cases 3, 7, 8, 13 and 18)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import mcp_client

pytestmark = pytest.mark.anyio

HOOKS = "docs/claude-code/hooks-reference.md"


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


async def test_case3_read_only_zone(vault: Path) -> None:
    before = (vault / HOOKS).read_bytes()
    async with mcp_client(vault) as c:
        for action, extra in (
            ("edit", {"old": "Referencia de hooks", "new": "x"}),
            ("append", {"text": "x"}),
            ("set", {"fields": {"a": 1}}),
            ("archive", {}),
        ):
            text = await c.error("revise", note=HOOKS, action=action, **extra)
            assert text.startswith("read_only_zone:"), text
        text = await c.error("remember", type="decision", title="t", body="b", supersedes=HOOKS)
        assert text.startswith(("read_only_zone:", "invalid_argument:")), text
    assert (vault / HOOKS).read_bytes() == before


async def test_case4_write_paths_leaving_the_vault(vault: Path) -> None:
    async with mcp_client(vault) as c:
        for bad in ("../x.md", "/etc/passwd"):
            text = await c.error("revise", note=bad, action="append", text="x")
            assert text.startswith("outside_vault:")
            text = await c.error("remember", type="lesson", title="t", body="b", related=[bad])
            assert text.startswith("outside_vault:")


async def test_case7_near_duplicate(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok(
            "remember",
            type="lesson",
            title="El watchdog de OMEGA cierra el proceso al pasar 1024 MB de RSS",
            body="OMEGA se «desconectaba» sin error visible: su watchdog cierra el proceso stdio "
            "al llegar a 1024 MB de RSS. Arreglo: `OMEGA_RSS_LIMIT_MB=2048` y "
            "`OMEGA_IDLE_TIMEOUT=0` en la entrada de `.mcp.json`.",
        )
        assert res["created"] is False and res["path"] is None
        assert res["similar"][0]["path"] == "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md"
        assert res["similar"][0]["similarity"] >= 0.8
        assert len(list((vault / "memory/fabrik/lessons").iterdir())) == 1
        res = await c.ok(
            "remember",
            type="lesson",
            title="El watchdog de OMEGA cierra el proceso al pasar 1024 MB de RSS",
            body="OMEGA se desconectaba: su watchdog cierra el proceso stdio al llegar a 1024 MB "
            "de RSS. Arreglo: OMEGA_RSS_LIMIT_MB=2048 y OMEGA_IDLE_TIMEOUT=0 en .mcp.json.",
            force=True,
        )
        assert res["created"] is True
        assert (vault / res["path"]).exists()


async def test_case8_supersede(vault: Path) -> None:
    async with mcp_client(vault) as c:
        new = await c.ok(
            "remember",
            type="decision",
            title="Serena usa ty 0.0.90",
            body="Se sube ty a 0.0.90 en `.serena/project.yml`.",
            priority=5,
        )
        res = await c.ok("revise", note="2026-10-02-serena-ty", action="supersede", by=new["path"])
        assert res["by"] == new["path"] and "status" in res["changed"]
        old_fm = _fm(vault / "memory/fabrik/decisions/2026-10-02-serena-ty.md")
        assert old_fm["status"] == "superseded" and old_fm["priority"] == 5
        assert _fm(vault / new["path"])["supersedes"] == "[[2026-10-02-serena-ty]]"
        links = (await c.ok("read", note=new["path"], links="out"))["links"]
        old = "memory/fabrik/decisions/2026-10-02-serena-ty.md"
        assert ("supersedes", old) in [(o["kind"], o["path"]) for o in links["outgoing"]]
        # remember(supersedes=...) does the same in one call
        newer = await c.ok(
            "remember",
            type="decision",
            title="Serena usa ty 0.1.0",
            body="Se sube ty a 0.1.0 en `.serena/project.yml`.",
            supersedes=new["path"],
        )
        assert _fm(vault / new["path"])["status"] == "superseded"
        assert _fm(vault / newer["path"])["supersedes"] == "[[2026-10-19-serena-usa-ty-0-0-90]]"


async def test_case18_zone_rules_for_append(vault: Path) -> None:
    (vault / "scratch").mkdir()
    (vault / "scratch/x.md").write_text("# x\n")
    (vault / "plans").mkdir()
    (vault / "plans/x.md").write_text("# x\n")
    async with mcp_client(vault) as c:
        text = await c.error("revise", note="scratch/x.md", action="append", text="more")
        assert text.startswith("read_only_zone:")
        res = await c.ok("revise", note="plans/x.md", action="append", text="more")
        assert res["changed"] == ["body"]
    assert (vault / "scratch/x.md").read_text() == "# x\n"
    assert (vault / "plans/x.md").read_text() == "# x\n\nmore\n"


WRITER = """
import anyio, sys
sys.path.insert(0, {tests!r})
from pathlib import Path
from conftest import mcp_client

async def main():
    async with mcp_client(Path({vault!r})) as c:
        for i in range(12):
            await c.ok("remember", type="insight", title=f"{tag} parallel note {{i}}",
                       body=f"Body {tag} {{i}} zorro{tag}{{i}}", force=True)

anyio.run(main)
"""


def test_case13_concurrent_writers(vault: Path) -> None:
    tests = str(Path(__file__).parent)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", WRITER.format(tests=tests, vault=str(vault), tag=tag)],
        )
        for tag in ("alfa", "beta")
    ]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    files = list((vault / "memory/fabrik/insights").iterdir())
    assert len(files) == 24
    import anyio

    async def check() -> None:
        async with mcp_client(vault) as c:
            for tag in ("alfa", "beta"):
                res = await c.ok("search", query=f"parallel {tag}", path="memory", limit=100)
                assert res["total"] == 12
            # index integrity
            res = await c.ok("search", query="zorroalfa0")
            assert res["total"] == 1

    anyio.run(check)
    import sqlite3

    conn = sqlite3.connect(vault / ".index/index.db")
    assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


async def test_remember_explicit_slug(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok(
            "remember",
            type="lesson",
            title="Checkpoint fuera de change",
            body="El checkpoint se guarda aunque no haya change activo.",
            slug="checkpoint-fuera-de-change",
        )
        assert res["path"].endswith("/2026-10-19-checkpoint-fuera-de-change.md")
