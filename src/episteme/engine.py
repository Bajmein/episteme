"""Engine: the vault, its index and the default project, shared by every tool."""

from __future__ import annotations

import difflib
import re
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from episteme.errors import NOT_FOUND, EpistemeError, invalid
from episteme.index import Index, jsonable, query_terms
from episteme.links import reachable
from episteme.markdown import ParsedNote, clip, clip_at_newline, find_section, parse
from episteme.vault import Vault, is_ignored

READ_CAP = 20_000
SECTION_CAP = 60_000
PARTIAL_BELOW = 3
PARTIAL_MAX = 5


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
        }
        for key in ("zone", "type", "status", "project", "created", "priority"):
            value = getattr(h, key)
            if value is not None:
                row[key] = value
        heading = self.index.heading_at(h.path, h.line)
        if heading:
            row["heading"] = heading
        if h.status == "superseded":
            newer = self.index.superseded_by(h.path)
            if newer:
                row["superseded_by"] = newer
        return row

    def _hints(
        self,
        query: str | None,
        path: str | None,
        type: str | None,
        tags: list[str] | None,
        project: str | None,
        status: str | None,
    ) -> list[str]:
        from episteme.index import normalize_tag

        hints: list[str] = []
        idx = self.index
        for label, value in (("type", type), ("project", project)):
            if value:
                known = idx.known(label)
                if value not in known:
                    hints.append(
                        f'no note has {label} "{value}". '
                        f"{label.capitalize()}s in the vault: {', '.join(known)}."
                    )
        if status and status != "any":
            known = idx.known("status")
            if status not in known:
                hints.append(
                    f'no note has status "{status}". Statuses in the vault: {", ".join(known)}. '
                    '"any" includes superseded and archived.'
                )
        if tags:
            known_tags = idx.known_tags()
            for tag in tags:
                norm = normalize_tag(tag)
                if norm in known_tags:
                    continue
                similar = difflib.get_close_matches(norm, known_tags, n=5, cutoff=0.6)
                text = f'no note has tag "{tag}".'
                if similar:
                    text += f" Similar tags: {', '.join(similar)}."
                hints.append(text)
        if path:
            prefix = path.strip().strip("/")
            hits, _ = idx.search(None, path=prefix, status="any", limit=1)
            if not hits:
                zones = ", ".join(sorted(z.path for z in self.vault.config.zones))
                hints.append(f'no note under "{path}". Zones: {zones}.')
        if not hints and query is not None:
            hints.append(
                "Nothing matches. search is literal: try the plural, the abbreviation or the "
                "proper name, or drop a filter. If you find the answer elsewhere, save it "
                "with remember."
            )
        return hints

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
    ) -> dict[str, Any]:
        if not (1 <= limit <= 100):
            raise invalid(f"limit must be 1-100, got {limit}.")
        if query is not None and not query.strip():
            query = None
        if query is None:
            if not (tags or type or project or zone or facets):
                raise invalid(
                    "query has no words. "
                    "Pass the words to look for, or tags, type, project or zone."
                )
        elif not re.search(r"[^\W_]", query):
            raise invalid("query has no words. Pass the words to look for.")
        if path:
            self.check_path(path.strip().rstrip("/") or "/")
        zone = zone.strip().strip("/") if zone else None
        if zone and zone not in {z.path for z in self.vault.config.zones}:
            known = ", ".join(sorted(z.path for z in self.vault.config.zones))
            raise invalid(f'unknown zone "{zone}". Use one of: {known}.')
        projects: str | list[str] | None = project
        if project and project != "_shared":
            projects = [project, "_shared"]
        kwargs: dict[str, Any] = {
            "path": path,
            "type": type,
            "tags": tags,
            "project": projects,
            "status": status,
            "zone": zone,
        }
        index = self.index
        if query is None and facets and not (path or type or tags or project or zone or status):
            hits: list[Any] = []
            total = index.search(None, limit=1, **kwargs)[1]
        else:
            hits, total = index.search(query, limit=limit, **kwargs)
        fallback = False
        if total == 0 and query is not None and len(query_terms(query)) > 1:
            hits, total = index.search(query, any_term=True, limit=limit, **kwargs)
            fallback = bool(hits)
        out: dict[str, Any] = {"results": [self._row(h) for h in hits], "total": total}
        if fallback:
            out["match"] = "or"
            out["note"] = "No note has all the words; showing notes with any of them (OR)."
        elif (
            query is not None
            and 1 <= total < PARTIAL_BELOW
            and total == len(hits)
            and len(query_terms(query)) > 1
        ):
            seen = {h.path for h in hits}
            more, _ = index.search(
                query, any_term=True, limit=PARTIAL_MAX + len(seen), **kwargs
            )
            extra = [self._row(h) for h in more if h.path not in seen][:PARTIAL_MAX]
            if extra:
                out["partial"] = extra
                out["note"] = "Few notes have all the words; partial lists notes with some of them."
        if total == 0:
            hints = self._hints(query, path, type, tags, project, status)
            if hints:
                out["hints"] = hints
        if facets:
            out["facets"] = index.facets(query, any_term=fallback, **kwargs)
        return out

    # -- read --------------------------------------------------------------

    def read(
        self,
        note: str,
        heading: str | None = None,
        lines: str | None = None,
        outline: bool | None = None,
        content: bool = True,
    ) -> dict:
        if heading is not None and lines is not None:
            raise invalid("pass heading or lines, not both.")
        if not content and (heading is not None or lines is not None or outline is False):
            raise invalid(
                "content=false returns only the outline. Drop heading, lines and outline=false."
            )
        rel = self.resolve_note(note)
        parsed = self.load(rel)
        total = len(parsed.lines)
        partial = heading is not None or lines is not None
        if not content:
            start = end = 0
            cap = READ_CAP
        elif heading is not None:
            rng = find_section(parsed, heading)
            if rng is None:
                names = clip(", ".join(f'"{h.text}"' for h in parsed.headings), 4000)
                raise EpistemeError(
                    NOT_FOUND,
                    f'no heading "{heading}" in {rel}. Headings are: {names or "none"}.',
                )
            start, end, cap = rng[0], rng[1], SECTION_CAP
        elif lines is not None:
            start, end = _parse_range(lines, total)
            cap = SECTION_CAP
        else:
            start, end, cap = parsed.fm_end, total, READ_CAP
        text = "\n".join(parsed.lines[start:end])
        truncated = len(text) > cap
        shown_end = end
        if truncated:
            notice_room = 200
            kept = clip_at_newline(text, cap - notice_room)
            shown = kept.count("\n") + 1
            missing = (end - start) - shown
            shown_end = start + shown
            text = (
                f"{kept}\n[truncated: {missing} more lines (file lines {start + shown + 1}-{end}). "
                "Use heading or lines to read the rest.]"
            )
        out: dict[str, Any] = {
            "path": rel,
            "frontmatter": jsonable(parsed.frontmatter),
            "fm_valid": parsed.fm_valid,
        }
        if outline is True or (outline is None and not partial):
            out["outline"] = _outline(parsed)
        out["content"] = text
        out["truncated"] = truncated
        out["total_lines"] = total
        if partial:
            out["range"] = f"{start + 1}-{shown_end}"
        return out

    # -- links -------------------------------------------------------------

    def links(self, note: str, direction: str = "both", depth: int = 1) -> dict[str, Any]:
        if direction not in ("out", "in", "both"):
            raise invalid(f'direction must be "out", "in" or "both", got "{direction}".')
        if not (1 <= depth <= 3):
            raise invalid(f"depth must be 1-3, got {depth}.")
        rel = self.resolve_note(note)
        out: dict[str, Any] = {"path": rel, "outgoing": [], "backlinks": []}
        if direction in ("out", "both"):
            out["outgoing"] = [
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
        if direction in ("in", "both"):
            out["backlinks"] = [
                {"path": r["src"], "kind": r["kind"], "line": r["line"]}
                for r in self.index.backlinks(rel)
            ]
        if depth > 1:

            def neighbours(p: str) -> list[str]:
                return sorted(
                    {
                        r["dst_path"]
                        for r in self.index.outgoing(p)
                        if r["dst_path"] and r["dst_path"] != p
                    }
                )

            out["reachable"] = [
                {"path": p, "distance": d} for p, d in reachable(rel, neighbours, depth)
            ]
        return out


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


def _outline(parsed) -> list[dict]:
    """Headings with `end`, the last 1-based line of each section (same rule as find_section)."""
    out = []
    for idx, h in enumerate(parsed.headings):
        end = len(parsed.lines)
        for nxt in parsed.headings[idx + 1 :]:
            if nxt.level <= h.level:
                end = nxt.line - 1
                break
        out.append({"level": h.level, "text": h.text, "line": h.line, "end": end})
    return out
