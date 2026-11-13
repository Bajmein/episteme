"""Per-message injection for the ``UserPromptSubmit`` hook: reminders, recall and nudges."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from episteme import memory
from episteme.index import STOPWORDS_ES
from episteme.markdown import tokens
from episteme.memory import STOPWORDS_EN
from episteme.vault import MEMORY, today

if TYPE_CHECKING:
    from episteme.engine import Engine

REMIND_EVERY = 10
NUDGE_AFTER = 8
NUDGE_EVERY = 15
RECALL_MAX = 5
RECALL_TERMS = 40
MAX_SESSIONS = 50
OVERDUE_MAX = 5

WRITES: int = 0  # memories written in this process by agent calls (remember, revise); see server


@dataclass
class SessionState:
    prompts: int = 0
    reminded_at: int = 0
    nudged_at: int = NUDGE_AFTER - NUDGE_EVERY
    baseline: int | None = None
    delivered: set[str] = field(default_factory=set)
    surfaced: set[str] = field(default_factory=set)


_SESSIONS: dict[str, SessionState] = {}


def _store(session: str, st: SessionState) -> SessionState:
    _SESSIONS.pop(session, None)
    _SESSIONS[session] = st
    while len(_SESSIONS) > MAX_SESSIONS:
        del _SESSIONS[next(iter(_SESSIONS))]
    return st


def state(session: str) -> SessionState:
    """The state of ``session``, created on first use."""
    return _SESSIONS.get(session) or _store(session, SessionState())


def reset(session: str) -> SessionState:
    """Replace the state of ``session`` with a new one."""
    return _store(session, SessionState())


def overdue_block(engine: Engine, project: str) -> tuple[str, list[dict[str, Any]]]:
    """The active reminders due today or earlier (5 at most), oldest due first."""
    rows = engine.index.memories(
        "type = 'reminder' and status = 'active' and project in (?, '_shared') "
        "and due is not null and due <= ?",
        (project, today().isoformat()),
    )
    rows = sorted(rows, key=lambda r: (r["due"], r["path"]))[:OVERDUE_MAX]
    if not rows:
        return "", []
    lines = ['episteme · recordatorios vencidos (al resolver uno: revise(note, action="dismiss")):']
    lines += [f"- [{r['due']}] {r['title']} ({r['path']})" for r in rows]
    entries = [{"path": r["path"], "score": None, "kind": "reminder"} for r in rows]
    return "\n".join(lines), entries


_NOTICE_PARTS = (
    ("expired", "vencidas"),
    ("stale", "viejas"),
    ("similar", "grupos parecidos"),
    ("contradictions", "contradicciones posibles"),
    ("flagged", "marcadas"),
)


def review_notice(engine: Engine, project: str) -> str:
    """One line with what review has pending for the project, or "" when nothing."""
    zone = engine.vault.memory_zone
    if zone is None:
        return ""
    totals = memory.review(engine, None, project, 1, zone.path)["totals"]
    parts = [f"{label} {totals[key]}" for key, label in _NOTICE_PARTS if totals.get(key, 0) > 0]
    if not parts:
        return ""
    return (
        f"episteme · mantención pendiente en {project}: {' · '.join(parts)}. "
        f'Corre review(project="{project}", zone="memory") y propón qué archivar o unificar; '
        "no cambies nada sin aprobación."
    )


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def recall(
    engine: Engine, prompt: str, project: str, st: SessionState, skip: set[str]
) -> tuple[str, list[dict[str, Any]]]:
    """Memories whose title, tags or keywords hold a rare word of the user's message."""
    prompt = prompt.strip()
    if prompt.startswith("/"):
        prompt = prompt.partition(" ")[2].strip()
    if not prompt or prompt == "${prompt}":
        return "", []
    terms: list[str] = []
    for t in tokens(prompt, min_len=3):
        if t in STOPWORDS_ES or t in STOPWORDS_EN or t.isdigit() or t in terms:
            continue
        terms.append(t)
    terms = terms[:RECALL_TERMS]
    if not terms:
        return "", []
    scope = [project, "_shared"]
    rows = engine.index.memories("project in (?, '_shared') and status = 'active'", (project,))
    total = len(rows)
    limit = max(3, total // 4)
    counted = []
    for t in terms:
        _, df = engine.index.search(
            t, mode=MEMORY, project=scope, status="active", limit=1, snippets=False
        )
        if 1 <= df <= limit:
            counted.append(t)
    if not counted:
        return "", []
    hits, _ = engine.index.search(
        " ".join(counted),
        any_term=True,
        mode=MEMORY,
        project=scope,
        status="active",
        limit=30,
        snippets=False,
    )
    iso = today().isoformat()
    ranked = []
    for pos, hit in enumerate(hits):
        if hit.path in skip or hit.path in st.delivered:
            continue
        row = engine.index.note(hit.path)
        if row is None or row["type"] == "reminder":
            continue
        if row["valid_until"] and row["valid_until"] < iso:
            continue
        props = engine.index.props(hit.path)
        strong_words = set(tokens(row["title"] or ""))
        for key in ("tags", "keywords"):
            for item in _as_list(props.get(key)):
                strong_words.update(tokens(item))
        strong = {t for t in counted if t in strong_words}
        if not strong:
            continue
        body_words = set(tokens(row["search_text"] or ""))
        hit_terms = strong | {t for t in counted if t in body_words}
        if len(hit_terms) >= 2 or len(counted) <= 3:
            ranked.append((-len(strong), -len(hit_terms), pos, row))
    ranked.sort(key=lambda x: x[:3])
    chosen = [x[3] for x in ranked[:RECALL_MAX]]
    if not chosen:
        return "", []
    st.delivered.update(r["path"] for r in chosen)
    lines = ["episteme · memorias que pueden venir al caso (ábrelas con read si aplican):"]
    lines += [f"- [{r['type']} p{r['priority']}] {r['title']} ({r['path']})" for r in chosen]
    entries = [{"path": r["path"], "score": None, "kind": "recall"} for r in chosen]
    return "\n".join(lines), entries


def nudge(st: SessionState) -> str:
    """A reminder to save memories, when the session has written none."""
    if (
        st.prompts >= NUDGE_AFTER
        and st.prompts - st.nudged_at >= NUDGE_EVERY
        and WRITES == st.baseline
    ):
        st.nudged_at = st.prompts
        return (
            "episteme · en esta sesión aún no se ha guardado ninguna memoria. Si se cerró "
            "una decisión, se acordó un plan o la persona corrigió algo, guárdalo con remember."
        )
    return ""
