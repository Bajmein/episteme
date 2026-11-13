"""Tests for the rotating vault backup."""

from __future__ import annotations

import datetime as dt
import tarfile
from pathlib import Path

import pytest

from episteme import backup
from episteme.vault import Vault


def _names(path: Path) -> list[str]:
    with tarfile.open(path, "r:gz") as tar:
        return tar.getnames()


def _touch(vault: Path, text: str) -> None:
    note = next((vault / "memory").rglob("*.md"))
    with note.open("a", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _at(n: int) -> dt.datetime:
    return dt.datetime(2026, 11, 13, 10, 0, n, tzinfo=dt.UTC)


def test_contents(vault: Path, tmp_path: Path) -> None:
    out = backup.run(Vault(vault), tmp_path / "bk", keep=3)
    assert out is not None
    names = _names(out)
    assert "episteme.toml" in names
    assert any(n.startswith("memory/") for n in names)
    assert not any(n.startswith("docs/claude-code/") for n in names)
    assert not any(".index" in n for n in names)


def test_unchanged_returns_none(vault: Path, tmp_path: Path) -> None:
    dest = tmp_path / "bk"
    assert backup.run(Vault(vault), dest, keep=3) is not None
    assert backup.run(Vault(vault), dest, keep=3, now=_at(5)) is None
    assert len(list(dest.glob("episteme-*.tar.gz"))) == 1


def test_change_creates_new_archive(vault: Path, tmp_path: Path) -> None:
    dest = tmp_path / "bk"
    first = backup.run(Vault(vault), dest, keep=3, now=_at(1))
    _touch(vault, "\nmore\n")
    second = backup.run(Vault(vault), dest, keep=3, now=_at(2))
    assert second is not None and second != first


def test_keep_rotates(vault: Path, tmp_path: Path) -> None:
    dest = tmp_path / "bk"
    made = []
    for i in range(3):
        _touch(vault, f"\nedit {i}\n")
        made.append(backup.run(Vault(vault), dest, keep=2, now=_at(i)))
    left = sorted(p.name for p in dest.glob("episteme-*.tar.gz"))
    assert left == sorted(p.name for p in made[1:] if p)


def test_failure_leaves_no_temp(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "bk"

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(tarfile, "open", boom)
    with pytest.raises(OSError, match="disk full"):
        backup.run(Vault(vault), dest, keep=2)
    assert list(dest.iterdir()) == []
