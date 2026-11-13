"""archive_expired: archives every active memory past valid_until, in all projects."""

from __future__ import annotations

from pathlib import Path

import pytest

from episteme import memory
from episteme.engine import Engine


def write(
    vault: Path,
    rel: str,
    typ: str,
    title: str,
    valid_until: str,
    status: str = "active",
    project: str = "fabrik",
) -> str:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntype: {typ}\nproject: {project}\npriority: 3\nstatus: {status}\n"
        f"created: 2026-10-20\nvalid_until: {valid_until}\n---\n# {title}\n\nCuerpo de {title}.\n",
        encoding="utf-8",
        newline="",
    )
    return rel


@pytest.fixture
def engine(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-22")
    return Engine(vault, "fabrik")


def _status(vault: Path, rel: str) -> str:
    line = next(x for x in (vault / rel).read_text(encoding="utf-8").splitlines() if "status:" in x)
    return line.split(":", 1)[1].strip()


def _run(engine: Engine) -> list[str]:
    engine.index.refresh()
    return memory.archive_expired(engine)


def test_archives_expired_only(vault: Path, engine: Engine) -> None:
    old = write(vault, "memory/fabrik/lessons/2026-10-20-vencida.md", "lesson", "V", "2026-10-21")
    keep = write(vault, "memory/fabrik/lessons/2026-10-20-vigente.md", "lesson", "G", "2026-10-23")
    today_ = write(vault, "memory/fabrik/lessons/2026-10-20-hoy.md", "lesson", "H", "2026-10-22")
    done = write(
        vault, "memory/fabrik/lessons/2026-10-20-arch.md", "lesson", "A", "2026-10-01", "archived"
    )
    ckpt = write(vault, "memory/fabrik/sessions/checkpoint-viejo.md", "session", "C", "2026-10-01")
    assert _run(engine) == [old]
    assert _status(vault, old) == "archived"
    for rel in (keep, today_, done, ckpt):
        assert _status(vault, rel) == ("archived" if rel == done else "active")
    row = engine.index.memories(f"path = '{old}'")
    assert row[0]["status"] == "archived"
    assert _run(engine) == []


def test_archives_across_projects(vault: Path, engine: Engine) -> None:
    a = write(vault, "memory/fabrik/lessons/2026-10-20-a.md", "lesson", "A", "2026-10-01")
    b = write(
        vault, "memory/otro/lessons/2026-10-20-b.md", "lesson", "B", "2026-10-02", project="otro"
    )
    assert _run(engine) == [a, b]


def test_invalid_frontmatter_is_skipped(vault: Path, engine: Engine) -> None:
    bad = write(vault, "memory/fabrik/lessons/2026-10-20-mala.md", "lesson", "M", "2026-10-01")
    good = write(vault, "memory/fabrik/lessons/2026-10-20-buena.md", "lesson", "B", "2026-10-02")
    engine.index.refresh()
    (vault / bad).write_text(
        (vault / bad).read_text(encoding="utf-8").replace("priority: 3", "priority: [9"),
        encoding="utf-8",
        newline="",
    )
    assert memory.archive_expired(engine) == [good]
    assert _status(vault, good) == "archived"


def test_stale_index_is_rechecked_against_file(vault: Path, engine: Engine) -> None:
    rel = write(vault, "memory/fabrik/lessons/2026-10-20-ext.md", "lesson", "E", "2026-10-01")
    engine.index.refresh()
    (vault / rel).write_text(
        (vault / rel).read_text(encoding="utf-8").replace("2026-10-01", "2026-12-01"),
        encoding="utf-8",
        newline="",
    )
    assert memory.archive_expired(engine) == []
    assert _status(vault, rel) == "active"


@pytest.mark.parametrize("new", ["", "valid_until: 2026-1-5\n"])
def test_stale_index_without_a_readable_date_is_not_archived(
    vault: Path, engine: Engine, new: str
) -> None:
    rel = write(vault, "memory/fabrik/lessons/2026-10-20-sin.md", "lesson", "S", "2026-10-01")
    engine.index.refresh()
    text = (vault / rel).read_text(encoding="utf-8")
    (vault / rel).write_text(
        text.replace("valid_until: 2026-10-01\n", new), encoding="utf-8", newline=""
    )

    archived = memory.archive_expired(engine)

    assert archived == []
    assert _status(vault, rel) == "active"
