"""The session welcome."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from episteme.memory.schema import UPCOMING_DAYS
from episteme.memory.scoring import _neg_date, entry_line, welcome_score
from episteme.vault import today

if TYPE_CHECKING:
    from episteme.engine import Engine

WELCOME_RESERVE = 160  # welcome: minimum chars of the 4000 held back for the "no caben aquí" line


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
    iso = now.isoformat()
    soon = (now + dt.timedelta(days=upcoming_days)).isoformat()
    rows = engine.index.memories("project in (?, '_shared') and status = 'active'", (project,))
    reminders = sorted(
        (r for r in rows if r["type"] == "reminder" and r["due"]),
        key=lambda r: (r["due"], r["path"]),
    )
    overdue = [r for r in reminders if r["due"] <= iso]
    upcoming = [r for r in reminders if iso < r["due"] <= soon]
    candidates = [
        r
        for r in rows
        if r["type"] not in ("session", "reminder")
        and not (r["valid_until"] and r["valid_until"] < iso)
    ]
    norms = sorted(
        (r for r in candidates if r["priority"] == 5),
        key=lambda r: (_neg_date(r["created"]), r["path"]),
    )
    scored = sorted(
        ((welcome_score(r, now), r) for r in candidates if r["priority"] != 5),
        key=lambda x: (-x[0], _neg_date(x[1]["created"]), x[1]["path"]),
    )
    header = f"episteme · memoria de {project}"
    lines = [header]
    entries: list[dict[str, Any]] = []
    reserve = max(WELCOME_RESERVE, len(welcome_notice(project, 99999, 99999)) + 1)
    budget = 4000 - len(header) - 1 - reserve
    ranked = 0
    missed = {"norms": 0, "reminders": 0}

    def add(line: str, section: str | None, ranked_entry: bool = False) -> bool:
        nonlocal budget, ranked
        extra = len(line) + 1 + (len(section) + 1 if section else 0)
        if (ranked_entry and ranked >= 10) or extra > budget:
            return False
        if section:
            lines.append(section)
        lines.append(line)
        budget -= extra
        ranked += ranked_entry
        return True

    def reminder_lines(rows_: list[Any], section: str, count_missed: bool = False) -> None:
        first = True
        for i, r in enumerate(rows_):
            line = f"- [{r['due']}] {r['title']} ({r['path']})"
            if not add(line, section if first else None):
                if count_missed:
                    missed["reminders"] += len(rows_) - i
                break
            first = False
            entries.append({"path": r["path"], "score": None, "kind": "reminder"})

    reminder_lines(overdue, "Recordatorios vencidos:", True)
    first = True
    for i, r in enumerate(norms):
        if not add(entry_line(r), "Normas:" if first else None):
            missed["norms"] += len(norms) - i
            break
        first = False
        entries.append({"path": r["path"], "score": None, "kind": "norm"})
    if not any(missed.values()):
        budget += reserve  # nothing to warn about: the reserve goes back to the rest
    reminder_lines(upcoming, f"Vencen pronto ({upcoming_days} días):")
    first = True
    shared_used = 0
    spill: list[tuple[float, Any]] = []
    full = False
    for score, r in scored:
        if project != "_shared" and r["project"] == "_shared":
            if shared_used >= SHARED_MAX:
                spill.append((score, r))
                continue
            shared_used += 1
        if not add(entry_line(r), "Memorias:" if first else None, True):
            full = True
            break
        first = False
        entries.append({"path": r["path"], "score": round(score, 4), "kind": "memory"})
    for score, r in [] if full else spill:
        if not add(entry_line(r), "Memorias:" if first else None, True):
            break
        first = False
        entries.append({"path": r["path"], "score": round(score, 4), "kind": "memory"})
    if not entries and not any(missed.values()):
        return "", []
    if any(missed.values()):
        lines.append(welcome_notice(project, missed["norms"], missed["reminders"]))
    return "\n".join(lines), entries
