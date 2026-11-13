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
from typing import TYPE_CHECKING

from episteme.index import Index
from episteme.vault import INDEX_DIR, today

if TYPE_CHECKING:
    from episteme.engine import Engine
    from episteme.vault import Vault

SCHEMA_VERSION = 1
LOG_RETENTION_DAYS = 365
CONNECT_TIMEOUT_S = 5.0
BUSY_TIMEOUT_MS = 5000
MAX_LISTED = 5

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
                self.db_path,
                timeout=CONNECT_TIMEOUT_S,
                isolation_level=None,
                check_same_thread=False,
            )
            try:
                conn.execute("pragma journal_mode = wal")
                conn.execute(f"pragma busy_timeout = {BUSY_TIMEOUT_MS}")
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
                except sqlite3.Error:  # nosec B110
                    # Closing is best-effort: a failure here must not break shutdown.
                    pass


def _archived_line(paths: list[str]) -> str:
    shown = ", ".join(paths[:MAX_LISTED])
    more = f" +{len(paths) - MAX_LISTED} más" if len(paths) > MAX_LISTED else ""
    return (
        f"episteme · mantención: {len(paths)} memorias vencidas archivadas "
        f"(valid_until pasado): {shown}{more}. Se revierte con revise."
    )


def _archive_line(engine: Engine, store: Store, every_days: int) -> str:
    """Archive expired memories if due; return the notice line (``""`` if none)."""
    from episteme import memory

    previous = store.claim("archive_expired", every_days)
    if previous is None:
        return ""
    try:
        paths = memory.archive_expired(engine)
    except Exception:
        store.restore("archive_expired", previous)
        return ""
    if not paths:
        return ""
    store.log("archive_expired", paths)
    return _archived_line(paths)


def _notify_line(engine: Engine, store: Store, project: str, every_days: int) -> str:
    """Build the review notice if due; return it (``""`` if none)."""
    from episteme import prompting

    previous = store.claim(f"notify:{project}", every_days)
    if previous is None:
        return ""
    try:
        return prompting.review_notice(engine, project)
    except Exception:
        store.restore(f"notify:{project}", previous)
        return ""


def run(engine: Engine, store: Store, project: str) -> str:
    """Run the due maintenance tasks and return the lines to show (``""`` if none)."""
    cfg = engine.vault.config.maintenance
    lines: list[str] = []
    if cfg.archive_expired:
        lines.append(_archive_line(engine, store, cfg.every_days))
    if cfg.notify:
        lines.append(_notify_line(engine, store, project, cfg.every_days))
    return "\n".join(line for line in lines if line)


def start_backup(vault: Vault, store: Store) -> threading.Thread | None:
    """Start the due backup in a daemon thread; ``None`` if not configured or not due."""
    from episteme import backup

    dest = vault.config.backup.dir
    if dest is None:
        return None
    previous = store.claim("backup", vault.config.maintenance.every_days)
    if previous is None:
        return None
    keep = vault.config.backup.keep

    def work() -> None:
        try:
            made = backup.run(vault, dest, keep)
            if made is not None:
                store.log("backup", [], made.name)
        except Exception:
            store.restore("backup", previous)

    thread = threading.Thread(target=work, name="episteme-backup", daemon=True)
    thread.start()
    return thread
