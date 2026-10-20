"""Engine: the vault, its index and the default project, shared by every tool."""

from __future__ import annotations

import re
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from episteme.errors import NOT_FOUND, EpistemeError, invalid
from episteme.index import Index, jsonable
from episteme.links import reachable
from episteme.markdown import ParsedNote, clip, clip_at_newline, find_section, parse
from episteme.vault import Vault, is_ignored

READ_CAP = 20_000
SECTION_CAP = 60_000


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

    # -- search ------------------------------------------------------------

    def search(
        self,
        query: str,
        path: str | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        project: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not (1 <= limit <= 100):
            raise invalid(f"limit must be 1-100, got {limit}.")
        if not query or not re.search(r"[^\W_]", query):
            raise invalid("query has no words. Pass the words to look for.")
        if path:
            self.check_path(path.strip().rstrip("/") or "/")
        hits, total = self.index.search(
            query,
            path=path,
            type=type,
            tags=tags,
            project=project,
            status=status,
            limit=limit,
        )
        return {
            "results": [
                {
                    "path": h.path,
                    "title": h.title,
                    "line": h.line,
                    "snippet": h.snippet,
                    "score": h.score,
                }
                for h in hits
            ],
            "total": total,
        }

    # -- read --------------------------------------------------------------

    def read(self, note: str, heading: str | None = None, lines: str | None = None) -> dict:
        if heading is not None and lines is not None:
            raise invalid("pass heading or lines, not both.")
        rel = self.resolve_note(note)
        parsed = self.load(rel)
        total = len(parsed.lines)
        if heading is not None:
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
        content = "\n".join(parsed.lines[start:end])
        truncated = len(content) > cap
        if truncated:
            notice_room = 200
            kept = clip_at_newline(content, cap - notice_room)
            shown = kept.count("\n") + 1
            missing = (end - start) - shown
            content = (
                f"{kept}\n[truncated: {missing} more lines (file lines {start + shown + 1}-{end}). "
                "Use heading or lines to read the rest.]"
            )
        return {
            "path": rel,
            "frontmatter": jsonable(parsed.frontmatter),
            "fm_valid": parsed.fm_valid,
            "outline": [
                {"level": h.level, "text": h.text, "line": h.line} for h in parsed.headings
            ],
            "content": content,
            "truncated": truncated,
            "total_lines": total,
        }

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
