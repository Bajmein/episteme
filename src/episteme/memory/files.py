"""File matching between a path and the memories that list it."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.memory.scoring import _neg_date

if TYPE_CHECKING:
    from episteme.engine import Engine


def project_relative(file: str, project_dir: str | None) -> str:
    """The project-relative form of ``file`` when ``project_dir`` contains it."""
    f = file.replace("\\", "/")
    if project_dir and os.path.isabs(f):
        for base, target in (
            (os.path.normpath(project_dir), os.path.normpath(f)),
            (os.path.realpath(project_dir), os.path.realpath(f)),
        ):
            # normcase: on Windows separators are "\" and the drive letter's case varies.
            if os.path.normcase(target).startswith(os.path.normcase(os.path.join(base, ""))):
                return os.path.relpath(target, base).replace("\\", "/")
    return f.removeprefix("./")


def file_matches(file: str, rel: str, entry: str) -> bool:
    """Match a ``files`` entry against a file (see «Casado de file con files»)."""
    entry = entry.strip().replace("\\", "/").removeprefix("./")
    if not entry:
        return False
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatchcase(rel, entry)
    file = file.replace("\\", "/")
    return rel == entry or file.endswith("/" + entry) or rel.endswith("/" + entry)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [f for f in value if isinstance(f, str)] if isinstance(value, list) else []


def _files_of(engine: Engine) -> dict[str, list[str]]:
    """The ``files`` entries of every note that has them, in one query: ``{path: [entry]}``."""
    return {
        r["path"]: _as_list(json.loads(r["value"]))
        for r in engine.index.conn.execute("select path, value from props where key = 'files'")
    }


def _hook_file(
    file: str, relative_path: str | None, project_dir: str | None
) -> tuple[str, str] | None:
    """The file a hook is about: ``file`` or, for Serena edits, ``relative_path``; None if both
    are empty."""
    chosen = (file or "").strip() or (relative_path or "").strip()
    return (chosen, project_relative(chosen, project_dir)) if chosen else None


def _clean_entry(entry: str) -> str:
    return entry.strip().replace("\\", "/").removeprefix("./")


def _is_other_path_same_name(e: str, rel: str, name: str) -> bool:
    """True when entry ``e`` is a distinct plain path with base name ``name``."""
    if not e or any(c in e for c in "*?[") or e == rel or PurePosixPath(e).name != name:
        return False
    return not rel.endswith("/" + e) and not e.endswith("/" + rel)


def _name_is_unambiguous(rel: str, name: str, files: dict[str, list[str]]) -> bool:
    """True when no other known path in the project shares the base name ``name``."""
    if name == rel:
        return False
    return not any(
        _is_other_path_same_name(_clean_entry(e), rel, name)
        for entries in files.values()
        for e in entries
    )


def _by_priority(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda r: (-(r["priority"] or 0), _neg_date(r["created"]), r["path"]))
