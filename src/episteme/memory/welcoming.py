"""The session welcome."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any, NamedTuple

from episteme.hookmode import clean_line
from episteme.index import is_past
from episteme.memory.schema import UPCOMING_DAYS
from episteme.memory.scoring import _neg_date, entry_line, welcome_score
from episteme.vault import today

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from episteme.engine import Engine

RANKED_MAX = 10  # welcome: most entries in "Memorias"

WELCOME_RESERVE = 160  # welcome: minimum chars of the 4000 held back for the "no caben aquí" line


class _Page:
    """The welcome being built: its lines, entries and the character budget left."""

    def __init__(self, header: str, budget: int, reserve: int) -> None:
        self.lines = [header]
        self.entries: list[dict[str, Any]] = []
        self.budget = budget
        self.reserve = reserve
        self.ranked = 0
        self.missed = {"norms": 0, "reminders": 0}

    def _fits(self, extra: int, ranked_entry: bool) -> bool:
        """Whether ``extra`` chars (and a ranked slot, if needed) are still available."""
        if ranked_entry and self.ranked >= RANKED_MAX:
            return False
        return extra <= self.budget

    def _add(self, line: str, section: str | None, ranked_entry: bool) -> bool:
        extra = len(line) + 1 + (len(section) + 1 if section else 0)
        if not self._fits(extra, ranked_entry):
            return False
        if section:
            self.lines.append(section)
        self.lines.append(line)
        self.budget -= extra
        self.ranked += ranked_entry
        return True

    def add_group(
        self,
        items: Iterable[tuple[Any, float | None]],
        section: str,
        kind: str,
        line_of: Callable[[Any], str],
        ranked: bool = False,
    ) -> int:
        """List ``(row, score)`` items under ``section`` until one does not fit.

        Returns how many were left out.
        """
        items = list(items)
        for i, (r, score) in enumerate(items):
            if not self._add(line_of(r), None if i else section, ranked):
                return len(items) - i
            self.entries.append(
                {
                    "path": r["path"],
                    "score": None if score is None else round(score, 4),
                    "kind": kind,
                }
            )
        return 0

    def release_reserve(self) -> None:
        """Nothing to warn about: the reserve goes back to the rest."""
        if not any(self.missed.values()):
            self.budget += self.reserve


def _reminder_line(r: Any) -> str:
    return f"- [{r['due']}] {clean_line(r['title'])} ({r['path']})"


def _memory_order(scored: list[tuple[float, Any]], project: str) -> list[tuple[Any, float | None]]:
    """The ranked memories, with the ``_shared`` ones past ``SHARED_MAX`` moved to the end."""
    main: list[tuple[Any, float | None]] = []
    spill: list[tuple[Any, float | None]] = []
    shared_used = 0
    for score, r in scored:
        if project != "_shared" and r["project"] == "_shared":
            if shared_used >= SHARED_MAX:
                spill.append((r, score))
                continue
            shared_used += 1
        main.append((r, score))
    return main + spill


def welcome_notice(project: str, norms: int, reminders: int) -> str:
    parts = []
    if norms:
        parts.append(f"+{norms} normas")
    if reminders:
        parts.append(f"+{reminders} recordatorios")
    return (
        f"({' y '.join(parts)} no caben aquí: "
        f'search(project="{project}", zone="memory", type="reminder") o review)'
    )


SHARED_MAX = 3  # welcome: most `_shared` memories listed ahead of the project's own


class _Buckets(NamedTuple):
    """The rows of the welcome, split by section."""

    overdue: list[Any]
    upcoming: list[Any]
    norms: list[Any]
    scored: list[tuple[float, Any]]


def _is_candidate(r: Any, iso: str) -> bool:
    """Whether ``r`` can be listed under "Normas" or "Memorias"."""
    if r["type"] in ("session", "reminder"):
        return False
    return not is_past(r["valid_until"], iso)


def _bucket(rows: list[Any], now: dt.date, upcoming_days: int) -> _Buckets:
    """Split ``rows`` into overdue and upcoming reminders, norms and scored memories."""
    iso = now.isoformat()
    soon = (now + dt.timedelta(days=upcoming_days)).isoformat()
    reminders = sorted(
        (r for r in rows if r["type"] == "reminder" and r["due"]),
        key=lambda r: (r["due"], r["path"]),
    )
    overdue = [r for r in reminders if r["due"] <= iso]
    upcoming = [r for r in reminders if iso < r["due"] <= soon]
    candidates = [r for r in rows if _is_candidate(r, iso)]
    norms = sorted(
        (r for r in candidates if r["priority"] == 5),
        key=lambda r: (_neg_date(r["created"]), r["path"]),
    )
    scored = sorted(
        ((welcome_score(r, now), r) for r in candidates if r["priority"] != 5),
        key=lambda x: (-x[0], _neg_date(x[1]["created"]), x[1]["path"]),
    )
    return _Buckets(overdue, upcoming, norms, scored)


def _fill_page(page: _Page, buckets: _Buckets, project: str, upcoming_days: int) -> None:
    """List the groups: overdue, norms, then (reserve released) upcoming and memories."""
    page.missed["reminders"] = page.add_group(
        [(r, None) for r in buckets.overdue], "Recordatorios vencidos:", "reminder", _reminder_line
    )
    page.missed["norms"] = page.add_group(
        [(r, None) for r in buckets.norms], "Normas:", "norm", entry_line
    )
    page.release_reserve()
    page.add_group(
        [(r, None) for r in buckets.upcoming],
        f"Vencen pronto ({upcoming_days} días):",
        "reminder",
        _reminder_line,
    )
    page.add_group(
        _memory_order(buckets.scored, project), "Memorias:", "memory", entry_line, ranked=True
    )


def welcome(
    engine: Engine, project: str | None, upcoming_days: int = UPCOMING_DAYS
) -> tuple[str, list[dict[str, Any]]]:
    """The welcome text (4000 chars max).

    Sections, in order: overdue reminders, "Normas" (every active priority-5 memory, whatever
    its age), "Vencen pronto" (reminders due within ``upcoming_days``) and "Memorias" (the
    10 best by score, without the norms already listed). At most ``SHARED_MAX`` of those are
    ``_shared`` ones (when the project is not ``_shared``); the extra ``_shared`` memories only
    fill the slots left once the others are listed. A reserve of ``max(WELCOME_RESERVE, longest
    notice for the project)`` characters is held back: if an overdue reminder or a priority-5
    norm did not fit, a last line says how many were left out; otherwise the reserve goes back
    to the memories.
    """
    project = engine.need_project(project)
    now = today()
    rows = engine.index.memories("project in (?, '_shared') and status = 'active'", (project,))
    buckets = _bucket(rows, now, upcoming_days)
    header = f"episteme · memoria de {project}"
    reserve = max(WELCOME_RESERVE, len(welcome_notice(project, 99999, 99999)) + 1)
    page = _Page(header, 4000 - len(header) - 1 - reserve, reserve)
    _fill_page(page, buckets, project, upcoming_days)
    missed = any(page.missed.values())
    if not page.entries and not missed:
        return "", []
    if missed:
        page.lines.append(welcome_notice(project, page.missed["norms"], page.missed["reminders"]))
    return "\n".join(page.lines), page.entries
