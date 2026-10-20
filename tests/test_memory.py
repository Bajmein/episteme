"""memory.py: schema, file names, duplicates and revise (unit level)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from episteme import memory
from episteme.engine import Engine
from episteme.errors import EpistemeError


@pytest.fixture
def engine(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-19")
    eng = Engine(vault, "fabrik")
    eng.index.refresh()
    return eng


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


def test_kind_and_priority_defaults() -> None:
    assert memory.kind_for("session") == "episodic"
    assert memory.kind_for("error") == "procedural"
    assert memory.kind_for("insight") == "semantic"
    assert memory.default_priority("decision") == 4
    assert memory.default_priority("lesson") == 3


@pytest.mark.parametrize(
    ("fields", "word"),
    [
        ({"priority": 9}, "priority"),
        ({"type": "note"}, "type"),
        ({"status": "done"}, "status"),
        ({"project": "a/b"}, "project"),
        ({"project": ".."}, "project"),
        ({"tags": ["dominio:auth"]}, "tag"),
        ({"tags": ["two words"]}, "tag"),
        ({"files": "x.py"}, "files"),
        ({"created": None}, "created"),
        ({"type": "reminder"}, "due"),
    ],
)
def test_validation(fields: dict, word: str) -> None:
    base = {
        "type": "decision",
        "project": "fabrik",
        "priority": 3,
        "status": "active",
        "created": "2026-10-19",
    }
    with pytest.raises(EpistemeError) as err:
        memory.validate(base | fields)
    assert err.value.code == "invalid_schema"
    assert word in str(err.value)


def test_remember_writes_schema(engine: Engine, vault: Path) -> None:
    res = memory.remember(
        engine,
        "decision",
        "Usar ÚV para dependencias",
        "Las dependencias van con `uv add`, nunca con pip.",
        tags=["pieza/uv"],
        related=["2026-10-02-serena-ty"],
        source="abc123",
    )
    assert res["created"] is True
    assert res["path"] == "memory/fabrik/decisions/2026-10-19-usar-uv-para-dependencias.md"
    text = (vault / res["path"]).read_text()
    fm = _fm(vault / res["path"])
    assert list(fm) == [
        "type", "kind", "project", "priority", "status", "created", "tags",
        "related", "source", "helpful",
    ]  # fmt: skip
    assert fm["priority"] == 4 and fm["kind"] == "semantic"
    assert fm["related"] == ["[[2026-10-02-serena-ty]]"]
    assert "\n# Usar ÚV para dependencias\n\nLas dependencias" in text
    again = memory.remember(engine, "decision", "Usar ÚV para dependencias", "Otra cosa distinta.")
    assert again["path"].endswith("usar-uv-para-dependencias-2.md")


def test_remember_errors(engine: Engine) -> None:
    with pytest.raises(EpistemeError) as err:
        memory.remember(engine, "reminder", "x", "y")
    assert err.value.code == "invalid_schema" and "due" in str(err.value)
    with pytest.raises(EpistemeError) as err:
        memory.remember(engine, "lesson", "x", "y", related=["nothing-here"])
    assert err.value.code == "not_found"
    with pytest.raises(EpistemeError) as err:
        memory.remember(engine, "lesson", "x", "y", project="a/b")
    assert err.value.code == "invalid_schema"
    engine.project = None
    with pytest.raises(EpistemeError) as err:
        memory.remember(engine, "lesson", "x", "y")
    assert err.value.code == "invalid_argument"


def test_append_under_heading(engine: Engine, vault: Path) -> None:
    (vault / "plans").mkdir()
    (vault / "plans/p.md").write_text("---\na: 1 # keep\n---\n# P\n\n## One\nx\n\n## Two\ny\n")
    engine.index.refresh()
    memory.revise(engine, "plans/p.md", "append", text="added", heading="one")
    assert (vault / "plans/p.md").read_text() == (
        "---\na: 1 # keep\n---\n# P\n\n## One\nx\n\nadded\n\n## Two\ny\n"
    )
    memory.revise(engine, "plans/p.md", "append", text="end")
    assert (vault / "plans/p.md").read_text().endswith("## Two\ny\n\nend\n")
    memory.revise(engine, "plans/p.md", "edit", old="added", new="changed")
    assert "changed" in (vault / "plans/p.md").read_text()
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, "plans/p.md", "archive")
    assert err.value.code == "invalid_argument"


def test_revise_through_symlink_cannot_reach_read_only_zone(engine: Engine, vault: Path) -> None:
    target = vault / "docs/claude-code/hooks-reference.md"
    before = target.read_text()
    (vault / "plans").mkdir()
    os.symlink(target, vault / "plans/link.md")
    engine.index.refresh()
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, "plans/link.md", "append", text="tampered")
    assert err.value.code == "read_only_zone"
    assert target.read_text() == before


def test_feedback_and_set(engine: Engine, vault: Path) -> None:
    rel = "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md"
    memory.revise(engine, rel, "feedback", value="helpful")
    assert _fm(vault / rel)["helpful"] == 4
    for _ in range(6):
        memory.revise(engine, rel, "feedback", value="unhelpful")
    assert _fm(vault / rel)["helpful"] == 0
    memory.revise(engine, rel, "feedback", value="outdated")
    assert _fm(vault / rel)["flagged"] is True
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, rel, "set", fields={"priority": 9})
    assert err.value.code == "invalid_schema"
    assert _fm(vault / rel)["priority"] == 3
    res = memory.revise(engine, rel, "set", fields={"priority": 5, "valid_until": "2027-01-01"})
    assert set(res["changed"]) == {"priority", "valid_until"}
    memory.revise(engine, rel, "set", fields={"valid_until": None})
    assert "valid_until" not in _fm(vault / rel)
    memory.revise(engine, rel, "archive")
    assert _fm(vault / rel)["status"] == "archived"


def test_welcome_caps(engine: Engine) -> None:
    for i in range(15):
        memory.remember(
            engine, "insight", f"Insight número {i} sobre {'x' * i}", f"Cuerpo {i}. " * 40,
            force=True,
        )  # fmt: skip
    text, entries = memory.welcome(engine, "fabrik")
    assert len(entries) == 10
    assert len(text) <= 4000
    assert all(len(line) < 400 for line in text.splitlines())


def test_review_reports_memory_without_project(engine: Engine, vault: Path) -> None:
    rel = "memory/fabrik/decisions/no-project.md"
    (vault / rel).write_text(
        "---\ntype: decision\nstatus: active\ncreated: 2026-10-01\n---\n# No project\n"
    )
    engine.index.refresh()
    out = memory.review(engine, None, None, 50)
    assert rel in {x["path"] for x in out["invalid_frontmatter"]}
