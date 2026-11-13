"""SQLite index: FTS5, links, tags, properties and incremental reindexing by mtime."""

from __future__ import annotations

from episteme.index.store import Hit, Index
from episteme.index.text import STOPWORDS_ES, locate, normalize_tag, query_terms
from episteme.index.text import _term_regex as _term_regex
from episteme.index.values import as_date, as_int, is_past, jsonable, to_json

__all__ = [
    "STOPWORDS_ES",
    "Hit",
    "Index",
    "_term_regex",
    "as_date",
    "as_int",
    "is_past",
    "jsonable",
    "locate",
    "normalize_tag",
    "query_terms",
    "to_json",
]
