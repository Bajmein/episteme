"""The plan copies: one note per plan of plan mode in the plan zone (``planes/``).

Only the ``plan`` tool writes there. The ``PreToolUse(ExitPlanMode)`` hook hands the plan text
and its path in Claude Code's plans folder; the server never reads that folder. A copy is
rewritten whole on each save of the same slug, archived in place (``status: archived``) and
never deleted. The originals of Claude Code are never touched.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import TYPE_CHECKING, Any, NamedTuple

from episteme import hookmode
from episteme.errors import NOT_FOUND, EpistemeError, invalid
from episteme.markdown import clip_at_newline, compose, parse
from episteme.memory import redact_secrets
from episteme.memory.schema import _PROJECT_NAME
from episteme.vault import PLAN, SESSION, today
from episteme.worktree import normalized_dir, resolve_project_dir, same_worktree

if TYPE_CHECKING:
    from episteme.engine import Engine

PLAN_TYPE = "plan"
PLAN_TAG = "sesion/plan"
ACTIVE = "active"
ARCHIVED = "archived"
PLAN_MAX = 200_000  # characters of plan text kept, cut mark included
TITLE_MAX = 120  # characters of the title taken from the plan's first "# " line
PATH_MAX = 4096  # characters of planFilePath kept as source_path
HASH_CHARS = 12  # sha1 characters of the path when its basename is not a usable slug
CURRENT_MAX = 64  # (project, worktree) pairs one process remembers
CUT_MARK = f"\n\n[episteme: plan cut at {PLAN_MAX:,} characters]"

SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
# A hook variable Claude Code did not substitute, e.g. "${tool_input.plan}".
_PLACEHOLDER = re.compile(r"\$\{[\w.]+\}")
_SESSION_ID = re.compile(r"[\w-]{1,128}")
_SEPARATORS = re.compile(r"[\\/]")
_SESSION_TYPE = "session"

# The plan of each (project, worktree) in this process: set by save and restore. Bounded by
# CURRENT_MAX; the server outlives /clear, so restore finds it first.
CURRENT: dict[tuple[str, str], str] = {}


class SaveArgs(NamedTuple):
    """What ``save`` receives from the tool (the hook passes them all)."""

    plan: str | None
    plan_path: str | None
    session_id: str | None = None


def now() -> str:
    """Local date and time to the second; the date follows ``EPISTEME_TODAY`` in tests."""
    clock = dt.datetime.now().time().replace(microsecond=0)
    return dt.datetime.combine(today(), clock).isoformat()


def is_placeholder(value: str | None) -> bool:
    """True when ``value`` is a hook variable Claude Code left unsubstituted."""
    return _PLACEHOLDER.fullmatch((value or "").strip()) is not None


def folder(engine: Engine, project: str) -> str:
    """``<plan zone>/<project>``, once ``project`` is a valid project name."""
    if not _PROJECT_NAME.fullmatch(project):
        raise invalid(
            f'project "{project}" is not a valid project name. Use 1-64 letters, digits, dots, '
            "hyphens or underscores, not starting with a dot or hyphen."
        )
    return f"{engine.vault.plan_zone.path}/{project}"


def slug_for(plan_path: str) -> str:
    """The basename of ``plan_path`` without ``.md``, or a short hash of the path."""
    base = _SEPARATORS.split(plan_path.strip())[-1]
    if base.lower().endswith(".md"):
        base = base[:-3]
    if SLUG.fullmatch(base):
        return base
    digest = hashlib.sha1(plan_path.encode("utf-8"), usedforsecurity=False).hexdigest()
    return digest[:HASH_CHARS]


def check_slug(slug: str | None) -> str:
    """``slug`` when it is a valid plan slug, else ``invalid_argument``."""
    value = (slug or "").strip()
    if not SLUG.fullmatch(value):
        raise invalid(
            f'slug "{value}" is not a plan slug. Pass the slug plan(action="show") lists.'
        )
    return value


def _here(project_dir: str | None) -> str:
    return normalized_dir(project_dir) if project_dir else ""


def _key(project: str, project_dir: str | None) -> tuple[str, str]:
    return project, _here(project_dir)


def _remember_current(key: tuple[str, str], rel: str) -> None:
    CURRENT.pop(key, None)
    CURRENT[key] = rel
    while len(CURRENT) > CURRENT_MAX:
        CURRENT.pop(next(iter(CURRENT)))


def _current_of(key: tuple[str, str]) -> str | None:
    """``CURRENT`` of ``key``; without a worktree, the one this project set last."""
    if key[1]:
        return CURRENT.get(key)
    mine = [rel for (project, _), rel in CURRENT.items() if project == key[0]]
    return mine[-1] if mine else None


def _forget(rel: str) -> None:
    for key in [k for k, v in CURRENT.items() if v == rel]:
        del CURRENT[key]


def _in_zone(engine: Engine, rel: str, mode: str) -> bool:
    """True when ``rel`` and the path it really resolves to are in a zone of ``mode``."""
    try:
        return engine.vault.check_writable(rel) == mode
    except EpistemeError:
        return False


def _in_plan_zone(engine: Engine, rel: str) -> bool:
    """True when ``rel`` and the path it really resolves to are in a plan zone."""
    return _in_zone(engine, rel, PLAN)


def _require_plan_zone(engine: Engine, rel: str) -> None:
    """Refuse to write ``rel`` unless its real path is in a plan zone."""
    if not _in_plan_zone(engine, rel):
        raise invalid(
            f"{rel} does not resolve to a note in a plan zone. Remove the link or pass the "
            "slug of a plan."
        )


def _write(engine: Engine, rel: str, meta: dict[str, Any], body: str) -> None:
    _require_plan_zone(engine, rel)
    engine.vault.write_atomic(rel, compose(meta, body))
    engine.index.reindex(rel)


def _read(engine: Engine, rel: str) -> tuple[dict[str, Any], str]:
    text = engine.vault.resolve(rel).read_text(encoding="utf-8", errors="replace")
    parsed = parse(text, rel)
    return dict(parsed.frontmatter), parsed.body


def _clip(text: str) -> str:
    """``text`` cut at a line break so that it fits ``PLAN_MAX`` with the cut mark."""
    if len(text) <= PLAN_MAX:
        return text
    return clip_at_newline(text, PLAN_MAX - len(CUT_MARK)) + CUT_MARK


def _title(text: str, slug: str) -> str:
    """The first ``# `` line of the plan as one clean line, or the slug."""
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return hookmode.clean_line(line[2:].strip(), TITLE_MAX)
    return slug


def _session_id(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _SESSION_ID.fullmatch(value) else None


def _old_meta(engine: Engine, rel: str) -> dict[str, Any]:
    """The frontmatter of the copy at ``rel`` when there is one in a plan zone."""
    if not _in_plan_zone(engine, rel) or not engine.vault.resolve(rel).is_file():
        return {}
    return _read(engine, rel)[0]


class _Copy(NamedTuple):
    """A plan ready to write: where, under which slug, its clipped text and its title."""

    rel: str
    slug: str
    body: str
    title: str
    source_path: str


def _is_unsubstituted(args: SaveArgs) -> bool:
    return is_placeholder(args.plan) or is_placeholder(args.plan_path)


def _copy(base: str, args: SaveArgs) -> _Copy:
    """Check the plan and its path and build the copy; credentials redacted, text clipped."""
    raw_path = (args.plan_path or "").strip()
    if not raw_path:
        raise invalid("plan_path is empty. Pass the planFilePath of the plan.")
    text = redact_secrets(args.plan or "").strip()
    if not text:
        raise invalid("plan is empty. Pass the text of the plan.")
    slug = slug_for(raw_path)
    body = _clip(text)
    source = hookmode.clean_line(redact_secrets(raw_path), PATH_MAX)
    return _Copy(f"{base}/{slug}.md", slug, body, redact_secrets(_title(body, slug)), source)


def _plan_meta(
    copy: _Copy, old: dict[str, Any], fresh: dict[str, Any]
) -> dict[str, Any]:
    """The frontmatter of a copy; ``fresh`` has its ``project``, ``session_id`` and ``worktree``."""
    meta: dict[str, Any] = {
        "type": PLAN_TYPE,
        "status": ACTIVE,
        "created": old.get("created") or today(),
        "tags": [PLAN_TAG],
        "project": fresh["project"],
        "slug": copy.slug,
        "title": copy.title,
        "saved_at": now(),
        "session_id": fresh["session_id"] or old.get("session_id"),
        "worktree": fresh["worktree"] or old.get("worktree"),
        "source_path": copy.source_path,
    }
    return {k: v for k, v in meta.items() if v is not None}


def save(
    engine: Engine, project: str, project_dir: str | None, args: SaveArgs
) -> dict[str, Any]:
    """Write the copy of a plan and make it the current one. Returns {"path", "saved", ...}.

    A hook variable left unsubstituted saves nothing. Credentials in the text, title and path
    are redacted, never refused: the plan cannot be lost.
    """
    if _is_unsubstituted(args):
        return {"path": None, "saved": False}
    copy = _copy(folder(engine, project), args)
    fresh = {
        "project": project,
        "session_id": _session_id(args.session_id),
        "worktree": resolve_project_dir(project_dir).as_posix() if project_dir else None,
    }
    old = _old_meta(engine, copy.rel)
    _write(engine, copy.rel, _plan_meta(copy, old, fresh), f"{copy.body}\n")
    _remember_current(_key(project, project_dir), copy.rel)
    return {
        "path": copy.rel,
        "saved": True,
        "slug": copy.slug,
        "title": copy.title,
        "created": not old,
    }


def current_slug(engine: Engine, project: str, project_dir: str | None) -> str | None:
    """The slug of the active plan this process saved or restored for the project and worktree."""
    rel = _current_of(_key(project, project_dir))
    if rel is None or not _is_active_plan(engine, rel):
        return None
    return rel.rsplit("/", 1)[-1][:-3]


def _active_rows(engine: Engine, project: str | None = None) -> list[Any]:
    where = "type = ? and status = ?"
    params: tuple[Any, ...] = (PLAN_TYPE, ACTIVE)
    if project is not None:
        where += " and project = ?"
        params += (project,)
    rows = engine.index.rows_in_mode(PLAN, where, params)
    return [r for r in rows if _in_plan_zone(engine, r["path"])]


def _saved_at(engine: Engine, rel: str) -> str:
    value = engine.index.props(rel).get("saved_at")
    return str(value) if value else ""


def _is_active_plan(engine: Engine, rel: str) -> bool:
    row = engine.index.note(rel)
    return (
        row is not None
        and row["mode"] == PLAN
        and row["status"] == ACTIVE
        and _in_plan_zone(engine, rel)
    )


def _newest(engine: Engine, rows: list[Any]) -> str | None:
    if not rows:
        return None
    best = max(rows, key=lambda r: (_saved_at(engine, r["path"]), r["mtime_ns"] or 0, r["path"]))
    return best["path"]


def _linked_by_state(engine: Engine, project: str, project_dir: str | None) -> str | None:
    """The plan the session state in use links (its ``plan`` key), when it is active."""
    from episteme import session  # session.store imports this module

    state = session.current(engine, project, project_dir)
    slug = engine.index.props(state).get("plan") if state else None
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        return None
    rel = f"{folder(engine, project)}/{slug}.md"
    return rel if _is_active_plan(engine, rel) else None


def find_current(engine: Engine, project: str, project_dir: str | None) -> str | None:
    """The plan of the task: ``CURRENT``, else the one the state links, else the newest."""
    key = _key(project, project_dir)
    rel = _current_of(key)
    if rel is not None and _is_active_plan(engine, rel):
        return rel
    rel = _linked_by_state(engine, project, project_dir)
    if rel is not None:
        return rel
    here = key[1]
    rows = [r for r in _active_rows(engine, project) if not here or same_worktree(engine, r, here)]
    return _newest(engine, rows)


def _summary(engine: Engine, rel: str) -> dict[str, Any]:
    props = engine.index.props(rel)
    return {
        "path": rel,
        "slug": str(props.get("slug") or rel.rsplit("/", 1)[-1][:-3]),
        "title": str(props.get("title") or ""),
        "saved_at": _saved_at(engine, rel) or None,
        "worktree": props.get("worktree"),
    }


def restore(
    engine: Engine, project: str, project_dir: str | None, source: str | None
) -> dict[str, Any]:
    """After ``/clear``, the plan of the task made current: {"found", "path", "title", ...}."""
    rel = find_current(engine, project, project_dir) if source == "clear" else None
    if rel is None:
        return {"found": False, "path": None, "title": None, "saved_at": None}
    _remember_current(_key(project, project_dir), rel)
    data = _summary(engine, rel)
    return {"found": True, "path": rel, "title": data["title"], "saved_at": data["saved_at"]}


def plan_path(engine: Engine, project: str, slug: str | None) -> str:
    """The vault path of the copy ``slug`` of ``project``; it must exist in a plan zone."""
    rel = f"{folder(engine, project)}/{check_slug(slug)}.md"
    if not _in_plan_zone(engine, rel) or not engine.vault.resolve(rel).is_file():
        raise EpistemeError(
            NOT_FOUND, f'{rel} does not exist. Pass a slug plan(action="show") lists.'
        )
    return rel


def show(engine: Engine, project: str, slug: str | None) -> dict[str, Any]:
    """Without ``slug``, the active plans of the project, newest first; with it, that plan."""
    if not slug:
        rows = _active_rows(engine, project)
        plans = sorted(
            (_summary(engine, r["path"]) for r in rows),
            key=lambda p: (p["saved_at"] or "", p["path"]),
            reverse=True,
        )
        return {"plans": plans}
    rel = plan_path(engine, project, slug)
    meta, body = _read(engine, rel)
    return {**_summary(engine, rel), "status": meta.get("status"), "content": body.strip()}


def archive(engine: Engine, rel: str) -> bool:
    """Set ``status: archived`` on a plan copy; False if it already was. Never deletes."""
    _forget(rel)
    meta, body = _read(engine, rel)
    if meta.get("status") == ARCHIVED:
        return False
    meta["status"] = ARCHIVED
    _write(engine, rel, meta, body)
    return True


def has_active(engine: Engine) -> bool:
    """True when some project has an active plan (rotation has something to look at)."""
    return bool(_active_rows(engine))


def _linked_plans(engine: Engine) -> set[tuple[str, str]]:
    """(project, slug) of the plans that an active session state links."""
    rows = engine.index.rows_in_mode(
        SESSION, "type = ? and status = ?", (_SESSION_TYPE, ACTIVE)
    )
    linked: set[tuple[str, str]] = set()
    for row in rows:
        if not _in_zone(engine, row["path"], SESSION):
            continue
        slug = engine.index.props(row["path"]).get("plan")
        if isinstance(slug, str) and row["project"]:
            linked.add((row["project"], slug))
    return linked


def _saved_before(engine: Engine, rel: str, cutoff: dt.date) -> bool:
    try:
        saved = dt.datetime.fromisoformat(_saved_at(engine, rel)).date()
    except ValueError:
        return False
    return saved < cutoff


def rotate(engine: Engine, archive_days: int) -> list[str]:
    """Archive the active plans saved more than ``archive_days`` days ago.

    A plan that an active session state of its project links stays: it has work pending.
    """
    cutoff = today() - dt.timedelta(days=archive_days)
    linked = _linked_plans(engine)
    stale = [
        r["path"]
        for r in _active_rows(engine)
        if (r["project"], _summary(engine, r["path"])["slug"]) not in linked
        and _saved_before(engine, r["path"], cutoff)
    ]
    return [rel for rel in stale if archive(engine, rel)]
