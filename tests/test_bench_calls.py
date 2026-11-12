"""scripts/bench_calls.py: replay of a logged burst and the per-process summary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from episteme.activity import Activity

SCRIPT = Path(__file__).parents[1] / "scripts/bench_calls.py"
WORDS = ("alfauno", "betados", "gammatres")
READ = [f"memory/n{n}.md" for n in range(3)]


def _script():
    spec = importlib.util.spec_from_file_location("bench_calls", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _vault(tmp_path: Path, log: bool = True) -> Path:
    root = tmp_path / "v"
    (root / "memory").mkdir(parents=True)
    (root / "episteme.toml").write_text(
        '[zones."memory"]\nmode = "memory"\n', encoding="utf-8", newline=""
    )
    for n in range(6):
        (root / "memory" / f"n{n}.md").write_text(
            f"# Nota {n}\n\nTexto sobre {WORDS[n % 3]} y nada más.\n",
            encoding="utf-8",
            newline="",
        )
    if log:
        act = Activity(root)
        try:
            for word in WORDS:
                act.record("search", {"query": word, "limit": 50}, "", 1, True)
            for rel in READ:
                act.record("read", {"note": rel}, "", 1, True)
        finally:
            act.close()
    return root


def test_replay_batches_the_burst(tmp_path: Path, capsys) -> None:
    m = _script()
    root = _vault(tmp_path)
    result = m.replay(root)
    base, batch = result["base"], result["batch"]
    assert (base["search"]["calls"], base["read"]["calls"]) == (3, 3)
    assert (batch["search"]["calls"], batch["read"]["calls"]) == (1, 1)
    assert base["errors"] == batch["errors"] == 0
    assert set(batch["search_paths"]) == {f"memory/n{n}.md" for n in range(6)}
    assert result["read_notes"] == result["read_in_batch_search"] == 3
    assert batch["read_paths"] == READ
    merged = result["batch_calls"][0][1]
    assert merged["query"] == " ".join(WORDS) and merged["match"] == "any"
    assert merged["limit"] == 50

    assert m.main(["replay", "--vault", str(root)]) == 0
    shown = capsys.readouterr().out
    assert "| total | 6 | 2 |" in shown
    assert "alfauno" not in shown and "memory/n0.md" not in shown
    assert m.main(["replay", "--vault", str(root), "--show"]) == 0
    assert "alfauno" in capsys.readouterr().out
    # The real vault's index is never opened or created.
    assert not (root / ".index" / "index.db").exists()


def test_batch_keeps_what_cannot_be_joined() -> None:
    m = _script()
    calls = [
        ("search", {"query": "uno"}, None),
        ("search", {"query": "dos", "zone": "memory"}, None),
        ("search", {"query": "tres cuatro"}, None),
        ("search", {"tags": ["x"]}, None),
        ("search", {"query": "cinco", "limit": 100}, None),
        ("read", {"note": "a", "heading": "H"}, None),
        ("read", {"note": "a"}, None),
        ("read", {"note": "b"}, None),
        ("read", {"note": "a"}, None),
    ]
    out = m.batch_calls(calls)
    assert out == [
        ("search", {"query": "uno cinco", "match": "any", "limit": 100}, None),
        ("search", {"query": "dos", "zone": "memory"}, None),
        ("search", {"query": "tres cuatro"}, None),
        ("search", {"tags": ["x"]}, None),
        ("read", {"note": "a", "heading": "H"}, None),
        ("read", {"notes": ["a", "b"]}, None),
    ]


def test_summarize_groups_by_process(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path)
    act = Activity(root)
    try:
        act.record("search", {"query": "a b", "match": "any"}, "", 1, True)
        act.record("read", {"notes": READ}, "", 1, True)
        act.record("context", {"mode": "welcome", "hook_event": "UserPromptSubmit"}, "", 1, True)
    finally:
        act.close()
    db = m.activity_db(root)
    (group,) = m.summarize(db)
    assert group["calls"] == {"search": 4, "read": 4}
    assert group["total"] == 8 and group["hooks"] == 1
    assert group["search_any"] == 1 and group["read_batch"] == 1
    (later,) = m.summarize(db, after_id=6)
    assert later["calls"] == {"search": 1, "read": 1}
    assert m.summarize(db, after_id=99) == []
    assert m.summarize(tmp_path / "missing.db") == []


def test_no_log_or_no_burst_exits_1(tmp_path: Path, capsys) -> None:
    m = _script()
    root = _vault(tmp_path, log=False)
    assert m.main(["replay", "--vault", str(root)]) == 1
    act = Activity(root)
    try:
        act.record("context", {"mode": "task"}, "", 1, True)
    finally:
        act.close()
    assert m.main(["replay", "--vault", str(root)]) == 1
    assert m.main(["replay", "--vault", str(tmp_path / "nope")]) == 1
    assert "no burst" in capsys.readouterr().err
