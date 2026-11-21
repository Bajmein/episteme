"""memory.py: schema, file names, duplicates and revise (unit level)."""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import pytest
import yaml

from episteme import memory
from episteme.engine import Engine
from episteme.errors import EpistemeError
from episteme.memory import NoteFile
from episteme.vault import today


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
    assert res["path"] == "memory/fabrik/decisions/2026-10-19-usar-uv-dependencias.md"
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
    assert again["path"].endswith("usar-uv-dependencias-2.md")


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


def test_set_type_moves_memory(engine: Engine, vault: Path) -> None:
    a = memory.remember(engine, "preference", "Usar uv para las dependencias", "uv sync, uv add.")
    b = memory.remember(
        engine, "lesson", "pip suelto rompe el entorno", "Ver la otra.", related=[a["path"]]
    )
    rel = a["path"]
    name = Path(rel).name
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, rel, "set", fields={"type": "norma"})
    assert err.value.code == "invalid_schema"
    assert (vault / rel).exists()

    res = memory.revise(engine, rel, "set", fields={"type": "error"})
    new = f"memory/fabrik/errors/{name}"
    assert res["path"] == new and res["moved_from"] == rel
    assert set(res["changed"]) == {"type", "kind"}
    assert not (vault / rel).exists()
    fm = _fm(vault / new)
    assert (fm["type"], fm["kind"]) == ("error", "procedural")
    dst = engine.index.conn.execute(
        "select dst_path from links where src = ? and kind = 'related'", (b["path"],)
    ).fetchone()
    assert dst["dst_path"] == new

    res = memory.revise(engine, new, "set", fields={"project": "vigilia"})
    assert res["path"] == f"memory/vigilia/errors/{name}"

    c = memory.remember(engine, "lesson", "Enlace por ruta", f"Ver [[{res['path'][:-3]}]].")
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, res["path"], "set", fields={"type": "constraint"})
    assert err.value.code == "invalid_argument" and c["path"] in str(err.value)
    assert (vault / res["path"]).exists()


def test_set_type_refuses_name_taken(engine: Engine, vault: Path) -> None:
    rel = memory.remember(engine, "lesson", "Nombre repetido", "Uno.", slug="repetido")["path"]
    taken = vault / "memory/fabrik/errors" / Path(rel).name
    taken.parent.mkdir(parents=True, exist_ok=True)
    taken.write_text((vault / rel).read_text())
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, rel, "set", fields={"type": "error"})
    assert err.value.code == "invalid_argument" and "already exists" in str(err.value)
    assert _fm(vault / rel)["type"] == "lesson"


def test_welcome_caps(engine: Engine) -> None:
    for i in range(15):
        memory.remember(
            engine, "insight", f"Insight número {i} sobre {'x' * i}", f"Cuerpo {i}. " * 40,
            force=True,
        )  # fmt: skip
    text, entries = memory.welcome(engine, "fabrik")
    assert sum(e["kind"] == "memory" for e in entries) == 8
    assert len(text) <= 4000
    assert all(len(line) < 400 for line in text.splitlines())


def _mentioning(engine: Engine, title: str, priority: int) -> str:
    return memory.remember(
        engine, "insight", title, f"{title}: ojo con `src/zeta/borde.py` al tocarlo.",
        priority=priority, force=True,
    )["path"]  # fmt: skip


def test_surface_mention_needs_priority_4(engine: Engine) -> None:
    low = _mentioning(engine, "Mención baja del borde", 3)
    high = _mentioning(engine, "Mención alta del borde", 4)

    _, data = memory.surface(engine, "src/zeta/borde.py", None, "fabrik", 3)

    assert [(m["path"], m["match"]) for m in data["memories"]] == [(high, "mention")]
    assert low not in {m["path"] for m in data["memories"]}


def test_surface_lists_at_most_two_mentions_after_the_files_matches(engine: Engine) -> None:
    by_files = memory.remember(
        engine, "lesson", "Lección con archivo borde", "x" * 50, files=["src/zeta/borde.py"]
    )["path"]
    for i in range(4):
        _mentioning(engine, f"Mención {i} del borde", 4)

    _, data = memory.surface(engine, "src/zeta/borde.py", None, "fabrik", 10)

    matches = [m["match"] for m in data["memories"]]
    assert data["memories"][0]["path"] == by_files
    assert matches == ["files", "mention", "mention"]


def test_task_context_leaves_out_the_norms_already_delivered(engine: Engine) -> None:
    norm = memory.remember(
        engine, "decision", "Norma del borde zeta", "Siempre revisar el borde zeta.", priority=5
    )["path"]
    other = memory.remember(
        engine, "decision", "Decisión del borde zeta", "El borde zeta usa otro formato.", priority=4
    )["path"]

    _, full = memory.task_context(engine, "borde zeta", "fabrik", 2000)
    _, skipped = memory.task_context(engine, "borde zeta", "fabrik", 2000, skip={norm, other})

    assert {norm, other} <= {e["path"] for e in full}
    assert norm not in {e["path"] for e in skipped}
    assert other in {e["path"] for e in skipped}


def test_review_reports_memory_without_project(engine: Engine, vault: Path) -> None:
    rel = "memory/fabrik/decisions/no-project.md"
    (vault / rel).write_text(
        "---\ntype: decision\nstatus: active\ncreated: 2026-10-01\n---\n# No project\n"
    )
    engine.index.refresh()
    out = memory.review(engine, None, None, 50)
    assert rel in {x["path"] for x in out["invalid_frontmatter"]}


def test_welcome_keeps_old_norm_and_lists_upcoming_reminders(engine: Engine, vault: Path) -> None:
    norm = memory.remember(engine, "constraint", "Norma vieja", "Siempre validar.", priority=5)[
        "path"
    ]
    nf = NoteFile(engine, norm)
    nf.set_fields({"created": dt.date(2025, 1, 1)})
    nf.save()
    for i in range(12):
        memory.remember(engine, "insight", f"Reciente {i} {'y' * i}", f"Cuerpo {i}.", force=True)
    soon = (today() + dt.timedelta(days=3)).isoformat()
    far = (today() + dt.timedelta(days=30)).isoformat()
    near = memory.remember(engine, "reminder", "Pronto", "x", due=soon)["path"]
    memory.remember(engine, "reminder", "Lejano", "x", due=far)
    text, entries = memory.welcome(engine, "fabrik")
    lines = text.splitlines()
    assert lines.index("Normas:") < lines.index("Memorias:")
    assert any(e["path"] == norm and e["kind"] == "norm" for e in entries)
    assert "Vencen pronto (7 días):" in lines
    assert near in {e["path"] for e in entries}
    assert "Lejano" not in text
    memory.revise(engine, near, "dismiss")
    assert _fm(vault / near)["status"] == "archived"
    assert "Pronto" not in memory.welcome(engine, "fabrik")[0]
    with pytest.raises(EpistemeError) as err:
        memory.revise(engine, norm, "dismiss")
    assert err.value.code == "invalid_argument"


@pytest.mark.skipif(sys.platform == "win32", reason="time.tzset is POSIX only")
def test_today_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.delenv("EPISTEME_TODAY", raising=False)
    monkeypatch.setenv("TZ", "Etc/GMT+12")
    time.tzset()
    try:
        expected = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=12)).date()
        assert today() == expected
    finally:
        monkeypatch.undo()
        time.tzset()


@pytest.mark.parametrize(
    ("title", "project", "type", "expected"),
    [
        (
            "Revisar qué guarda y restaura el checkpoint de episteme al cambiar de sesión",
            "fabrik", "decision", "revisar-guarda-restaura-checkpoint",
        ),
        (
            "Driver headless de claude -p: trampas halladas al montar el benchmark",
            "fabrik", "lesson", "driver-headless-claude-trampas-halladas",
        ),
        (
            "Benchmark fabrik 0.4.0: episteme vs nativo, diseño, ubicación y métricas "
            "(proyecto fabrik)",
            "fabrik", "decision", "benchmark-0-4-0-episteme-nativo-diseno",
        ),
        (
            "Migración a índices únicos en Postgres",
            "fabrik", "decision", "migracion-indices-unicos-postgres",
        ),
        ("uv", "fabrik", "decision", "uv"),
        ("Y de que", "fabrik", "decision", "y-de-que"),
        ("¿?", "fabrik", "decision", "note"),
        ("Serena usa ty 0.0.90", "fabrik", "lesson", "serena-usa-ty-0-0-90"),
        (
            "Decisión fabrik: lessons sobre episteme", "episteme", "lesson", "decision-fabrik",
        ),
    ],
)  # fmt: skip
def test_memory_slug(title: str, project: str, type: str, expected: str) -> None:
    slug = memory.memory_slug(title, project, type)
    assert slug == expected
    assert len(slug) <= 40 and len(slug.split("-")) <= 8


def test_memory_slug_never_cuts_a_word() -> None:
    title = "Internacionalizacion institucional extraordinariamente interdisciplinaria total"
    slug = memory.memory_slug(title, "x", "lesson")
    assert slug == "internacionalizacion-institucional"
    assert all(part in title.lower().split() for part in slug.split("-"))


def test_remember_collision_and_explicit_slug(engine: Engine, vault: Path) -> None:
    a = memory.remember(engine, "lesson", "Cosa uno", "Cuerpo alfa distinto.", force=True)
    b = memory.remember(engine, "lesson", "Cosa uno", "Cuerpo alfa distinto.", force=True)
    assert b["path"] == a["path"].replace(".md", "-2.md")
    c = memory.remember(engine, "lesson", "T1", "Texto uno zeta.", slug="mi-slug")
    d = memory.remember(engine, "lesson", "T2", "Texto dos omega.", slug="mi-slug")
    assert c["path"].endswith("/2026-10-19-mi-slug.md")
    assert d["path"].endswith("/2026-10-19-mi-slug-2.md")


@pytest.mark.parametrize(
    "slug", ["Mayúsculas", "con_guion_bajo", "--doble", "a" * 41, "2026-10-24-x", "a--b", ""]
)
def test_remember_invalid_slug(engine: Engine, slug: str) -> None:
    with pytest.raises(EpistemeError) as err:
        memory.remember(engine, "lesson", "T", "Cuerpo.", slug=slug)
    assert str(err.value).startswith("invalid_argument:")
