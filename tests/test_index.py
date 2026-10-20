"""index.py: FTS, link resolution, incremental reindex and rebuild (case 14 at module level)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from episteme.index import Index, query_terms
from episteme.vault import Vault


def _index(vault: Path) -> Index:
    ix = Index(Vault(vault))
    ix.refresh()
    return ix


def test_invalid_frontmatter_indexed(vault: Path) -> None:
    ix = _index(vault)
    row = ix.note("docs/claude-code/README.index.md")
    assert row is not None
    assert row["fm_valid"] == 0 and row["fm_error"]
    hits, _ = ix.search("Mapa Rápido por Objetivos")
    assert hits[0].path == "docs/claude-code/README.index.md"


def test_unindexable_frontmatter_does_not_break_reindex(vault: Path) -> None:
    (vault / "plans").mkdir()
    (vault / "plans" / "bad-date.md").write_text("---\ncreated: 2026-02-30\n---\n# Bad date\n")
    (vault / "plans" / "date-keys.md").write_text(
        "---\nhistory:\n  2026-10-01: started\n---\n# Dated keys\n\nzorbulax\n"
    )
    ix = _index(vault)
    bad = ix.note("plans/bad-date.md")
    assert bad is not None and bad["fm_valid"] == 0
    assert ix.props("plans/date-keys.md")["history"] == {"2026-10-01": "started"}
    hits, _ = ix.search("zorbulax")
    assert hits[0].path == "plans/date-keys.md"


def test_resolver_sees_notes_indexed_by_another_process(vault: Path) -> None:
    a, b = _index(vault), _index(vault)
    assert b.resolver().resolve_quiet("nota-nueva") is None
    (vault / "plans").mkdir()
    (vault / "plans" / "nota-nueva.md").write_text("# Nueva\n")
    a.refresh()
    b.refresh()
    assert b.resolver().resolve_quiet("nota-nueva") == "plans/nota-nueva.md"


def test_backlinks_and_comment_links(vault: Path) -> None:
    ix = _index(vault)
    sources = {r["src"] for r in ix.backlinks("docs/claude-code/hooks-reference.md")}
    assert "docs/claude-code/README.index.md" in sources
    # the %% nav %% block links count
    out = {r["dst_path"] for r in ix.outgoing("docs/claude-code/hooks-reference.md")}
    assert "docs/claude-code/routines.md" in out
    broken = ix.conn.execute(
        "select count(*) from links where dst_path is null or heading_missing = 1"
    ).fetchone()[0]
    assert broken == 0


def test_search_diacritics_and_syntax_escaping(vault: Path) -> None:
    ix = _index(vault)
    hits, total = ix.search("configuracion")
    assert total > 0 and "**" in hits[0].snippet
    for q in ['NEAR(a b)', 'foo AND OR "', "col:umn", "*", "^x", "(-)"]:
        ix.search(q)  # never FTS5 syntax errors
    assert query_terms('a "b c" -d') == [["a"], ["b", "c"], ["d"]]


def test_incremental_reindex(vault: Path) -> None:
    ix = _index(vault)
    assert ix.refresh() is False
    note = vault / "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md"
    note.write_text(note.read_text() + "\nzanahoria\n")
    (vault / "plans").mkdir()
    (vault / "plans/new.md").write_text("# New\n\n[[hooks-reference]] zanahoria\n")
    os.unlink(vault / "memory/_shared/perfil.md")
    assert ix.refresh() is True
    hits, total = ix.search("zanahoria")
    assert total == 2
    assert ix.note("memory/_shared/perfil.md") is None
    sources = {r["src"] for r in ix.backlinks("docs/claude-code/hooks-reference.md")}
    assert "plans/new.md" in sources


def test_new_note_makes_link_ambiguous(vault: Path) -> None:
    ix = _index(vault)
    (vault / "plans").mkdir()
    (vault / "plans/a.md").write_text("[[routines]]\n")
    ix.refresh()
    assert ix.outgoing("plans/a.md")[0]["dst_path"] == "docs/claude-code/routines.md"
    (vault / "plans/routines.md").write_text("# other\n")
    ix.refresh()
    assert ix.outgoing("plans/a.md")[0]["dst_path"] is None


def test_corrupt_index_is_rebuilt(vault: Path) -> None:
    ix = _index(vault)
    ix.close()
    db = vault / ".index/index.db"
    for suffix in ("-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    db.write_bytes(b"this is not a database" * 100)
    ix = _index(vault)
    assert ix.note("docs/claude-code/hooks-reference.md") is not None


def test_missing_index_is_rebuilt(vault: Path) -> None:
    _index(vault).close()
    for p in (vault / ".index").iterdir():
        p.unlink()
    ix = _index(vault)
    assert ix.note("memory/_shared/perfil.md") is not None


def test_lock_at_open_is_retried_not_treated_as_corruption(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ix = _index(vault)
    assert ix.mark_welcomed("s1")
    ix.close()
    calls = {"n": 0}
    real_connect = Index._connect

    def flaky_connect(self: Index) -> sqlite3.Connection:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(self)

    monkeypatch.setattr(Index, "_connect", flaky_connect)
    ix = Index(Vault(vault))
    assert calls["n"] == 2
    # the existing index (and what other processes wrote to it) survives
    assert not ix.mark_welcomed("s1")
