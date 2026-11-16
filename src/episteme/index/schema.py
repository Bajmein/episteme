"""Schema of the SQLite index."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = "2"

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

# The text of each note already lives in ``notes.search_text``, so the FTS is contentless
# (it keeps only its index); ``contentless_delete`` lets a row go by rowid. Older SQLite
# has no ``contentless_delete``: there the FTS keeps its own copy, as before.
CONTENTLESS_MIN_SQLITE = (3, 43, 0)


def fts_schema(sqlite_version: tuple[int, int, int] = sqlite3.sqlite_version_info) -> str:
    """The ``create`` statement of the FTS table for this SQLite."""
    options = ""
    if sqlite_version >= CONTENTLESS_MIN_SQLITE:
        options = ", content = '', contentless_delete = 1"
    return (
        "create virtual table fts using fts5("
        f"title, tags, body, tokenize = 'unicode61 remove_diacritics 2'{options})"
    )
