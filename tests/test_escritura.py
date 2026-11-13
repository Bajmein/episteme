"""Secret rejection and the duplicate hint in remember/revise (items 3 and 19)."""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES, mcp_client

from episteme.memory import find_secrets

SCRIPT = Path(__file__).parents[1] / "scripts/migrate_omega.py"
EXPORT = FIXTURES / "omega-export/omega-memories"

SECRETS = [
    ("private key", "-----BEGIN RSA PRIVATE KEY-----\nabc"),
    ("AWS access key", "AKIA" + "A1B2C3D4E5F6G7H8"),
    ("GitHub token", "ghp_" + "a" * 36),
    ("GitHub token", "github_pat_" + "A" * 22),
    ("Anthropic API key", "sk-ant-" + "a" * 20),
    ("API key", "sk-" + "b" * 32),
    ("Stripe live key", "sk_live_" + "c" * 16),
    ("npm token", "npm_" + "d" * 36),
    ("Hugging Face token", "hf_" + "e" * 30),
    ("Slack token", "xoxb-" + "1234567890"),
    ("Google API key", "AIza" + "f" * 35),
    ("JWT", "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 12),
    ("password in URL", "postgres://admin:" + "s3cr3tvalue" + "@db.local/x"),
]
HARMLESS = [
    "el token empieza por ghp_",
    "usa AKIA como prefijo",
    "sk-ant- es el prefijo",
    "https://user:pass@host/x",
    "https://user:password@host/x",
    "https://user:<clave>@host/x",
    "https://user:$PASS123@host/x",
    "https://user:******@host/x",
    "https://host:8080/x",
    "-----BEGIN CERTIFICATE-----",
]


@pytest.mark.parametrize("name,value", SECRETS)
def test_find_secrets_detects(name: str, value: str) -> None:
    assert find_secrets(f"clave: {value} fin") == name


@pytest.mark.parametrize("text", HARMLESS)
def test_find_secrets_ignores_mentions(text: str) -> None:
    assert find_secrets(text) is None


@pytest.mark.anyio
async def test_remember_rejects_secret_fields(vault: Path) -> None:
    secret = "ghp_" + "a" * 36
    async with mcp_client(vault) as c:
        base = {"type": "lesson", "title": "Token de CI", "body": "Guardado en el gestor."}
        for field, value in (
            ("title", f"Token {secret}"),
            ("body", f"El token es {secret}"),
            ("keywords", [secret]),
            ("source", secret),
        ):
            err = await c.error("remember", **{**base, field: value})
            assert err.startswith(f"invalid_argument: {field} looks like a secret (GitHub token)")
            assert secret not in err
        ok = await c.ok("remember", **{**base, "body": "El token empieza por ghp_ y está en pass."})
        assert ok["created"] is True


@pytest.mark.anyio
async def test_remember_duplicate_hint(vault: Path) -> None:
    async with mcp_client(vault) as c:
        args = {
            "type": "lesson",
            "title": "Reiniciar el watchdog de OMEGA",
            "body": "Subir OMEGA_RSS_LIMIT_MB a 2048 en .mcp.json cuando el proceso stdio cierra.",
        }
        first = await c.ok("remember", **args)
        again = await c.ok("remember", **args)
        assert again["created"] is False
        assert again["similar"][0]["path"] == first["path"]
        path = first["path"]
        assert again["hint"] == (
            f'Already saved as {path}. If it happened again, revise(note="{path}", '
            f'action="feedback", value="helpful"). If it changed, call remember again with '
            f'supersedes="{path}". Use force=true only for a genuinely different memory.'
        )
        assert "hint" not in first


@pytest.mark.anyio
async def test_revise_checks_only_incoming_text(vault: Path) -> None:
    secret = "ghp_" + "a" * 36
    async with mcp_client(vault) as c:
        made = await c.ok(
            "remember", type="lesson", title="Nota con falso positivo", body="Texto inicial."
        )
        path = made["path"]
        for kwargs in (
            {"action": "append", "text": f"token {secret}"},
            {"action": "edit", "old": "Texto inicial.", "new": secret},
            {"action": "set", "fields": {"source": secret}},
        ):
            err = await c.error("revise", note=path, **kwargs)
            assert err.startswith("invalid_argument:") and "looks like a secret" in err
    # A note that already holds a false positive stays editable.
    note = vault / path
    note.write_text(note.read_text().replace("Texto inicial.", f"Texto {secret}"))
    async with mcp_client(vault) as c:
        res = await c.ok("revise", note=path, action="append", text="Otra línea.")
        assert res["changed"] == ["body"]
        res = await c.ok("revise", note=path, action="set", fields={"priority": 5})
        assert res["changed"] == ["priority"]


def _script():
    spec = importlib.util.spec_from_file_location("migrate_omega", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_migrate_reports_secret_and_continues(vault: Path, tmp_path: Path) -> None:
    export = tmp_path / "omega-memories"
    shutil.copytree(EXPORT, export)
    lessons = export / "lessons"
    src = (lessons / "mem-1b2c3d4e5f60.md").read_text()
    bad = src.replace("mem-1b2c3d4e5f60", "mem-ffffffffffff").replace(
        "el watchdog de OMEGA cierra el proceso stdio al pasar 1024 MB de RSS; subir "
        "OMEGA_RSS_LIMIT_MB a 2048 en .mcp.json.",
        "clave del despliegue " + "ghp_" + "a" * 36,
    )
    assert "ghp_" in bad
    (lessons / "mem-ffffffffffff.md").write_text(bad)
    out = io.StringIO()
    done = _script().migrate(export, vault, "fabrik", out=out)
    text = out.getvalue()
    assert "! lesson_learned mem-ffffffffffff: invalid_argument: title looks like a secret" in text
    assert done["error:lesson"] == 1
    assert "ghp_" + "a" * 36 not in text
    assert done["lesson"] >= 1  # the other lessons still migrate
