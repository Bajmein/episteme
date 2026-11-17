"""The session state: one living note per line of work in the session zone (``sesiones/``).

Only the ``session`` tool writes there. A state is rewritten whole on each save (the path does
not change), archived in place (``status: archived``) and never deleted.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any, NamedTuple

from episteme.checkpoint import _normalized_dir, _project_dir, _same_worktree
from episteme.errors import NOT_FOUND, EpistemeError, invalid
from episteme.markdown import body_without_title, compose, parse
from episteme.memory import check_files, memory_slug, template_hint
from episteme.memory.schema import _PROJECT_NAME
from episteme.memory.secrets import _reject_secrets
from episteme.memory.templates import missing_sections
from episteme.vault import SESSION, today

if TYPE_CHECKING:
    from episteme.engine import Engine

STATE_TYPE = "session"
STATE_TAG = "sesion/estado"
ORIGINS = ("agent", "extractor")
ACTIVE = "active"
ARCHIVED = "archived"
CURRENT_MAX = 64  # (project, worktree) pairs one process remembers

# The state of each (project, worktree) in this process: set by save and restore. Bounded by
# CURRENT_MAX; losing it on restart is fine (the newest active state is looked up instead).
CURRENT: dict[tuple[str, str], str] = {}


class SaveArgs(NamedTuple):
    """What ``save`` receives from the tool."""

    title: str | None
    body: str | None
    note: str | None = None
    files: list[str] | None = None
    origin: str | None = None
    session_id: str | None = None


def now() -> str:
    """Local date and time to the second; the date follows ``EPISTEME_TODAY`` in tests."""
    clock = dt.datetime.now().time().replace(microsecond=0)
    return dt.datetime.combine(today(), clock).isoformat()


def folder(engine: Engine, project: str) -> str:
    """``<session zone>/<project>``, once ``project`` is a valid project name."""
    if not _PROJECT_NAME.fullmatch(project):
        raise invalid(
            f'project "{project}" is not a valid project name. Use 1-64 letters, digits, dots, '
            "hyphens or underscores, not starting with a dot or hyphen."
        )
    return f"{engine.vault.session_zone.path}/{project}"


def _here(project_dir: str | None) -> str:
    """The normalized worktree of the call, or ``""`` when no project_dir is given."""
    return _normalized_dir(project_dir) if project_dir else ""


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


def _active_rows(engine: Engine, project: str | None = None) -> list[Any]:
    """Active state rows of ``project`` (every project when None)."""
    where = "type = ? and status = ?"
    params: tuple[Any, ...] = (STATE_TYPE, ACTIVE)
    if project is not None:
        where += " and project = ?"
        params += (project,)
    return engine.index.rows_in_mode(SESSION, where, params)


def _saved_at(engine: Engine, rel: str) -> str:
    value = engine.index.props(rel).get("saved_at")
    return str(value) if value else ""


def _is_active_state(engine: Engine, rel: str) -> bool:
    row = engine.index.note(rel)
    return row is not None and row["mode"] == SESSION and row["status"] == ACTIVE


def current(engine: Engine, project: str, project_dir: str | None) -> str | None:
    """The state in use: ``CURRENT`` of this process, else the newest active of the worktree."""
    key = _key(project, project_dir)
    rel = _current_of(key)
    if rel is not None and _is_active_state(engine, rel):
        return rel
    here = key[1]
    rows = [
        r
        for r in _active_rows(engine, project)
        if not here or _same_worktree(engine, r, here)
    ]
    if not rows:
        return None
    newest = max(rows, key=lambda r: (_saved_at(engine, r["path"]), r["mtime_ns"] or 0, r["path"]))
    return newest["path"]


def note_path(engine: Engine, note: str) -> str:
    """The vault path of a state note given by the caller; it must exist in a session zone."""
    rel = note.strip().replace("\\", "/")
    if not rel.lower().endswith(".md"):
        rel += ".md"
    if engine.vault.check_writable(rel) != SESSION:
        raise invalid(
            f"{rel} is not in a session zone. Pass the path of a session state "
            f"(session(action=\"show\") gives it)."
        )
    if not engine.vault.resolve(rel).is_file():
        raise EpistemeError(NOT_FOUND, f"{rel} does not exist. Pass the path of a session state.")
    return rel


def _read(engine: Engine, rel: str) -> tuple[dict[str, Any], str]:
    """Frontmatter and body of a state note."""
    text = engine.vault.resolve(rel).read_text(encoding="utf-8", errors="replace")
    parsed = parse(text, rel)
    return dict(parsed.frontmatter), parsed.body


def _write(engine: Engine, rel: str, meta: dict[str, Any], body: str) -> None:
    engine.vault.write_atomic(rel, compose(meta, body))
    engine.index.reindex(rel)


def _clean_title(title: str | None) -> str | None:
    if title is None:
        return None
    clean = " ".join(title.split())
    if not clean:
        raise invalid("title is empty. Give the state a short title, e.g. the task.")
    return clean


def _clean_body(body: str | None) -> str:
    """The body without its leading ``# title`` line (written from the title)."""
    text = (body or "").strip()
    if not text:
        raise invalid(
            'body is empty. Write the state with the session template (action="template").'
        )
    if text.split("\n", 1)[0].strip().startswith("# "):
        text = body_without_title(text).strip()
    return text


def _check_origin(origin: str | None) -> str:
    origin = origin or ORIGINS[0]
    if origin not in ORIGINS:
        raise invalid(f'origin must be one of {", ".join(ORIGINS)}, got "{origin}".')
    return origin


def _target(engine: Engine, project: str, project_dir: str | None, note: str | None) -> str | None:
    """The state a save rewrites: ``note`` (of this project), else the current one."""
    if not note:
        return current(engine, project, project_dir)
    rel = note_path(engine, note)
    owner = engine.index.props(rel).get("project")
    if owner not in (None, project):
        raise invalid(f'{rel} is a state of project "{owner}". Pass project="{owner}".')
    return rel


def _meta(old: dict[str, Any], fresh: dict[str, Any], args: SaveArgs) -> dict[str, Any]:
    """The frontmatter of a saved state: the fixed keys first, then the extra ones.

    ``fresh`` has the ``project``, ``task_title`` and ``worktree`` of this save.
    """
    meta: dict[str, Any] = {
        "type": STATE_TYPE,
        "status": ACTIVE,
        "created": old.get("created") or today(),
        "tags": [STATE_TAG],
        "files": args.files if args.files is not None else old.get("files") or [],
        "project": old.get("project") or fresh["project"],
        "task_title": fresh["task_title"],
        "saved_at": now(),
        "saved_by": _check_origin(args.origin),
        "worktree": fresh["worktree"] or old.get("worktree"),
        "session_id": args.session_id or old.get("session_id"),
    }
    return {k: v for k, v in meta.items() if v not in (None, [])}


def _create(engine: Engine, project: str, title: str, text: str) -> str:
    """Create the file of a new state under the first free numbered name."""
    base_dir = folder(engine, project)
    base = f"{today().isoformat()}-estado-{memory_slug(title, project, STATE_TYPE)}"
    n = 1
    while True:
        rel = f"{base_dir}/{base}.md" if n == 1 else f"{base_dir}/{base}-{n}.md"
        if engine.vault.check_writable(rel) != SESSION:
            raise invalid(f"{rel} is not in a session zone. Check the {base_dir} folder.")
        if not engine.vault.resolve(rel).exists() and engine.vault.create_exclusive(rel, text):
            return rel
        n += 1


def _checked(args: SaveArgs) -> tuple[str | None, str]:
    """The cleaned title and body of a save, once nothing in them looks like a credential."""
    title = _clean_title(args.title)
    body = _clean_body(args.body)
    check_files(args.files)
    for field, value in (
        ("title", title),
        ("body", body),
        ("files", args.files),
        ("session", args.session_id),
    ):
        _reject_secrets(field, value)
    return title, body


def _store(engine: Engine, rel: str | None, fresh: dict[str, Any], text: str) -> str:
    """Rewrite the state at ``rel``, or create a new one when it is None; reindex it."""
    if rel is None:
        rel = _create(engine, fresh["project"], fresh["task_title"], text)
    else:
        engine.vault.write_atomic(rel, text)
    engine.index.reindex(rel)
    return rel


def _save_result(rel: str, created: bool, body: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": rel,
        "created": created,
        "missing_sections": missing_sections(STATE_TYPE, body),
    }
    hint = template_hint(STATE_TYPE, body)
    if hint:
        result["template_hint"] = hint
    return result


def save(
    engine: Engine, project: str, project_dir: str | None, args: SaveArgs
) -> dict[str, Any]:
    """Create or rewrite the state. Returns {"path", "created", "missing_sections", ...}."""
    folder(engine, project)
    title, body = _checked(args)
    worktree = _project_dir(project_dir).as_posix() if project_dir else None
    rel = _target(engine, project, project_dir, args.note)
    old: dict[str, Any] = _read(engine, rel)[0] if rel else {}
    title = title or str(old.get("task_title") or "").strip()
    if not title:
        raise invalid("a new session state needs title. Pass title, e.g. the task in a few words.")
    fresh = {"project": project, "task_title": title, "worktree": worktree}
    text = compose(_meta(old, fresh, args), f"# {title}\n\n{body}\n")
    saved = _store(engine, rel, fresh, text)
    _remember_current(_key(project, project_dir), saved)
    return _save_result(saved, rel is None, body)


def show(engine: Engine, project: str, project_dir: str | None) -> dict[str, Any]:
    """The state in use as {"found", "path", "task_title", "saved_at", "content"}."""
    rel = current(engine, project, project_dir)
    if rel is None:
        return {"found": False, "path": None, "task_title": None, "saved_at": None, "content": ""}
    text = engine.vault.resolve(rel).read_text(encoding="utf-8", errors="replace")
    parsed = parse(text, rel)
    meta, body = parsed.frontmatter, parsed.body
    title = str(meta.get("task_title") or "").strip() or parsed.title
    return {
        "found": True,
        "path": rel,
        "task_title": title,
        "saved_at": str(meta.get("saved_at") or "") or None,
        "content": body_without_title(body.strip()).strip(),
    }


def mark_current(engine: Engine, project: str, project_dir: str | None, rel: str) -> None:
    """Make ``rel`` the state in use for this project and worktree."""
    if _is_active_state(engine, rel):
        _remember_current(_key(project, project_dir), rel)


def archive(engine: Engine, rel: str) -> bool:
    """Set ``status: archived`` on a state; False if it already was. Never deletes."""
    _forget(rel)
    meta, body = _read(engine, rel)
    if meta.get("status") == ARCHIVED:
        return False
    meta["status"] = ARCHIVED
    _write(engine, rel, meta, body)
    return True


def _saved_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(value).date()
    except ValueError:
        return None


def has_active(engine: Engine) -> bool:
    """True when some project has an active state (rotation has something to look at)."""
    return bool(_active_rows(engine))


def rotate(engine: Engine, archive_days: int) -> list[str]:
    """Archive the active states whose ``saved_at`` is more than ``archive_days`` days old."""
    cutoff = today() - dt.timedelta(days=archive_days)
    stale = [r["path"] for r in _active_rows(engine) if _saved_before(engine, r["path"], cutoff)]
    return [rel for rel in stale if archive(engine, rel)]


def _saved_before(engine: Engine, rel: str, cutoff: dt.date) -> bool:
    """True when the state's ``saved_at`` is a date before ``cutoff``; False without one."""
    saved = _saved_date(_saved_at(engine, rel))
    return saved is not None and saved < cutoff

