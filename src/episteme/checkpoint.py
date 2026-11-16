"""Task checkpoints from the project's ``estado.md`` (save on PreCompact, restore after)."""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.index import is_past
from episteme.markdown import (
    ParsedNote,
    body_without_title,
    compose,
    parse,
    section_text,
    slugify,
)
from episteme.memory import NoteFile, find_secrets, ordered, validate
from episteme.vault import today

if TYPE_CHECKING:
    from episteme.engine import Engine

SECTIONS = ("Plan", "Progreso", "Decisiones", "Trampas", "Siguientes pasos")
VALID_DAYS = 7
CHECKPOINT_PRIORITY = 3
CHECKPOINT_HELPFUL = 0
COPIED_KEYS = ("estado", "etapa", "tags", "keywords", "files")
TASK_CHECKBOX = re.compile(r"^[-*]\s*\[([ xX~])\]\s*(\S+)", re.MULTILINE)
BRANCH_CHANGE = re.compile(r"refs/heads/[a-z]+/(\d{3}-[a-z0-9][a-z0-9-]*)$")


def _project_dir(project_dir: str | None) -> Path:
    raw = project_dir or os.getcwd()
    path = Path(raw)
    if not path.is_absolute():
        raise invalid(f'project_dir "{raw}" is not absolute. Pass the session cwd.')
    if not path.is_dir():
        raise invalid(f'project_dir "{raw}" does not exist.')
    return Path(os.path.realpath(path))


def _normalized_dir(project_dir: str | None) -> str:
    """The resolved ``project_dir`` as it is compared with a checkpoint's ``worktree``."""
    return os.path.normcase(_project_dir(project_dir).as_posix())


def _git_head(base: Path) -> str:
    """Contents of ``.git/HEAD`` for a checkout or a linked worktree, or an empty string."""
    git = base / ".git"
    try:
        if git.is_file():
            first = git.read_text(encoding="utf-8").strip()
            if not first.startswith("gitdir:"):
                return ""
            git = Path(first.removeprefix("gitdir:").strip())
            if not git.is_absolute():
                git = base / git
        return (git / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def branch_change(base: Path) -> str | None:
    """``<ID>-<change>`` from a ``<type>/<ID>-<change>`` branch, read from ``.git/HEAD``."""
    match = BRANCH_CHANGE.search(_git_head(base))
    return match.group(1) if match else None


def _state_glob(engine: Engine) -> str:
    """The validated ``state_glob`` of the vault config."""
    glob = engine.vault.config.state_glob
    if not glob:
        raise invalid(
            "episteme.toml has no [checkpoint] state_glob. "
            'Add a [checkpoint] section with state_glob = ".fabrik/**/estado.md" '
            "(relative to project_dir)."
        )
    if Path(glob).is_absolute() or ".." in Path(glob).parts:
        raise invalid("state_glob must be relative to project_dir and stay inside it.")
    return glob


def _load_state(base: Path, candidate: Path) -> tuple[int, Path, ParsedNote] | None:
    """``(mtime, real path, note)`` of an active state file inside ``base``, else None."""
    real = Path(os.path.realpath(candidate))
    if base not in real.parents or not real.is_file():
        return None
    try:
        note = parse(real.read_text(encoding="utf-8", errors="replace"), real.name)
        mtime = real.stat().st_mtime_ns
    except OSError:
        return None
    if str(note.frontmatter.get("estado", "")).strip().lower() != "activo":
        return None
    return mtime, real, note


def active_states(engine: Engine, project_dir: str | None) -> list[tuple[Path, ParsedNote]]:
    """Every ``estado: activo`` file matched by ``state_glob``, newest mtime first."""
    glob = _state_glob(engine)
    base = _project_dir(project_dir)
    loaded = (_load_state(base, candidate) for candidate in base.glob(glob))
    found = [item for item in loaded if item is not None]
    found.sort(key=lambda f: (f[0], str(f[1])), reverse=True)
    return [(path, note) for _, path, note in found]


def _title(path: Path, note: ParsedNote) -> str:
    title = str(note.frontmatter.get("task_title") or "").strip()
    if title:
        return title
    heading = next((h.text for h in note.headings if h.level == 1), None)
    return heading or path.parent.name


def _pick(
    states: list[tuple[Path, ParsedNote]], project_dir: str | None
) -> tuple[Path, ParsedNote] | None:
    """The state of the current branch's change, else the newest active one."""
    if not states:
        return None
    branch = branch_change(_project_dir(project_dir))
    mine = [s for s in states if branch and s[0].parent.name == branch]
    return (mine or states)[0]


def flow_line(path: Path, note: ParsedNote) -> str:
    """One line with the change, its ``etapa`` and the progress of the sibling ``tasks.md``."""
    change = path.parent
    etapa = str(note.frontmatter.get("etapa") or "?")
    line = f"Flujo fabrik: change {change.name} ({change.parent.name}), etapa {etapa}"
    try:
        matches = TASK_CHECKBOX.findall((change / "tasks.md").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return line
    done = sum(1 for m in matches if m[0] in "xX")
    doing = [m[1] for m in matches if m[0] == "~"]
    pending = [m[1] for m in matches if m[0] == " "]
    current = f", en curso {' '.join(doing)}" if doing else ""
    nxt = pending[0] if pending else "ninguna"
    return f"{line}, tasks {done}/{len(matches)}{current}, siguiente {nxt}"


def _render(path: Path, note: ParsedNote) -> tuple[str, str]:
    """(title, checkpoint body) from a state file: the five SECTIONS, no Bitácora."""
    title = _title(path, note)
    parts = [f"# Checkpoint · {title}"]
    for name in SECTIONS:
        text = section_text(note, name)
        if text is not None:
            parts.append(text.strip())
    return title, "\n\n".join(parts) + "\n"


def _children(value: Any) -> Iterable[Any]:
    """The items nested directly inside a frontmatter value (none for a scalar)."""
    if isinstance(value, dict):
        return value.values()
    if isinstance(value, (list, tuple)):
        return value
    return ()


def _strings(value: Any) -> Iterator[str]:
    """Every string inside a frontmatter value, however nested."""
    if isinstance(value, str):
        yield value
        return
    for item in _children(value):
        yield from _strings(item)


def _reject_secrets_in(meta: dict[str, Any], body: str) -> None:
    """Raise ``invalid_argument`` when what is about to be saved looks like a credential."""
    for text in (body, *_strings(meta)):
        found = find_secrets(text)
        if found:
            raise invalid(
                f"estado.md looks like it holds a secret ({found}). "
                "Remove it from the state file and say where it is stored instead."
            )


def save(engine: Engine, project_dir: str | None, project: str | None) -> dict[str, Any]:
    project = engine.need_project(project)
    zone = engine.vault.memory_zone
    if zone is None:
        raise invalid('the vault has no zone with mode = "memory". Declare one in episteme.toml.')
    picked = _pick(active_states(engine, project_dir), project_dir)
    if picked is None:
        return {"saved": False, "path": None, "task_title": None}
    state, note = picked
    fm = note.frontmatter
    title, body = _render(state, note)

    now = today()
    meta: dict[str, Any] = {
        "type": "session",
        "kind": "episodic",
        "project": project,
        "priority": CHECKPOINT_PRIORITY,
        "status": "active",
        "created": now,
        "valid_until": now + dt.timedelta(days=VALID_DAYS),
        "helpful": CHECKPOINT_HELPFUL,
        "task_title": title,
    }
    if project_dir:  # without it the base is the server's cwd, which says nothing of the session
        meta["worktree"] = _project_dir(project_dir).as_posix()
    meta.update({key: fm[key] for key in COPIED_KEYS if key in fm and key not in meta})
    _reject_secrets_in(meta, body)
    validate(meta)
    rel = f"{zone.path}/{project}/sessions/checkpoint-{slugify(title)}.md"
    engine.vault.check_writable(rel)
    engine.vault.write_atomic(rel, compose(ordered(meta), body))
    engine.index.reindex(rel)
    return {"saved": True, "path": rel, "task_title": title}


def _saved(engine: Engine, project: str) -> list[Any]:
    """Active, unexpired checkpoint memories of the project."""
    iso = today().isoformat()
    rows = engine.index.memories(
        "project = ? and type = 'session' and status = 'active' and path like ?",
        (project, "%/checkpoint-%"),
    )
    return [r for r in rows if not is_past(r["valid_until"], iso)]


def _row_title(engine: Engine, row: Any) -> str:
    """The task title of a saved checkpoint row."""
    return engine.index.props(row["path"]).get("task_title") or row["title"]


def _same_worktree(engine: Engine, row: Any, here: str) -> bool:
    """True when the checkpoint was saved in ``here`` or predates the ``worktree`` key."""
    saved = engine.index.props(row["path"]).get("worktree")
    return not saved or os.path.normcase(str(saved)) == here


def _saved_result(engine: Engine, rows: list[Any]) -> dict[str, Any]:
    """The newest of the saved ``rows`` as a restore result, or the empty result."""
    if not rows:
        return {"found": False, "path": None, "task_title": None, "content": "", "source": None}
    row = max(rows, key=lambda r: (r["created"] or "", r["mtime_ns"] or 0, r["path"]))
    title = _row_title(engine, row)
    body = f"# Checkpoint · {title}\n\n{body_without_title(row['body'] or '')}".strip()
    content = (
        f"Saved checkpoint from {row['created']}, not the live state: check it against the "
        f"working tree and do not redo listed steps without a current request.\n\n{body}"
    )
    return {
        "found": True,
        "path": row["path"],
        "task_title": title,
        "content": content,
        "source": "checkpoint",
    }


def _archive_stale(
    engine: Engine, project: str, active_titles: set[str], project_dir: str | None = None
) -> None:
    """Archive the saved checkpoints of tasks that no longer have an active state.

    Only those of this worktree (or without the ``worktree`` key): another worktree's
    checkpoints are not this state's to judge.
    """
    here = _normalized_dir(project_dir)
    for row in _saved(engine, project):
        if not _same_worktree(engine, row, here):
            continue
        if _row_title(engine, row) not in active_titles:
            nf = NoteFile(engine, row["path"])
            nf.set_fields({"status": "archived"})
            nf.save()


def _restore_live(
    engine: Engine, project: str, project_dir: str | None, task_title: str | None
) -> dict[str, Any] | None:
    """The live-state result (the requested task, else the branch's or newest), or None."""
    states = active_states(engine, project_dir) if project_dir else []
    if task_title:
        wanted = task_title.strip()
        chosen = next((s for s in states if _title(*s) == wanted), None)
    else:
        chosen = _pick(states, project_dir)
        if chosen is not None:
            # A saved checkpoint of a task that is no longer active must not come back later.
            _archive_stale(engine, project, {_title(*s) for s in states}, project_dir)
    if chosen is None:
        return None
    path, note = chosen
    title, body = _render(path, note)
    base = _project_dir(project_dir)
    content = f"{flow_line(path, note)}\n\n{body}".strip()
    return {
        "found": True,
        "path": path.relative_to(base).as_posix(),
        "task_title": title,
        "content": content,
        "source": "state",
    }


def _restore_saved(
    engine: Engine, project: str, project_dir: str | None, task_title: str | None
) -> dict[str, Any]:
    """The saved-checkpoint result for this worktree (and task, if asked), or the empty one."""
    rows = _saved(engine, project)
    if project_dir:
        here = _normalized_dir(project_dir)
        rows = [r for r in rows if _same_worktree(engine, r, here)]
    if task_title:
        wanted = task_title.strip()
        rows = [r for r in rows if _row_title(engine, r) == wanted]
    return _saved_result(engine, rows)


def restore(
    engine: Engine,
    project: str | None,
    project_dir: str | None = None,
    task_title: str | None = None,
) -> dict[str, Any]:
    """Live ``estado.md`` first (branch's change, else newest active), saved checkpoint after.

    With ``task_title`` it resumes that task instead. Without ``project_dir`` only saved
    checkpoints are looked at. With ``project_dir`` the saved ones are limited to that
    worktree (checkpoints saved before the ``worktree`` key match any); a saved checkpoint's
    content starts with a notice that it is not the live state.
    """
    project = engine.need_project(project)
    live = _restore_live(engine, project, project_dir, task_title)
    if live is not None:
        return live
    return _restore_saved(engine, project, project_dir, task_title)
