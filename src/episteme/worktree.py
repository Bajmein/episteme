"""Worktree helpers: resolve a session's ``project_dir`` and match saved notes to it.

Session states and plans record the worktree they were saved in; these helpers resolve the
directory the hook passes and compare it with that ``worktree`` key.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from episteme.errors import invalid

if TYPE_CHECKING:
    from episteme.engine import Engine


def resolve_project_dir(project_dir: str | None) -> Path:
    """The real path of ``project_dir`` (the cwd when absent); it must be an existing dir."""
    raw = project_dir or os.getcwd()
    path = Path(raw)
    if not path.is_absolute():
        raise invalid(f'project_dir "{raw}" is not absolute. Pass the session cwd.')
    if not path.is_dir():
        raise invalid(f'project_dir "{raw}" does not exist.')
    return Path(os.path.realpath(path))


def normalized_dir(project_dir: str | None) -> str:
    """The resolved ``project_dir`` as it is compared with a note's ``worktree``."""
    return os.path.normcase(resolve_project_dir(project_dir).as_posix())


def same_worktree(engine: Engine, row: Any, here: str) -> bool:
    """True when the note was saved in ``here`` or predates the ``worktree`` key."""
    saved = engine.index.props(row["path"]).get("worktree")
    return not saved or os.path.normcase(str(saved)) == here
