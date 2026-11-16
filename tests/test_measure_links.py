"""scripts/measure_links.py: link graph between memories."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
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


def _migrated(root: Path, *names: str) -> None:
    for name in names:
        path = root / "memory" / "p" / f"{name}.md"
        text = path.read_text(encoding="utf-8").replace("---\n", "---\nsource: omega:1\n", 1)
        path.write_text(text, encoding="utf-8")


def test_every_wikilink_counts_in_both_directions(tmp_path: Path) -> None:
    m = _script()

    reach = m.measure(_vault(tmp_path))["reach"]

    # a, b and c by related; d only through the body link of a.
    assert reach["with_any"] == 4
    # b and d are only linked to: a forward-only walk never reaches anything from them.
    assert reach["backlink_gain"] == 2
    assert reach["backlink_only"] == 2


def test_related_pairs_are_split_by_origin(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)
    _migrated(root, "a", "b")

    origins = m.measure(root)["origins"]

    assert origins["omega"]["pairs"] == 1  # a-b: both ends came from OMEGA
    assert origins["nativo"]["pairs"] == 1  # b-c


def test_baseline_compares_every_pair_of_the_same_project(tmp_path: Path) -> None:
    m = _script()

    r = m.measure(_vault(tmp_path))

    assert r["baseline"]["pairs"] == 10  # 5 active memories of one project
    assert r["baseline"]["low"] == 9  # only a and c share vocabulary
    assert r["linked"]["pairs"] == 2
    assert "Línea base" in m.render(r, 3)


def _activity_db(root: Path, rows: list[tuple]) -> None:
    db = root / ".index" / "activity.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute(
        "create table calls (id integer primary key, at text, pid integer, tool text, "
        "args text, paths text, ok integer)"
    )
    conn.executemany(
        "insert into calls (at, pid, tool, args, paths, ok) values (?, ?, ?, ?, ?, 1)",
        [("2999-01-01T00:00:00", pid, tool, json.dumps(args), json.dumps(paths))
         for pid, tool, args, paths in rows],
    )  # fmt: skip
    conn.commit()
    conn.close()


def _read(pid: int, name: str) -> tuple:
    path = f"memory/p/{name}.md"
    return (pid, "read", {"note": path}, [path])


def test_reads_after_a_search_are_matched_against_the_graph(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)
    (root / "memory" / "p" / "z.md").write_text(_note("p", "active", "", "suelta"), "utf-8")
    rows = [
        _read(1, "a"),  # before any search: not counted
        (1, "context", {"mode": "task"}, ["memory/p/e.md"]),
        (1, "search", {"query": "delta"}, ["memory/p/c.md"]),
        (1, "search", {"query": "alfa"}, ["memory/p/a.md"]),
        _read(1, "a"),  # returned by the search
        _read(1, "b"),  # a links to b
        _read(1, "f"),  # only f links to a
        _read(1, "c"),  # returned by the search before
        _read(1, "e"),  # delivered by context
        _read(1, "z"),  # nothing in the log explains it
        _read(2, "b"),  # another process, no search
    ]
    _activity_db(root, rows)

    r = m.measure(root)

    activity = r["activity"]
    assert activity["searches"] == 2
    assert dict(activity["reads"]) == {
        "returned": 1, "forward": 1, "backlink": 1, "earlier": 1, "delivered": 1, "other": 1,
    }  # fmt: skip
    assert ("backlink", "memory/p/f.md") in activity["examples"]
    assert "solo por backlink: 1" in m.render(r, 3)


def test_no_activity_log_is_reported_not_an_error(tmp_path: Path) -> None:
    m = _script()

    r = m.measure(_vault(tmp_path))

    assert r["activity"] is None
    assert "sin registro de actividad" in m.render(r, 3)
