"""Rotating ``.tar.gz`` backups of a vault's writable zones and its config file."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import stat
import tarfile
import tempfile
import time
from pathlib import Path

from episteme.vault import CONFIG_FILE, DOCS, READ_ONLY, Vault

PREFIX = "episteme-"
SUFFIX = ".tar.gz"
STALE_TMP_SECONDS = 3600
SEAL_LENGTH = 12
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
TMP_PREFIX = ".episteme-backup-"
TMP_GLOB = f"{TMP_PREFIX}*.tmp"
# Docs zones hold third-party pages that /episteme-docs:docs can download again.
SKIPPED_MODES = (READ_ONLY, DOCS)


def _members(vault: Vault) -> list[tuple[str, os.stat_result]]:
    """Notes of the backed-up zones plus the config file, sorted by relative path."""
    found = [
        (rel, st) for rel, st in vault.iter_notes() if vault.mode_for(rel) not in SKIPPED_MODES
    ]
    try:
        config = (vault.root / CONFIG_FILE).lstat()
    except OSError:
        config = None  # A vault without its config file is still backed up: only notes go in.
    if config is not None and stat.S_ISREG(config.st_mode):
        found.append((CONFIG_FILE, config))
    return sorted(found, key=lambda item: item[0])


def _seal(members: list[tuple[str, os.stat_result]]) -> str:
    lines = sorted(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}" for rel, st in members)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:SEAL_LENGTH]


def run(vault: Vault, dest: Path, keep: int, now: dt.datetime | None = None) -> Path | None:
    """Write a .tar.gz of the writable zones and episteme.toml to dest. None if unchanged."""
    members = _members(vault)
    seal = _seal(members)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if _unchanged(dest, seal):
        _rotate(dest, keep)
        return None

    stamp = (now or dt.datetime.now(dt.UTC)).strftime(STAMP_FORMAT)
    final = dest / f"{PREFIX}{stamp}-{seal}{SUFFIX}"
    _write_archive(vault, members, dest, final)

    _rotate(dest, keep)
    return final


def _unchanged(dest: Path, seal: str) -> bool:
    """Whether the newest archive in ``dest`` already carries ``seal``."""
    existing = sorted(p.name for p in dest.glob(f"{PREFIX}*{SUFFIX}"))
    return bool(existing) and existing[-1].endswith(f"-{seal}{SUFFIX}")


def _write_archive(
    vault: Vault, members: list[tuple[str, os.stat_result]], dest: Path, final: Path
) -> None:
    """Write the members to a temp file in ``dest`` and move it to ``final``."""
    fd, tmp_name = tempfile.mkstemp(dir=dest, prefix=TMP_PREFIX, suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for rel, _ in members:
                try:
                    tar.add(vault.root / rel, arcname=rel)
                except FileNotFoundError:
                    continue
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _rotate(dest: Path, keep: int) -> None:
    archives = sorted(dest.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name)
    keep = max(keep, 1)  # never delete the newest archive
    for old in archives[: max(len(archives) - keep, 0)]:
        old.unlink(missing_ok=True)
    cutoff = time.time() - STALE_TMP_SECONDS
    for tmp in dest.glob(TMP_GLOB):
        try:
            if tmp.stat().st_mtime < cutoff:
                tmp.unlink()
        except OSError:
            continue  # A stale temp file we cannot stat or remove is retried on the next backup.
