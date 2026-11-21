"""The SQL ``where`` of a search, built filter by filter."""

from __future__ import annotations

from typing import Any, NamedTuple

from episteme.index.text import _fts_term, _like_prefix, normalize_tag, query_terms
from episteme.vault import MEMORY, PLAN, SESSION

type Filter = tuple[str, list[Any]]


class Built(NamedTuple):
    """A search ready to run: ``source`` is the ``from`` clause, ``clause`` the ``where``."""

    source: str
    clause: str
    params: list[Any]
    terms: list[list[str]]


def _match_filter(terms: list[list[str]], any_term: bool) -> Filter:
    joiner = " OR " if any_term else " AND "
    return "fts match ?", [joiner.join(_fts_term(t) for t in terms)]


def _path_filter(path: str) -> Filter:
    prefix = path.strip().strip("/")
    return "(n.path = ? or n.path like ? escape '\\')", [prefix, _like_prefix(prefix) + "/%"]


def _project_filter(project: str | list[str]) -> Filter:
    projects = [project] if isinstance(project, str) else project
    return f"n.project in ({','.join('?' * len(projects))})", list(projects)


def _status_filter(status: str | None) -> Filter | None:
    """By default superseded and archived memories, session states and plans are hidden;
    ``any`` shows every status."""
    if status is None:
        clause = (
            "not (n.mode in (?, ?, ?) and coalesce(n.status, '') in ('superseded', 'archived'))"
        )
        return clause, [MEMORY, SESSION, PLAN]
    if status != "any":
        return "n.status = ?", [status]
    return None


def _valid_filter(valid: str, today: str) -> Filter:
    """``current``: no valid_until or not yet past; ``expired``: valid_until before today."""
    if valid == "expired":
        return "n.valid_until < ?", [today]
    return "(n.valid_until is null or n.valid_until >= ?)", [today]


def _linked_filter(rel: str) -> Filter:
    return (
        "(n.path != ? and (n.path in (select src from links where dst_path = ?) "
        "or n.path in (select dst_path from links where src = ? and dst_path is not null)))",
        [rel, rel, rel],
    )


def extra_filters(
    priority_min: int | None, valid: str | None, today: str | None, linked_to: str | None
) -> list[Filter]:
    """The priority, validity and link filters, when given."""
    out: list[Filter] = []
    if priority_min is not None:
        out.append(("n.priority >= ?", [priority_min]))
    if valid and today:
        out.append(_valid_filter(valid, today))
    if linked_to:
        out.append(_linked_filter(linked_to))
    return out


def _equals_filters(**columns: str | None) -> list[Filter]:
    """``n.<column> = ?`` for each column that was given."""
    return [(f"n.{col} = ?", [value]) for col, value in columns.items() if value]


def build_where(
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
    zone: str | None = None,
    extra: list[Filter] | None = None,
) -> Built | None:
    """The ``(source, clause, params, terms)`` of a search; None if the query has no terms."""
    terms: list[list[str]] = []
    filters: list[Filter | None] = []
    if query is not None:
        terms = query_terms(query, drop_stopwords=drop_stopwords)
        if not terms:
            return None
        filters.append(_match_filter(terms, any_term))
    if path:
        filters.append(_path_filter(path))
    if project:
        filters.append(_project_filter(project))
    filters.extend(_equals_filters(type=type, mode=mode, zone=zone))
    filters.append(_status_filter(status))
    filters.extend(extra or [])
    filters.extend(
        ("n.path in (select path from tags where tag = ?)", [normalize_tag(tag)])
        for tag in tags or []
    )
    present = [f for f in filters if f is not None]
    params = [p for _, values in present for p in values]
    source = "from fts join notes n on n.id = fts.rowid" if query is not None else "from notes n"
    return Built(source, " and ".join(c for c, _ in present) or "1", params, terms)
