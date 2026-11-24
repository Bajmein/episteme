"""scripts/bench_calls.py: replay of a logged burst and the per-process summary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


ANSWER = {
    "num_turns": 3,
    "total_cost_usd": 0.5,
    "result": "hola",
    "usage": {
        "input_tokens": 10,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 790,
        "output_tokens": 55,
    },
}


def _run_fake(m, tmp_path: Path, answer: dict) -> list[dict]:
    fake = tmp_path / "claude"
    fake.write_text(
        f"#!{sys.executable}\nimport json\nprint(json.dumps({answer!r}))\n",
        encoding="utf-8",
        newline="",
    )
    fake.chmod(0o755)
    options = m.AbOptions(runs=1, claude_bin=str(fake), baseline_cmd="true")
    return m.run_ab(_vault(tmp_path), "p", "pregunta", tmp_path / "out", options)


def test_usage_tokens_sum_the_window_and_keep_cache_and_output() -> None:
    m = _script()

    tokens = m._usage_tokens(ANSWER)

    assert tokens == {"tokens_in": 1000, "tokens_cached": 790, "tokens_out": 55}


def test_usage_tokens_are_none_when_usage_is_missing() -> None:
    m = _script()

    assert m._usage_tokens({}) == {"tokens_in": None, "tokens_cached": None, "tokens_out": None}
    partial = m._usage_tokens({"usage": {"output_tokens": 7}})
    assert partial == {"tokens_in": None, "tokens_cached": None, "tokens_out": 7}
    no_creation = m._usage_tokens({"usage": {"input_tokens": 1, "cache_read_input_tokens": 5}})
    assert no_creation["tokens_in"] is None
    assert no_creation["tokens_cached"] == 5


@pytest.mark.skipif(sys.platform == "win32", reason="the fake claude is a shebang script")
def test_run_ab_with_a_fake_claude_reports_tokens(tmp_path: Path) -> None:
    m = _script()

    results = _run_fake(m, tmp_path, ANSWER)
    report = m.render_ab(results, tmp_path / "out")

    assert [r["tokens_in"] for r in results] == [1000, 1000]
    assert "Tokens entrada" in report
    assert "| 1000 | 790 | 55 |" in report
    assert "Mediana de tokens de entrada por corrida: 1000 en base y 1000 en new (+0%)." in report


def test_render_ab_shows_dashes_and_the_token_change() -> None:
    m = _script()

    def run(variant: str, tokens_in: int | None) -> dict:
        return {
            "variant": variant, "n": 1, "note": "", "total": 4, "calls": {}, "search_any": 0,
            "read_batch": 0, "chars": 9, "turns": 2, "cost": 0.1, "tokens_in": tokens_in,
            "tokens_cached": None, "tokens_out": None,
        }  # fmt: skip

    report = m.render_ab([run("base", 1000), run("new", 500), run("new", None)], Path("x"))

    assert "| – | – | – |" in report
    assert "1000 en base y 500 en new (-50%)." in report
