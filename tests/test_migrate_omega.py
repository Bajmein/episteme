"""scripts/migrate_omega.py against tests/fixtures/omega-export."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml
from conftest import FIXTURES

SCRIPT = Path(__file__).parents[1] / "scripts/migrate_omega.py"
EXPORT = FIXTURES / "omega-export/omega-memories"
MAP = "/home/ana/src/fabrik=fabrik"


def _run(
    vault: Path, *extra: str, mapped: bool = True, export: Path = EXPORT
) -> subprocess.CompletedProcess[str]:
    args = ["--map-project", MAP] if mapped else []
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--export", str(export), "--vault", str(vault),
         "--project", "fabrik", *args, *extra],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "EPISTEME_TODAY": "2026-10-19"},
    )  # fmt: skip


def _memories(vault: Path) -> set[Path]:
    return set((vault / "memory").rglob("*.md"))


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


def _summary(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout.splitlines()[-1].split(": ", 1)[1]


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table memories (id integer primary key autoincrement, node_id text unique,"
        " content text, metadata text, created_at text, event_type text, project text,"
        " priority integer, status text)"
    )
    rows = [
        ("mem-0a1b2c3d4e5f", "x", {}, "decision", "fabrik", 5, "active"),
        ("mem-1b2c3d4e5f60", "x", {}, "lesson_learned", "fabrik", 4, "active"),
        ("mem-4e5f60718293", "x", {}, "session_summary", "fabrik", 2, "active"),
        (
            "mem-aaaaaaaaaaaa",
            "fabrik (19-10-2026): revisar la PR de explore antes de cerrar.",
            {"reminder_status": "pending", "remind_at": "2026-11-02T10:00:00+00:00",
             "context": "Ver docs/flujo.md.", "tags": ["pieza:explore", "/docs/flujo.md"]},
            "reminder", "fabrik", 5, "active",
        ),
        (
            "mem-bbbbbbbbbbbb", "fabrik: recordatorio descartado.",
            {"reminder_status": "dismissed", "remind_at": "2026-10-20T10:00:00+00:00"},
            "reminder", "fabrik", 3, "active",
        ),
        (
            "mem-cccccccccccc", "otro: recordatorio de otro proyecto.",
            {"reminder_status": "pending", "remind_at": "2026-11-03T10:00:00+00:00"},
            "reminder", "otro", 3, "active",
        ),
    ]  # fmt: skip
    for node_id, content, meta, event, project, priority, status in rows:
        conn.execute(
            "insert into memories (node_id, content, metadata, created_at, event_type, project,"
            " priority, status) values (?, ?, ?, '2026-10-19T08:00:00+00:00', ?, ?, ?, ?)",
            (node_id, content, json.dumps(meta), event, project, priority, status),
        )
    conn.commit()
    conn.close()


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
    assert folders == ["decisions", "errors", "lessons", "sessions"]
    lines = proc.stdout.splitlines()
    assert sum(line.startswith("+ ") for line in lines) == 4
    assert lines[-1].startswith("Resumen:")

    decision = next(p for p in new if p.parent.name == "decisions")
    fm = _fm(decision)
    assert fm["type"] == "decision" and fm["priority"] == 4  # no DB: the default
    assert str(fm["created"]) == "2026-10-05"
    assert fm["tags"] == ["dominio/auth", "pieza/serena_guard"]
    assert fm["files"] == [".claude/hooks/serena_guard.py"]  # the project root tag is dropped
    assert fm["source"] == "omega:mem-0a1b2c3d4e5f"
    assert "helpful" not in fm or fm["helpful"] == 0  # never access_count (3 here)
    body = decision.read_text()
    assert "# serena_guard deja pasar `cd $VAR`" in body  # «fabrik (fecha):» removed
    lesson = next(p for p in new if p.parent.name == "lessons")
    assert fm["related"] == [f"[[{lesson.stem}]]"]
    lfm = _fm(lesson)
    assert lfm["source"] == "omega:mem-1b2c3d4e5f60"
    assert lfm["tags"] == ["pieza/omega"] and lfm["files"] == [".claude/settings.json"]
    assert lfm["related"] == [f"[[{decision.stem}]]"]
    assert "# el watchdog de OMEGA" in lesson.read_text()  # «Lesson:» removed
    assert lfm["created"].isoformat() == "2026-10-14"  # the newer duplicate stays
    error = next(p for p in new if p.parent.name == "errors")
    assert "# codemap.py check daba" in error.read_text()  # «Assistant fix:» removed
    assert _fm(error)["files"] == ["plugins/fabrik/skills/explore/scripts/codemap.py"]
    title = decision.read_text().split("\n# ", 1)[1].split("\n", 1)[0]
    assert len(title) <= 80
    session = next(p for p in new if p.parent.name == "sessions")
    assert _fm(session)["kind"] == "episodic"

    out = proc.stdout
    assert "project_status (descartada)" in out
    assert "(edit pattern)" in out and "(captura automática)" in out
    assert "(texto del harness) mem-a0b1c2d3e4f5" in out
    assert "duplicada de mem-1b2c3d4e5f60" in out
    assert "(proyecto vigilia)" in out
    assert not any(p.parent.name == "insights" for p in new)
    assert not any("reminder" in line for line in lines if line.startswith("+ "))

    texts = {p: p.read_text() for p in _memories(vault)}
    again = _run(vault)
    assert again.returncode == 0, again.stderr
    assert "+ " not in again.stdout
    assert again.stdout.count("(ya existe)") == 4
    assert {p: p.read_text() for p in _memories(vault)} == texts


def test_unmapped_project_is_skipped(vault: Path) -> None:
    before = _memories(vault)
    proc = _run(vault, mapped=False)
    assert proc.returncode == 0, proc.stderr
    assert "(proyecto /home/ana/src/fabrik)" in proc.stdout
    assert {p.parent.name for p in _memories(vault) - before} == {
        "decisions",
        "lessons",
        "sessions",
    }


def test_omega_db_priority_and_reminders(vault: Path, tmp_path: Path) -> None:
    db = tmp_path / "omega.db"
    _make_db(db)
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    before = _memories(vault)

    dry = _run(vault, "--omega-db", str(db), "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert _memories(vault) == before
    real = _run(vault, "--omega-db", str(db))
    assert real.returncode == 0, real.stderr
    assert _summary(dry) == _summary(real)  # dry-run counts what the real run does
    assert "reminder 1" in _summary(real)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest  # OMEGA is only read

    new = _memories(vault) - before
    by_type = {_fm(p)["type"]: _fm(p) for p in new}
    assert by_type["decision"]["priority"] == 5
    assert by_type["lesson"]["priority"] == 4
    assert by_type["session"]["priority"] == 2
    reminder = next(p for p in new if p.parent.name == "reminders")
    fm = _fm(reminder)
    assert fm["priority"] == 5 and str(fm["due"]) == "2026-11-02"
    assert fm["source"] == "omega:mem-aaaaaaaaaaaa"
    assert fm["tags"] == ["pieza/explore"] and fm["files"] == ["docs/flujo.md"]
    text = reminder.read_text()
    assert "# revisar la PR de explore" in text and "Ver docs/flujo.md." in text
    assert len([p for p in new if p.parent.name == "reminders"]) == 1  # dismissed/other: no

    again = _run(vault, "--omega-db", str(db))
    assert "+ " not in again.stdout and "existente:reminder 1" in again.stdout
    assert _memories(vault) - before == new


def test_bad_vault(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode != 0 and "episteme.toml" in proc.stderr


def test_bad_db_and_map(vault: Path, tmp_path: Path) -> None:
    proc = _run(vault, "--omega-db", str(tmp_path / "nope.db"))
    assert proc.returncode == 2 and "omega.db" in proc.stderr
    proc = _run(vault, "--map-project", "sin-igual")
    assert proc.returncode == 2 and "OLD=NEW" in proc.stderr


def _script():
    spec = importlib.util.spec_from_file_location("migrate_omega", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up there (Python < 3.14)
    spec.loader.exec_module(module)
    return module


def test_windows_paths() -> None:
    m = _script()
    root = r"C:\Users\Ana\gam"
    tags = ["dominio:auth", r"c:\users\ana\gam\src\app.py", r"C:\Users\Ana\gam", r"D:\x\y.py"]
    assert m.split_tags(tags, (root,)) == (["dominio/auth"], ["src/app.py", "x/y.py"])
    mapping = {m.path_key(r"c:\users\ana\gam"): "gam"}
    assert m._project_for(r"C:\Users\Ana\gam\\", "otro", mapping) == "gam"
    assert m._project_for("/home/ana/gam/", "otro", {m.path_key("/home/ana/gam"): "gam"}) == "gam"


def test_title_label_is_dropped() -> None:
    m = _script()

    def title(text: str) -> str:
        note = m.OmegaMemory(id="mem-x", omega_type="decision", tags=[], created=None, text=text)
        return note.title

    assert title("[MEMORIA GI - feedback] Feedback: claridad") == "Feedback: claridad"
    assert title("[[nota]] sigue igual") == "[[nota]] sigue igual"
    assert title("[guía](https://x.y) sigue igual") == "[guía](https://x.y) sigue igual"
    assert title("[solo etiqueta]") == "[solo etiqueta]"


def test_unassigned_and_skipped_projects(vault: Path, tmp_path: Path) -> None:
    export = tmp_path / "export"
    shutil.copytree(EXPORT, export)
    notes = {
        "mem-dddddddddddd": "",
        "mem-eeeeeeeeeeee": "project: C:\\Users\\Ana\\gam\n",
    }
    for node_id, project in notes.items():
        (export / "decisions" / f"{node_id}.md").write_text(
            f"---\nid: {node_id}\ntype: decision\ntags: []\ncreated: 2026-10-06\n{project}---\n\n"
            f"Decisión {node_id} sobre la arquitectura del cliente con colas.\n",
            encoding="utf-8",
        )
    proc = _run(vault, "--dry-run", export=export)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert "Proyectos omitidos: vigilia (1), C:\\Users\\Ana\\gam (1)." in proc.stdout
    assert "Sin proyecto en OMEGA: 1, migradas a fabrik." in proc.stdout
    assert lines[-1].startswith("Resumen (dry-run):")

    proc = _run(vault, "--dry-run", "--unassigned", "skip", export=export)
    assert "(sin proyecto) mem-dddddddddddd" in proc.stdout
    assert "omitida:sin-proyecto 1" in _summary(proc)
    assert "Sin proyecto en OMEGA" not in proc.stdout

    proc = _run(vault, "--dry-run", "--map-project", "c:\\users\\ana\\gam=fabrik", export=export)
    assert "C:\\Users\\Ana\\gam (1)" not in proc.stdout
