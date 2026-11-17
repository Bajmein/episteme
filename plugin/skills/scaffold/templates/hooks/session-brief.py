#!/usr/bin/env python3
"""SessionStart hook: work state, a map of the repo and the index of its rules.

Module session-brief of /episteme:scaffold (local by default). startup, clear and compact get
everything: work state, the map of MAP_DIRS (first paragraph of each Python module docstring;
left out when there is no Python) and the index of .claude/rules/. resume and fork only get the
work state: the rest is already in the resumed conversation.

Prints {"systemMessage": ..., "hookSpecificOutput": {"hookEventName": "SessionStart",
"additionalContext": ...}}: the systemMessage is a bold cyan line for the person.
Every part is best-effort: if git, gh or a file fails (or is missing), only its line is left out.
Standard library only.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

# Filled in by /episteme:scaffold with the detected source folders (relative to the repo root).
MAP_DIRS = ["src", "scripts"]
BASE_BRANCH = "main"
ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
GH_TIMEOUT = 6
GH_FAILURES = (f"sin respuesta de gh en {GH_TIMEOUT} s", "gh falló")
GIT_TIMEOUT = 3
DESC_MAX = 110
CHANGELOG_MAX = 6
FULL_SOURCES = {"startup", "clear", "compact"}
NOTICE_STYLE = "\x1b[1;36m"
NOTICE_RESET = "\x1b[0m"
GH_QUERIES = {
    "PR abiertos": [
        "gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName",
        "--jq", '.[] | "#\\(.number) \\(.title) [\\(.headRefName)]"',
    ],
    "Issues abiertos": [
        "gh", "issue", "list", "--state", "open", "--json", "number,title",
        "--jq", '.[] | "#\\(.number) \\(.title)"',
    ],
}


def run(args: list[str], timeout: int = GIT_TIMEOUT) -> str | None:
    """Return the command's stdout, or None if it fails or times out."""
    try:
        # fixed argv, no shell.
        done = subprocess.run(  # nosec B603
            args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def start_gh() -> dict[str, subprocess.Popen[str]]:
    """Launch the gh queries at once (they are the slow part); none without gh."""
    if shutil.which("gh") is None:
        return {}
    procs = {}
    for label, args in GH_QUERIES.items():
        try:
            # fixed argv, no shell.
            procs[label] = subprocess.Popen(  # nosec B603
                args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8",
            )
        except OSError:
            continue
    return procs


def gh_line(label: str, proc: subprocess.Popen[str], deadline: float) -> str:
    try:
        out, _ = proc.communicate(timeout=max(deadline - time.monotonic(), 0.1))
    except subprocess.TimeoutExpired:
        proc.kill()
        return f"- {label}: sin respuesta de gh en {GH_TIMEOUT} s"
    if proc.returncode != 0:
        return f"- {label}: gh falló"
    items = [line for line in out.strip().splitlines() if line]
    return f"- {label}: " + ("; ".join(items) if items else "ninguno")


def finish_gh(procs: dict[str, subprocess.Popen[str]]) -> list[str]:
    deadline = time.monotonic() + GH_TIMEOUT  # one budget for all the queries
    return [gh_line(label, proc, deadline) for label, proc in procs.items()]


def ahead_behind(line: str) -> str:
    ahead, behind = line.split(" ")[2:4]
    if ahead != "+0" or behind != "-0":
        return f" ({ahead} {behind} respecto de su remoto)"
    return " (al día con su remoto)"


def branch_line() -> str | None:
    out = run(["git", "status", "--porcelain=v2", "--branch"])
    if out is None:
        return None
    branch, sync, changes = "?", "", 0
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            sync = ahead_behind(line)
        elif not line.startswith("#"):
            changes += 1
    return f"- Rama: {branch}{sync}; archivos con cambios sin commit: {changes}"


def branches_line() -> str | None:
    out = run(["git", "branch", "--no-merged", BASE_BRANCH, "--format=%(refname:short)"])
    if out is None:
        return None
    names = out.split()
    return f"- Ramas locales sin mezclar en {BASE_BRANCH}: " + (", ".join(names) or "ninguna")


def worktrees_line() -> str | None:
    out = run(["git", "worktree", "list", "--porcelain"])
    if out is None:
        return None
    prefix = "worktree "
    paths = [line.removeprefix(prefix) for line in out.splitlines() if line.startswith(prefix)]
    extra = [p for p in paths if Path(p).resolve() != ROOT.resolve()]
    return "- Worktrees aparte: " + (", ".join(extra) if extra else "ninguno")


def tag_line() -> str | None:
    out = run(["git", "describe", "--tags", "--abbrev=0"])
    return f"- Último tag: {out}" if out else None


def unreleased(text: str) -> list[str]:
    inside, entries = False, []
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = "Sin publicar" in line or "Unreleased" in line
        elif inside and line.startswith("- "):
            entries.append(line[2:].strip())
    return entries


def changelog_lines() -> list[str]:
    try:
        entries = unreleased((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not entries:
        return ["- CHANGELOG «Sin publicar»: vacío"]
    shown = [f"  - {shorten(e)}" for e in entries[:CHANGELOG_MAX]]
    more = len(entries) - CHANGELOG_MAX
    if more > 0:
        shown.append(f"  - … y {more} más")
    return [f"- CHANGELOG «Sin publicar»: {len(entries)} entradas", *shown]


def shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= DESC_MAX else text[: DESC_MAX - 1] + "…"


def module_summary(path: Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (OSError, SyntaxError, ValueError):
        return "?"
    return shorten((doc or "").strip().split("\n\n")[0]) or "(sin docstring)"


def module_map(base: str) -> list[str]:
    folder = ROOT / base
    files = sorted(folder.rglob("*.py")) if folder.is_dir() else []
    if not files:
        return []
    lines = [f"## Mapa de {base}/ (primer párrafo del docstring de cada módulo)", ""]
    lines += [f"- `{p.relative_to(folder).as_posix()}`: {module_summary(p)}" for p in files]
    return [*lines, ""]


# @CodeScene(disable:"Complex Method")
def rule_paths(path: Path) -> list[str]:
    """The `paths:` globs of a rule's frontmatter (simple YAML list, no parser needed)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return []
    if not lines or lines[0].strip() != "---":
        return []
    globs, in_paths = [], False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if line.startswith("paths:"):
            in_paths = True
        elif in_paths and stripped.startswith("- "):
            globs.append(stripped[2:].strip().strip("\"'"))
        elif stripped:
            in_paths = False
    return globs


def rules_index() -> list[str]:
    rules = sorted((ROOT / ".claude" / "rules").glob("*.md"))
    if not rules:
        return []
    lines = [
        "## Reglas de .claude/rules/",
        "",
        "Una regla se carga cuando Read, Edit o Write toca un archivo que coincide con sus rutas.",
        "",
    ]
    for rule in rules:
        globs = rule_paths(rule)
        listed = ", ".join(f"`{g}`" for g in globs) if globs else "siempre"
        lines.append(f"- `{rule.name}`: {listed}")
    return [*lines, ""]


def count_items(section: list[str]) -> int:
    return sum(1 for line in section if line.startswith("- `"))


def full_parts() -> tuple[list[str], list[str]]:
    """The map and the rules index, with their part of the notice."""
    modules = [line for base in MAP_DIRS for line in module_map(base)]
    rules = rules_index()
    parts = [f"índice de {count_items(rules)} reglas"]
    if modules:
        parts.insert(0, f"mapa de {count_items(modules)} módulos")
    return modules + rules, parts


def build(source: str) -> tuple[str, str]:
    """The context for Claude and the one-line notice for the person."""
    procs = start_gh()
    state = [branch_line(), branches_line(), worktrees_line(), tag_line()]
    gh_lines = finish_gh(procs)
    lines = [
        f"Contexto de inicio (hook session-brief, source={source})",
        "",
        "## Estado del trabajo",
        "",
        *[line for line in state if line],
        *changelog_lines(),
        *gh_lines,
        "",
    ]
    gh_failed = bool(procs) and any(line.endswith(GH_FAILURES) for line in gh_lines)
    parts = ["estado del trabajo" + (" (gh no respondió)" if gh_failed else "")]
    if source in FULL_SOURCES:
        extra, extra_parts = full_parts()
        lines += extra
        parts += extra_parts
    notice = "▶ session-brief: contexto inicial cargado (" + ", ".join(parts) + ")"
    return "\n".join(lines).rstrip() + "\n", notice


def paint(text: str) -> str:
    """Bold cyan for the terminal; plain with NO_COLOR."""
    if os.environ.get("NO_COLOR"):
        return text
    return f"{NOTICE_STYLE}{text}{NOTICE_RESET}"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    source = (payload.get("source") if isinstance(payload, dict) else None) or "startup"
    text, notice = build(source)
    print(
        json.dumps({
            "systemMessage": paint(notice),
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text},
        })
    )


if __name__ == "__main__":
    main()
