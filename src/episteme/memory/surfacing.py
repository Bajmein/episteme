"""Memories surfaced for a file: ``surface`` and ``constraints``."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid
from episteme.markdown import (
    body_without_title,
    clip,
)
from episteme.memory.files import (
    _by_priority,
    _files_of,
    _hook_file,
    _name_is_unambiguous,
    file_matches,
)
from episteme.memory.scoring import entry_line
from episteme.vault import MEMORY, today

if TYPE_CHECKING:
    from episteme.engine import Engine


def _file_memories(
    engine: Engine, project: str, type_clause: str
) -> tuple[list[Any], dict[str, list[str]]]:
    """The project's (and ``_shared``) active, unexpired memories of the types in ``type_clause``,
    and the ``files`` entries of every note."""
    rows = engine.index.memories(
        "project in (?, '_shared') and status = 'active'"
        f" and {type_clause} and (valid_until is null or valid_until >= ?)",  # nosec B608
        (project, today().isoformat()),
    )
    return rows, _files_of(engine)


def _by_files(rows: list[Any], files: dict[str, list[str]], file: str, rel: str) -> list[Any]:
    """The ``rows`` whose ``files`` entries match the file, by priority."""
    return _by_priority(
        [r for r in rows if any(file_matches(file, rel, e) for e in files.get(r["path"], []))]
    )


def surface(
    engine: Engine,
    file: str,
    project_dir: str | None,
    project: str | None,
    limit: int,
    relative_path: str | None = None,
    skip: set[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Memories about a file. ``skip``: paths already shown; left out of the text, not the data."""
    if not (1 <= limit <= 50):
        raise invalid(f"limit must be 1-50, got {limit}.")
    project = engine.need_project(project)
    target = _hook_file(file, relative_path, project_dir)
    if target is None:
        return "", {"file": "", "memories": []}
    file, rel = target
    rows, files = _file_memories(
        engine, project, "type not in ('constraint', 'session', 'reminder')"
    )
    by_files = _by_files(rows, files, file, rel)
    seen = {r["path"] for r in by_files}
    name = PurePosixPath(rel).name
    query = f'"{rel}"' + (f' "{name}"' if _name_is_unambiguous(rel, name, files) else "")
    hits, _ = engine.index.search(
        query,
        any_term=True,
        mode=MEMORY,
        project=[project, "_shared"],
        limit=1000,
        snippets=False,
    )
    hit_paths = {h.path for h in hits}
    by_mention = _by_priority([r for r in rows if r["path"] in hit_paths and r["path"] not in seen])
    chosen = [(r, "files") for r in by_files] + [(r, "mention") for r in by_mention]
    chosen = chosen[:limit]
    text = ""
    fresh = [r for r, _ in chosen if r["path"] not in (skip or ())]
    if fresh:
        shown = len(chosen) - len(fresh)
        head = f"Memories about {rel}" + (f" (+{shown} ya mostradas)" if shown else "") + ":"
        text = "\n".join([head] + [entry_line(r) for r in fresh])
    data = {
        "file": rel,
        "memories": [
            {
                "path": r["path"],
                "title": r["title"],
                "type": r["type"],
                "priority": r["priority"],
                "match": match,
            }
            for r, match in chosen
        ],
    }
    return text, data


def constraints(
    engine: Engine,
    file: str,
    project_dir: str | None,
    project: str | None,
    relative_path: str | None = None,
) -> tuple[str, dict[str, Any]]:
    project = engine.need_project(project)
    target = _hook_file(file, relative_path, project_dir)
    if target is None:
        return "", {"file": "", "constraints": []}
    file, rel = target
    rows, files = _file_memories(engine, project, "type = 'constraint'")
    found = _by_files(rows, files, file, rel)
    items = [
        {
            "path": r["path"],
            "title": r["title"],
            "priority": r["priority"],
            "body": clip(body_without_title(r["body"] or ""), 600),
        }
        for r in found
    ]
    text = ""
    if items:
        parts = [f"Constraints that apply to {rel}:"]
        for item in items:
            parts.append(f"- {item['title']} ({item['path']})")
            parts.append(item["body"])
        text = "\n".join(parts)
    return text, {"file": rel, "constraints": items}
