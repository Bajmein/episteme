"""The optional one-line ``description`` of a memory: saved, validated, indexed and shown."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml
from conftest import mcp_client

from episteme.engine import Engine
from episteme.errors import EpistemeError
from episteme.index.schema import SCHEMA_VERSION
from episteme.memory.schema import validate
from episteme.memory.scoring import entry_line

pytestmark = pytest.mark.anyio

_VALID = {
    "type": "lesson", "project": "p", "priority": 3, "status": "active", "created": "2026-10-22",
}  # fmt: skip
BODY = "Quasar cache is rebuilt nightly. Second sentence stays out."


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


async def test_description_is_saved_in_the_frontmatter_and_shown_by_search(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok(
            "remember",
            type="lesson",
            title="Quasar cache",
            body=BODY,
            description="  Why the quasar cache is rebuilt  ",
        )
        fm = _fm(vault / res["path"])
        found = await c.ok("search", query="quasar", zone="memory")

    assert list(fm)[:3] == ["type", "kind", "description"]
    assert fm["description"] == "Why the quasar cache is rebuilt"
    assert "description_hint" not in res
    row = next(r for r in found["results"] if r["path"] == res["path"])
    assert row["description"] == "Why the quasar cache is rebuilt"


async def test_missing_description_is_derived_when_shown_and_not_stored(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("remember", type="lesson", title="Quasar cache", body=BODY)
        fm = _fm(vault / res["path"])
        found = await c.ok("search", query="quasar", zone="memory")

    assert "description" not in fm
    assert "description_hint" in res
    row = next(r for r in found["results"] if r["path"] == res["path"])
    assert row["description"] == "Quasar cache is rebuilt nightly."


@pytest.mark.parametrize("bad", ["two\nlines", "x" * 161])
async def test_invalid_description_is_refused(vault: Path, bad: str) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        text = await c.error(
            "remember", type="lesson", title="Quasar cache", body=BODY, description=bad
        )

    assert text.startswith("invalid_schema: description ")


async def test_description_that_looks_like_a_secret_is_refused(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        text = await c.error(
            "remember",
            type="lesson",
            title="Quasar cache",
            body=BODY,
            description="password=hunter2hunter2",
        )

    assert text.startswith("invalid_argument:")


async def test_revise_set_validates_the_description(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok("remember", type="lesson", title="Quasar cache", body=BODY)
        text = await c.error(
            "revise", note=res["path"], action="set", fields={"description": "a\nb"}
        )
        await c.ok("revise", note=res["path"], action="set", fields={"description": "Fine"})

    assert text.startswith("invalid_schema: description ")
    assert _fm(vault / res["path"])["description"] == "Fine"


async def test_remember_schema_lists_description(vault: Path) -> None:
    async with mcp_client(vault) as c:
        tools = {t.name: t for t in (await c.session.list_tools()).tools}

    assert "description" in tools["remember"].input_schema["properties"]


def test_entry_line_prefers_the_description_over_the_first_sentence() -> None:
    row = {
        "type": "lesson", "priority": 3, "title": "T", "path": "memory/x.md",
        "body": "First sentence. Second.", "description": "Stored line",
    }  # fmt: skip

    assert entry_line(row).endswith("(memory/x.md) — Stored line")
    assert entry_line({**row, "description": None}).endswith("(memory/x.md) — First sentence.")


def test_description_with_unicode_line_separator_is_refused() -> None:
    with pytest.raises(EpistemeError, match="single line"):
        validate({**_VALID, "description": "a b"})


async def test_existing_schema_2_index_is_not_rebuilt_and_returns_description(
    vault: Path,
) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        res = await c.ok(
            "remember", type="lesson", title="Quasar cache", body=BODY, description="Stored line"
        )
    with sqlite3.connect(vault / ".index" / "index.db") as conn:
        conn.execute("insert into meta(key, value) values ('sentinel', 'kept')")

    engine = Engine(vault, "fabrik")
    row = engine.index.note(res["path"])
    kept = engine.index.conn.execute("select value from meta where key = 'sentinel'").fetchone()

    assert SCHEMA_VERSION == "2"
    assert kept is not None
    assert row is not None
    assert row["description"] == "Stored line"
