"""Task checkpoints from the project's ``estado.md`` (save on PreCompact, restore after)."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.markdown import body_without_title, compose, parse, section_text, slugify
from episteme.memory import ordered, validate
from episteme.vault import today

if TYPE_CHECKING:
    from episteme.engine import Engine

SECTIONS = ("Plan", "Progreso", "Decisiones", "Trampas", "Siguientes pasos")
VALID_DAYS = 7


def _project_dir(project_dir: str | None) -> Path:
    raw = project_dir or os.getcwd()
    path = Path(raw)
    if not path.is_absolute():
        raise invalid(f'project_dir "{raw}" is not absolute. Pass the session cwd.')
    if not path.is_dir():
        raise invalid(f'project_dir "{raw}" does not exist.')
    return Path(os.path.realpath(path))


def active_state(engine: Engine, project_dir: str | None) -> Path | None:
    """The ``estado: activo`` file with the newest mtime, read only through ``state_glob``."""
    glob = engine.vault.config.state_glob
    if not glob:
        raise invalid(
            "episteme.toml has no [checkpoint] state_glob. "
            'Add e.g. state_glob = ".fabrik/*/*/estado.md".'
        )
    if Path(glob).is_absolute() or ".." in Path(glob).parts:
        raise invalid("state_glob must be relative to project_dir and stay inside it.")
    base = _project_dir(project_dir)
    best: tuple[int, Path] | None = None
    for candidate in base.glob(glob):
        real = Path(os.path.realpath(candidate))
        if base not in real.parents or not real.is_file():
            continue
        try:
            note = parse(real.read_text(encoding="utf-8", errors="replace"), real.name)
        except OSError:
            continue
        if str(note.frontmatter.get("estado", "")).strip().lower() != "activo":
            continue
        mtime = real.stat().st_mtime_ns
        if best is None or mtime > best[0]:
            best = (mtime, real)
    return best[1] if best else None


def save(engine: Engine, project_dir: str | None, project: str | None) -> dict[str, Any]:
    project = engine.need_project(project)
    zone = engine.vault.memory_zone
    if zone is None:
        raise invalid('the vault has no zone with mode = "memory". Declare one in episteme.toml.')
    state = active_state(engine, project_dir)
    if state is None:
        return {"saved": False, "path": None, "task_title": None}
    note = parse(state.read_text(encoding="utf-8", errors="replace"), state.name)
    fm = note.frontmatter
    title = str(fm.get("task_title") or "").strip()
    if not title:
        heading = next((h.text for h in note.headings if h.level == 1), None)
        title = heading or state.parent.name

    parts = [f"# Checkpoint · {title}"]
    for name in SECTIONS:
        text = section_text(note, name)
        if text is not None:
            parts.append(text.strip())
    body = "\n\n".join(parts) + "\n"

    now = today()
    meta: dict[str, Any] = {
        "type": "session",
        "kind": "episodic",
        "project": project,
        "priority": 3,
        "status": "active",
        "created": now,
        "valid_until": now + dt.timedelta(days=VALID_DAYS),
        "helpful": 0,
        "task_title": title,
    }
    for key, value in fm.items():
        if key not in meta and key != "task_title":
            meta[key] = value
    validate(meta)
    rel = f"{zone.path}/{project}/sessions/checkpoint-{slugify(title)}.md"
    engine.vault.check_writable(rel)
    engine.vault.write_atomic(rel, compose(ordered(meta), body))
    engine.index.reindex(rel)
    return {"saved": True, "path": rel, "task_title": title}


def restore(engine: Engine, project: str | None) -> dict[str, Any]:
    project = engine.need_project(project)
    iso = today().isoformat()
    rows = engine.index.memories(
        "project = ? and type = 'session' and status = 'active' and path like ?",
        (project, "%/checkpoint-%"),
    )
    rows = [r for r in rows if not (r["valid_until"] and r["valid_until"] < iso)]
    if not rows:
        return {"found": False, "path": None, "task_title": None, "content": ""}
    best = max(rows, key=lambda r: (r["created"] or "", r["mtime_ns"] or 0, r["path"]))
    props = engine.index.props(best["path"])
    title = props.get("task_title") or best["title"]
    content = f"# Checkpoint · {title}\n\n{body_without_title(best['body'] or '')}".strip()
    return {"found": True, "path": best["path"], "task_title": title, "content": content}
