"""index.py: FTS, link resolution, incremental reindex and rebuild (case 14 at module level)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from episteme.index import Index, locate, query_terms
from episteme.index.schema import fts_schema
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
    for q in ["NEAR(a b)", 'foo AND OR "', "col:umn", "*", "^x", "(-)"]:
        ix.search(q)  # never FTS5 syntax errors
    assert query_terms('a "b c" -d') == [["a"], ["b", "c"], ["d"]]


def test_query_terms_split_hyphens_only() -> None:
    assert query_terms("save-clear") == [["save"], ["clear"]]
    assert query_terms("save-cl*") == [["save"], ["cl*"]]
    assert query_terms('"save-clear"') == [["save", "clear"]]
    assert query_terms("ROADMAP.md .fabrik/x") == [["roadmap", "md"], ["fabrik", "x"]]
    assert query_terms("fin-de-semana", drop_stopwords=True) == [["fin"], ["semana"]]


def test_incremental_reindex(vault: Path) -> None:
    ix = _index(vault)
    assert ix.refresh() is False
    note = vault / "memory/fabrik/lessons/2026-10-14-omega-rss-limit.md"
    note.write_text(note.read_text() + "\nzanahoria\n")
    (vault / "plans").mkdir()
    (vault / "plans/new.md").write_text("# New\n\n[[hooks-reference]] zanahoria\n")
    os.unlink(vault / "memory/_shared/perfil.md")
    assert ix.refresh() is True
    _, total = ix.search("zanahoria")
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
    (vault / "plans/sub").mkdir()
    (vault / "plans/sub/routines.md").write_text("# other\n")
    ix.refresh()
    assert ix.outgoing("plans/a.md")[0]["dst_path"] is None
    # A note with the same name in the link's own folder wins, as in Obsidian.
    (vault / "plans/routines.md").write_text("# same folder\n")
    ix.refresh()
    assert ix.outgoing("plans/a.md")[0]["dst_path"] == "plans/routines.md"


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


def _links(ix: Index) -> list[tuple[object, ...]]:
    rows = ix.conn.execute("select src, dst_raw, dst_path, heading_missing from links order by 1,2")
    return [tuple(r) for r in rows]


def test_incremental_relink_matches_full_rebuild(vault: Path) -> None:
    ix = _index(vault)
    plans = vault / "plans"
    plans.mkdir()
    (plans / "src.md").write_text("# Src\n\n[[target]] [[target#Sec]] [[alias-x]] [[plans/gone]]\n")
    ix.refresh()
    assert {r["dst_raw"]: r["dst_path"] for r in ix.outgoing("plans/src.md")}["target"] is None
    # create: the dangling links resolve
    (plans / "target.md").write_text("---\naliases: [alias-x]\n---\n# Target\n\n## Sec\n")
    (plans / "gone.md").write_text("# Gone\n")
    ix.refresh()
    out = {r["dst_raw"]: r for r in ix.outgoing("plans/src.md")}
    assert out["target"]["dst_path"] == "plans/target.md"
    assert out["alias-x"]["dst_path"] == "plans/target.md"
    assert out["plans/gone"]["dst_path"] == "plans/gone.md"
    assert out["target"]["heading_missing"] == 0
    # edit: a heading disappears, an alias is lost
    (plans / "target.md").write_text("# Target\n\n## Other\n")
    os.utime(plans / "target.md", ns=(1, 1))
    ix.refresh()
    rows = [r for r in ix.outgoing("plans/src.md") if r["dst_raw"] in ("target", "alias-x")]
    by = {(r["dst_raw"], r["heading"]): r for r in rows}
    assert by[("target", "Sec")]["heading_missing"] == 1
    assert by[("alias-x", None)]["dst_path"] is None
    # delete
    (plans / "gone.md").unlink()
    ix.refresh()
    assert {r["dst_raw"]: r["dst_path"] for r in ix.outgoing("plans/src.md")}["plans/gone"] is None
    incremental = _links(ix)
    ix.close()
    (vault / ".index" / "index.db").unlink()
    rebuilt = Index(Vault(vault))
    rebuilt.refresh()
    assert _links(rebuilt) == incremental


def test_moving_a_note_relinks_its_backlinks(vault: Path) -> None:
    ix = _index(vault)
    plans = vault / "plans"
    (plans / "sub").mkdir(parents=True)
    (plans / "src.md").write_text("# Src\n\n[[target#Sec]] [[plans/target]]\n")
    (plans / "target.md").write_text("# Target\n\n## Sec\n")
    ix.refresh()
    assert {r["dst_path"] for r in ix.outgoing("plans/src.md")} == {"plans/target.md"}
    # delete and create in the same refresh: the base name follows, the full path breaks
    (plans / "target.md").rename(plans / "sub" / "target.md")
    ix.refresh()
    out = {r["dst_raw"]: r for r in ix.outgoing("plans/src.md")}
    assert out["target"]["dst_path"] == "plans/sub/target.md"
    assert out["target"]["heading_missing"] == 0
    assert out["plans/target"]["dst_path"] is None
    assert [r["src"] for r in ix.backlinks("plans/sub/target.md")] == ["plans/src.md"]
    incremental = _links(ix)
    ix.close()
    (vault / ".index" / "index.db").unlink()
    rebuilt = Index(Vault(vault))
    rebuilt.refresh()
    assert _links(rebuilt) == incremental


def test_refresh_reuses_directory_listing_until_it_changes(vault: Path) -> None:
    ix = _index(vault)
    assert ix.refresh() is False
    cached = dict(ix._dirs)
    assert cached and ix.refresh() is False
    assert ix._dirs["docs/claude-code"] is cached["docs/claude-code"]
    (vault / "docs" / "claude-code" / "fresh.md").write_text("# Fresh\n")
    assert ix.refresh() is True
    assert ix.note("docs/claude-code/fresh.md") is not None
    assert ix._dirs["docs/claude-code"] is not cached["docs/claude-code"]
    (vault / "docs" / "claude-code" / "fresh.md").unlink()
    assert ix.refresh() is True
    assert ix.note("docs/claude-code/fresh.md") is None


def test_welcomed_old_rows_are_pruned(vault: Path) -> None:
    ix = _index(vault)
    assert ix.mark_welcomed("old") is True
    ix.conn.execute("update welcomed set at = '2020-01-01T00:00:00+00:00'")
    assert ix.mark_welcomed("new") is True
    ids = {r[0] for r in ix.conn.execute("select session_id from welcomed")}
    assert ids == {"new"}
    assert ix.mark_welcomed("new") is False


def test_locate_single_words_scans_line_by_line() -> None:
    text = "Título\n\nLa migración del índice quedó lista\nmás texto\n"
    line, snippet = locate(text, query_terms("migracion indice"))
    assert line == 3
    assert "**migración**" in snippet and "**índice**" in snippet


def test_locate_phrase_across_a_line_break() -> None:
    line, snippet = locate("alfa\nbeta", query_terms('"alfa beta"'))
    assert line == 1
    assert snippet == "**alfa beta**"


def test_locate_without_a_match_returns_the_first_non_empty_line() -> None:
    assert locate("\n\nPrimera línea\notra", query_terms("zzz")) == (3, "Primera línea otra")
    assert locate("uno\ndos", []) == (1, "uno dos")


def test_search_without_snippets_returns_the_same_notes(vault: Path) -> None:
    ix = _index(vault)
    full, total = ix.search("configuracion")
    bare, bare_total = ix.search("configuracion", snippets=False)
    assert total == bare_total > 0
    assert [h.path for h in bare] == [h.path for h in full]
    assert [h.score for h in bare] == [h.score for h in full]
    assert all(h.snippet == "" and h.line == 1 for h in bare)


def test_fts_keeps_no_copy_of_the_text(vault: Path) -> None:
    ix = _index(vault)

    tables = {r[0] for r in ix.conn.execute("select name from sqlite_master")}

    assert "fts" in tables
    assert "fts_content" not in tables


def test_body_is_stored_only_for_memories(vault: Path) -> None:
    ix = _index(vault)

    memory = ix.note("memory/_shared/perfil.md")
    doc = ix.note("docs/claude-code/hooks-reference.md")

    assert memory is not None and memory["body"]
    assert doc is not None and doc["body"] is None and doc["search_text"]


def test_deleted_note_leaves_the_fts_index(vault: Path) -> None:
    (vault / "plans").mkdir()
    (vault / "plans/gone.md").write_text("# Gone\n\nquimbombo\n")
    ix = _index(vault)
    assert ix.search("quimbombo")[1] == 1

    os.unlink(vault / "plans/gone.md")
    ix.refresh()

    assert ix.search("quimbombo")[1] == 0


def test_index_from_an_older_schema_is_rebuilt_without_free_pages(vault: Path) -> None:
    _index(vault).close()
    with sqlite3.connect(vault / ".index/index.db") as conn:
        # Schema 1 kept the body of every note, not just of memories.
        conn.execute("update notes set body = search_text where body is null")
        conn.execute("update meta set value = '1' where key = 'schema'")
    conn.close()

    ix = _index(vault)

    assert ix.conn.execute("pragma freelist_count").fetchone()[0] == 0
    assert ix.note("memory/_shared/perfil.md") is not None


@pytest.mark.parametrize(
    ("version", "contentless"), [((3, 42, 0), False), ((3, 43, 0), True), ((3, 53, 1), True)]
)
def test_fts_is_contentless_only_where_sqlite_can_delete_from_it(
    tmp_path: Path, version: tuple[int, int, int], contentless: bool
) -> None:
    conn = sqlite3.connect(tmp_path / "x.db")

    sql = fts_schema(version)
    conn.execute(sql)

    assert ("content = ''" in sql) is contentless
    conn.close()


def test_alias_bomb_note_does_not_block_indexing(vault: Path) -> None:
    lines = ["a0: &a0 [x, x]"] + [f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]" for i in range(1, 25)]
    ix = _index(vault)  # the full build is not what is timed
    (vault / "plans").mkdir()
    (vault / "plans" / "bomb.md").write_text("---\n" + "\n".join(lines) + "\n---\n# Bomb\n")

    start = time.perf_counter()
    ix.refresh()
    elapsed = time.perf_counter() - start

    row = ix.note("plans/bomb.md")
    assert row is not None and row["fm_valid"] == 0
    assert elapsed < 1


def test_note_over_2_mb_is_skipped_with_a_warning(vault: Path, caplog) -> None:
    (vault / "plans").mkdir()
    (vault / "plans" / "huge.md").write_text("# Huge\n\n" + "zorbhuge palabra\n" * 150_000)

    with caplog.at_level("WARNING"):
        ix = _index(vault)

    assert ix.note("plans/huge.md") is None
    assert "plans/huge.md" in caplog.text


def test_note_over_2_mb_is_warned_once_per_size(vault: Path, caplog) -> None:
    (vault / "plans").mkdir()
    huge = vault / "plans" / "huge.md"
    huge.write_text("# Huge\n\n" + "zorbhuge palabra\n" * 150_000)
    ix = Index(Vault(vault))

    with caplog.at_level("WARNING"):
        ix.refresh()
        ix.refresh()
        ix.refresh()
        huge.write_text("# Huge\n\n" + "zorbhuge palabra\n" * 160_000)
        ix.refresh()

    assert caplog.text.count("skipping plans/huge.md") == 2


def test_query_terms_are_capped_in_count_and_length() -> None:
    assert len(query_terms(" ".join(f"w{i}" for i in range(100)))) == 32
    assert query_terms("a " * 5000 + "zorbtail") == [["a"]] * 32
    assert query_terms("x" * 1990 + " tail words") == [["x" * 1990], ["tail"], ["word"]]
    assert query_terms("x" * 1990 + " tail words more") == query_terms("x" * 1990 + " tail word")
