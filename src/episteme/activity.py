"""Activity log: one row per tool call in ``<vault>/.index/activity.db``."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from episteme.vault import INDEX_DIR

SCHEMA_VERSION = 1
RETENTION_DAYS = 180
MAX_PATHS = 30
MAX_STRING = 200
ARG_KEYS = (
    "mode", "action", "type", "path", "note", "notes", "file", "relative_path", "query",
    "tags", "status", "zone", "heading", "lines", "limit", "match", "title", "task",
)  # fmt: skip
_MD_IN_PARENS = re.compile(r"\(([^()\s]+\.md)\)")

_SCHEMA = """
create table calls (
    id integer primary key,
    at text, pid integer, session text, tool text, hook_event text, project text,
    args text, paths text, chars integer, ms integer, ok integer
);
create index calls_at on calls (at);
create index calls_tool on calls (tool);
"""


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in value]
    return value


def _walk(node: Any, depth: int, found: list[str]) -> None:
    if depth > 3:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "path" and isinstance(value, str):
                found.append(value)
            elif key == "paths" and isinstance(value, list):
                found.extend(v for v in value if isinstance(v, str))
            else:
                _walk(value, depth + 1, found)
    elif isinstance(node, list):
        for item in node:
            _walk(item, depth + 1, found)


def extract_paths(text: str) -> list[str]:
    """Vault paths that appear in a tool result (JSON ``path``/``paths`` or ``(x.md)``)."""
    found: list[str] = []
    if text.lstrip().startswith(("{", "[")):
        try:
            _walk(json.loads(text), 0, found)
        except ValueError:
            pass
    found.extend(_MD_IN_PARENS.findall(text))
    return list(dict.fromkeys(found))[:MAX_PATHS]


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class Activity:
    """Best-effort call log; ``record`` never raises."""

    def __init__(self, vault_root: Path) -> None:
        self.db_path = Path(vault_root) / INDEX_DIR / "activity.db"
        self._conn: sqlite3.Connection | None = None
        self._pruned = False

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False
            )
            try:
                conn.execute("pragma journal_mode = wal")
                conn.execute("pragma busy_timeout = 5000")
                version = conn.execute("pragma user_version").fetchone()[0]
                if version < SCHEMA_VERSION:
                    conn.execute("drop table if exists calls")
                    conn.executescript(_SCHEMA)
                    conn.execute(f"pragma user_version = {SCHEMA_VERSION}")
            except Exception:
                conn.close()
                raise
            self._conn = conn
        return self._conn

    def record(
        self, tool: str, arguments: dict[str, Any] | None, text: str, ms: int, ok: bool
    ) -> None:
        try:
            if os.environ.get("EPISTEME_ACTIVITY") == "0":
                return
            arguments = arguments if isinstance(arguments, dict) else {}
            conn = self._connect()
            now = datetime.now(UTC)
            if not self._pruned:
                self._pruned = True
                cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
                conn.execute("delete from calls where at < ?", (cutoff,))
            args = {k: _clip(arguments[k]) for k in ARG_KEYS if k in arguments}
            text = text or ""
            conn.execute(
                "insert into calls (at, pid, session, tool, hook_event, project, args,"
                " paths, chars, ms, ok) values (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now.isoformat(timespec="seconds"),
                    os.getpid(),
                    _text(arguments.get("session")),
                    tool,
                    _text(arguments.get("hook_event")),
                    _text(arguments.get("project")),
                    json.dumps(args, ensure_ascii=False, default=str),
                    json.dumps(extract_paths(text), ensure_ascii=False),
                    len(text),
                    int(ms),
                    1 if ok else 0,
                ),
            )
        except Exception:  # nosec B110
            pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # nosec B110
                pass
            self._conn = None
