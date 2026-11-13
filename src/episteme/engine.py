"""Engine: the vault, its index and the default project, shared by every tool."""

from __future__ import annotations

import difflib
import re
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from episteme.errors import NOT_FOUND, EpistemeError, invalid
from episteme.index import Index, jsonable, normalize_tag, query_terms, to_json
from episteme.links import reachable
from episteme.markdown import (
    ParsedNote,
    clip,
    clip_at_newline,
    find_section,
    parse,
    section_end,
)
from episteme.vault import Vault, is_ignored

READ_CAP = 20_000
BATCH_MAX = 20
BATCH_CAP = 50_000
SECTION_CAP = 60_000
PARTIAL_BELOW = 3
PARTIAL_MAX = 5
SEARCH_LIMIT_MAX = 100
HEADING_NAMES_CAP = 4000
NOTICE_ROOM = 200
SIMILAR_TAGS_MAX = 5
SIMILAR_TAGS_CUTOFF = 0.6
LINKS_DEPTH_MAX = 3
NO_MATCH_HINT = (
    "Nothing matches. search is literal: try the plural, the abbreviation or the "
    'proper name, all in one query with match="any", or drop a filter. '
    "If you find the answer elsewhere, save it with remember."
)


class Engine:
    def __init__(self, root: Path, project: str | None = None) -> None:
        self.vault = Vault(root)
        self.project = project
        self._index: Index | None = None
        self._lock = threading.Lock()

    @property
    def index(self) -> Index:
        if self._index is None:
            self._index = Index(self.vault)
        return self._index

    @contextmanager
    def session(self) -> Generator[Engine]:
        """Serialize tool calls and reindex what changed on disk first."""
        with self._lock:
            self.index.refresh()
            yield self

    # -- shared helpers ----------------------------------------------------

    def need_project(self, project: str | None) -> str:
        project = project or self.project
        if not project:
            raise invalid("no project given and the server has no --project. Pass project.")
        return project

    def check_path(self, raw: str) -> None:
        """Reject absolute paths, ``..`` and symlinks leaving the vault (``outside_vault``)."""
        self.vault.resolve(raw)
        if not raw.lower().endswith(".md"):
            self.vault.resolve(raw + ".md")

    def resolve_note(self, note: str) -> str:
        """A path (with or without ``.md``) or a note name, resolved to a vault path."""
        if not isinstance(note, str) or not note.strip():
            raise invalid("note is empty. Pass a path relative to the vault or a note name.")
        note = note.strip()
        self.check_path(note)
        rel = self.index.resolver().resolve(note)
        if is_ignored(rel):
            raise EpistemeError(NOT_FOUND, f'no note "{note}". Use search to find the path.')
        return rel

    def load(self, rel: str) -> ParsedNote:
        path = self.vault.resolve(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise EpistemeError(
                NOT_FOUND, f'no note "{rel}". Use search to find the path.'
            ) from exc
        return parse(text, rel)

    def _row(self, h: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "path": h.path,
            "title": h.title,
            "line": h.line,
            "snippet": h.snippet,
            "score": h.score,
            **_optional_fields(h),
        }
        heading = self.index.heading_at(h.path, h.line)
        if heading:
            row["heading"] = heading
        if h.status == "superseded":
            newer = self.index.superseded_by(h.path)
            if newer:
                row["superseded_by"] = newer
        return row

    def _rows(self, hits: list[Any], query: str | None = None) -> list[dict[str, Any]]:
        """Result rows; with ``query`` (an OR search) each row lists the terms it has."""
        matched = self.index.matched_terms(query, [h.path for h in hits]) if query else {}
        rows = []
        for h in hits:
            row = self._row(h)
            if query:
                row["matched"] = matched.get(h.path, [])
            rows.append(row)
        return rows

    def _hints(self, query: str | None, f: _Filters, zones: list[str]) -> list[str]:
        hints = [
            *self._unknown_value_hints(f.type, f.project, f.status),
            *self._unknown_tag_hints(f.tags),
            *self._unknown_path_hints(f.path, zones),
        ]
        if not hints and query is not None:
            hints.append(NO_MATCH_HINT)
        return hints

    def _unknown_value_hints(
        self, type: str | None, project: str | None, status: str | None
    ) -> list[str]:
        hints = [
            hint
            for label, value in (("type", type), ("project", project))
            if (hint := self._unknown_label_hint(label, value))
        ]
        status_hint = self._unknown_status_hint(status)
        return [*hints, status_hint] if status_hint else hints

    def _unknown_label_hint(self, label: str, value: str | None) -> str | None:
        if not value:
            return None
        known = self.index.known(label)
        if value in known:
            return None
        return (
            f'no note has {label} "{value}". '
            f"{label.capitalize()}s in the vault: {', '.join(known)}."
        )

    def _unknown_status_hint(self, status: str | None) -> str | None:
        if not status or status == "any":
            return None
        known = self.index.known("status")
        if status in known:
            return None
        return (
            f'no note has status "{status}". Statuses in the vault: {", ".join(known)}. '
            '"any" includes superseded and archived.'
        )

    def _unknown_tag_hints(self, tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        hints: list[str] = []
        known_tags = self.index.known_tags()
        for tag in tags:
            norm = normalize_tag(tag)
            if norm in known_tags:
                continue
            similar = difflib.get_close_matches(
                norm, known_tags, n=SIMILAR_TAGS_MAX, cutoff=SIMILAR_TAGS_CUTOFF
            )
            text = f'no note has tag "{tag}".'
            if similar:
                text += f" Similar tags: {', '.join(similar)}."
            hints.append(text)
        return hints

    def _unknown_path_hints(self, path: str | None, zones: list[str]) -> list[str]:
        if not path:
            return []
        prefix = path.strip().strip("/")
        hits, _ = self.index.search(None, path=prefix, status="any", limit=1, snippets=False)
        if hits:
            return []
        return [f'no note under "{path}". Zones: {", ".join(zones)}.']

    # -- search ------------------------------------------------------------

    def search(
        self,
        query: str | None = None,
        path: str | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        project: str | None = None,
        status: str | None = None,
        limit: int = 20,
        zone: str | None = None,
        facets: bool = False,
        match: str = "all",
    ) -> dict[str, Any]:
        query = _check_query(query, match, limit, bool(tags or type or project or zone or facets))
        any_mode = match == "any" and query is not None
        if path:
            self.check_path(path.strip().rstrip("/") or "/")
        zones = sorted(z.path for z in self.vault.config.zones)
        zone = _check_zone(zone, zones)
        f = _Filters(path, type, tags, project, status, zone)
        kwargs = f.as_kwargs()
        hits, total, fallback = self._run_query(query, f, kwargs, any_mode, limit, facets)
        out = self._build_search_out(query, hits, total, fallback, any_mode, kwargs)
        if total == 0:
            hints = self._hints(query, f, zones)
            if hints:
                out["hints"] = hints
        if facets:
            out["facets"] = self.index.facets(query, any_term=fallback or any_mode, **kwargs)
        return out

    def _run_query(
        self,
        query: str | None,
        f: _Filters,
        kwargs: dict[str, Any],
        any_mode: bool,
        limit: int,
        facets: bool,
    ) -> tuple[list[Any], int, bool]:
        """Run the search; return the hits, the total and whether it fell back to OR."""
        index = self.index
        if _only_facets(query, f, facets):
            return [], index.search(None, limit=1, snippets=False, **kwargs)[1], False
        hits, total = index.search(query, any_term=any_mode, limit=limit, **kwargs)
        if not _should_fall_back(any_mode, total, query):
            return hits, total, False
        hits, total = index.search(query, any_term=True, limit=limit, **kwargs)
        return hits, total, bool(hits)

    def _build_search_out(
        self,
        query: str | None,
        hits: list[Any],
        total: int,
        fallback: bool,
        any_mode: bool,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "results": self._rows(hits, query if (any_mode or fallback) else None),
            "total": total,
        }
        if fallback:
            out["match"] = "or"
            out["note"] = "No note has all the words; showing notes with any of them (OR)."
        elif not any_mode and query is not None:
            self._add_partial(out, query, hits, total, kwargs)
        return out

    def _add_partial(
        self, out: dict[str, Any], query: str, hits: list[Any], total: int, kwargs: dict[str, Any]
    ) -> None:
        """Few AND matches: also list notes that have some of the words."""
        if not _wants_partial(query, hits, total):
            return
        seen = {h.path for h in hits}
        more, _ = self.index.search(query, any_term=True, limit=PARTIAL_MAX + len(seen), **kwargs)
        extra = [h for h in more if h.path not in seen][:PARTIAL_MAX]
        if extra:
            out["partial"] = self._rows(extra, query)
            out["note"] = "Few notes have all the words; partial lists notes with some of them."

    # -- read --------------------------------------------------------------

    def read(
        self,
        note: str,
        heading: str | None = None,
        lines: str | None = None,
        outline: bool | None = None,
        content: bool = True,
    ) -> dict[str, Any]:
        _check_read_args(heading, lines, outline, content)
        rel = self.resolve_note(note)
        parsed = self.load(rel)
        partial = heading is not None or lines is not None
        start, end, cap = _read_window(parsed, rel, heading, lines, content)
        text, truncated, shown_end = _truncate("\n".join(parsed.lines[start:end]), start, end, cap)
        return _read_result(
            rel,
            parsed,
            text=text,
            truncated=truncated,
            with_outline=_wants_outline(outline, partial),
            line_range=f"{start + 1}-{shown_end}" if partial else None,
        )

    def read_many(
        self,
        notes: list[str],
        heading: str | None = None,
        lines: str | None = None,
        outline: bool | None = None,
        content: bool = True,
    ) -> dict[str, Any]:
        """Several whole notes in one call; a note that fails is reported, not raised."""
        _check_batch_args(notes, heading, lines, outline, content)
        wanted = None if not content else bool(outline)
        out_notes, pending = self._read_batch(notes, wanted, content)
        out: dict[str, Any] = {"notes": out_notes}
        if pending:
            out["pending"] = pending
            out["note"] = "Output limit reached; call read again with the notes in pending."
        return out

    def _read_batch(
        self, notes: list[str], wanted: bool | None, content: bool
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Read each note; return the items and the notes left over once BATCH_CAP is hit."""
        out_notes: list[dict[str, Any]] = []
        seen: set[str] = set()
        used = 0
        for pos, raw in enumerate(notes):
            try:
                item = self.read(raw, None, None, wanted, content)
            except EpistemeError as exc:
                out_notes.append({"note": raw, "error": str(exc)})
                continue
            if item["path"] in seen:
                continue
            # The cap is on the JSON of each note, not on its body: with content=false or
            # outline=true the outline is what weighs.
            size = len(to_json(item))
            if seen and used + size > BATCH_CAP:
                return out_notes, notes[pos:]
            seen.add(item["path"])
            used += size
            out_notes.append(item)
        return out_notes, []

    # -- links -------------------------------------------------------------

    def links(self, note: str, direction: str = "both", depth: int = 1) -> dict[str, Any]:
        _check_links_args(direction, depth)
        rel = self.resolve_note(note)
        out: dict[str, Any] = {"path": rel, "outgoing": [], "backlinks": []}
        if direction in ("out", "both"):
            out["outgoing"] = self._outgoing_rows(rel)
        if direction in ("in", "both"):
            out["backlinks"] = self._backlink_rows(rel)
        if depth > 1:
            out["reachable"] = [
                {"path": p, "distance": d} for p, d in reachable(rel, self._neighbours, depth)
            ]
        return out

    def _outgoing_rows(self, rel: str) -> list[dict[str, Any]]:
        return [
            {
                "target": r["dst_raw"] or f"#{r['heading'] or ''}",
                "path": r["dst_path"],
                "kind": r["kind"],
                "heading": r["heading"],
                "line": r["line"],
                "resolved": r["dst_path"] is not None and not r["heading_missing"],
            }
            for r in self.index.outgoing(rel)
        ]

    def _backlink_rows(self, rel: str) -> list[dict[str, Any]]:
        return [
            {"path": r["src"], "kind": r["kind"], "line": r["line"]}
            for r in self.index.backlinks(rel)
        ]

    def _neighbours(self, p: str) -> list[str]:
        return sorted(
            {
                r["dst_path"]
                for r in self.index.outgoing(p)
                if r["dst_path"] and r["dst_path"] != p
            }
        )


@dataclass(frozen=True)
class _Filters:
    """The search filters as the caller gave them (``project`` not yet expanded)."""

    path: str | None
    type: str | None
    tags: list[str] | None
    project: str | None
    status: str | None
    zone: str | None

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "tags": self.tags,
            "project": _project_scope(self.project),
            "status": self.status,
            "zone": self.zone,
        }

    def is_empty(self) -> bool:
        return not (self.path or self.type or self.tags or self.project or self.zone or self.status)


def _project_scope(project: str | None) -> str | list[str] | None:
    """A project also sees the ``_shared`` memories."""
    if project and project != "_shared":
        return [project, "_shared"]
    return project


def _only_facets(query: str | None, f: _Filters, facets: bool) -> bool:
    return query is None and facets and f.is_empty()


def _should_fall_back(any_mode: bool, total: int, query: str | None) -> bool:
    """An AND search with no hits and several words is retried as OR."""
    return not any_mode and total == 0 and query is not None and len(query_terms(query)) > 1


def _wants_partial(query: str, hits: list[Any], total: int) -> bool:
    return 1 <= total < PARTIAL_BELOW and total == len(hits) and len(query_terms(query)) > 1


def _optional_fields(h: Any) -> dict[str, Any]:
    """The hit fields that are set, in row order."""
    keys = ("zone", "type", "status", "project", "created", "priority")
    return {key: getattr(h, key) for key in keys if getattr(h, key) is not None}


def _check_read_args(
    heading: str | None, lines: str | None, outline: bool | None, content: bool
) -> None:
    if heading is not None and lines is not None:
        raise invalid("pass heading or lines, not both.")
    if not content and (heading is not None or lines is not None or outline is False):
        raise invalid(
            "content=false returns only the outline. Drop heading, lines and outline=false."
        )


def _wants_outline(outline: bool | None, partial: bool) -> bool:
    return outline is True or (outline is None and not partial)


def _read_result(
    rel: str,
    parsed: ParsedNote,
    *,
    text: str,
    truncated: bool,
    with_outline: bool,
    line_range: str | None,
) -> dict[str, Any]:
    """The read payload; ``line_range`` is None unless a heading or lines were asked for."""
    out: dict[str, Any] = {
        "path": rel,
        "frontmatter": jsonable(parsed.frontmatter),
        "fm_valid": parsed.fm_valid,
    }
    if with_outline:
        out["outline"] = _outline(parsed)
    out["content"] = text
    out["truncated"] = truncated
    out["total_lines"] = len(parsed.lines)
    if line_range is not None:
        out["range"] = line_range
    return out


def _check_batch_args(
    notes: list[str],
    heading: str | None,
    lines: str | None,
    outline: bool | None,
    content: bool,
) -> None:
    if heading is not None or lines is not None:
        raise invalid("heading and lines apply to one note. Use note, or drop them.")
    if not content and outline is False:
        raise invalid("content=false returns only the outline. Drop outline=false.")
    if not isinstance(notes, list) or not notes:
        raise invalid("notes is empty. Pass 1-20 paths or note names.")
    if len(notes) > BATCH_MAX:
        raise invalid(f"notes takes at most {BATCH_MAX} notes, got {len(notes)}. Split the list.")


def _check_links_args(direction: str, depth: int) -> None:
    if direction not in ("out", "in", "both"):
        raise invalid(f'direction must be "out", "in" or "both", got "{direction}".')
    if not (1 <= depth <= LINKS_DEPTH_MAX):
        raise invalid(f"depth must be 1-{LINKS_DEPTH_MAX}, got {depth}.")


def _check_query(query: str | None, match: str, limit: int, has_filter: bool) -> str | None:
    """Validate the search arguments; return the query, or None when it is blank."""
    if match not in ("all", "any"):
        raise invalid(f'match must be "all" or "any", got "{match}".')
    if not (1 <= limit <= SEARCH_LIMIT_MAX):
        raise invalid(f"limit must be 1-{SEARCH_LIMIT_MAX}, got {limit}.")
    if query is not None and not query.strip():
        query = None
    if query is None:
        if not has_filter:
            raise invalid(
                "query has no words. Pass the words to look for, or tags, type, project or zone."
            )
    elif not re.search(r"[^\W_]", query):
        raise invalid("query has no words. Pass the words to look for.")
    return query


def _check_zone(zone: str | None, zones: list[str]) -> str | None:
    zone = zone.strip().strip("/") if zone else None
    if zone and zone not in zones:
        raise invalid(f'unknown zone "{zone}". Use one of: {", ".join(zones)}.')
    return zone


def _read_window(
    parsed: ParsedNote, rel: str, heading: str | None, lines: str | None, content: bool
) -> tuple[int, int, int]:
    """The 0-based [start, end) lines to show and the character cap that applies."""
    if not content:
        return 0, 0, READ_CAP
    if lines is not None:
        start, end = _parse_range(lines, len(parsed.lines))
        return start, end, SECTION_CAP
    if heading is None:
        return parsed.fm_end, len(parsed.lines), READ_CAP
    rng = find_section(parsed, heading)
    if rng is None:
        names = clip(", ".join(f'"{h.text}"' for h in parsed.headings), HEADING_NAMES_CAP)
        raise EpistemeError(
            NOT_FOUND,
            f'no heading "{heading}" in {rel}. Headings are: {names or "none"}.',
        )
    return rng[0], rng[1], SECTION_CAP


def _truncate(text: str, start: int, end: int, cap: int) -> tuple[str, bool, int]:
    """Cut ``text`` to ``cap`` characters with a notice; return it, the flag and the last line."""
    if len(text) <= cap:
        return text, False, end
    kept = clip_at_newline(text, cap - NOTICE_ROOM)
    shown = kept.count("\n") + 1
    missing = (end - start) - shown
    notice = (
        f"{kept}\n[truncated: {missing} more lines (file lines {start + shown + 1}-{end}). "
        "Use heading or lines to read the rest.]"
    )
    return notice, True, start + shown


def _parse_range(spec: str, total: int) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", spec or "")
    if not m:
        raise invalid(f'lines must look like "10-40", got "{spec}".')
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else first
    if first < 1 or last < first:
        raise invalid(f'lines "{spec}" is not a valid 1-based range.')
    if first > total:
        raise invalid(f'lines "{spec}" starts after the end of the note ({total} lines).')
    return first - 1, min(last, total)


def _outline(parsed: ParsedNote) -> list[dict[str, Any]]:
    """Headings with `end`, the last 1-based line of each section (same rule as find_section)."""
    return [
        {"level": h.level, "text": h.text, "line": h.line, "end": section_end(parsed, idx)}
        for idx, h in enumerate(parsed.headings)
    ]
