"""Secret rejection and the duplicate hint in remember/revise (items 3 and 19)."""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES, mcp_client

from episteme.memory import REDACTED, find_secrets, redact_secrets

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
    ("password in URL", "mysql://u:" + "$ecret" + "123@h/db"),
    ("API key", "sk-" + "proj-" + "A1b2C3d4" * 4),
    ("Bearer token", "Authorization: Bearer " + "abcdEFGH12" * 3),
    ("credential assignment", "DB_PASSWORD" + "=" + "hunter2hunter2"),
    ("credential assignment", 'api_key: "' + "k9" * 8 + '"'),
    ("credential assignment", '{"password": "' + "abcd1234" + 'efgh"}'),
    ("credential assignment", "AWS_SECRET" + "_ACCESS_KEY=" + "wJalrXUtn" + "FEMI7K7MDENG"),
    ("Bearer token", "authorization: bearer " + "abcdEFGH12" * 3),
    ("private key", "-----BEGIN RSA PRIV\u200bATE KEY-----"),
    ("private key", "-----BEGIN RSA PRIVATE KEY-----"),
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
    "https://user:changeme@host/x",
    "https://host:8080/x",
    "https://user:${DB_PASS}@host/x",
    "password: <tu clave>",
    "token = $GITHUB_TOKEN_VALUE",
    "DB_PASSWORD=changeme",
    "el password es corto",
    "Bearer token en la cabecera",
    "password_hash: 123456789",
    '"token": "el campo"',
    "token=self._next_token()",
    "el secret: identificador",
    "token = get_token(user)",
    "api_key=settings.API_KEY",
    "password=$(vault read x1)",
    "token: ${{ secrets.GITHUB_TOKEN }}",
    "nombre-de-tarea-sk-" + "x" * 5,
    "disk-" + "a" * 40,
    "task-sk-" + "a" * 10,
    "-----BEGIN CERTIFICATE-----",
]


@pytest.mark.parametrize("name,value", SECRETS)
def test_find_secrets_detects(name: str, value: str) -> None:
    assert find_secrets(f"clave: {value} fin") == name


@pytest.mark.parametrize("text", HARMLESS)
def test_find_secrets_ignores_mentions(text: str) -> None:
    assert find_secrets(text) is None


@pytest.mark.parametrize("name,value", SECRETS)
def test_redact_secrets_leaves_nothing_find_secrets_sees(name: str, value: str) -> None:
    redacted = redact_secrets(f"clave: {value} fin")

    assert REDACTED in redacted
    assert redacted.startswith("clave: ")
    assert find_secrets(redacted) is None


@pytest.mark.parametrize("text", HARMLESS)
def test_redact_secrets_keeps_text_without_credentials(text: str) -> None:
    assert redact_secrets(text) == text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("postgres://admin:" + "s3cr3tvalue@db.local/x", f"postgres://admin:{REDACTED}@db.local/x"),
        ("DB_PASSWORD" + "=" + "hunter2hunter2 y sigue", f"DB_PASSWORD={REDACTED} y sigue"),
        ("usa ghp_" + "a" * 36 + " y nada mas", f"usa {REDACTED} y nada mas"),
    ],
)
def test_redact_secrets_replaces_only_the_value(text: str, expected: str) -> None:
    assert redact_secrets(text) == expected


@pytest.mark.parametrize(
    "tail,rest",
    [("\n-----END RSA PRIVATE KEY----- y sigue", " y sigue"), ("\n\ny sigue", "\n\ny sigue")],
    ids=["end-line", "no-end-line"],
)
def test_redact_secrets_drops_the_whole_private_key(tail: str, rest: str) -> None:
    key = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEvQIBADANBgkq\nhkiG9w0BAQEFAASC=" + tail

    assert redact_secrets(f"antes {key}") == f"antes {REDACTED}{rest}"


def test_redact_secrets_keeps_the_text_between_a_truncated_key_and_a_full_one() -> None:
    begin = "-----BEGIN RSA " + "PRIVATE KEY-----"
    end = "-----END RSA " + "PRIVATE KEY-----"
    text = f"{begin}\nMIIEvQIBADANBgkq\n\nTexto en medio.\n{begin}\nhkiG9w0BAQEFAASC=\n{end} fin"

    assert redact_secrets(text) == f"{REDACTED}\n\nTexto en medio.\n{REDACTED} fin"


def test_redact_secrets_drops_an_encrypted_key_with_its_headers() -> None:
    text = (
        "-----BEGIN RSA " + "PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,AB12\n"
        "\nMIIEvQIBADANBgkq\n-----END RSA " + "PRIVATE KEY----- y sigue"
    )

    assert redact_secrets(text) == f"{REDACTED} y sigue"


@pytest.mark.parametrize("lead,trail", [("    ", ""), ("> ", ""), ("", " ")])
def test_redact_secrets_drops_an_indented_or_quoted_key(lead: str, trail: str) -> None:
    lines = [
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        "MIIEvQIBADANBgkq",
        "hkiG9w0BAQEFAASC=",
        "-----END RSA " + "PRIVATE KEY-----",
    ]
    key = "\n".join(f"{lead}{line}{trail}" for line in lines)

    out = redact_secrets(f"antes\n{key}\ndespués")

    assert "MIIE" not in out and "hkiG" not in out and "END RSA" not in out
    assert out.startswith("antes\n") and out.endswith("después")


@pytest.mark.parametrize("sep", ["\\n", " "], ids=["escaped-newline", "spaces"])
def test_redact_secrets_drops_a_key_written_on_one_line(sep: str) -> None:
    key = sep.join(
        ["-----BEGIN " + "PRIVATE KEY-----", "MIIEvQIBADANBgkq", "-----END " + "PRIVATE KEY-----"]
    )

    out = redact_secrets(f'{{"private_key": "{key}{sep}", "x": 1}}')

    assert out == f'{{"private_key": "{REDACTED}{sep}", "x": 1}}'


def test_redact_secrets_returns_on_a_long_key_without_end_line() -> None:
    lines = "".join("\nProc-Type: " + "a b c " * 20 for _ in range(200))

    out = redact_secrets("-----BEGIN RSA " + "PRIVATE KEY-----" + lines)

    assert out == REDACTED


def test_redact_secrets_keeps_the_rest_of_the_text_as_is() -> None:
    text = "ﬁle x² 👨\u200d👩 con ghp_" + "a" * 36

    assert redact_secrets(text) == f"ﬁle x² 👨\u200d👩 con {REDACTED}"


def test_redact_secrets_is_idempotent_and_catches_hidden_keys() -> None:
    text = "token gh\u200bp_" + "b" * 36 + " y https://u:" + "c" * 6 + "1@h/x"

    once = redact_secrets(text)

    assert once == f"token {REDACTED} y https://u:{REDACTED}@h/x"
    assert redact_secrets(once) == once


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
            ("tags", [secret]),
            ("files", [secret]),
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
    text = note.read_text(encoding="utf-8").replace("Texto inicial.", f"Texto {secret}")
    note.write_text(text, encoding="utf-8", newline="")
    async with mcp_client(vault) as c:
        res = await c.ok("revise", note=path, action="append", text="Otra línea.")
        assert res["changed"] == ["body"]
        res = await c.ok(
            "revise", note=path, action="edit", old=f"Texto {secret}", new=f"Texto {secret} ok"
        )
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
    src = (lessons / "mem-1b2c3d4e5f60.md").read_text(encoding="utf-8")
    bad = src.replace("mem-1b2c3d4e5f60", "mem-ffffffffffff").replace(
        "el watchdog de OMEGA cierra el proceso stdio al pasar 1024 MB de RSS; subir "
        "OMEGA_RSS_LIMIT_MB a 2048 en .mcp.json.",
        "clave del despliegue " + "ghp_" + "a" * 36,
    )
    assert "ghp_" in bad
    (lessons / "mem-ffffffffffff.md").write_text(bad, encoding="utf-8", newline="")
    out = io.StringIO()
    done = _script().migrate(export, vault, "fabrik", out=out)
    text = out.getvalue()
    assert "! lesson_learned mem-ffffffffffff: invalid_argument: title looks like a secret" in text
    assert done["error:lesson"] == 1
    assert "ghp_" + "a" * 36 not in text
    assert done["lesson"] >= 1  # the other lessons still migrate


@pytest.mark.anyio
async def test_remember_rejects_secret_project(vault: Path) -> None:
    async with mcp_client(vault) as c:
        err = await c.error(
            "remember", type="lesson", title="Algo", body="Texto.", project="ghp_" + "a" * 36
        )
        assert "looks like a secret" in err and "a" * 36 not in err


@pytest.mark.anyio
async def test_revise_rejects_nested_secret_and_more_secrets(vault: Path) -> None:
    secret = "ghp_" + "a" * 36
    async with mcp_client(vault) as c:
        made = await c.ok("remember", type="lesson", title="Nota anidada", body="Texto inicial.")
        path = made["path"]
        for value in ({"a": {"b": secret}}, {"a": [secret]}, [{"x": secret}]):
            err = await c.error("revise", note=path, action="set", fields={"extra": value})
            assert "looks like a secret" in err and secret not in err
    note = vault / path
    text = note.read_text(encoding="utf-8").replace("Texto inicial.", f"Texto {secret}")
    note.write_text(text, encoding="utf-8", newline="")
    async with mcp_client(vault) as c:
        err = await c.error(
            "revise", note=path, action="edit", old=f"Texto {secret}", new=f"{secret} y {secret}"
        )
        assert "looks like a secret" in err
        other = "ghp_" + "b" * 36
        err = await c.error(
            "revise", note=path, action="edit", old=f"Texto {secret}", new=f"Texto {other}"
        )
        assert "looks like a secret" in err and other not in err


@pytest.mark.anyio
@pytest.mark.parametrize("pattern", ["*", "**", "**/*", "*.*", " ./** ", "*/**", "?*", "."])
async def test_files_reject_match_all(vault: Path, pattern: str) -> None:
    async with mcp_client(vault) as c:
        base = {"type": "constraint", "title": "Norma", "body": "Texto de la norma."}
        err = await c.error("remember", **base, files=["src/a.py", pattern])
        assert err.startswith("invalid_argument: files entry")
        made = await c.ok("remember", **base, files=["src/**/*.py"])
        err = await c.error(
            "revise", note=made["path"], action="set", fields={"files": [pattern]}
        )
        assert err.startswith("invalid_argument: files entry")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "project", ["../x", "con espacios", ".oculto", "-x", "a" * 65, "a\x00b", "a/b", "x:y"]
)
async def test_remember_rejects_invalid_project(vault: Path, project: str) -> None:
    async with mcp_client(vault) as c:
        err = await c.error("remember", type="lesson", title="Algo", body="Texto.", project=project)
        assert err.startswith(("invalid_schema:", "invalid_argument:"))
        assert str(vault) not in err


@pytest.mark.anyio
@pytest.mark.parametrize("project", ["_shared", "fabrik", "a.b-c_d", "a" * 64])
async def test_remember_accepts_valid_project(vault: Path, project: str) -> None:
    async with mcp_client(vault) as c:
        out = await c.ok("remember", type="lesson", title="Algo", body="Texto.", project=project)
        assert out["created"] is True
