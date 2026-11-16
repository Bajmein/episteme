"""scripts/measure_index.py: indexer timings on a copy of the vault."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from conftest import FIXTURES

SCRIPT = Path(__file__).parents[1] / "scripts/measure_index.py"


def _script():
    spec = importlib.util.spec_from_file_location("measure_index", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_measure_times_every_step_without_touching_the_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURES / "vault", vault)
    before = _snapshot(vault)
    mod = _script()

    r = mod.measure(vault, runs=2)

    assert r.notes > 10 and r.db_bytes > 0 and r.runs == 2
    assert r.full_ms >= 0 and r.noop_ms >= 0
    assert set(r.incremental_ms) == {1, 10}
    assert all(ms >= 0 for ms in r.incremental_ms.values())
    assert not (vault / ".index").exists()
    assert _snapshot(vault) == before
    text = mod.render(r)
    assert "refresh() sin cambios" in text and "Indexado completo" in text


def test_main_fails_without_a_vault(tmp_path: Path, capsys) -> None:
    mod = _script()

    code = mod.main(["--vault", str(tmp_path / "nowhere")])

    assert code == 1
    assert capsys.readouterr().err.startswith("not_found:")
