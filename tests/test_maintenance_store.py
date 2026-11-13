from __future__ import annotations

import sqlite3

import pytest

from episteme.maintenance import Store


@pytest.fixture
def stores(tmp_path):
    made: list[Store] = []

    def make(root=None):
        s = Store(root or tmp_path)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def rows(tmp_path, sql):
    conn = sqlite3.connect(tmp_path / ".index" / "maintenance.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_nothing_created_before_claim(tmp_path, stores):
    s = stores()
    s.close()
    assert not (tmp_path / ".index").exists()


def test_first_claims_second_does_not(tmp_path, monkeypatch, stores):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    a, b = stores(), stores()
    assert a.claim("review", 1) == ""
    assert b.claim("review", 1) is None


def test_new_day_returns_previous_date(tmp_path, monkeypatch, stores):
    s = stores()
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    assert s.claim("review", 1) == ""
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-02")
    assert s.claim("review", 1) == "2026-11-01"
    assert s.claim("review", 1) is None


def test_every_three_days(tmp_path, monkeypatch, stores):
    s = stores()
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    assert s.claim("backup", 3) == ""
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-03")
    assert s.claim("backup", 3) is None
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-04")
    assert s.claim("backup", 3) == "2026-11-01"


def test_tasks_are_independent(tmp_path, monkeypatch, stores):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    s = stores()
    assert s.claim("a", 1) == ""
    assert s.claim("b", 1) == ""


def test_invalid_date_is_due(tmp_path, monkeypatch, stores):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    s = stores()
    assert s.claim("a", 1) == ""
    s.restore("a", "garbage")
    assert s.claim("a", 1) == "garbage"


def test_restore_previous_value(tmp_path, monkeypatch, stores):
    s = stores()
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    s.claim("review", 1)
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-02")
    previous = s.claim("review", 1)
    assert previous == "2026-11-01"
    s.restore("review", previous)
    assert rows(tmp_path, "select at from runs where task='review'") == [("2026-11-01",)]
    assert s.claim("review", 1) == "2026-11-01"


def test_restore_empty_deletes_row(tmp_path, monkeypatch, stores):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    s = stores()
    previous = s.claim("review", 1)
    assert previous == ""
    s.restore("review", previous)
    assert rows(tmp_path, "select * from runs") == []
    assert s.claim("review", 1) == ""


def test_log_rows(tmp_path, stores):
    s = stores()
    s.log("archive", ["memory/a.md", "memory/b.md"], "expired")
    s.log("backup", [])
    got = rows(tmp_path, "select task, path, detail from log order by id")
    assert got == [
        ("archive", "memory/a.md", "expired"),
        ("archive", "memory/b.md", "expired"),
        ("backup", "", ""),
    ]
    at = rows(tmp_path, "select at from log limit 1")[0][0]
    assert at.endswith("+00:00")


def test_claim_prunes_old_log(tmp_path, monkeypatch, stores):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    s = stores()
    s.log("x", ["new.md"])
    conn = sqlite3.connect(tmp_path / ".index" / "maintenance.db")
    conn.execute(
        "insert into log(at, task, path, detail) values ('2020-01-01T00:00:00', 'x', 'old.md', '')"
    )
    conn.commit()
    conn.close()
    s.claim("review", 1)
    assert rows(tmp_path, "select path from log") == [("new.md",)]


def test_impossible_path_never_raises(tmp_path, stores):
    root = tmp_path / "file"
    root.write_text("x", encoding="utf-8")
    s = stores(root)
    assert s.claim("review", 1) is None
    s.restore("review", "")
    s.log("review", ["a.md"])


def test_future_date_counts_as_due(tmp_path, monkeypatch, stores):
    s = stores()
    monkeypatch.setenv("EPISTEME_TODAY", "2030-01-01")
    assert s.claim("a", 1) == ""
    monkeypatch.setenv("EPISTEME_TODAY", "2026-11-01")
    assert s.claim("a", 1) == "2030-01-01"
