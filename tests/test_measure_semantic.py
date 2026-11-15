"""scripts/measure_semantic.py: embeddings vs keyword search, with a fake provider."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/measure_semantic.py"


def _script():
    spec = importlib.util.spec_from_file_location("measure_semantic", SCRIPT)
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
        "a": "# Perro\n\nEl perro ladra en el jardin.\n",
        "b": "# Can\n\nEl can ladra fuerte por la noche.\n",
        "c": "# Factura\n\nPagar la factura del banco.\n",
    }
    for name, body in notes.items():
        (root / "memory" / f"{name}.md").write_text(body, encoding="utf-8")
    return root


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Dog-ish texts (perro, can, mascota) point at one axis, the rest at another."""
    out = []
    for text in texts:
        low = text.lower()
        dog = any(w in low for w in ("perro", "can\n", "can ", "mascota"))
        out.append([1.0, 0.0] if dog else [0.0, 1.0])
    return out


def test_semantic_neighbours_add_what_keywords_miss(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)

    result = m.measure(root, _fake_embed, queries=["mascota"])

    row = result["rows"][0]
    assert row["keyword"] == []
    assert {r for r, _ in row["new"]} == {"memory/a.md", "memory/b.md"}
    assert [(a, b) for a, b, _s, _t in result["pairs"]] == [("memory/a.md", "memory/b.md")]


def test_render_summarises_queries_pairs_and_latency(tmp_path: Path) -> None:
    m = _script()
    result = m.measure(_vault(tmp_path), _fake_embed, queries=["mascota", "factura"])

    out = m.render(result, 5)

    assert "1 de 2" in out
    assert "## Pares parecidos" in out
    assert "Primera llamada" in out


def test_activity_queries_are_read_without_writing(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)
    db = root / ".index" / "activity.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute(
        "create table calls (id integer primary key, at text, tool text, args text, ok integer)"
    )
    rows = [
        ("2999-01-01T00:00:00", "search", json.dumps({"query": "mascota"}), 1),
        ("2999-01-01T00:00:01", "context", json.dumps({"task": "arreglar factura"}), 1),
        ("2000-01-01T00:00:00", "search", json.dumps({"query": "vieja"}), 1),
    ]
    conn.executemany("insert into calls (at, tool, args, ok) values (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()

    found = m.load_activity_queries(root, 30)

    assert found == ["mascota", "arreglar factura"]


@pytest.mark.parametrize(
    "url", ["http://example.com", "https://localhost:11434", "http://10.0.0.1"]
)
def test_non_local_url_is_rejected(url: str) -> None:
    m = _script()

    with pytest.raises(m.EpistemeError, match="invalid_argument"):
        m.make_embedder(url, "bge-m3")


def test_ollama_down_is_a_clean_error_with_exit_code_1(tmp_path: Path, capsys) -> None:
    m = _script()
    root = _vault(tmp_path)

    code = m.main(["--vault", str(root), "--url", "http://127.0.0.1:9", "--days", "0"])

    err = capsys.readouterr().err
    assert code == 1
    assert "ollama serve" in err
    assert "ollama pull bge-m3" in err


def test_main_rejects_non_local_url(tmp_path: Path, capsys) -> None:
    m = _script()

    code = m.main(["--vault", str(_vault(tmp_path)), "--url", "http://example.com"])

    assert code == 1
    assert capsys.readouterr().err.startswith("invalid_argument:")
