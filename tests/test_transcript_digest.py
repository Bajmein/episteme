"""The extractor's transcript digest script (plugin/skills/sesion/scripts/transcript_digest.py)."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / "plugin/skills/sesion/scripts/transcript_digest.py"


@pytest.fixture
def digest() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT))


def _user(ts: str, content: Any, **extra: Any) -> dict[str, Any]:
    message = {"role": "user", "content": content}
    return {"type": "user", "timestamp": ts, "message": message, **extra}


def _assistant(ts: str, *blocks: dict[str, Any]) -> dict[str, Any]:
    message = {"role": "assistant", "content": list(blocks)}
    return {"type": "assistant", "timestamp": ts, "message": message}


RECORDS = [
    _user("2026-11-18T10:00:00Z", "Arregla el bug del gate"),
    _assistant(
        "2026-11-18T10:00:05Z",
        {"type": "text", "text": "Miro el código."},
        {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest " + "x" * 300}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/src/gate.py"}},
    ),
    _user(
        "2026-11-18T10:00:10Z",
        [
            {"type": "tool_result", "content": "ok, todo bien", "is_error": False},
            {"type": "tool_result", "content": "Traceback: boom", "is_error": True},
        ],
    ),
    _user("2026-11-18T10:01:00Z", "<system-reminder>ruido</system-reminder>Sigue con los tests"),
    _user("2026-11-18T10:01:30Z", "<local-command-stdout>salida</local-command-stdout>"),
    _user("2026-11-18T10:01:40Z", "meta", isMeta=True),
    _user(
        "2026-11-18T10:02:00Z",
        "<analysis>borrador</analysis>\n\nResumen: el gate ya bloquea.",
        isCompactSummary=True,
    ),
    {"type": "system", "timestamp": "2026-11-18T10:03:00Z", "content": "x"},
]


def _transcript(tmp_path: Path, records: list[dict[str, Any]] = RECORDS) -> Path:
    path = tmp_path / "projects" / "-repo" / "abc.jsonl"
    path.parent.mkdir(parents=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in records] + ["no es json"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(digest: dict[str, Any], capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = digest["main"](list(argv))
    return code, capsys.readouterr().out


def test_digest_keeps_messages_calls_errors_and_summary(
    tmp_path: Path, digest: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(digest, capsys, str(_transcript(tmp_path)))

    assert code == 0
    assert "- desde: 2026-11-18T10:00:00Z" in out and "- hasta: 2026-11-18T10:02:00Z" in out
    assert "**Persona:** Arregla el bug del gate" in out
    assert "**Asistente:** Miro el código." in out
    assert "- Read(/repo/src/gate.py)" in out
    assert "- Bash(uv run pytest " + "x" * 106 + " […])" in out
    assert "- error: Traceback: boom" in out and "todo bien" not in out
    assert "**Persona:** Sigue con los tests" in out
    assert "ruido" not in out and "salida" not in out and "meta" not in out
    assert "Resumen: el gate ya bloquea." in out and "borrador" not in out


def test_digest_clips_long_messages(digest: dict[str, Any]) -> None:
    [line] = digest["entries"](_user("2026-11-18T10:00:00Z", "a" * 3000))

    assert line == "**Persona:** " + "a" * 2000 + " […]"


@pytest.mark.parametrize(
    ("since", "first"),
    [("2026-11-18T10:00:30+00:00", "Sigue con los tests"), ("inicio", "Arregla el bug")],
)
# @CodeScene(disable:"Excess Number of Function Arguments")
def test_digest_window_since(
    tmp_path: Path,
    digest: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    since: str,
    first: str,
) -> None:
    _, out = _run(digest, capsys, str(_transcript(tmp_path)), "--since", since)

    assert out.split("**Persona:** ", 1)[1].startswith(first)


def test_digest_says_nothing_new_after_the_last_entry(
    tmp_path: Path, digest: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _run(digest, capsys, str(_transcript(tmp_path)), "--since", "2026-11-18T11:00:00")

    assert out.strip() == "sin novedades"


def test_digest_keeps_the_newest_entries_within_max_chars(
    tmp_path: Path, digest: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    records = [
        _user(f"2026-11-18T10:{i:02d}:00Z", f"mensaje {i:02d} " + "z" * 80) for i in range(20)
    ]

    _, out = _run(digest, capsys, str(_transcript(tmp_path, records)), "--max-chars", "500")

    assert "entradas anteriores omitidas]" in out and "mensaje 19" in out
    assert "mensaje 00" not in out and "- entradas: 20" in out


@pytest.mark.parametrize("name", ["outside/abc.jsonl", "projects/-repo/abc.txt"])
def test_digest_refuses_a_path_outside_projects(
    tmp_path: Path, digest: dict[str, Any], capsys: pytest.CaptureFixture[str], name: str
) -> None:
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")

    code, out = _run(digest, capsys, str(path))

    assert code == 2 and out == ""


def test_digest_refuses_a_bad_since(tmp_path: Path, digest: dict[str, Any]) -> None:
    with pytest.raises(SystemExit, match="--since"):
        digest["main"]([str(_transcript(tmp_path)), "--since", "ayer"])
