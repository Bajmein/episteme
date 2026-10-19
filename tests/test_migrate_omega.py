"""scripts/migrate_omega.py against tests/fixtures/omega-export."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from conftest import FIXTURES

SCRIPT = Path(__file__).parents[1] / "scripts/migrate_omega.py"
EXPORT = FIXTURES / "omega-export/omega-memories"


def _run(vault: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--export", str(EXPORT), "--vault", str(vault),
         "--project", "fabrik", *extra],
        capture_output=True, text=True, timeout=120, env={"EPISTEME_TODAY": "2026-10-19"},
    )  # fmt: skip


def _memories(vault: Path) -> set[Path]:
    return set((vault / "memory").rglob("*.md"))


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


def test_dry_run_writes_nothing(vault: Path) -> None:
    before = _memories(vault)
    proc = _run(vault, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "+ decision → memory/fabrik/decisions/2026-10-05-" in proc.stdout
    assert "- checkpoint (descartada)" in proc.stdout
    assert "Resumen (dry-run)" in proc.stdout
    assert _memories(vault) == before


def test_migration_and_idempotency(vault: Path) -> None:
    before = _memories(vault)
    proc = _run(vault)
    assert proc.returncode == 0, proc.stderr
    new = _memories(vault) - before
    folders = sorted(p.parent.name for p in new)
    assert folders == ["decisions", "insights", "lessons", "sessions"]
    lines = proc.stdout.splitlines()
    assert sum(line.startswith("+ ") for line in lines) == 4
    assert lines[-1].startswith("Resumen:")

    decision = next(p for p in new if p.parent.name == "decisions")
    fm = _fm(decision)
    assert fm["type"] == "decision" and fm["priority"] == 4
    assert str(fm["created"]) == "2026-10-05"
    assert fm["tags"] == ["dominio/auth", "pieza/serena_guard"]
    assert fm["helpful"] == 3
    lesson = next(p for p in new if p.parent.name == "lessons")
    assert fm["related"] == [f"[[{lesson.stem}]]"]
    lfm = _fm(lesson)
    assert lfm["source"] == "session 00000000-0000-4000-8000-000000000001"
    assert lfm["tags"] == ["pieza/omega"]
    assert lfm["related"] == [f"[[{decision.stem}]]"]
    title = decision.read_text().split("\n# ", 1)[1].split("\n", 1)[0]
    assert len(title) <= 80
    session = next(p for p in new if p.parent.name == "sessions")
    assert _fm(session)["kind"] == "episodic"
    assert "tags" not in _fm(next(p for p in new if p.parent.name == "insights"))

    texts = {p: p.read_text() for p in _memories(vault)}
    again = _run(vault)
    assert again.returncode == 0, again.stderr
    assert "+ " not in again.stdout
    assert again.stdout.count("(ya existe)") == 4
    assert {p: p.read_text() for p in _memories(vault)} == texts


def test_bad_vault(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode != 0 and "episteme.toml" in proc.stderr
