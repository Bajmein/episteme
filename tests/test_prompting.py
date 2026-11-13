"""prompting.py: reminders, recall by prompt and nudges (unit and stdio integration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

from episteme import memory, prompting
from episteme.engine import Engine
from episteme.prompting import SessionState

pytestmark = pytest.mark.anyio


def hook_text(raw: str) -> str:
    """Text a hook call delivers: the plain string or the additionalContext of the JSON envelope."""
    if raw.startswith("{"):
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return raw


@pytest.fixture
def engine(vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-22")
    eng = Engine(vault, "fabrik")
    eng.index.refresh()
    yield eng
    eng.index.conn.close()


def _remember(engine: Engine, title: str, body: str = "Cuerpo sin relevancia.", **kw) -> str:
    res = memory.remember(engine, "decision", title, body, "fabrik", force=True, **kw)
    return res["path"]


def test_overdue_block(engine: Engine) -> None:
    text, entries = prompting.overdue_block(engine, "fabrik")
    lines = text.splitlines()
    assert lines[0].startswith("episteme · recordatorios vencidos")
    assert lines[1].startswith("- [2026-10-21] Correr las trigger queries")
    assert entries and entries[0]["kind"] == "reminder" and entries[0]["score"] is None


def test_overdue_block_empty(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPISTEME_TODAY", "2000-01-01")
    assert prompting.overdue_block(engine, "fabrik") == ("", [])


def test_recall_title_word(engine: Engine) -> None:
    path = _remember(engine, "Zorbflux dicta el formato")
    text, entries = prompting.recall(engine, "¿qué con zorbflux?", "fabrik", SessionState(), set())
    assert path in text and text.startswith("episteme · memorias que pueden venir al caso")
    assert [e["path"] for e in entries] == [path]
    assert entries[0]["kind"] == "recall"


def test_recall_body_only_does_not_suggest(engine: Engine) -> None:
    _remember(engine, "Otra cosa distinta", body="Aquí vive zorbflux en el cuerpo.")
    assert prompting.recall(engine, "zorbflux", "fabrik", SessionState(), set()) == ("", [])


def test_recall_many_terms_need_second_term(engine: Engine) -> None:
    path = _remember(engine, "Zorbflux dicta el formato")
    _remember(engine, "Sin titulo comun", body="Menciona quuxplo, wibblor y snarfel.")
    prompt = "zorbflux quuxplo wibblor snarfel"
    assert prompting.recall(engine, prompt, "fabrik", SessionState(), set()) == ("", [])
    other = _remember(engine, "Zorbflux con quuxplo", body="Menciona wibblor y snarfel.")
    text, _ = prompting.recall(engine, prompt, "fabrik", SessionState(), set())
    assert other in text
    assert path not in text


def test_recall_tag_and_keywords_count_as_title(engine: Engine) -> None:
    tagged = _remember(engine, "Nota con etiqueta", tags=["zorbtag"])
    text, _ = prompting.recall(engine, "zorbtag", "fabrik", SessionState(), set())
    assert tagged in text
    kw = _remember(engine, "Nota con claves", body="Habla de quuxkey.")
    f = engine.vault.resolve(kw)
    content = f.read_text(encoding="utf-8")
    content = content.replace("\nstatus:", "\nkeywords: [quuxkey]\nstatus:", 1)
    f.write_text(content, encoding="utf-8", newline="")
    engine.index.reindex(kw)
    text, _ = prompting.recall(engine, "quuxkey", "fabrik", SessionState(), set())
    assert kw in text


def test_recall_word_only_in_keywords(engine: Engine) -> None:
    # keywords go into the FTS title column, so a word that is nowhere else still counts
    path = _remember(engine, "Nota sin la palabra", keywords=["zorbkwonly"])
    text, _ = prompting.recall(engine, "zorbkwonly", "fabrik", SessionState(), set())
    assert path in text


def test_recall_no_repeat_skip_command_and_literal(engine: Engine) -> None:
    path = _remember(engine, "Zorbflux dicta el formato")
    st = SessionState()
    assert path in prompting.recall(engine, "zorbflux", "fabrik", st, set())[0]
    assert prompting.recall(engine, "zorbflux", "fabrik", st, set()) == ("", [])
    assert prompting.recall(engine, "zorbflux", "fabrik", SessionState(), {path}) == ("", [])
    assert path in prompting.recall(engine, "/review zorbflux", "fabrik", SessionState(), set())[0]
    assert prompting.recall(engine, "/zorbflux", "fabrik", SessionState(), set()) == ("", [])
    assert prompting.recall(engine, "${prompt}", "fabrik", SessionState(), set()) == ("", [])


def test_nudge() -> None:
    st = SessionState(baseline=prompting.WRITES)
    st.prompts = 7
    assert prompting.nudge(st) == ""
    st.prompts = 8
    assert "aún no se ha guardado ninguna memoria" in prompting.nudge(st)
    st.prompts = 9
    assert prompting.nudge(st) == ""


def test_nudge_not_shown_after_remember() -> None:
    st = SessionState(baseline=prompting.WRITES, prompts=8)
    prompting.WRITES += 1
    assert prompting.nudge(st) == ""


async def test_integration_cadence(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        first = await c.ok("context", mode="welcome", session="cad")
        assert first["already_sent"] is False
        assert "Correr las trigger queries" in first["text"]
        for n in range(2, 12):
            r = await c.ok("context", mode="welcome", session="cad")
            assert r["already_sent"] is True
            if n == 8:
                assert "aún no se ha guardado ninguna memoria" in r["text"]
            elif n == 11:
                assert r["text"].startswith("episteme · recordatorios vencidos")
                assert r["entries"][0]["kind"] == "reminder"
            else:
                assert r == {"text": "", "entries": [], "already_sent": True}
        raw = await c.ok("context", mode="welcome", session="cad", hook_event="SessionStart")
        assert "episteme · memoria de fabrik" in hook_text(raw)


async def test_integration_recall(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok("context", mode="welcome", session="rec")
        made = await c.ok(
            "remember", type="decision", title="Zorbflux dicta el formato", body="Sin más."
        )
        r = await c.ok("context", mode="welcome", session="rec", prompt="sobre zorbflux")
        assert made["path"] in r["text"]
        assert [e["kind"] for e in r["entries"]] == ["recall"]
        again = await c.ok("context", mode="welcome", session="rec", prompt="sobre zorbflux")
        assert again["text"] == ""
