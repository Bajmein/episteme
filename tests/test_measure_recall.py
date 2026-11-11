"""scripts/measure_recall.py: stem and trigram recall on a vault."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from conftest import FIXTURES

SCRIPT = Path(__file__).parents[1] / "scripts/measure_recall.py"


def _script():
    spec = importlib.util.spec_from_file_location("measure_recall", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "v"
    (root / "memory").mkdir(parents=True)
    (root / "episteme.toml").write_text('[zones."memory"]\nmode = "memory"\n', encoding="utf-8")
    notes = {
        "a": "# Uso\n\nEl hook corre antes. Una regla simple.\n",
        "b": "# Otros\n\nVarios hooks activos. Muchas reglas listas.\n",
        "c": "# Campana\n\nEl marketing de la marca.\n",
        "d": "# Atajo\n\nEl mkt de siempre.\n",
    }
    for name, body in notes.items():
        (root / "memory" / f"{name}.md").write_text(body, encoding="utf-8")
    return root


def test_stem_and_trigram_join_variants(tmp_path: Path) -> None:
    m = _script()
    r = m.measure(_vault(tmp_path), "memory", ["hook", "regla", "mkt", "marketing"])
    t = r["terms"]
    both = {"memory/a.md", "memory/b.md"}
    assert t["regla"]["exact"] == {"memory/a.md"}
    assert t["regla"]["stem"] == both
    assert t["hook"]["exact"] == {"memory/a.md"}
    assert t["hook"]["trigram"] == both
    # Snowball keeps "hook" and "hooks" apart (English word), so stem misses what trigram finds.
    assert t["hook"]["stem"] == {"memory/a.md"}
    # Nothing links mkt with marketing.
    for key in ("exact", "prefix", "stem", "trigram"):
        assert t["mkt"][key] == {"memory/d.md"}
        assert t["marketing"][key] == {"memory/c.md"}


def test_read_only_on_fixture(tmp_path: Path, capsys) -> None:
    m = _script()
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURES / "vault", vault)
    assert m.main(["--vault", str(vault), "--top", "20"]) == 0
    out = capsys.readouterr().out
    assert "Familias de raíz" in out
    assert not (vault / ".index").exists()


def test_unknown_zone_fails(tmp_path: Path, capsys) -> None:
    m = _script()
    assert m.main(["--vault", str(_vault(tmp_path)), "--zone", "memroy"]) == 1
    assert "invalid_argument" in capsys.readouterr().err
