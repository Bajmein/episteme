"""scripts/measure_links.py: link graph between memories."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from conftest import FIXTURES

SCRIPT = Path(__file__).parents[1] / "scripts/measure_links.py"


def _script():
    spec = importlib.util.spec_from_file_location("measure_links", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _note(project: str, status: str, related: str, body: str) -> str:
    return (
        f"---\ntype: lesson\nproject: {project}\nstatus: {status}\n"
        f"related: [{related}]\n---\n# T\n\n{body}\n"
    )


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "v"
    (root / "memory" / "p").mkdir(parents=True)
    (root / "episteme.toml").write_text('[zones."memory"]\nmode = "memory"\n', encoding="utf-8")
    notes = {
        "a": _note("p", "active", '"[[b]]", "[[ghost]]"', "alfa beta gamma. Ver [[memory/p/d]]."),
        "b": _note("p", "active", "", "uno dos tres cuatro"),
        "c": _note("p", "active", '"[[memory/p/b.md]]"', "alfa beta gamma delta"),
        "d": _note("p", "active", "", "solitaria"),
        "e": _note("p", "active", "", "huerfana total"),
        "f": _note("p", "archived", '"[[a]]"', "archivada"),
    }
    for name, text in notes.items():
        (root / "memory" / "p" / f"{name}.md").write_text(text, encoding="utf-8")
    return root


def test_counts_and_neighbours(tmp_path: Path) -> None:
    m = _script()
    r = m.measure(_vault(tmp_path))
    assert r["active"] == 5
    assert r["kinds"]["related"] == 3
    assert r["kinds"]["body"] == 1
    # "ghost" does not resolve; the archived f is not measured.
    assert r["unresolved"]["related"] == 1
    assert r["with_related"] == 3  # a, b, c
    assert [o.rel for o in r["orphans"]] == ["memory/p/e.md"]
    assert dict(r["buckets"]) == {0: 2, 1: 2, 2: 1}
    assert r["scoped"] == 3
    assert len(r["pairs"]) == 2  # a-b and b-c, each once
    assert all(s < 0.2 for s, _a, _b in r["low"])


def test_unknown_project_fails(tmp_path: Path, capsys) -> None:
    m = _script()
    assert m.main(["--vault", str(_vault(tmp_path)), "--project", "otro"]) == 1
    assert "invalid_argument" in capsys.readouterr().err


def test_cross_project_and_archived_links(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)
    (root / "memory" / "q").mkdir()
    other = _note("q", "active", '"[[e]]"', "otra cosa")
    (root / "memory" / "q" / "g.md").write_text(other, encoding="utf-8")
    shared = _note("_shared", "active", "", "global")
    (root / "memory" / "q" / "h.md").write_text(shared, encoding="utf-8")
    (root / "memory" / "p" / "f.md").write_text(_note("p", "archived", '"[[d]]"', "x"), "utf-8")

    r = m.measure(root, project="p")

    # e is linked from the other project's g, so it is not an orphan; d from archived f.
    assert r["orphans"] == []
    # e has a related neighbour (g) but of another project: counted, not in scope.
    assert r["with_related"] == 4
    assert r["scoped"] == 3


def test_read_only_on_fixture(tmp_path: Path, capsys) -> None:
    m = _script()
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURES / "vault", vault)
    assert m.main(["--vault", str(vault), "--examples", "3"]) == 0
    out = capsys.readouterr().out
    assert "Medición del grafo de enlaces" in out
    assert "Huérfanas" in out
    assert not (vault / ".index").exists()


def test_unknown_zone_fails(tmp_path: Path, capsys) -> None:
    m = _script()
    assert m.main(["--vault", str(_vault(tmp_path)), "--zone", "memroy"]) == 1
    assert "invalid_argument" in capsys.readouterr().err
