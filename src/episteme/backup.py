"""Rotating ``.tar.gz`` backups of a vault's writable zones and its config file."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import tarfile
import tempfile
import time
from pathlib import Path

from episteme.vault import CONFIG_FILE, READ_ONLY, Vault

PREFIX = "episteme-"
SUFFIX = ".tar.gz"
STALE_TMP_SECONDS = 3600


def _members(vault: Vault) -> list[tuple[str, os.stat_result]]:
    """Writable notes plus the config file, sorted by relative path."""
    found = [(rel, st) for rel, st in vault.iter_notes() if vault.mode_for(rel) != READ_ONLY]
    try:
        found.append((CONFIG_FILE, (vault.root / CONFIG_FILE).stat()))
    except OSError:
        pass
    return sorted(found, key=lambda item: item[0])


def _seal(members: list[tuple[str, os.stat_result]]) -> str:
    lines = sorted(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}" for rel, st in members)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:12]


def run(vault: Vault, dest: Path, keep: int, now: dt.datetime | None = None) -> Path | None:
    """Write a .tar.gz of the writable zones and episteme.toml to dest. None if unchanged."""
    members = _members(vault)
    seal = _seal(members)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    existing = sorted(p.name for p in dest.glob(f"{PREFIX}*{SUFFIX}"))
    if existing and existing[-1].endswith(f"-{seal}{SUFFIX}"):
        _rotate(dest, keep)
        return None

    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%dT%H%M%SZ")
    final = dest / f"{PREFIX}{stamp}-{seal}{SUFFIX}"

    fd, tmp_name = tempfile.mkstemp(dir=dest, prefix=".tmp-", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tarfile.open(tmp, "w:gz", dereference=True) as tar:
            for rel, _ in members:
                try:
                    tar.add(vault.root / rel, arcname=rel)
                except FileNotFoundError:
                    continue
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    _rotate(dest, keep)
    return final


def _rotate(dest: Path, keep: int) -> None:
    archives = sorted(dest.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: p.name)
    keep = max(keep, 1)  # never delete the newest archive
    for old in archives[: max(len(archives) - keep, 0)]:
        old.unlink(missing_ok=True)
    cutoff = time.time() - STALE_TMP_SECONDS
    for tmp in dest.glob(".tmp-*.tmp"):
        try:
            if tmp.stat().st_mtime < cutoff:
                tmp.unlink()
        except OSError:
            pass
