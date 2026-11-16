"""Owner-only permissions for ``.index/`` and its databases (POSIX; a no-op on Windows)."""

from __future__ import annotations

import os
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600
_SIDE_SUFFIXES = ("", "-wal", "-shm")


def make_private_dir(path: Path) -> None:
    """Create ``path`` (and parents) and restrict it to its owner."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return
    try:
        os.chmod(path, DIR_MODE)
    except OSError:
        pass  # Not ours to change (shared mount): the databases are restricted anyway.


def restrict_db(path: Path) -> None:
    """Restrict a SQLite file and its WAL side files to their owner."""
    if os.name == "nt":
        return
    for suffix in _SIDE_SUFFIXES:
        try:
            os.chmod(f"{path}{suffix}", FILE_MODE)
        except OSError:
            continue  # Absent side file, or not ours to change.
