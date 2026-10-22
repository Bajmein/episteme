"""Entry point: parse --vault and --project, validate and start the stdio server."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from episteme.errors import StartupError


def _check_fts5() -> None:
    try:
        sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")
    except sqlite3.OperationalError as exc:
        raise StartupError(
            "this Python's SQLite has no FTS5 support. Use a Python build with FTS5."
        ) from exc


DEFAULT_TOML = """\
# Vault global de episteme, creado al arrancar sin --vault ni EPISTEME_VAULT.
# Una ruta que no está en ninguna zona es de solo lectura.

[zones."memory"]
mode = "memory"

[checkpoint]
state_glob = ".fabrik/**/estado.md"   # relativo a project_dir
"""


def default_vault() -> Path:
    return Path.home() / ".episteme"


def resolve_vault(arg: str | None) -> Path:
    """Return the vault from ``--vault``, ``EPISTEME_VAULT`` or ``~/.episteme``.

    An explicit path must already be a vault; only the default one is created when missing.
    """
    raw = arg or os.environ.get("EPISTEME_VAULT")
    if not raw:
        path = default_vault()
        if not path.exists():
            path.mkdir(parents=True)
            (path / "episteme.toml").write_text(DEFAULT_TOML, encoding="utf-8")
        raw = str(path)
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
        prog="episteme", description="MCP server for an episteme Markdown vault."
    )
    parser.add_argument(
        "--vault", help="absolute path of the vault (or EPISTEME_VAULT; default ~/.episteme)"
    )
    parser.add_argument("--project", help="default project for memory tools, e.g. fabrik")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        vault = resolve_vault(args.vault)
        _check_fts5()
        from episteme.server import build_server

        server = build_server(vault, args.project)
    except StartupError as exc:
        print(f"episteme: {exc}", file=sys.stderr)
        sys.exit(2)
    server.run("stdio")


if __name__ == "__main__":
    main()
