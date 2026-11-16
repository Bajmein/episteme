"""vault.py: episteme.toml, zones, confinement and atomic writes (cases 3, 4 and 12)."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest
from test_startup import _start

from episteme.errors import EpistemeError, StartupError
from episteme.vault import (
    MEMORY,
    READ_ONLY,
    READ_WRITE,
    Backup,
    Maintenance,
    Vault,
    is_ignored,
    load_config,
)


def test_load_fixture_config(vault: Path) -> None:
    cfg = load_config(vault)
    assert {(z.path, z.mode) for z in cfg.zones} == {
        ("docs/claude-code", READ_ONLY),
        ("memory", MEMORY),
        ("plans", READ_WRITE),
    }
    assert cfg.state_glob == ".fabrik/*/*/estado.md"


@pytest.mark.parametrize(
    "toml",
    [
        '[zones."docs"]\nmode = "write"\n',
        '[zones."docs"]\nmode = "read-only"\n[zones."docs/"]\nmode = "memory"\n',
        '[zones."docs"]\nmode = "read-only"\n[zones."docs"]\nmode = "memory"\n',
        "not toml at all [",
    ],
)
def test_bad_config_refuses_to_start(tmp_path: Path, toml: str) -> None:
    (tmp_path / "episteme.toml").write_text(toml)
    with pytest.raises(StartupError):
        load_config(tmp_path)
    proc = _start("--vault", str(tmp_path))
    assert proc.returncode != 0
    assert proc.stderr
    assert not (tmp_path / ".index").exists()


def test_maintenance_backup_defaults(vault: Path) -> None:
    cfg = load_config(vault)
    assert cfg.maintenance == Maintenance(every_days=1, notify=True, archive_expired=False)
    assert cfg.backup == Backup(dir=None, keep=14)


def test_maintenance_backup_valid(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    target = tmp_path / "backups"
    (vault_dir / "episteme.toml").write_text(
        "[maintenance]\nevery_days = 7\nnotify = false\narchive_expired = true\n"
        f"[backup]\ndir = '{target}'\nkeep = 3\n",
        encoding="utf-8",
    )
    cfg = load_config(vault_dir)
    assert cfg.maintenance == Maintenance(every_days=7, notify=False, archive_expired=True)
    assert cfg.backup == Backup(dir=target, keep=3)


@pytest.mark.parametrize(
    "toml",
    [
        "[maintenance]\nevery_dayz = 1\n",
        "[backup]\ndir = '{abs}'\nretain = 2\n",
        "maintenance = 3\n",
        "[maintenance]\nevery_days = 0\n",
        "[maintenance]\nevery_days = true\n",
        '[maintenance]\nnotify = "yes"\n',
        "[maintenance]\narchive_expired = 1\n",
        "[backup]\nkeep = 3\n",
        "[backup]\ndir = '{abs}'\nkeep = true\n",
        "[backup]\ndir = '{abs}'\nkeep = 0\n",
        "[backup]\ndir = ''\n",
        "[backup]\ndir = 'relative/backups'\n",
        "[backup]\ndir = '{vault}'\n",
        "[backup]\ndir = '{vault}/sub/backups'\n",
    ],
)
def test_bad_maintenance_backup_refuses_to_start(tmp_path: Path, toml: str) -> None:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    toml = toml.replace("{abs}", str(tmp_path / "out")).replace("{vault}", str(vault_dir))
    (vault_dir / "episteme.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(StartupError):
        load_config(vault_dir)
    proc = _start("--vault", str(vault_dir))
    assert proc.returncode != 0
    assert proc.stderr
    assert not (vault_dir / ".index").exists()


def test_zone_lookup_prefers_most_specific(tmp_path: Path) -> None:
    (tmp_path / "episteme.toml").write_text(
        '[zones."docs"]\nmode = "read-write"\n[zones."docs/claude-code"]\nmode = "read-only"\n'
    )
    v = Vault(tmp_path)
    assert v.mode_for("docs/claude-code/x.md") == READ_ONLY
    assert v.mode_for("docs/other.md") == READ_WRITE
    assert v.mode_for("docs-other/x.md") == READ_ONLY
    assert v.mode_for("scratch/x.md") == READ_ONLY


def test_read_only_zone_rejected(vault: Path) -> None:
    v = Vault(vault)
    with pytest.raises(EpistemeError) as err:
        v.check_writable("docs/claude-code/hooks-reference.md")
    assert err.value.code == "read_only_zone"
    with pytest.raises(EpistemeError) as err:
        v.check_writable("scratch/x.md")
    assert err.value.code == "read_only_zone"
    assert v.check_writable("plans/x.md") == READ_WRITE
    assert v.check_writable("memory/fabrik/x.md") == MEMORY


@pytest.mark.parametrize("bad", ["../x.md", "docs/../../x.md", "/etc/passwd", "~/x.md"])
def test_confinement(vault: Path, bad: str) -> None:
    with pytest.raises(EpistemeError) as err:
        Vault(vault).resolve(bad)
    assert err.value.code == "outside_vault"


def test_symlink_leaving_vault(vault: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("# secret\n")
    os.symlink(outside, vault / "plans")
    v = Vault(vault)
    with pytest.raises(EpistemeError) as err:
        v.resolve("plans/secret.md")
    assert err.value.code == "outside_vault"
    with pytest.raises(EpistemeError):
        v.write_atomic("plans/new.md", "x")
    assert not (outside / "new.md").exists()
    assert "plans/secret.md" not in {rel for rel, _ in v.iter_notes()}


def test_symlink_into_read_only_zone_is_read_only(vault: Path) -> None:
    target = "docs/claude-code/hooks-reference.md"
    (vault / "plans").mkdir()
    os.symlink(vault / target, vault / "plans/link.md")
    with pytest.raises(EpistemeError) as err:
        Vault(vault).check_writable("plans/link.md")
    assert err.value.code == "read_only_zone"
    assert target in str(err.value)


def test_temporary_files_are_never_notes(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real_replace, real_link = os.replace, os.link

    def replace(src: str, dst: str) -> None:
        seen.append(str(src))
        real_replace(src, dst)

    def link(src: str, dst: str) -> None:
        seen.append(str(src))
        real_link(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "link", link)
    v = Vault(vault)
    v.write_atomic("plans/a.md", "one\n")
    v.create_exclusive("plans/b.md", "two\n")
    assert len(seen) == 2
    assert all(is_ignored(PurePosixPath(name).name) for name in seen)


def test_atomic_write_and_exclusive_create(vault: Path) -> None:
    v = Vault(vault)
    v.write_atomic("plans/a.md", "one\n")
    v.write_atomic("plans/a.md", "two\n")
    assert (vault / "plans/a.md").read_text() == "two\n"
    assert v.create_exclusive("plans/b.md", "b\n")
    assert not v.create_exclusive("plans/b.md", "other\n")
    assert (vault / "plans/b.md").read_text() == "b\n"
    assert not [p for p in (vault / "plans").iterdir() if p.name.startswith(".tmp-")]


def test_iter_notes_skips_hidden_and_non_markdown(vault: Path) -> None:
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "x.md").write_text("x")
    notes = {rel for rel, _ in Vault(vault).iter_notes()}
    assert "docs/claude-code/hooks-reference.md" in notes
    assert "docs/llms.txt" not in notes
    assert not any(n.startswith(".") for n in notes)
    assert is_ignored(".git/x.md") and is_ignored("docs/llms.txt")


def test_resolve_wraps_os_errors(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    v = Vault(vault)
    with pytest.raises(EpistemeError) as err:
        v.resolve("memory/a\x00b.md")
    assert err.value.code == "invalid_argument" and str(vault) not in str(err.value)

    def boom(_path: object) -> str:
        raise OSError("File name too long")

    monkeypatch.setattr(os.path, "realpath", boom)
    with pytest.raises(EpistemeError) as err:
        v.resolve("memory/" + "a" * 300 + ".md")
    assert err.value.code == "invalid_argument" and str(vault) not in str(err.value)
