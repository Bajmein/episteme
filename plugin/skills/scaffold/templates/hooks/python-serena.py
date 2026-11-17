#!/usr/bin/env python3
"""Prefer Serena (+ ty LSP) for Python files, and type-check Python after every edit.

Module serena-python of /episteme:scaffold (local by default). Registered in
.claude/settings.local.json:

    pre   PreToolUse  Read|Edit|MultiEdit|Write
          A whole-file Read, or an Edit/Write of an existing .py/.pyi file, gets a short
          additionalContext naming the Serena tool to use instead. Once per session, tool kind
          and file; it never blocks (serena-hooks remind already denies long grep/read streaks).
    post  PostToolUse Edit|MultiEdit|Write and Serena's editing tools
          Runs `uv run --frozen ty check --output-format concise` on the project (the same ty
          that Serena's python_ty language server runs) and, if it fails, hands the diagnostics
          to Claude as additionalContext. Silent when everything passes.

Any error exits 0 without output: the hook never gets in the way of a tool call.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

PY_SUFFIXES = (".py", ".pyi")
SERENA = "mcp__serena__"
SERENA_EDIT_TOOLS = {
    "replace_symbol_body",
    "insert_after_symbol",
    "insert_before_symbol",
    "replace_content",
    "replace_in_files",
    "rename_symbol",
    "safe_delete_symbol",
    "replace_lines",
    "delete_lines",
    "insert_at_line",
    "create_text_file",
}
# Tools that may touch several files: always type-check, whatever relative_path says.
SERENA_MULTI_FILE_TOOLS = {"replace_in_files", "rename_symbol", "safe_delete_symbol"}
MAX_DIAGNOSTIC_LINES = 40
TY_TIMEOUT_SECONDS = 60

READ_HINT = (
    "Python file {rel}: prefer Serena over a whole-file Read. Start with "
    "mcp__serena__get_symbols_overview(relative_path=\"{rel}\"), then "
    "mcp__serena__find_symbol(name_path=..., relative_path=\"{rel}\", include_body=true) for the "
    "symbols you need; find_referencing_symbols / find_declaration to follow usages. "
    "Read with offset/limit is fine for a few lines once you have the overview."
)
EDIT_HINT = (
    "Python file {rel}: prefer Serena's symbolic edits over Edit/Write: "
    "replace_symbol_body for a whole function/method, insert_before_symbol / insert_after_symbol "
    "to add code, replace_content for a few lines, rename_symbol and safe_delete_symbol for "
    "refactors (they update every reference). Check types with get_diagnostics_for_file."
)


def project_root(data: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())


def relative(path: str, root: Path) -> str | None:
    """Project-relative path of a Python file inside the project, or None."""
    if not path.endswith(PY_SUFFIXES):
        return None
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def first_time(session: str, key: str) -> bool:
    """True the first time `key` is seen in this session (state in the temp dir)."""
    user = getattr(os, "getuid", lambda: os.environ.get("USERNAME", "user"))()
    state_dir = Path(tempfile.gettempdir()) / f"claude-python-serena-{user}"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = state_dir / f"{session or 'no-session'}.json"
    try:
        seen = set(json.loads(state.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    if key in seen:
        return False
    seen.add(key)
    with open(state, "w", encoding="utf-8", newline="") as f:
        json.dump(sorted(seen), f)
    return True


def emit(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def hint_for(tool: str, tool_input: dict) -> tuple[str, str] | None:
    """(kind, hint) for a Read/Edit/Write of an existing Python file, or None."""
    if tool == "Read":
        if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
            return None  # a targeted read of a few lines is fine
        return "read", READ_HINT
    if tool in ("Edit", "MultiEdit"):
        return "edit", EDIT_HINT
    if tool == "Write" and Path(tool_input.get("file_path") or "").exists():
        return "edit", EDIT_HINT  # creating a new module with Write is fine
    return None


def pre(data: dict) -> None:
    tool_input = data.get("tool_input") or {}
    rel = relative(tool_input.get("file_path") or "", project_root(data))
    found = hint_for(data.get("tool_name", ""), tool_input) if rel else None
    if rel is None or found is None:
        return
    kind, hint = found
    if first_time(data.get("session_id", ""), f"{kind}:{rel}"):
        emit("PreToolUse", hint.format(rel=rel))


def touches_python(data: dict, root: Path) -> bool:
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if tool in ("Edit", "MultiEdit", "Write"):
        return relative(tool_input.get("file_path") or "", root) is not None
    if not tool.startswith(SERENA):
        return False
    name = tool.removeprefix(SERENA)
    if name not in SERENA_EDIT_TOOLS:
        return False
    if name in SERENA_MULTI_FILE_TOOLS:
        return True
    return relative(tool_input.get("relative_path") or "", root) is not None


def post(data: dict) -> None:
    root = project_root(data)
    if not touches_python(data, root) or not (root / "pyproject.toml").is_file():
        return
    # fixed argv, no shell.
    result = subprocess.run(  # nosec B603 B607
        ["uv", "run", "--frozen", "ty", "check", "--output-format", "concise"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TY_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode == 0:
        return
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    shown = lines[:MAX_DIAGNOSTIC_LINES]
    more = f"\n… {len(lines) - len(shown)} more lines" if len(lines) > len(shown) else ""
    emit(
        "PostToolUse",
        "ty check (the same ty as Serena's python_ty language server) fails after this edit:\n"
        + "\n".join(shown)
        + more
        + "\nFix it before moving on; mcp__serena__get_diagnostics_for_file or "
        "get_diagnostics_for_symbol give the detail per file or symbol.",
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
        {"pre": pre, "post": post}[sys.argv[1]](data)
    # a hook must never break the tool call.
    except Exception:  # nosec B110
        pass


if __name__ == "__main__":
    main()
