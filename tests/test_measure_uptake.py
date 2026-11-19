"""scripts/measure_uptake.py: deliveries, reads and empty searches from a synthetic log."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from episteme.activity import _SCHEMA

SCRIPT = Path(__file__).parents[1] / "scripts/measure_uptake.py"
NOW = datetime(2026, 12, 1, tzinfo=UTC)
A, B, C = "memory/p/a.md", "memory/p/b.md", "memory/p/c.md"


def _script():
    spec = importlib.util.spec_from_file_location("measure_uptake", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _vault(tmp_path: Path, calls: list[tuple]) -> Path:
    root = tmp_path / "v"
    (root / "memory/p").mkdir(parents=True)
    (root / ".index").mkdir()
    (root / "episteme.toml").write_text('[zones."memory"]\nmode = "memory"\n', encoding="utf-8")
    for name, created in (("a", "2026-01-01"), ("b", "2026-11-20"), ("c", "2026-01-02")):
        (root / "memory/p" / f"{name}.md").write_text(
            f"---\ntype: lesson\ncreated: {created}\n---\n# {name}\n", encoding="utf-8"
        )
    conn = sqlite3.connect(root / ".index/activity.db")
    conn.executescript(_SCHEMA)
    for mins, session, tool, hook, args, paths, ok in calls:
        at = (NOW - timedelta(days=1) + timedelta(minutes=mins)).isoformat(timespec="seconds")
        conn.execute(
            "insert into calls (at, session, tool, hook_event, project, args, paths, ok)"
            " values (?,?,?,?,?,?,?,?)",
            (at, session, tool, hook, "p", json.dumps(args), json.dumps(paths), ok),
        )
    conn.commit()
    conn.close()
    return root


CALLS = [
    (0, "s1", "context", "SessionStart", {"mode": "welcome"}, [A, B], 1),
    (1, "s1", "surface", "UserPromptSubmit", {}, [A], 1),
    (2, "s1", "read", None, {"notes": [A]}, [A], 1),
    (3, "s2", "context", "SessionStart", {"mode": "welcome"}, [A, B], 1),
    (4, "s2", "read", None, {"note": "a"}, [A], 1),
    (5, "s2", "remember", None, {}, [], 1),
    (6, "s3", "constraints", "PreToolUse", {}, [B], 1),
    (7, "s3", "context", "UserPromptSubmit", {"mode": "task"}, [B], 1),
    (8, "s3", "search", None, {"query": "zzz", "match": "any", "zone": "memory"}, [], 1),
    (9, "s3", "search", None, {"query": "zzz", "match": "any", "zone": "memory"}, [], 1),
    (10, "s3", "search", None, {"query": "otra"}, [], 1),
    (11, "s3", "search", None, {"query": "fail"}, [], 0),
    (12, "s3", "search", None, {"query": "hit"}, [C], 1),
    (13, "s3", "search", "UserPromptSubmit", {"query": "hooked"}, [], 1),
    (14, "s3", "read", None, {"note": C}, [C], 1),
]


def test_measure_counts(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path, CALLS)
    r = m.measure(root, project="p", days=7, min_deliveries=2, now=NOW)
    s = r["stats"]
    assert (s[A]["context"], s[A]["welcome"], s[A]["surface"], s[A]["reads"]) == (2, 2, 1, 2)
    assert s[A]["reads_after"] == 2
    assert (s[B]["context"], s[B]["welcome"], s[B]["constraints"], s[B]["reads"]) == (3, 2, 1, 0)
    assert s[C]["searches"] == 1 and s[C]["reads"] == 1 and s[C]["reads_after"] == 0
    # deliveries: A x3, B x4; followed: A in s1 (context, surface) and s2 (context)
    assert r["deliveries"] == 7
    assert r["followed"] == 3
    assert r["never_read"] == [(B, 4)]
    assert (r["old_total"], r["old_read"], r["old_unread"]) == (2, [A, C], [])
    assert r["sessions_read"] == 3
    assert r["sessions_no_write"] == ["s1", "s3"]
    assert r["empty"] == [(("zzz", "any", "memory"), 2), (("otra", "", ""), 1)]
    assert r["empty_total"] == 3


def test_agent_calls_take_the_session_of_their_server_process(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path, [])
    conn = sqlite3.connect(root / ".index/activity.db")
    rows = [
        (0, "s1", 10, "context", "UserPromptSubmit", {"mode": "welcome"}, [A]),
        (1, None, 10, "read", None, {"notes": [A]}, [A]),
        (2, None, 20, "read", None, {"note": B}, [B]),
    ]
    for mins, session, pid, tool, hook, args, paths in rows:
        at = (NOW - timedelta(days=1) + timedelta(minutes=mins)).isoformat(timespec="seconds")
        conn.execute(
            "insert into calls (at, pid, session, tool, hook_event, project, args, paths, ok)"
            " values (?,?,?,?,?,?,?,?,1)",
            (at, pid, session, tool, hook, "p", json.dumps(args), json.dumps(paths)),
        )
    conn.commit()
    conn.close()

    r = m.measure(root, days=7, now=NOW)

    assert r["followed"] == 1
    assert r["stats"][A]["reads_after"] == 1
    assert r["sessions_read"] == 2


def test_window_and_project_filter(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path, CALLS)
    assert m.measure(root, project="other", days=7, now=NOW)["rows"] == 0
    assert m.measure(root, days=0, now=NOW)["rows"] == 0


def test_cli_renders_and_is_read_only(tmp_path: Path) -> None:
    root = _vault(tmp_path, CALLS)
    db = root / ".index/activity.db"
    before = db.read_bytes()
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(root), "--days", "100000"],
        capture_output=True,
        check=True,
    )
    out = r.stdout.decode("utf-8")
    assert f"| {A} |" in out
    for section in ("(a)", "(b)", "(c)", "(d)", "(e)"):
        assert f"### {section}" in out
    assert "`zzz`" in out
    assert db.read_bytes() == before
    assert not (root / ".index/index.db").exists()


def test_missing_log(tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    (root / "episteme.toml").write_text('[zones."memory"]\nmode = "memory"\n', encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(root)], capture_output=True, text=True
    )
    assert r.returncode == 1
    assert r.stderr.startswith("not_found:")


def test_calls_are_broken_down_by_client(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path, CALLS)
    conn = sqlite3.connect(root / ".index/activity.db")
    conn.execute("update calls set client = 'agy' where id <= 2")
    conn.commit()
    conn.close()

    r = m.measure(root, days=7, now=NOW)

    assert r["clients"] == [(m.NO_CLIENT, len(CALLS) - 2), ("agy", 2)]
    assert "- agy: 2" in m.render(r)


def test_v1_log_without_client_column_still_loads(tmp_path: Path) -> None:
    m = _script()
    root = _vault(tmp_path, CALLS)
    conn = sqlite3.connect(root / ".index/activity.db")
    conn.execute("alter table calls drop column client")
    conn.commit()
    conn.close()

    r = m.measure(root, days=7, now=NOW)

    assert r["rows"] == len(CALLS)
    assert r["clients"] == [(m.NO_CLIENT, len(CALLS))]
