"""Per-message injection for the ``UserPromptSubmit`` hook: reminders, recall and nudges."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from episteme import memory
from episteme.index import STOPWORDS_ES, is_past
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
RECALL_MIN_LEN = 3  # shortest word of the message that counts as a term
RECALL_RARE_FLOOR = 3  # a term is rare when it is in at most max(this, a quarter of) the memories
RECALL_RARE_SHARE = 4
RECALL_SEARCH_LIMIT = 30
RECALL_MIN_HIT_TERMS = 2  # terms a memory must hold, unless the message has few terms
RECALL_FEW_TERMS = 3

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

TRAIL_MAX = 30
TRAIL_SHOWN = 8
# Notes the agent wrote or read in this process, oldest first. It is per process, not per
# session id: /clear starts a new session id in the same process, and the trail must cross it.
TRAIL: dict[str, str] = {}


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


def _listing(
    header: str, rows: list[Any], kind: str, line: Callable[[Any], str]
) -> tuple[str, list[dict[str, Any]]]:
    """The text block (``header`` and one ``line`` per row) and its delivery entries."""
    text = "\n".join([header, *(line(r) for r in rows)])
    return text, [{"path": r["path"], "score": None, "kind": kind} for r in rows]


def track(path: str, kind: str) -> None:
    """Note that this process wrote (``"written"``) or read (``"read"``) the note ``path``."""
    if not path:
        return
    written = kind == "written" or TRAIL.pop(path, "") == "written"
    TRAIL.pop(path, None)
    TRAIL[path] = "written" if written else "read"
    while len(TRAIL) > TRAIL_MAX:
        del TRAIL[next(iter(TRAIL))]


def trail_block(engine: Engine, skip: set[str]) -> tuple[str, list[dict[str, Any]]]:
    """The active memories this process wrote or read, for the welcome after compact or clear.

    Written ones first, then read ones, newest first within each; ``TRAIL_SHOWN`` at most,
    without those in ``skip`` (already listed in the welcome).
    """
    paths = [p for p in reversed(TRAIL) if p not in skip]
    if not paths:
        return "", []
    marks = ",".join("?" * len(paths))
    found = engine.index.memories(f"path in ({marks}) and status = 'active'", tuple(paths))  # nosec B608
    rows = {r["path"]: r for r in found}
    ordered = [p for p in paths if TRAIL[p] == "written"] + [p for p in paths if TRAIL[p] == "read"]
    chosen = [rows[p] for p in ordered if p in rows][:TRAIL_SHOWN]
    if not chosen:
        return "", []
    labels = {"written": "escrita", "read": "leída"}
    return _listing(
        "De esta sesión, antes de compactar o limpiar (ábrelas con read si hacen falta):",
        chosen,
        "trail",
        lambda r: (
            f"- [{r['type']} p{r['priority']}] {r['title']} ({r['path']}) "
            f"· {labels[TRAIL[r['path']]]}"
        ),
    )


def _recovered_parts(memories: int, trail: int) -> list[str]:
    """The phrases that say what the welcome recovered (project memories, session trail)."""
    parts = [f"{memories} memorias del proyecto"] if memories else []
    if trail:
        parts.append(f"{trail} de esta sesión" if memories else f"{trail} memorias de esta sesión")
    return parts


def recovered_notice(source: str | None, memories: int, trail: int) -> str:
    """The line shown to the person when the welcome is resent after compact or clear."""
    after = {"compact": "tras compactar", "clear": "tras /clear"}.get(
        (source or "").strip(), "tras compactar o limpiar"
    )
    if not memories and not trail:
        return f"episteme · {after}: no había memorias que recuperar"
    parts = _recovered_parts(memories, trail)
    return f"episteme · contexto recuperado {after}: {' y '.join(parts)}"


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
    return _listing(
        'episteme · recordatorios vencidos (al resolver uno: revise(note, action="dismiss")):',
        rows,
        "reminder",
        lambda r: f"- [{r['due']}] {r['title']} ({r['path']})",
    )


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


def _strip_command(prompt: str) -> str:
    """The prompt without a leading slash command's name."""
    prompt = prompt.strip()
    if prompt.startswith("/"):
        prompt = prompt.partition(" ")[2].strip()
    return prompt


def _is_noise(term: str) -> bool:
    return term in STOPWORDS_ES or term in STOPWORDS_EN or term.isdigit()


def _recall_terms(prompt: str) -> list[str]:
    """Distinct content words of the user's message (a slash command's name is dropped)."""
    prompt = _strip_command(prompt)
    if not prompt or prompt == "${prompt}":
        return []
    terms: list[str] = []
    for t in tokens(prompt, min_len=RECALL_MIN_LEN):
        if _is_noise(t) or t in terms:
            continue
        terms.append(t)
    return terms[:RECALL_TERMS]


def _rare_terms(engine: Engine, terms: list[str], scope: list[str]) -> list[str]:
    """The ``terms`` that appear in few of the active memories of ``scope``."""
    marks = ", ".join("?" * len(scope))
    clause = f"project in ({marks}) and status = 'active'"  # nosec B608
    rows = engine.index.memories(clause, tuple(scope))
    limit = max(RECALL_RARE_FLOOR, len(rows) // RECALL_RARE_SHARE)
    counted = []
    for t in terms:
        _, df = engine.index.search(
            t, mode=MEMORY, project=scope, status="active", limit=1, snippets=False
        )
        if 1 <= df <= limit:
            counted.append(t)
    return counted


def _is_recallable(row: Any, iso: str) -> bool:
    """Whether a note can be recalled: it is not a reminder and has not expired."""
    if row["type"] == "reminder":
        return False
    return not is_past(row["valid_until"], iso)


def _strong_words(engine: Engine, row: Any) -> set[str]:
    """The words of the note's title, tags and keywords."""
    props = engine.index.props(row["path"])
    words = set(tokens(row["title"] or ""))
    for key in ("tags", "keywords"):
        for item in _as_list(props.get(key)):
            words.update(tokens(item))
    return words


def _enough_hits(hit_terms: set[str], counted: list[str]) -> bool:
    """Whether the note holds enough of the message's terms (or the message has few terms)."""
    return len(hit_terms) >= RECALL_MIN_HIT_TERMS or len(counted) <= RECALL_FEW_TERMS


def _score(
    engine: Engine, path: str, pos: int, counted: list[str], iso: str
) -> tuple[int, int, int, Any] | None:
    """Sort key and row of a hit worth recalling, or None (reminder, expired, weak match)."""
    row = engine.index.note(path)
    if row is None or not _is_recallable(row, iso):
        return None
    words = _strong_words(engine, row)
    strong = {t for t in counted if t in words}
    if not strong:
        return None
    body_words = set(tokens(row["search_text"] or ""))
    hit_terms = strong | {t for t in counted if t in body_words}
    if not _enough_hits(hit_terms, counted):
        return None
    return (-len(strong), -len(hit_terms), pos, row)


def _rank_hits(engine: Engine, hits: list[Any], counted: list[str], seen: set[str]) -> list[Any]:
    """The rows of the hits worth recalling, best first, leaving out the paths in ``seen``."""
    iso = today().isoformat()
    ranked = []
    for pos, hit in enumerate(hits):
        if hit.path in seen:
            continue
        scored = _score(engine, hit.path, pos, counted, iso)
        if scored is not None:
            ranked.append(scored)
    ranked.sort(key=lambda x: x[:3])
    return [x[3] for x in ranked[:RECALL_MAX]]


def _search_memories(engine: Engine, counted: list[str], scope: list[str]) -> list[Any]:
    """The active memories of ``scope`` that match any of the ``counted`` terms."""
    hits, _ = engine.index.search(
        " ".join(counted),
        any_term=True,
        mode=MEMORY,
        project=scope,
        status="active",
        limit=RECALL_SEARCH_LIMIT,
        snippets=False,
    )
    return hits


def recall(
    engine: Engine, prompt: str, project: str, st: SessionState, skip: set[str]
) -> tuple[str, list[dict[str, Any]]]:
    """Memories whose title, tags or keywords hold a rare word of the user's message."""
    terms = _recall_terms(prompt)
    if not terms:
        return "", []
    scope = [project, "_shared"]
    counted = _rare_terms(engine, terms, scope)
    if not counted:
        return "", []
    hits = _search_memories(engine, counted, scope)
    chosen = _rank_hits(engine, hits, counted, skip | st.delivered)
    if not chosen:
        return "", []
    st.delivered.update(r["path"] for r in chosen)
    return _listing(
        "episteme · memorias que pueden venir al caso (ábrelas con read si aplican):",
        chosen,
        "recall",
        lambda r: f"- [{r['type']} p{r['priority']}] {r['title']} ({r['path']})",
    )


def _nudge_due(st: SessionState) -> bool:
    if st.prompts < NUDGE_AFTER or st.prompts - st.nudged_at < NUDGE_EVERY:
        return False
    return st.baseline == WRITES


def nudge(st: SessionState) -> str:
    """A reminder to save memories, when the session has written none."""
    if _nudge_due(st):
        st.nudged_at = st.prompts
        return (
            "episteme · en esta sesión aún no se ha guardado ninguna memoria. Si se cerró "
            "una decisión, se acordó un plan o la persona corrigió algo, guárdalo con remember."
        )
    return ""
