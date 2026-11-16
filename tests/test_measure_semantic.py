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


def test_keyword_side_falls_back_to_any_word_like_search(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)

    result = m.measure(root, _fake_embed, queries=["perro factura", "perro ladra"])

    any_row, all_row = result["rows"]
    assert any_row["keyword"] == ["memory/a.md", "memory/c.md"]
    assert {r for r, _ in any_row["new"]} == {"memory/b.md"}
    assert all_row["keyword"] == ["memory/a.md"]


def test_new_neighbours_are_split_by_strong_score(tmp_path: Path) -> None:
    m = _script()

    def embed(texts: list[str]) -> list[list[float]]:
        base = _fake_embed(texts)
        return [[0.6, 0.8] if t == "zzz" else v for t, v in zip(texts, base, strict=True)]

    result = m.measure(_vault(tmp_path), embed, queries=["zzz"])

    row = result["rows"][0]
    assert {r for r, _ in row["new"]} == {"memory/a.md", "memory/b.md", "memory/c.md"}
    assert [r for r, _ in row["strong"]] == ["memory/c.md"]
    assert "1 claros, 2 bajo 0.65" in m.render(result, 5)


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


def _memory_vault(tmp_path: Path) -> Path:
    root = tmp_path / "m"
    (root / "memory").mkdir(parents=True)
    (root / "episteme.toml").write_text('[zones."memory"]\nmode = "memory"\n', encoding="utf-8")
    notes = {
        "orphan": ("decision", "p", "active", "tags: [dominio/x, tema/y]", "# Perro\n\nEl perro."),
        "tagged": ("lesson", "p", "active", "tags: [dominio/x, tema/y]\nrelated: ['[[bill]]']",
                   "# Can\n\nEl can ladra."),
        "bill": ("decision", "p", "active", "tags: []", "# Factura\n\nPagar la factura."),
        "other": ("decision", "q", "active", "tags: []", "# Mascota\n\nLa mascota de q."),
        "old": ("decision", "p", "archived", "tags: []", "# Perro viejo\n\nEl perro viejo."),
        "log": ("session", "p", "active", "tags: []", "# Sesion\n\nEl perro en sesion."),
        "common": ("insight", "_shared", "active", "tags: []", "# Mascota comun\n\nLa mascota."),
    }
    for name, (kind, project, status, extra, body) in notes.items():
        fm = f"---\ntype: {kind}\nproject: {project}\nstatus: {status}\n{extra}\n---\n"
        (root / "memory" / f"{name}.md").write_text(fm + body + "\n", encoding="utf-8")
    return root


def test_orphans_get_semantic_candidates_of_their_project_or_shared(tmp_path: Path) -> None:
    m = _script()
    root = _memory_vault(tmp_path)

    result = m.measure(root, _fake_embed)

    by_path = {o["path"]: o for o in result["orphans"]}
    assert set(by_path) == {"memory/orphan.md", "memory/other.md", "memory/common.md"}
    found = {c["path"]: c for c in by_path["memory/orphan.md"]["candidates"]}
    assert set(found) == {"memory/tagged.md", "memory/common.md"}
    assert found["memory/tagged.md"]["reason"] == "shares tags dominio/x, tema/y"
    assert found["memory/common.md"]["reason"] is None
    (only,) = by_path["memory/other.md"]["candidates"]
    assert (only["path"], only["title"], only["score"]) == (
        "memory/common.md", "Mascota comun", 1.0
    )
    assert by_path["memory/common.md"]["candidates"] == []
    assert result["orphans"][-1]["path"] == "memory/common.md"


def test_orphan_candidates_respect_the_link_score(tmp_path: Path) -> None:
    m = _script()
    root = _memory_vault(tmp_path)

    result = m.measure(root, _fake_embed, opts=m.Options(link_score=1.5))

    assert all(o["candidates"] == [] for o in result["orphans"])


def test_render_reports_orphans_with_candidates_review_does_not_offer(tmp_path: Path) -> None:
    m = _script()
    root = _memory_vault(tmp_path)

    report = m.render(m.measure(root, _fake_embed), examples=5)

    assert "## Huérfanas y candidatas por significado" in report
    assert "- Huérfanas: 3" in report
    assert "- Con alguna candidata: 2" in report
    assert "- Con alguna candidata que review no ofrece: 2" in report
    assert "Mascota comun (memory/common.md)" in report
