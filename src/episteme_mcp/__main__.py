"""Entry point: parse --vault and --project, validate and start the stdio server."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


class StartupError(Exception):
    """The server cannot start; the message is printed to stderr."""


def _check_fts5() -> None:
    try:
        sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")
    except sqlite3.OperationalError as exc:
        raise StartupError(
            "this Python's SQLite has no FTS5 support. Use a Python build with FTS5."
        ) from exc


def resolve_vault(arg: str | None) -> Path:
    """Return the vault path from ``--vault`` or ``EPISTEME_VAULT``, or raise StartupError."""
    raw = arg or os.environ.get("EPISTEME_VAULT")
    if not raw:
        raise StartupError("no vault given. Pass --vault <absolute path> or set EPISTEME_VAULT.")
    path = Path(raw)
    if not path.is_absolute():
        raise StartupError(f'vault path "{raw}" is not absolute. Pass an absolute path.')
    if not path.is_dir():
        raise StartupError(f'vault path "{raw}" does not exist or is not a directory.')
    if not (path / "episteme.toml").is_file():
        raise StartupError(
            f'"{raw}" has no episteme.toml. '
            "Create it at the vault root to mark the folder as a vault."
        )
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="episteme-mcp", description="MCP server for an episteme Markdown vault."
    )
    parser.add_argument("--vault", help="absolute path of the vault (or EPISTEME_VAULT)")
    parser.add_argument("--project", help="default project for memory tools, e.g. fabrik")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        vault = resolve_vault(args.vault)
        _check_fts5()
        from episteme_mcp.server import build_server

        server = build_server(vault, args.project)
    except StartupError as exc:
        print(f"episteme-mcp: {exc}", file=sys.stderr)
        sys.exit(2)
    server.run("stdio")


if __name__ == "__main__":
    main()
