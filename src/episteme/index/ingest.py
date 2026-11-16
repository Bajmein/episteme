"""Writing one note into the index tables and re-resolving the links it can affect."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from typing import Any

from episteme.index.values import as_date, as_int, to_json
from episteme.links import Resolver, _strip_md
from episteme.markdown import ParsedNote, normalize_heading
from episteme.vault import MEMORY, Vault


def _str_field(fm: dict[str, Any], key: str) -> str | None:
    value = fm.get(key)
    return value if isinstance(value, str) else None


def _insert_note_row(
    conn: sqlite3.Connection, vault: Vault, rel: str, sig: tuple[int, int], note: ParsedNote
) -> int | None:
    """Insert the ``notes`` row and return its rowid."""
    fm = note.frontmatter
    zone = vault.zone_for(rel)
    mode = vault.mode_for(rel)
    # Only memory rows read ``body``; other notes are found and shown via ``search_text``.
    body = note.body if mode == MEMORY else None
    cur = conn.execute(
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
            mode,
            int(note.fm_valid),
            note.fm_error,
            _str_field(fm, "type"),
            _str_field(fm, "project"),
            _str_field(fm, "status"),
            as_int(fm.get("priority")),
            as_date(fm.get("created")),
            as_date(fm.get("due")),
            as_date(fm.get("valid_until")),
            as_int(fm.get("helpful")) or 0,
            int(fm.get("flagged") is True),
            hashlib.sha1(note.body.encode(), usedforsecurity=False).hexdigest(),
            body,
            note.search_text,
        ),
    )
    return cur.lastrowid


def _insert_fts(conn: sqlite3.Connection, rowid: int | None, note: ParsedNote) -> None:
    keywords = note.frontmatter.get("keywords")
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        keywords = []
    conn.execute(
        "insert into fts(rowid, title, tags, body) values (?,?,?,?)",
        (
            rowid,
            f"{note.title} {' '.join(keywords)}".strip(),
            " ".join(note.tags),
            note.search_text,
        ),
    )


def _insert_aliases(conn: sqlite3.Connection, rel: str, fm: dict[str, Any]) -> None:
    aliases = fm.get("aliases")
    if isinstance(aliases, str):
        aliases = [aliases]
    if isinstance(aliases, list):
        conn.executemany(
            "insert into aliases(path, alias) values (?,?)",
            [(rel, str(a)) for a in aliases if a is not None],
        )


def insert_note(
    conn: sqlite3.Connection, vault: Vault, rel: str, sig: tuple[int, int], note: ParsedNote
) -> None:
    """Insert one parsed note into every table; its links are resolved later by ``relink``."""
    fm = note.frontmatter
    rowid = _insert_note_row(conn, vault, rel, sig, note)
    _insert_fts(conn, rowid, note)
    conn.executemany("insert into tags(path, tag) values (?,?)", [(rel, t) for t in note.tags])
    conn.executemany(
        "insert into props(path, key, value) values (?,?,?)",
        [(rel, k, to_json(v)) for k, v in fm.items()],
    )
    conn.executemany(
        "insert into headings(path, level, text, line) values (?,?,?,?)",
        [(rel, h.level, h.text, h.line) for h in note.headings],
    )
    _insert_aliases(conn, rel, fm)
    conn.executemany(
        "insert into links(src, dst_raw, kind, heading, block, line) values (?,?,?,?,?,?)",
        [(rel, lk.target, lk.kind, lk.heading, lk.block, lk.line) for lk in note.links],
    )


def build_resolver(conn: sqlite3.Connection) -> Resolver:
    aliases: dict[str, list[str]] = {}
    for r in conn.execute("select path, alias from aliases"):
        aliases.setdefault(r["path"], []).append(r["alias"])
    paths = [r["path"] for r in conn.execute("select path from notes order by path")]
    return Resolver((p, aliases.get(p, [])) for p in paths)


def _answers(
    raw: str, keys: set[str], aliases: set[str], names: set[str], stems: list[str]
) -> bool:
    """Whether the link target ``raw`` is answered by the touched keys, aliases or stems."""
    key = raw.strip().replace("\\", "/").strip("/").lower()
    stem = _strip_md(key)
    if key in keys or key in aliases:
        return True
    if "/" in stem:
        return any(s.endswith("/" + stem) for s in stems)
    return stem in names


def _touch_matcher(paths: set[str], aliases: set[str]) -> Callable[[str], bool]:
    """A memoized test: can a link target be answered by one of ``paths`` or ``aliases``?"""
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
            verdicts[raw] = _answers(raw, keys, aliases, names, stems)
        return verdicts[raw]

    return touched


def _heading_missing(
    conn: sqlite3.Connection, headings: dict[str, set[str]], dst: str | None, heading: str | None
) -> int:
    """1 if ``dst`` has no heading ``heading``; ``headings`` caches the headings per note."""
    if dst is None or not heading:
        return 0
    if dst not in headings:
        headings[dst] = {
            normalize_heading(h["text"])
            for h in conn.execute("select text from headings where path = ?", (dst,))
        }
    return int(normalize_heading(heading) not in headings[dst])


def _needs_relink(r: sqlite3.Row, changed: set[str], touched: Callable[[str], bool]) -> bool:
    """Whether a link row starts in or points at a changed note, or names a touched target."""
    if r["src"] in changed or r["dst_path"] in changed:
        return True
    return bool(r["dst_raw"]) and touched(r["dst_raw"])


def relink(
    conn: sqlite3.Connection, changed: set[str], paths: set[str], aliases: set[str]
) -> None:
    """Resolve again only the links that can have changed.

    ``changed`` are the notes just reindexed, ``paths`` those that appeared or vanished and
    ``aliases`` the aliases gained or lost (normalized). A link is redone if it starts in a
    changed note, points at one (its heading may have moved) or names something a touched
    path or alias can answer to.
    """
    touched = _touch_matcher(paths, aliases)
    resolver: Resolver | None = None
    headings: dict[str, set[str]] = {}
    updates = []
    rows = conn.execute(
        "select rowid, src, dst_raw, dst_path, heading, heading_missing from links"
    ).fetchall()
    for r in rows:
        if not _needs_relink(r, changed, touched):
            continue
        if not r["dst_raw"]:
            dst = r["src"]
        else:
            resolver = resolver or build_resolver(conn)
            dst = resolver.resolve_quiet(r["dst_raw"], r["src"])
        missing = _heading_missing(conn, headings, dst, r["heading"])
        if (dst, missing) != (r["dst_path"], r["heading_missing"]):
            updates.append((dst, missing, r["rowid"]))
    conn.executemany("update links set dst_path = ?, heading_missing = ? where rowid = ?", updates)
