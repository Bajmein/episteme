"""Task context: memories and notes relevant to a task."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.index import is_past
from episteme.markdown import (
    body_without_title,
    clip,
    fold,
)
from episteme.memory.files import _files_of
from episteme.memory.schema import MIN_CONTEXT_SCORE, STOPWORDS_EN
from episteme.memory.scoring import recency
from episteme.vault import MEMORY, today

if TYPE_CHECKING:
    from episteme.engine import Engine

MIN_RELEVANCE = 0.25  # task context: a memory's score relative to the best hit
LINKED_MAX = 3  # task context: memories listed under "Memorias enlazadas:"
LINK_SEEDS = 5  # task context: listed memories whose links are followed
NOTES_MAX = 5  # task context: most notes under "Notas relacionadas:"
MIN_NOTE_RELEVANCE = 0.5  # task context: a note's score relative to the best note
EXCERPT_CHARS = 300  # task context: chars of a memory's body shown


class _Pack:
    """The context text being built, with the character budget left."""

    def __init__(self, header: str, budget: int) -> None:
        self.parts = [header]
        self.used = len(header)
        self.budget = budget
        self.entries: list[dict[str, Any]] = []

    def add_memory(self, block: str, entry: dict[str, Any]) -> bool:
        """Add ``block`` unless it does not fit (later, shorter ones may)."""
        if self.used + len(block) + 1 > self.budget:
            return False
        self.parts.append(block)
        self.used += len(block) + 1
        self.entries.append(entry)
        return True

    def add_group(self, section: str, items: list[tuple[str, dict[str, Any]]]) -> None:
        """List ``(line, entry)`` items under ``section`` until one does not fit."""
        for i, (line, entry) in enumerate(items):
            extra = len(line) + 1 + (len(section) + 1 if i == 0 else 0)
            if self.used + extra > self.budget:
                return
            if i == 0:
                self.parts.append(section)
            self.parts.append(line)
            self.used += extra
            self.entries.append(entry)


def _need(terms: list[list[str]]) -> int:
    """How many of the ``terms`` a hit must match."""
    return 2 if len(terms) >= 3 else 1


def _relevance(score: float, best: float) -> float:
    """A score relative to the best hit (1.0 when there is no positive best)."""
    return score / best if best > 0 else 1.0


def _matched(engine: Engine, path: str, terms: list[list[str]]) -> int:
    """How many distinct ``terms`` occur in the title or text of ``path`` (at least 1)."""
    from episteme.index import _term_regex

    row = engine.index.note(path)
    text = ""
    if row is not None:
        tags = [t["tag"] for t in engine.index.conn.execute(
            "select tag from tags where path = ?", (path,)
        )]  # fmt: skip
        text = fold("\n".join([row["title"], row["search_text"], *tags]))
    return max(1, sum(1 for t in terms if _term_regex(t).search(text)))


def _query_terms(task: str) -> tuple[str, list[list[str]]]:
    """The search query for ``task`` (English stopwords dropped) and its terms."""
    from episteme.index import query_terms

    kept = [w for w in task.split() if fold(w).strip(".,;:!?()[]\"'") not in STOPWORDS_EN]
    query = " ".join(kept) if kept else task
    return query, query_terms(query, drop_stopwords=True)


def _context_score(row: Any, relevance: float, now: dt.date) -> float:
    """The blend of relevance, priority and recency that ranks a memory."""
    return (
        0.5 * relevance
        + 0.3 * ((row["priority"] or 1) - 1) / 4
        + 0.2 * recency(row["created"], now)
    )


def _is_pinned(row: Any, files: dict[str, Any]) -> bool:
    """Whether ``row`` is a constraint tied to files (always listed)."""
    return row["type"] == "constraint" and bool(files.get(row["path"]))


def _qualifies(
    engine: Engine, path: str, terms: list[list[str]], relevance: float, score: float
) -> bool:
    """Whether a memory clears the relevance, term-match and score thresholds."""
    return (
        relevance >= MIN_RELEVANCE
        and score >= MIN_CONTEXT_SCORE
        and _matched(engine, path, terms) >= _need(terms)
    )


def _rank(scored: list[tuple[bool, float, Any]]) -> list[tuple[float, Any]]:
    """Order ``(pinned, score, row)`` pinned first, then by score and path."""
    scored.sort(key=lambda x: (not x[0], -x[1], x[2]["path"]))
    return [(score, row) for _, score, row in scored]


def _relevant_memories(
    engine: Engine, query: str, terms: list[list[str]], project: str
) -> list[tuple[float, Any]]:
    """The memories to list, as ``(score, row)``: pinned constraints first, then by score."""
    now = today()
    hits, _ = engine.index.search(
        query,
        any_term=True,
        drop_stopwords=True,
        mode=MEMORY,
        project=[project, "_shared"],
        status="active",
        limit=200,
        snippets=False,
    )
    rows = {h.path: row for h in hits if (row := engine.index.note(h.path)) is not None}
    hits = [h for h in hits if h.path in rows]
    hi = max((h.score for h in hits), default=0.0)
    scored: list[tuple[bool, float, Any]] = []
    files = _files_of(engine)
    for h in hits:
        row = rows[h.path]
        relevance = _relevance(h.score, hi)
        score = _context_score(row, relevance, now)
        pinned = _is_pinned(row, files)
        if pinned or _qualifies(engine, h.path, terms, relevance, score):
            scored.append((pinned, score, row))
    return _rank(scored)


def _related_paths(engine: Engine, path: str) -> list[str | None]:
    """The paths one ``related`` link away from ``path``, outgoing then backlinks."""
    near = [x["dst_path"] for x in engine.index.outgoing(path) if x["kind"] == "related"]
    near += [x["src"] for x in engine.index.backlinks(path) if x["kind"] == "related"]
    return near


def _is_linkable(r: Any, project: str, iso: str) -> bool:
    """Whether ``r`` is an active, unexpired memory of ``project`` or ``_shared``."""
    if r is None or r["mode"] != MEMORY or r["status"] != "active":
        return False
    if r["project"] not in (project, "_shared"):
        return False
    return not is_past(r["valid_until"], iso)


def _linked_memories(engine: Engine, chosen: list[str], project: str) -> list[Any]:
    """Active memories one ``related`` link away from the first ``LINK_SEEDS`` of ``chosen``."""
    iso = today().isoformat()
    listed = set(chosen)
    linked: list[Any] = []
    for path in chosen[:LINK_SEEDS]:
        for other in _related_paths(engine, path):
            if other is None or other in listed:
                continue
            r = engine.index.note(other)
            if not _is_linkable(r, project, iso):
                continue
            listed.add(other)
            linked.append(r)
    return linked


def _related_notes(engine: Engine, query: str, terms: list[list[str]]) -> list[Any]:
    """The documentation notes relevant to the query, scored; at most ``NOTES_MAX``."""
    need = _need(terms)
    found, _ = engine.index.search(
        query, any_term=True, drop_stopwords=True, limit=50, snippets=False
    )
    found = [n for n in found if engine.vault.mode_for(n.path) != MEMORY]
    best = max((n.score for n in found), default=0.0)
    notes = []
    for n in found:
        relevance = _relevance(n.score, best)
        if relevance >= MIN_NOTE_RELEVANCE and _matched(engine, n.path, terms) >= need:
            n.score = round(0.5 * relevance, 4)
            notes.append(n)
    return notes[:NOTES_MAX]


def _memory_block(row: Any) -> str:
    """The listing of a memory: header line plus a clipped excerpt of its body."""
    excerpt = clip(" ".join(body_without_title(row["body"] or "").split()), EXCERPT_CHARS)
    return f"- [{row['type']} p{row['priority']}] {row['title']} ({row['path']})\n  {excerpt}"


def _linked_group(
    engine: Engine, chosen: list[str], project: str
) -> list[tuple[str, dict[str, Any]]]:
    """``(line, entry)`` items for the linked memories, at most ``LINKED_MAX``."""
    return [
        (
            f"- [{r['type']} p{r['priority']}] {r['title']} ({r['path']})",
            {"path": r["path"], "score": None, "kind": "linked"},
        )
        for r in _linked_memories(engine, chosen, project)[:LINKED_MAX]
    ]


def _notes_group(
    engine: Engine, query: str, terms: list[list[str]]
) -> list[tuple[str, dict[str, Any]]]:
    """``(line, entry)`` items for the related documentation notes."""
    return [
        (f"- {n.path} — {n.title}", {"path": n.path, "score": n.score, "kind": "note"})
        for n in _related_notes(engine, query, terms)
    ]


def task_context(
    engine: Engine, task: str, project: str | None, budget_tokens: int
) -> tuple[str, list[dict[str, Any]]]:
    """A context pack for ``task``: relevant memories, linked memories, then related notes.

    English stopwords are dropped from ``task`` first (Spanish ones by the search). With N
    remaining terms a hit must match ``need`` of them (2 if N >= 3, else 1). A memory is listed
    if it is a constraint with ``files``, or if its score relative to the best hit is at least
    ``MIN_RELEVANCE``, it matches ``need`` terms and ``0.5*relevance + 0.3*priority +
    0.2*recency`` is at least ``MIN_CONTEXT_SCORE``. "Memorias enlazadas:" adds up to
    ``LINKED_MAX`` active memories one ``related`` link away from the first five listed. Notes
    need relevance >= 0.5 (relative to the best note) and ``need`` terms; their score is
    ``0.5*relevance``; at most 5.
    """
    if budget_tokens < 1:
        raise invalid(f"budget_tokens must be positive, got {budget_tokens}.")
    project = engine.need_project(project)
    query, terms = _query_terms(task)
    pack = _Pack(f"episteme · contexto para: {' '.join(task.split())}", budget_tokens * 4)
    chosen: list[str] = []
    for score, row in _relevant_memories(engine, query, terms, project):
        entry = {"path": row["path"], "score": round(score, 4), "kind": "memory"}
        if pack.add_memory(_memory_block(row), entry):
            chosen.append(row["path"])
    pack.add_group("Memorias enlazadas:", _linked_group(engine, chosen, project))
    pack.add_group("Notas relacionadas:", _notes_group(engine, query, terms))
    if not pack.entries:
        return "", []
    return "\n".join(pack.parts), pack.entries
