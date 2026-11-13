"""Task context: memories and notes relevant to a task."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
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
    from episteme.index import query_terms

    if budget_tokens < 1:
        raise invalid(f"budget_tokens must be positive, got {budget_tokens}.")
    project = engine.need_project(project)
    now = today()
    kept = [w for w in task.split() if fold(w).strip(".,;:!?()[]\"'") not in STOPWORDS_EN]
    query = " ".join(kept) if kept else task
    terms = query_terms(query, drop_stopwords=True)
    need = 2 if len(terms) >= 3 else 1
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
    scored = []
    files = _files_of(engine)
    for h in hits:
        row = rows[h.path]
        relevance = h.score / hi if hi > 0 else 1.0
        score = (
            0.5 * relevance
            + 0.3 * ((row["priority"] or 1) - 1) / 4
            + 0.2 * recency(row["created"], now)
        )
        pinned = row["type"] == "constraint" and bool(files.get(h.path))
        if pinned or (
            relevance >= MIN_RELEVANCE
            and _matched(engine, h.path, terms) >= need
            and score >= MIN_CONTEXT_SCORE
        ):
            scored.append((pinned, score, row))
    scored.sort(key=lambda x: (not x[0], -x[1], x[2]["path"]))

    budget = budget_tokens * 4
    header = f"episteme · contexto para: {' '.join(task.split())}"
    parts = [header]
    used = len(header)
    entries: list[dict[str, Any]] = []
    chosen: list[str] = []
    for _, score, row in scored:
        excerpt = clip(" ".join(body_without_title(row["body"] or "").split()), 300)
        block = f"- [{row['type']} p{row['priority']}] {row['title']} ({row['path']})\n  {excerpt}"
        if used + len(block) + 1 > budget:
            continue
        parts.append(block)
        used += len(block) + 1
        entries.append({"path": row["path"], "score": round(score, 4), "kind": "memory"})
        chosen.append(row["path"])

    listed = set(chosen)
    iso = now.isoformat()
    linked: list[Any] = []
    for path in chosen[:5]:
        near = [x["dst_path"] for x in engine.index.outgoing(path) if x["kind"] == "related"]
        near += [x["src"] for x in engine.index.backlinks(path) if x["kind"] == "related"]
        for other in near:
            if other is None or other in listed:
                continue
            r = engine.index.note(other)
            if (
                r is None
                or r["mode"] != MEMORY
                or r["status"] != "active"
                or r["project"] not in (project, "_shared")
                or (r["valid_until"] and r["valid_until"] < iso)
            ):
                continue
            listed.add(other)
            linked.append(r)
    first = True
    for r in linked[:LINKED_MAX]:
        line = f"- [{r['type']} p{r['priority']}] {r['title']} ({r['path']})"
        extra = len(line) + 1 + (len("Memorias enlazadas:") + 1 if first else 0)
        if used + extra > budget:
            break
        if first:
            parts.append("Memorias enlazadas:")
            first = False
        parts.append(line)
        used += extra
        entries.append({"path": r["path"], "score": None, "kind": "linked"})

    found, _ = engine.index.search(
        query, any_term=True, drop_stopwords=True, limit=50, snippets=False
    )
    found = [n for n in found if engine.vault.mode_for(n.path) != MEMORY]
    nhi = max((n.score for n in found), default=0.0)
    notes = []
    for n in found:
        relevance = n.score / nhi if nhi > 0 else 1.0
        if relevance >= 0.5 and _matched(engine, n.path, terms) >= need:
            n.score = round(0.5 * relevance, 4)
            notes.append(n)
    notes = notes[:5]
    first = True
    for n in notes:
        line = f"- {n.path} — {n.title}"
        extra = len(line) + 1 + (len("Notas relacionadas:") + 1 if first else 0)
        if used + extra > budget:
            break
        if first:
            parts.append("Notas relacionadas:")
            first = False
        parts.append(line)
        used += extra
        entries.append({"path": n.path, "score": n.score, "kind": "note"})
    if not entries:
        return "", []
    return "\n".join(parts), entries
