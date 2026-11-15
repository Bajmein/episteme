"""prompting.review_notice: the one-line maintenance notice built from review totals."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from episteme import memory, prompting
from episteme.engine import Engine


@pytest.fixture
def engine(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-19")
    eng = Engine(vault, "fabrik")
    eng.index.refresh()
    return eng


def _add_pending(engine: Engine) -> None:
    folder = engine.vault.root / "memory" / "fabrik" / "lessons"
    folder.mkdir(parents=True, exist_ok=True)
    for name, extra, created, body in (
        ("2026-09-01-expiring.md", "valid_until: 2026-10-01\n", "2026-09-01", "Zorblax cache"),
        ("2026-01-05-old.md", "", "2026-01-05", "Quuxwomble pipeline"),
    ):
        (folder / name).write_text(
            f"---\ntype: lesson\nkind: semantic\nproject: fabrik\npriority: 3\n"
            f"status: active\ncreated: {created}\n{extra}---\n# {name[:-3]}\n\n{body}\n",
            encoding="utf-8",
            newline="",
        )
    engine.index.refresh()


def test_notice_matches_review_totals(engine: Engine) -> None:
    _add_pending(engine)
    totals = memory.review(engine, None, "fabrik", 1, "memory")["totals"]
    order = [
        ("expired", "vencidas"),
        ("stale", "viejas"),
        ("similar", "grupos parecidos"),
        ("contradictions", "contradicciones posibles"),
        ("flagged", "marcadas"),
    ]
    parts = [f"{label} {totals[k]}" for k, label in order if totals[k] > 0]
    assert totals["expired"] > 0 and totals["stale"] > 0
    assert parts, "the fixture vault should have something pending"
    notice = prompting.review_notice(engine, "fabrik")
    assert notice == (
        f"episteme · mantención pendiente en fabrik: {' · '.join(parts)}. "
        'Corre review(project="fabrik", zone="memory") y propón qué archivar o unificar; '
        "no cambies nada sin aprobación. "
        "Con poco tiempo: solo los 3 casos más claros, las vencidas primero."
    )
    for k, label in order:
        assert (f"{label} " in notice) == (totals[k] > 0)


def test_notice_empty_when_nothing_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-19")
    root = tmp_path / "mini"
    (root / "memory" / "fabrik" / "lessons").mkdir(parents=True)
    (root / "episteme.toml").write_text(
        '[zones."memory"]\nmode = "memory"\n', encoding="utf-8", newline=""
    )
    shutil.copy(
        next(Path(__file__).parent.glob("fixtures/vault/memory/fabrik/constraints/*.md")),
        root / "memory" / "fabrik" / "lessons" / "2026-10-18-one.md",
    )
    note = root / "memory" / "fabrik" / "lessons" / "2026-10-18-one.md"
    text = note.read_text(encoding="utf-8").replace("created: 2026-10-10", "created: 2026-10-18")
    note.write_text(text, encoding="utf-8", newline="")
    eng = Engine(root, "fabrik")
    eng.index.refresh()
    totals = memory.review(eng, None, "fabrik", 1, "memory")["totals"]
    assert not any(totals[k] for k in ("expired", "stale", "similar", "contradictions", "flagged"))
    assert prompting.review_notice(eng, "fabrik") == ""
