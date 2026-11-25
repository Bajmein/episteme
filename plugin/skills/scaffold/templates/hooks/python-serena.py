#!/usr/bin/env python3
"""Prefer Serena (+ ty LSP) for Python files, and type-check Python after every edit.

Module serena-python of /episteme:scaffold (local by default). Registered in
.claude/settings.local.json:

    pre   PreToolUse  Read|Edit|MultiEdit|Write
          A whole-file Read, or an Edit/Write of an existing .py/.pyi file, gets a short
          additionalContext naming the Serena tool to use instead. Once per session, tool kind
          and file; it never blocks (serena-hooks remind already denies long grep/read streaks).
    remind PreToolUse (every tool)
          Hands the call to `serena-hooks remind` only when it is Python work (Serena tools,
          .py/.pyi files, Grep or Bash on Python files or under src/, tests/, scripts/), so
          greps over Markdown, JSON or command output no longer count toward its streaks.
    post  PostToolUse Edit|MultiEdit|Write and Serena's editing tools
          Runs `uv run --frozen ty check --output-format concise` on the project (the same ty
          that Serena's python_ty language server runs) and, if it fails, hands the diagnostics
          to Claude as additionalContext. Silent when everything passes.

Any error exits 0 without output: the hook never gets in the way of a tool call.
"""

from __future__ import annotations

import json
import os
import re
import shlex
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
REMIND = ("serena-hooks", "remind", "--client=claude-code")
REMIND_TIMEOUT_SECONDS = 10
PY_DIRS = ("src", "tests", "scripts")
FILE_TOOLS = ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit")
PY_TOKEN = re.compile(r"\.pyi?(?=$|[\s'\"`:;|)&,])")
PY_FILTER = re.compile(r"--include=['\"]?\*\.pyi?|-g\s+['\"]?\*\.pyi?|-t\s*py\b|--type[= ]py\b")
# Run after PY_FILTER: any inclusion filter left is for another file type.
OTHER_FILTER = re.compile(r"--include=|-g\s|-t\s*\w|--type[= ]\w")
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1([^\n]*)\n.*?^[ \t]*\2[ \t]*$", re.S | re.M)
# A token with whitespace, a backslash or a pipe is a pattern or text, not a path.
NOT_A_PATH = re.compile(r"[\s\\|]")

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


def is_targeted_read(tool_input: dict) -> bool:
    """A Read with offset or limit: a few lines, fine without Serena."""
    return tool_input.get("offset") is not None or tool_input.get("limit") is not None


def writes_existing(tool_input: dict) -> bool:
    """A Write over an existing file (creating a new module with Write is fine)."""
    return Path(tool_input.get("file_path") or "").exists()


def hint_for(tool: str, tool_input: dict) -> tuple[str, str] | None:
    """(kind, hint) for a Read/Edit/Write of an existing Python file, or None."""
    if tool == "Read":
        return None if is_targeted_read(tool_input) else ("read", READ_HINT)
    if tool in ("Edit", "MultiEdit"):
        return "edit", EDIT_HINT
    if tool == "Write" and writes_existing(tool_input):
        return "edit", EDIT_HINT
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


def serena_touches_python(name: str, tool_input: dict, root: Path) -> bool:
    """A Serena editing tool that touches a Python file (multi-file tools always count)."""
    if name not in SERENA_EDIT_TOOLS:
        return False
    if name in SERENA_MULTI_FILE_TOOLS:
        return True
    return relative(tool_input.get("relative_path") or "", root) is not None


def touches_python(data: dict, root: Path) -> bool:
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if tool in ("Edit", "MultiEdit", "Write"):
        return relative(tool_input.get("file_path") or "", root) is not None
    if not tool.startswith(SERENA):
        return False
    return serena_touches_python(tool.removeprefix(SERENA), tool_input, root)


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


def under_py_dir(path: str, root: Path) -> bool:
    """Whether `path` is, or is inside, one of PY_DIRS of the project."""
    p = Path(path.strip("'\""))
    if not p.is_absolute():
        p = root / p
    try:
        parts = p.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] in PY_DIRS


def grep_is_python(tool_input: dict, root: Path) -> bool:
    if tool_input.get("type") == "py":
        return True
    glob = tool_input.get("glob") or ""
    path = tool_input.get("path") or ""
    if glob.endswith(PY_SUFFIXES) or path.endswith(PY_SUFFIXES):
        return True
    return bool(path) and under_py_dir(path, root)


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies, keeping the rest of their marker line."""
    return HEREDOC.sub(r"\3", command)


def bash_operands(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return [t for t in tokens if t and not t.startswith("-") and not NOT_A_PATH.search(t)]


def _exists(token: str, root: Path) -> bool:
    path = Path(token)
    return (path if path.is_absolute() else root / path).exists()


def searches_only_py_dirs(operands: list[str], root: Path) -> bool:
    py_dirs = [t for t in operands if under_py_dir(t, root) and not Path(t.strip("'\"")).suffix]
    outside = [t for t in operands if not under_py_dir(t, root) and _exists(t, root)]
    return bool(py_dirs) and not outside


def bash_is_python(command: str, root: Path) -> bool:
    """Python if it names .py/.pyi or filters on them, or searches only Python folders."""
    cmd = strip_heredocs(command)
    if PY_FILTER.search(cmd):
        return True
    operands = bash_operands(cmd)
    if any(PY_TOKEN.search(t) for t in operands):
        return True
    if OTHER_FILTER.search(cmd):
        return False
    return searches_only_py_dirs(operands, root)


def python_call(data: dict) -> bool:
    """Whether a tool call is Python work, the only kind serena-hooks remind should count."""
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    if tool.startswith(SERENA):
        return True
    if tool in FILE_TOOLS:
        return (tool_input.get("file_path") or "").endswith(PY_SUFFIXES)
    root = project_root(data)
    if tool == "Grep":
        return grep_is_python(tool_input, root)
    if tool == "Bash":
        return bash_is_python(tool_input.get("command") or "", root)
    return False


def remind(data: dict) -> None:
    """Pass Python calls on to serena-hooks remind; the rest never reaches its counter."""
    if not python_call(data):
        return
    # fixed argv, no shell.
    proc = subprocess.run(  # nosec B603
        REMIND,
        input=json.dumps(data),
        capture_output=True,
        text=True,
        timeout=REMIND_TIMEOUT_SECONDS,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    sys.exit(proc.returncode)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        {"pre": pre, "post": post, "remind": remind}[sys.argv[1]](data)
    # a hook must never break the tool call.
    except Exception:  # nosec B110
        pass


if __name__ == "__main__":
    main()
