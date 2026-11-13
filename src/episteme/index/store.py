"""SQLite index: FTS5, links, tags, properties and incremental reindexing by mtime."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from episteme.index.ingest import build_resolver, insert_note, relink
from episteme.index.query import Built, build_where
from episteme.index.schema import SCHEMA, SCHEMA_VERSION, TABLES, WELCOMED_TTL_DAYS
from episteme.index.text import _fts_term, locate, query_terms
from episteme.links import Resolver
from episteme.markdown import ParsedNote, parse
from episteme.vault import INDEX_DIR, MEMORY, DirListing, Vault


@dataclass
class Hit:
    path: str
    title: str
    line: int
    snippet: str
    score: float
    zone: str | None = None
    type: str | None = None
    status: str | None = None
    project: str | None = None
    created: str | None = None
    priority: int | None = None


class Index:
    """The index of one vault. It is a cache: the ``.md`` files are the truth."""

    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.dir = vault.root / INDEX_DIR
        self.db_path = self.dir / "index.db"
        self.generation = 0
        self._resolver: tuple[tuple[int, int], Resolver] | None = None
        self._dirs: dict[str, DirListing] = {}
        self.conn = self._open()

    # -- connection --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self.dir.mkdir(exist_ok=True)
        conn = sqlite3.connect(
            self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False
        )
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("pragma busy_timeout = 5000")
            conn.execute("pragma journal_mode = wal")
            conn.execute("pragma synchronous = normal")
        except BaseException:
            # On a corrupt file the pragmas raise; an open handle blocks the unlink on Windows.
            conn.close()
            raise
        return conn

    def _open(self) -> sqlite3.Connection:
        delay = 0.05
        for _ in range(40):
            conn = None
            try:
                conn = self._connect()
                if conn.execute("pragma quick_check").fetchone()[0] != "ok":
                    conn.close()
                    break
                if _schema_version(conn) != SCHEMA_VERSION:
                    self._create(conn)
                return conn
            except sqlite3.DatabaseError as exc:
                if conn is not None:
                    conn.close()
                if not _is_lock(exc):
                    break
                # Another process holds the lock (e.g. it is creating the schema): wait.
                delay = _backoff(delay)
        else:
            raise sqlite3.OperationalError("database is locked")
        # Corrupt: the index is a cache, so throw it away and rebuild.
        self._wipe_files()
        conn = self._connect()
        self._create(conn)
        return conn

    def _wipe_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(f"{self.db_path}{suffix}")
            except FileNotFoundError:
                pass

    def _create(self, conn: sqlite3.Connection) -> None:
        def create() -> None:
            if _schema_version(conn) == SCHEMA_VERSION:
                return  # another process got here first
            for table in TABLES:
                conn.execute(f"drop table if exists {table}")
            for stmt in SCHEMA.split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            conn.execute("insert into meta(key, value) values ('schema', ?)", (SCHEMA_VERSION,))

        self._in_transaction(conn, create)

    @staticmethod
    def _in_transaction(conn: sqlite3.Connection, fn: Any) -> Any:
        delay = 0.05
        for attempt in range(40):
            try:
                conn.execute("begin immediate")
            except sqlite3.OperationalError as exc:
                if _is_lock(exc):
                    delay = _backoff(delay)
                    continue
                raise
            try:
                result = fn()
                conn.execute("commit")
                return result
            except sqlite3.OperationalError as exc:
                conn.execute("rollback")
                if _is_lock(exc) and attempt < 39:
                    time.sleep(delay)
                    continue
                raise
            except BaseException:
                conn.execute("rollback")
                raise
        raise sqlite3.OperationalError("database is locked")

    def close(self) -> None:
        self.conn.close()

    # -- reindexing --------------------------------------------------------

    def refresh(self) -> bool:
        """Reindex what changed on disk since the last call. True if anything changed."""
        disk = {rel: (st.st_mtime_ns, st.st_size) for rel, st in self.vault.scan_notes(self._dirs)}
        changed, removed = _diff(disk, self._stored_signatures())
        if not changed and not removed:
            return False
        parsed = self._load_all(changed)

        self._in_transaction(self.conn, lambda: self._apply(removed, parsed))
        self.generation += 1
        return True

    def _stored_signatures(self) -> dict[str, tuple[int, int]]:
        return {
            r["path"]: (r["mtime_ns"], r["size"])
            for r in self.conn.execute("select path, mtime_ns, size from notes")
        }

    def _load_all(self, rels: list[str]) -> list[tuple[str, tuple[int, int], ParsedNote]]:
        parsed = []
        for rel in rels:
            item = self._load(rel)
            if item is not None:
                parsed.append(item)
        return parsed

    def reindex(self, rel: str) -> None:
        """Reindex one note right after a tool wrote it."""
        item = self._load(rel)

        self._in_transaction(
            self.conn, lambda: self._apply([] if item else [rel], [item] if item else [])
        )
        self.generation += 1

    def _apply(
        self, removed: list[str], items: list[tuple[str, tuple[int, int], ParsedNote]]
    ) -> None:
        """Delete and insert notes, then re-resolve only the links they can affect."""
        new = {item[0] for item in items}
        before = {rel: self._aliases_of(rel) for rel in [*removed, *new]}
        for rel in removed:
            self._delete(rel)
        for rel, sig, note in items:
            self._delete(rel)
            insert_note(self.conn, self.vault, rel, sig, note)
        paths, aliases = self._alias_changes(before, new)
        relink(self.conn, set(before), paths, aliases)

    def _alias_changes(
        self, before: dict[str, set[str] | None], new: set[str]
    ) -> tuple[set[str], set[str]]:
        """Paths that appeared or vanished and aliases gained or lost since ``before``."""
        paths: set[str] = set()
        aliases: set[str] = set()
        for rel, old in before.items():
            now = self._aliases_of(rel) if rel in new else None
            if (old is None) != (now is None):
                paths.add(rel)
            aliases |= (old or set()) ^ (now or set())
        return paths, aliases

    def _aliases_of(self, rel: str) -> set[str] | None:
        """Normalized aliases of an indexed note, or None if ``rel`` is not indexed."""
        if self.conn.execute("select 1 from notes where path = ?", (rel,)).fetchone() is None:
            return None
        rows = self.conn.execute("select alias from aliases where path = ?", (rel,))
        return {a for (a,) in ((r["alias"].strip().lower(),) for r in rows) if a}

    def _load(self, rel: str) -> tuple[str, tuple[int, int], ParsedNote] | None:
        path = self.vault.root / rel
        try:
            st = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return rel, (st.st_mtime_ns, st.st_size), parse(text, rel)

    def _delete(self, rel: str) -> None:
        row = self.conn.execute("select id from notes where path = ?", (rel,)).fetchone()
        if row is None:
            return
        self.conn.execute("delete from fts where rowid = ?", (row["id"],))
        self.conn.execute("delete from notes where id = ?", (row["id"],))
        for table in ("tags", "props", "headings", "aliases"):
            self.conn.execute(f"delete from {table} where path = ?", (rel,))  # nosec B608
        self.conn.execute("delete from links where src = ?", (rel,))

    def resolver(self) -> Resolver:
        # data_version moves when another connection commits; our own commits bump generation.
        version = (self.generation, self.conn.execute("pragma data_version").fetchone()[0])
        if self._resolver is None or self._resolver[0] != version:
            self._resolver = (version, build_resolver(self.conn))
        return self._resolver[1]

    # -- queries -----------------------------------------------------------

    def note(self, rel: str) -> sqlite3.Row | None:
        return self.conn.execute("select * from notes where path = ?", (rel,)).fetchone()

    def props(self, rel: str) -> dict[str, Any]:
        return {
            r["key"]: json.loads(r["value"])
            for r in self.conn.execute("select key, value from props where path = ?", (rel,))
        }

    def memories(self, where: str = "1", params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """Memory rows. ``where`` is a literal SQL fragment from this package; values go in
        ``params``, never into ``where``."""
        return self.conn.execute(
            f"select * from notes where mode = ? and ({where}) order by path",  # nosec B608
            (MEMORY, *params),
        ).fetchall()

    def outgoing(self, rel: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "select * from links where src = ? order by line, rowid", (rel,)
        ).fetchall()

    def backlinks(self, rel: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "select * from links where dst_path = ? and src != ? order by src, line", (rel, rel)
        ).fetchall()

    def facets(self, query: str | None = None, **filters: Any) -> dict[str, dict[str, int]]:
        """Counts by zone, project, type, status and tag over the notes the filters select."""
        built = build_where(query, **filters)
        out: dict[str, dict[str, int]] = {
            k: {} for k in ("zone", "project", "type", "status", "tags")
        }
        if built is None:
            return out
        source, clause, params, _ = built
        # Columns come from a closed list; user values are bound parameters.
        for col in ("zone", "project", "type", "status"):
            rows = self.conn.execute(
                f"select n.{col} as v, count(*) as c {source} "  # nosec B608
                f"where {clause} and n.{col} is not null group by n.{col} order by c desc, v",
                params,
            ).fetchall()
            out[col] = {r["v"]: r["c"] for r in rows}
        rows = self.conn.execute(
            f"select t.tag as v, count(*) as c from tags t where t.path in "  # nosec B608
            f"(select n.path {source} where {clause}) group by t.tag order by c desc, v limit 30",
            params,
        ).fetchall()
        out["tags"] = {r["v"]: r["c"] for r in rows}
        return out

    def known(self, column: str) -> list[str]:
        """Distinct non-null values of a ``notes`` column (zone, type, status or project)."""
        if column not in ("zone", "type", "status", "project"):
            raise ValueError(f"unknown column {column!r}")
        rows = self.conn.execute(
            f"select distinct {column} as v from notes where {column} is not null "  # nosec B608
            "order by v"
        ).fetchall()
        return [r["v"] for r in rows]

    def known_tags(self) -> list[str]:
        rows = self.conn.execute("select distinct tag from tags order by tag").fetchall()
        return [r["tag"] for r in rows]

    def heading_at(self, path: str, line: int) -> str | None:
        """Text of the closest heading at or before ``line``; None if none or it is an H1."""
        row = self.conn.execute(
            "select level, text from headings where path = ? and line <= ? "
            "order by line desc, rowid desc limit 1",
            (path, line),
        ).fetchone()
        if row is None or row["level"] == 1:
            return None
        return row["text"]

    def matched_terms(self, query: str, paths: list[str]) -> dict[str, list[str]]:
        """For each path, the terms of ``query`` its note matches in the full-text index."""
        out: dict[str, list[str]] = {p: [] for p in paths}
        if not paths:
            return out
        marks = ",".join("?" * len(paths))
        for term in query_terms(query):
            label = " ".join(term)
            rows = self.conn.execute(
                "select n.path from fts join notes n on n.id = fts.rowid "  # nosec B608
                f"where fts match ? and n.path in ({marks})",
                [_fts_term(term), *paths],
            )
            for r in rows:
                if label not in out[r["path"]]:
                    out[r["path"]].append(label)
        return out

    def superseded_by(self, path: str) -> str | None:
        row = self.conn.execute(
            "select src from links where kind = 'supersedes' and dst_path = ? "
            "order by src, line limit 1",
            (path,),
        ).fetchone()
        return row["src"] if row else None

    def mark_welcomed(self, session: str) -> bool:
        """Record that ``session`` got its welcome. False if it already had."""

        def insert() -> bool:
            cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=WELCOMED_TTL_DAYS)
            self.conn.execute(
                "delete from welcomed where at < ?", (cutoff.isoformat(timespec="seconds"),)
            )
            cur = self.conn.execute(
                "insert or ignore into welcomed(session_id, at) values (?, ?)",
                (session, dt.datetime.now(dt.UTC).isoformat(timespec="seconds")),
            )
            return cur.rowcount == 1

        return bool(self._in_transaction(self.conn, insert))

    def search(
        self,
        query: str | None,
        *,
        any_term: bool = False,
        drop_stopwords: bool = False,
        path: str | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        project: str | list[str] | None = None,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 20,
        zone: str | None = None,
        snippets: bool = True,
    ) -> tuple[list[Hit], int]:
        """Full-text search. Returns the hits (after ``limit``) and the total before it.

        Without ``query`` the filters alone select the notes (ordered by priority, then path).
        ``term*`` is a prefix match; ``drop_stopwords`` ignores Spanish function words.
        ``snippets=False`` skips locating the match: every hit has ``line`` 1 and no snippet,
        for callers that only need the paths.
        """
        built = build_where(
            query,
            any_term=any_term,
            drop_stopwords=drop_stopwords,
            path=path,
            type=type,
            tags=tags,
            project=project,
            status=status,
            mode=mode,
            zone=zone,
        )
        if built is None:
            return [], 0
        total = self.conn.execute(
            f"select count(*) {built.source} where {built.clause}",  # nosec B608
            built.params,
        ).fetchone()[0]
        rows = self._select_rows(built, ranked=query is not None, limit=limit, snippets=snippets)
        return [_hit(r, built.terms, snippets) for r in rows], total

    def _select_rows(
        self, built: Built, *, ranked: bool, limit: int, snippets: bool
    ) -> list[sqlite3.Row]:
        """The page of rows of a search, by bm25 rank if there is a query, else by priority."""
        if ranked:
            cols = "bm25(fts, 5.0, 1.0, 1.0) as rank"
            order = "order by rank, coalesce(n.priority, 0) desc, n.path"
        else:
            cols = "0.0 as rank"
            order = "order by coalesce(n.priority, 0) desc, n.path"
        text_col = "n.search_text, " if snippets else ""
        return self.conn.execute(
            f"select n.path, n.title, {text_col}n.zone, n.type, n.status, n.project, "  # nosec B608
            f"n.created, n.priority, {cols} {built.source} "
            f"where {built.clause} {order} limit ?",
            [*built.params, limit],
        ).fetchall()


def _hit(r: sqlite3.Row, terms: list[list[str]], snippets: bool) -> Hit:
    """One search row as a ``Hit``, locating the match when ``snippets`` is on."""
    line, snippet = locate(r["search_text"], terms) if snippets else (1, "")
    return Hit(
        r["path"], r["title"], line, snippet, round(-r["rank"], 4) + 0.0,
        r["zone"], r["type"], r["status"], r["project"], r["created"], r["priority"],
    )  # fmt: skip


def _diff(
    disk: dict[str, tuple[int, int]], stored: dict[str, tuple[int, int]]
) -> tuple[list[str], list[str]]:
    """Notes whose signature differs on disk, and stored notes no longer on disk."""
    changed = [rel for rel, sig in disk.items() if stored.get(rel) != sig]
    removed = [rel for rel in stored if rel not in disk]
    return changed, removed


def _schema_version(conn: sqlite3.Connection) -> str | None:
    """The schema version stored in ``meta``, or None if there is none."""
    have = {r[0] for r in conn.execute("select name from sqlite_master")}
    if "meta" not in have:
        return None
    row = conn.execute("select value from meta where key='schema'").fetchone()
    return row[0] if row else None


def _backoff(delay: float) -> float:
    """Sleep ``delay`` seconds and return the next, doubled up to 0.5."""
    time.sleep(delay)
    return min(delay * 2, 0.5)


def _is_lock(exc: sqlite3.DatabaseError) -> bool:
    """A busy/locked error from another process, as opposed to a corrupt file."""
    return isinstance(exc, sqlite3.OperationalError) and (
        "locked" in str(exc) or "busy" in str(exc)
    )
