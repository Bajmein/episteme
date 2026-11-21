"""The inbox: bodies ``docs_check.py diff`` downloaded, which ``docs(action="write")`` takes."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from episteme.docs.hashing import HASH_LEN, body_hash
from episteme.errors import NOT_FOUND, OUTSIDE_VAULT, EpistemeError, invalid
from episteme.index import NOTE_MAX_BYTES
from episteme.vault import INDEX_DIR

if TYPE_CHECKING:
    from episteme.vault import Vault, Zone

INBOX_DIR = f"{INDEX_DIR}/docs-inbox"
_HASH = re.compile(rf"[0-9a-f]{{{HASH_LEN}}}")


def inbox_dir(vault: Vault, zone: Zone) -> Path:
    """``<vault>/.index/docs-inbox/<zone>``: where the script leaves the bodies of a suite."""
    return vault.root / INBOX_DIR / zone.path


def check_ref(ref: str | None) -> None:
    """``invalid_argument`` unless ``ref`` is a body hash (lowercase hex, ``HASH_LEN`` digits)."""
    if ref is not None and not _HASH.fullmatch(ref):
        raise invalid(f"body_ref {ref!r} is not a body hash. Pass a hash from docs_check.py diff.")


def _shown(vault: Vault, path: Path) -> str:
    return path.relative_to(vault.root).as_posix()


def _confined(vault: Vault, zone: Zone, ref: str) -> Path:
    """The real path of the inbox file ``ref``, which must be a regular file inside the inbox."""
    inbox = inbox_dir(vault, zone)
    file = inbox / f"{ref}.md"
    shown = _shown(vault, file)
    if not os.path.lexists(file):
        raise EpistemeError(
            NOT_FOUND,
            f"no downloaded body {ref} in the inbox of {zone.path}. Run docs_check.py diff again.",
        )
    real = Path(os.path.realpath(file))
    if Path(os.path.realpath(inbox)) not in real.parents or not real.is_file():
        raise EpistemeError(
            OUTSIDE_VAULT, f"{shown} is not a regular file of the inbox. Run diff again."
        )
    return real


def read_body(vault: Vault, zone: Zone, ref: str) -> tuple[str, Path]:
    """The downloaded body for ``ref`` and its confined path; the hash must match."""
    real = _confined(vault, zone, ref)
    shown = _shown(vault, inbox_dir(vault, zone) / f"{ref}.md")
    if real.stat().st_size > NOTE_MAX_BYTES:
        limit = NOTE_MAX_BYTES // 1024 // 1024
        raise invalid(f"body is over the {limit} MB limit; episteme would not index it. Skip it.")
    text = real.read_text(encoding="utf-8")
    if body_hash(text) != ref:
        raise invalid(f"{shown} does not match its hash. Run docs_check.py diff again.")
    return text, real


def discard(path: Path) -> None:
    """Delete a consumed inbox file (``path`` comes from ``read_body``)."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
