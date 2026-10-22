"""SQLite index: FTS5, links, tags, properties and incremental reindexing by mtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from episteme.links import Resolver, _strip_md
from episteme.markdown import (
    ParsedNote,
    fold,
    fold_with_map,
    normalize_heading,
    parse,
)
from episteme.markdown import normalize_tag as markdown_normalize_tag
from episteme.vault import INDEX_DIR, MEMORY, DirListing, Vault

# Spanish function words: ignored when matching a task or comparing memories for duplicates.
STOPWORDS_ES = frozenset(
    """a al algo ante con contra cual cuando de del desde donde durante e el ella ellas ellos en
    entre era eran es esa esas ese eso esos esta estaba estan estar este esto estos fue ha han
    hay la las le les lo los me mi mis mucho muy ni no nos nuestro o para pero por porque que
    quien se ser si sin sobre son su sus te tiene tienen todo tu tus un una uno unos unas y ya
    yo como mas hacer hace cada tambien""".split()
)
SCHEMA_VERSION = "1"

# ``welcomed`` rows older than this are dropped when a new session is recorded.
WELCOMED_TTL_DAYS = 30

SCHEMA = """
create table meta(key text primary key, value text);
create table notes(
    id integer primary key,
    path text unique not null,
    title text, mtime_ns integer, size integer, zone text, mode text,
    fm_valid integer, fm_error text, type text, project text, status text,
    priority integer, created text, due text, valid_until text,
    helpful integer, flagged integer, body_hash text,
    body text, search_text text
);
create virtual table fts using fts5(
    title, tags, body, tokenize = 'unicode61 remove_diacritics 2'
);
create table links(
    src text not null, dst_raw text, dst_path text, kind text,
    heading text, block text, line integer, heading_missing integer default 0
);
create index links_src on links(src);
create index links_dst on links(dst_path);
create table tags(path text not null, tag text not null);
create index tags_tag on tags(tag);
create index tags_path on tags(path);
create table props(path text not null, key text not null, value text);
create index props_path on props(path);
create table headings(path text not null, level integer, text text, line integer);
create index headings_path on headings(path);
create table aliases(path text not null, alias text not null);
create table welcomed(session_id text primary key, at text);
"""

TABLES = ("meta", "notes", "fts", "links", "tags", "props", "headings", "aliases", "welcomed")


def as_date(value: Any) -> str | None:
    """A frontmatter date (date, datetime or ISO string) as ``YYYY-MM-DD``."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            return None
    return None


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _json_default(value: Any) -> Any:
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return str(value)


def _str_keys(value: Any) -> Any:
    """Copy ``value`` with every mapping key as a string, which JSON requires."""
    if isinstance(value, dict):
        return {str(k): _str_keys(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_str_keys(v) for v in value]
    return value


def to_json(value: Any) -> str:
    return json.dumps(_str_keys(value), ensure_ascii=False, default=_json_default)


def jsonable(value: Any) -> Any:
    return json.loads(to_json(value))


@dataclass
class Hit:
    path: str
    title: str
    line: int
    snippet: str
    score: float


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
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 5000")
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma synchronous = normal")
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
                have = {r[0] for r in conn.execute("select name from sqlite_master")}
                version = None
                if "meta" in have:
                    row = conn.execute("select value from meta where key='schema'").fetchone()
                    version = row[0] if row else None
                if version != SCHEMA_VERSION:
                    self._create(conn)
                return conn
            except sqlite3.DatabaseError as exc:
                if conn is not None:
                    conn.close()
                if not _is_lock(exc):
                    break
                # Another process holds the lock (e.g. it is creating the schema): wait.
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
        else:
            raise sqlite3.OperationalError("database is locked")
        # Corrupt: the index is a cache, so throw it away and rebuild.
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(f"{self.db_path}{suffix}")
            except FileNotFoundError:
                pass
        conn = self._connect()
        self._create(conn)
        return conn

    def _create(self, conn: sqlite3.Connection) -> None:
        def create() -> None:
            have = {r[0] for r in conn.execute("select name from sqlite_master")}
            row = None
            if "meta" in have:
                row = conn.execute("select value from meta where key='schema'").fetchone()
            if row and row[0] == SCHEMA_VERSION:
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
                    time.sleep(delay)
                    delay = min(delay * 2, 0.5)
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
        stored = {
            r["path"]: (r["mtime_ns"], r["size"])
            for r in self.conn.execute("select path, mtime_ns, size from notes")
        }
        changed = [rel for rel, sig in disk.items() if stored.get(rel) != sig]
        removed = [rel for rel in stored if rel not in disk]
        if not changed and not removed:
            return False
        parsed = []
        for rel in changed:
            item = self._load(rel)
            if item is not None:
                parsed.append(item)

        self._in_transaction(self.conn, lambda: self._apply(removed, parsed))
        self.generation += 1
        return True

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
            self._insert(rel, sig, note)
        paths: set[str] = set()
        aliases: set[str] = set()
        for rel, old in before.items():
            now = self._aliases_of(rel) if rel in new else None
            if (old is None) != (now is None):
                paths.add(rel)
            aliases |= (old or set()) ^ (now or set())
        self._relink(set(before), paths, aliases)

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

    def _insert(self, rel: str, sig: tuple[int, int], note: ParsedNote) -> None:
        fm = note.frontmatter
        zone = self.vault.zone_for(rel)
        flagged = fm.get("flagged")
        cur = self.conn.execute(
            """insert into notes(path, title, mtime_ns, size, zone, mode, fm_valid, fm_error,
                type, project, status, priority, created, due, valid_until, helpful, flagged,
                body_hash, body, search_text)
               values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rel,
                note.title,
                sig[0],
                sig[1],
                zone.path if zone else None,
                self.vault.mode_for(rel),
                int(note.fm_valid),
                note.fm_error,
                fm.get("type") if isinstance(fm.get("type"), str) else None,
                fm.get("project") if isinstance(fm.get("project"), str) else None,
                fm.get("status") if isinstance(fm.get("status"), str) else None,
                as_int(fm.get("priority")),
                as_date(fm.get("created")),
                as_date(fm.get("due")),
                as_date(fm.get("valid_until")),
                as_int(fm.get("helpful")) or 0,
                int(flagged is True),
                hashlib.sha1(note.body.encode(), usedforsecurity=False).hexdigest(),
                note.body,
                note.search_text,
            ),
        )
        rowid = cur.lastrowid
        self.conn.execute(
            "insert into fts(rowid, title, tags, body) values (?,?,?,?)",
            (rowid, note.title, " ".join(note.tags), note.search_text),
        )
        self.conn.executemany(
            "insert into tags(path, tag) values (?,?)", [(rel, t) for t in note.tags]
        )
        self.conn.executemany(
            "insert into props(path, key, value) values (?,?,?)",
            [(rel, k, to_json(v)) for k, v in fm.items()],
        )
        self.conn.executemany(
            "insert into headings(path, level, text, line) values (?,?,?,?)",
            [(rel, h.level, h.text, h.line) for h in note.headings],
        )
        aliases = fm.get("aliases")
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            self.conn.executemany(
                "insert into aliases(path, alias) values (?,?)",
                [(rel, str(a)) for a in aliases if a is not None],
            )
        self.conn.executemany(
            "insert into links(src, dst_raw, kind, heading, block, line) values (?,?,?,?,?,?)",
            [(rel, lk.target, lk.kind, lk.heading, lk.block, lk.line) for lk in note.links],
        )

    def _relink(self, changed: set[str], paths: set[str], aliases: set[str]) -> None:
        """Resolve again only the links that can have changed.

        ``changed`` are the notes just reindexed, ``paths`` those that appeared or vanished and
        ``aliases`` the aliases gained or lost (normalized). A link is redone if it starts in a
        changed note, points at one (its heading may have moved) or names something a touched
        path or alias can answer to.
        """
        keys: set[str] = set()
        names: set[str] = set()
        stems: list[str] = []
        for path in paths:
            stem = _strip_md(path).lower()
            keys.update((path.lower(), stem))
            names.add(stem.rsplit("/", 1)[-1])
            stems.append(stem)
        verdicts: dict[str, bool] = {}

        def touched(raw: str) -> bool:
            if raw not in verdicts:
                key = raw.strip().replace("\\", "/").strip("/").lower()
                stem = _strip_md(key)
                if key in keys or key in aliases:
                    hit = True
                elif "/" in stem:
                    hit = any(s.endswith("/" + stem) for s in stems)
                else:
                    hit = stem in names
                verdicts[raw] = hit
            return verdicts[raw]

        resolver: Resolver | None = None
        headings: dict[str, set[str]] = {}
        updates = []
        rows = self.conn.execute(
            "select rowid, src, dst_raw, dst_path, heading, heading_missing from links"
        ).fetchall()
        for r in rows:
            if r["src"] not in changed and r["dst_path"] not in changed:
                if not r["dst_raw"] or not touched(r["dst_raw"]):
                    continue
            if not r["dst_raw"]:
                dst = r["src"]
            else:
                resolver = resolver or self._build_resolver()
                dst = resolver.resolve_quiet(r["dst_raw"], r["src"])
            missing = 0
            if dst is not None and r["heading"]:
                if dst not in headings:
                    headings[dst] = {
                        normalize_heading(h["text"])
                        for h in self.conn.execute(
                            "select text from headings where path = ?", (dst,)
                        )
                    }
                missing = int(normalize_heading(r["heading"]) not in headings[dst])
            if (dst, missing) != (r["dst_path"], r["heading_missing"]):
                updates.append((dst, missing, r["rowid"]))
        self.conn.executemany(
            "update links set dst_path = ?, heading_missing = ? where rowid = ?", updates
        )

    def _build_resolver(self) -> Resolver:
        aliases: dict[str, list[str]] = {}
        for r in self.conn.execute("select path, alias from aliases"):
            aliases.setdefault(r["path"], []).append(r["alias"])
        paths = [r["path"] for r in self.conn.execute("select path from notes order by path")]
        return Resolver((p, aliases.get(p, [])) for p in paths)

    def resolver(self) -> Resolver:
        # data_version moves when another connection commits; our own commits bump generation.
        version = (self.generation, self.conn.execute("pragma data_version").fetchone()[0])
        if self._resolver is None or self._resolver[0] != version:
            self._resolver = (version, self._build_resolver())
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
    ) -> tuple[list[Hit], int]:
        """Full-text search. Returns the hits (after ``limit``) and the total before it.

        Without ``query`` the filters alone select the notes (ordered by priority, then path).
        ``term*`` is a prefix match; ``drop_stopwords`` ignores Spanish function words.
        """
        terms: list[list[str]] = []
        where: list[str] = []
        params: list[Any] = []
        if query is not None:
            terms = query_terms(query, drop_stopwords=drop_stopwords)
            if not terms:
                return [], 0
            joiner = " OR " if any_term else " AND "
            match = joiner.join(_fts_term(t) for t in terms)
            where.append("fts match ?")
            params.append(match)
        if path:
            prefix = path.strip().strip("/")
            where.append("(n.path = ? or n.path like ? escape '\\')")
            params += [prefix, _like_prefix(prefix) + "/%"]
        if type:
            where.append("n.type = ?")
            params.append(type)
        if project:
            projects = [project] if isinstance(project, str) else project
            where.append(f"n.project in ({','.join('?' * len(projects))})")
            params += projects
        if mode:
            where.append("n.mode = ?")
            params.append(mode)
        if status is None:
            where.append(
                "not (n.mode = ? and coalesce(n.status, '') in ('superseded', 'archived'))"
            )
            params.append(MEMORY)
        elif status != "any":
            where.append("n.status = ?")
            params.append(status)
        for tag in tags or []:
            where.append("n.path in (select path from tags where tag = ?)")
            params.append(normalize_tag(tag))
        # Every clause in ``where`` is a literal; user values are bound parameters.
        if query is not None:
            source = "from fts join notes n on n.id = fts.rowid"
            cols = "bm25(fts, 5.0, 1.0, 1.0) as rank"
            order = "order by rank, coalesce(n.priority, 0) desc, n.path"
        else:
            source = "from notes n"
            cols = "0.0 as rank"
            order = "order by coalesce(n.priority, 0) desc, n.path"
        clause = " and ".join(where) or "1"
        total = self.conn.execute(
            f"select count(*) {source} where {clause}",  # nosec B608
            params,
        ).fetchone()[0]
        rows = self.conn.execute(
            f"select n.path, n.title, n.search_text, {cols} {source} "  # nosec B608
            f"where {clause} {order} limit ?",
            [*params, limit],
        ).fetchall()
        hits = []
        for r in rows:
            line, snippet = locate(r["search_text"], terms)
            hits.append(Hit(r["path"], r["title"], line, snippet, round(-r["rank"], 4) + 0.0))
        return hits, total


def _is_lock(exc: sqlite3.DatabaseError) -> bool:
    """A busy/locked error from another process, as opposed to a corrupt file."""
    return isinstance(exc, sqlite3.OperationalError) and (
        "locked" in str(exc) or "busy" in str(exc)
    )


def _like_prefix(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_tag(tag: str) -> str:
    """A tag as stored: ``#Dominio:Auth`` and ``dominio/auth`` both become ``dominio/auth``."""
    return markdown_normalize_tag(tag).replace(":", "/")


def query_terms(query: str, drop_stopwords: bool = False) -> list[list[str]]:
    """Split a user query into terms (a quoted phrase is one term) of folded tokens.

    Only word characters survive, so the query is never read as FTS5 syntax. A bare ``word*``
    is a prefix term: its last token keeps a trailing ``*``. With ``drop_stopwords``, single
    Spanish function words are dropped (phrases are kept).
    """
    terms = []
    for phrase, word in re.findall(r'"([^"]*)"|(\S+)', query):
        toks = re.findall(r"[^\W_]+", fold(phrase or word))
        if not toks:
            continue
        if drop_stopwords and not phrase and len(toks) == 1 and toks[0] in STOPWORDS_ES:
            continue
        if word and word.endswith("*"):
            toks[-1] += "*"
        terms.append(toks)
    return terms


def _fts_term(term: list[str]) -> str:
    last = term[-1]
    if last.endswith("*"):
        return '"' + " ".join([*term[:-1], last[:-1]]) + '" *'
    return '"' + " ".join(term) + '"'


def _term_regex(term: list[str]) -> re.Pattern[str]:
    prefix = term[-1].endswith("*")
    toks = [*term[:-1], term[-1].rstrip("*")]
    body = r"[\W_]+".join(re.escape(t) for t in toks)
    return re.compile(rf"(?<![^\W_]){body}" + ("" if prefix else r"(?![^\W_])"))


def locate(text: str, terms: list[list[str]], width: int = 200) -> tuple[int, str]:
    """1-based line of the first match in ``text`` and a snippet with ``**match**``."""
    folded, index = fold_with_map(text)
    patterns = [_term_regex(t) for t in terms]
    first = None
    for pat in patterns:
        m = pat.search(folded)
        if m and (first is None or m.start() < first[0]):
            first = (m.start(), m.end())
    if first is None:
        lines = text.split("\n")
        start_line = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
        snippet = " ".join(" ".join(lines[start_line:]).split())[:width]
        return start_line + 1, snippet
    start = index[first[0]]
    end = index[first[1] - 1] + 1
    line = text.count("\n", 0, start) + 1
    lo = max(0, start - (width - (end - start)) // 3)
    hi = min(len(text), lo + width)
    window = text[lo:hi]
    wfold, windex = fold_with_map(window)
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        for m in pat.finditer(wfold):
            spans.append((windex[m.start()], windex[m.end() - 1] + 1))
    spans.sort()
    out: list[str] = []
    pos = 0
    for s, e in spans:
        if s < pos:
            continue
        out.append(window[pos:s])
        out.append(f"**{window[s:e]}**")
        pos = e
    out.append(window[pos:])
    snippet = " ".join("".join(out).split())
    if lo > 0:
        snippet = "…" + snippet
    if hi < len(text):
        snippet += "…"
    return line, snippet
