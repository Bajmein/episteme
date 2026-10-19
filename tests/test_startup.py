"""Case 12: the server refuses to start without a valid vault."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import mcp_client


def _start(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "episteme_mcp", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        env=env or {"PATH": "/usr/bin:/bin"},
    )


def test_no_vault_fails() -> None:
    proc = _start()
    assert proc.returncode != 0
    assert "no vault given" in proc.stderr


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
    assert not (tmp_path / "notes" / ".episteme").exists()


def test_env_var_is_used(tmp_path: Path) -> None:
    proc = _start(env={"PATH": "/usr/bin:/bin", "EPISTEME_VAULT": str(tmp_path / "nope")})
    assert proc.returncode != 0
    assert "does not exist" in proc.stderr


@pytest.mark.anyio
async def test_starts_with_valid_vault(vault: Path) -> None:
    async with mcp_client(vault) as client:
        info = await client.session.list_tools()
        assert isinstance(info.tools, list)
