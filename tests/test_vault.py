"""vault.py: episteme.toml, zones, confinement and atomic writes (cases 3, 4 and 12)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_startup import _start

from episteme_mcp.errors import EpistemeError, StartupError
from episteme_mcp.vault import MEMORY, READ_ONLY, READ_WRITE, Vault, is_ignored, load_config


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
    assert not (tmp_path / ".episteme").exists()


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
