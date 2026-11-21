"""Docs suites: zones of third-party pages that only ``docs_write`` changes."""

from __future__ import annotations

from episteme.docs.hashing import HASH_LEN, body_hash, page_body
from episteme.docs.inbox import INBOX_DIR, inbox_dir
from episteme.docs.status import docs_status
from episteme.docs.writing import docs_write

__all__ = [
    "HASH_LEN",
    "INBOX_DIR",
    "body_hash",
    "docs_status",
    "docs_write",
    "inbox_dir",
    "page_body",
]
