"""The body hash of a suite note, shared with the skill's ``docs_check.py``."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from episteme.markdown import load_frontmatter, split_frontmatter

HASH_LEN = 16


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def body_hash(body: str) -> str:
    """The first 16 hex digits of the SHA-256 of ``body`` with normalised line ends.

    ``docs_check.py`` (plugin/skills/docs/scripts) carries a copy: change both at once.
    """
    text = _lines(body).strip() + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_LEN]


@dataclass(frozen=True)
class SplitNote:
    frontmatter: dict[str, Any]
    fm_valid: bool
    body: str


def split_note(text: str) -> SplitNote:
    """The frontmatter of a note and its body (what follows the frontmatter block)."""
    lines = _lines(text).split("\n")
    raw, end = split_frontmatter(lines)
    fm, valid, _ = load_frontmatter(raw)
    return SplitNote(fm, valid, "\n".join(lines[end:]))
