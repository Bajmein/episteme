"""Case 12: the server refuses to start without a valid vault."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest
from conftest import mcp_client

import episteme
from episteme.__main__ import DEFAULT_TOML
from episteme.vault import Session, load_config


def _start(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k != "EPISTEME_VAULT"}
    return subprocess.run(
        [sys.executable, "-m", "episteme", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        env={**base, **(env or {})},
    )


def test_default_vault_is_created(tmp_path: Path) -> None:
    _start(env={"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)})
    toml = tmp_path / ".episteme" / "episteme.toml"
    assert toml.is_file()
    assert "checkpoint" not in toml.read_text(encoding="utf-8")


def test_explicit_missing_vault_is_not_created(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    proc = _start("--vault", str(tmp_path / "nope"), env=env)
    assert proc.returncode != 0
    assert "does not exist" in proc.stderr
    assert not (tmp_path / ".episteme").exists()


def test_relative_vault_fails(tmp_path: Path) -> None:
    proc = _start("--vault", "tests/fixtures/vault")
    assert proc.returncode != 0
    assert "not absolute" in proc.stderr


def test_missing_vault_fails(tmp_path: Path) -> None:
    proc = _start("--vault", str(tmp_path / "nope"))
    assert proc.returncode != 0
    assert "does not exist" in proc.stderr
    assert not (tmp_path / "nope").exists()


def test_vault_without_toml_fails(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    proc = _start("--vault", str(tmp_path / "notes"))
    assert proc.returncode != 0
    assert "episteme.toml" in proc.stderr
    assert not (tmp_path / "notes" / ".index").exists()


def test_env_var_is_used(tmp_path: Path) -> None:
    proc = _start(env={"EPISTEME_VAULT": str(tmp_path / "nope")})
    assert proc.returncode != 0
    assert "does not exist" in proc.stderr


@pytest.mark.anyio
async def test_starts_with_valid_vault(vault: Path) -> None:
    async with mcp_client(vault) as client:
        info = await client.session.list_tools()
        assert isinstance(info.tools, list)


def test_package_version_comes_from_the_installed_metadata() -> None:
    assert episteme.__version__ == metadata.version("episteme")


@pytest.mark.anyio
async def test_server_reports_the_package_version_on_initialize(vault: Path) -> None:
    async with mcp_client(vault) as client:
        server_info = client.session.server_info

    assert server_info is not None
    assert server_info.version == metadata.version("episteme")


def test_default_toml_session_block_uncommented_loads_the_defaults(tmp_path: Path) -> None:
    lines = DEFAULT_TOML.splitlines()
    start = lines.index("# [session]")
    block = []
    for line in lines[start:]:
        if not line.startswith("# "):
            break
        block.append(line[2:])
    (tmp_path / "episteme.toml").write_text(
        DEFAULT_TOML + "\n" + "\n".join(block) + "\n", encoding="utf-8"
    )

    session = load_config(tmp_path).session

    assert session == Session()
    assert "block_manual_compact" not in DEFAULT_TOML
