"""Maintenance coordination between server processes.

``Store`` keeps ``.index/maintenance.db``: when each maintenance task last ran
(so only one process per period runs it) and a short log of what it changed.
It is best-effort: no method raises, and nothing is created on disk until the
first ``claim``.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path

from episteme.index import Index
from episteme.vault import INDEX_DIR, today

SCHEMA_VERSION = 1
LOG_RETENTION_DAYS = 365

_SCHEMA = """
create table if not exists runs (task text primary key, at text);
create table if not exists log (
    id integer primary key, at text, task text, path text, detail text
);
create index if not exists log_at on log(at);
"""


class Store:
    """Per-vault run registry and change log; methods never raise."""

    def __init__(self, vault_root: Path) -> None:
        self.db_path = Path(vault_root) / INDEX_DIR / "maintenance.db"
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

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
                    conn.executescript(_SCHEMA)
                    conn.execute(f"pragma user_version = {SCHEMA_VERSION}")
            except Exception:
                conn.close()
                raise
            self._conn = conn
        return self._conn

    def claim(self, task: str, every_days: int) -> str | None:
        """Claim ``task`` for this period.

        Returns the previous run date (``""`` if none) when the task is due and
        is now marked as run today, or ``None`` when it is not due or on error.
        """
        try:
            with self._lock:
                conn = self._connect()
                now = today()

                def work() -> str | None:
                    row = conn.execute("select at from runs where task = ?", (task,)).fetchone()
                    previous = row[0] if row else ""
                    due = True
                    if row:
                        try:
                            days = (now - dt.date.fromisoformat(previous)).days
                            # A future date (clock skew) counts as due.
                            due = days < 0 or days >= every_days
                        except ValueError, TypeError:
                            due = True
                    if not due:
                        return None
                    cutoff = (
                        dt.datetime.now(dt.UTC) - dt.timedelta(days=LOG_RETENTION_DAYS)
                    ).isoformat()
                    conn.execute("delete from log where at < ?", (cutoff,))
                    conn.execute(
                        "insert into runs(task, at) values (?, ?) "
                        "on conflict(task) do update set at = excluded.at",
                        (task, now.isoformat()),
                    )
                    return previous if isinstance(previous, str) else ""

                return Index._in_transaction(conn, work)
        except sqlite3.Error, OSError, ValueError:
            return None

    def restore(self, task: str, previous: str) -> None:
        """Put ``previous`` back as the last run of ``task`` (delete if empty)."""
        try:
            with self._lock:
                conn = self._connect()

                def work() -> None:
                    if previous == "":
                        conn.execute("delete from runs where task = ?", (task,))
                    else:
                        conn.execute(
                            "insert into runs(task, at) values (?, ?) "
                            "on conflict(task) do update set at = excluded.at",
                            (task, previous),
                        )

                Index._in_transaction(conn, work)
        except sqlite3.Error, OSError:
            return

    def log(self, task: str, paths: list[str], detail: str = "") -> None:
        """Record one row per path (a single row with an empty path if none)."""
        try:
            with self._lock:
                conn = self._connect()
                at = dt.datetime.now(dt.UTC).isoformat()
                rows = [(at, task, p, detail) for p in (paths or [""])]

                def work() -> None:
                    conn.executemany(
                        "insert into log(at, task, path, detail) values (?, ?, ?, ?)", rows
                    )

                Index._in_transaction(conn, work)
        except sqlite3.Error, OSError:
            return

    def close(self) -> None:
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
