"""Welcome cap on _shared memories and relevance gating of context(mode="task")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import mcp_client

from episteme import hookmode, memory
from episteme.engine import Engine
from episteme.memory.scoring import entry_line

pytestmark = pytest.mark.anyio


def hook_text(raw: str) -> str:
    """Text a hook call delivers: the plain string or the additionalContext of the JSON envelope."""
    if raw.startswith("{"):
        return json.loads(raw)["hookSpecificOutput"]["additionalContext"]
    return raw


def put(
    vault: Path,
    project: str,
    slug: str,
    title: str,
    body: str = "",
    priority: int = 3,
    related: str = "",
    type_: str = "insight",
) -> str:
    rel = f"memory/{project}/insights/{slug}.md"
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    rel_line = f"related: ['[[{related}]]']\n" if related else ""
    path.write_text(
        f"---\ntype: {type_}\nkind: semantic\nproject: {project}\npriority: {priority}\n"
        f"status: active\ncreated: 2026-10-18\n{rel_line}---\n# {title}\n\n{body}\n",
        encoding="utf-8",
        newline="",
    )
    return rel


@pytest.fixture
def engine(vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EPISTEME_TODAY", "2026-10-22")
    eng = Engine(vault, "fabrik")
    yield eng
    eng.index.conn.close()


def _memory_paths(entries: list[dict]) -> list[str]:
    return [e["path"] for e in entries if e["kind"] == "memory"]


def test_welcome_caps_shared(vault: Path, engine: Engine) -> None:
    for i in range(5):
        put(vault, "_shared", f"sh{i}", f"Shared zorblax {i}")
    for i in range(12):
        put(vault, "fabrik", f"fb{i}", f"Fabrik quuxel {i}")
    engine.index.refresh()
    _, entries = memory.welcome(engine, "fabrik")
    paths = _memory_paths(entries)
    assert len(paths) == 8
    assert sum(p.startswith("memory/_shared/") for p in paths) == 1


def test_welcome_shared_fills_gaps(vault: Path, engine: Engine) -> None:
    for i in range(6):
        put(vault, "_shared", f"sh{i}", f"Shared zorblax {i}")
    for i in range(2):
        put(vault, "fabrik", f"fb{i}", f"Fabrik quuxel {i}")
    engine.index.refresh()
    _, entries = memory.welcome(engine, "fabrik")
    paths = _memory_paths(entries)
    assert sum(p.startswith("memory/_shared/") for p in paths) > 1
    assert len(paths) == 8


def test_task_needs_two_terms_of_four(vault: Path, engine: Engine) -> None:
    one = put(vault, "fabrik", "one", "Flurbo notes", "Only flurbo here.", priority=5)
    two = put(vault, "fabrik", "two", "Flurbo wibble notes", "flurbo and wibble.", priority=5)
    engine.index.refresh()
    _, entries = memory.task_context(engine, "flurbo wibble snarf plonk", "fabrik", 1000)
    paths = _memory_paths(entries)
    assert two in paths and one not in paths


def test_task_single_term_suffices(vault: Path, engine: Engine) -> None:
    one = put(vault, "fabrik", "one", "Flurbo notes", "Only flurbo here.", priority=5)
    engine.index.refresh()
    _, entries = memory.task_context(engine, "flurbo", "fabrik", 1000)
    assert one in _memory_paths(entries)


def test_task_english_stopwords_ignored(vault: Path, engine: Engine) -> None:
    put(vault, "fabrik", "d", "Docs update policy", "Update the docs after releases.", priority=4)
    put(vault, "fabrik", "e", "Other thing", "Unrelated docs mention.", priority=2)
    engine.index.refresh()
    a = memory.task_context(engine, "update the docs", "fabrik", 1000)
    b = memory.task_context(engine, "update docs", "fabrik", 1000)
    assert a[1] and [e["path"] for e in a[1]] == [e["path"] for e in b[1]]
    assert [e["score"] for e in a[1]] == [e["score"] for e in b[1]]


async def test_task_linked_memories(vault: Path) -> None:
    target = put(vault, "fabrik", "neighbour", "Neighbour unrelated words", "Nothing alike.")
    main = put(
        vault, "fabrik", "main", "Flurbo main decision", "flurbo", priority=5,
        related="neighbour",
    )  # fmt: skip
    async with mcp_client(vault, today="2026-10-22") as c:
        raw = await c.ok(
            "context", mode="task", task="flurbo", hook_event="UserPromptSubmit"
        )
        text = hook_text(raw)
        assert "Memorias enlazadas:" in text
        assert text.index(main) < text.index("Memorias enlazadas:") < text.index(target)
        res = await c.ok("context", mode="task", task="flurbo")
        assert {"path": target, "score": None, "kind": "linked"} in res["entries"]


async def test_task_linked_by_body_wikilink(vault: Path) -> None:
    target = put(vault, "fabrik", "bodylinked", "Bodylinked unrelated words", "Nothing alike.")
    main = put(vault, "fabrik", "zorblat", "Zorblat main decision", "zorblat, see [[bodylinked]]")
    async with mcp_client(vault, today="2026-10-22") as c:
        raw = await c.ok("context", mode="task", task="zorblat", hook_event="UserPromptSubmit")
        text = hook_text(raw)
        assert "Memorias enlazadas:" in text
        assert text.index(main) < text.index("Memorias enlazadas:") < text.index(target)


HOSTILE_TITLE = "Título \x1b]0;pwn\x07hostil ‮al revés"


def test_entry_line_drops_control_characters_from_the_title() -> None:
    row = {
        "type": "decision", "priority": 5, "title": HOSTILE_TITLE, "path": "memory/x.md",
        "body": "Primera frase \x1b[2Jcon ESC. Segunda.", "description": None,
    }  # fmt: skip

    line = entry_line(row)

    assert "\x1b" not in line and "\x07" not in line and "‮" not in line
    assert line.startswith("- [decision p5] Título hostil al revés (memory/x.md)")


async def test_session_start_output_has_no_escape_from_a_hostile_title(vault: Path) -> None:
    async with mcp_client(vault, today="2026-10-22") as c:
        await c.ok(
            "remember", type="decision", title=HOSTILE_TITLE,
            body="Regla \x1b[2Jcon una secuencia de escape.", priority=5,
        )  # fmt: skip

        raw = await c.ok(
            "context", mode="welcome", session="hostil", hook_event="SessionStart", source="clear"
        )

    out = json.loads(raw)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "al revés" in text
    assert "\x1b" not in text and "‮" not in text
    assert "\x1b" not in out["systemMessage"].removeprefix(hookmode.NOTICE_STYLE).removesuffix(
        hookmode.NOTICE_RESET
    )
