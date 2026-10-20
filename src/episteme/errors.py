"""Errors raised by tools. The message is always ``<code>: <what failed>. <what to do>``."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

NOT_FOUND = "not_found"
AMBIGUOUS = "ambiguous"
READ_ONLY_ZONE = "read_only_zone"
OUTSIDE_VAULT = "outside_vault"
INVALID_SCHEMA = "invalid_schema"
INVALID_ARGUMENT = "invalid_argument"


class EpistemeError(ToolError):
    """A tool failure the model can act on (anticipated, so the SDK logs no traceback)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class StartupError(Exception):
    """The server cannot start; the message is printed to stderr."""


def invalid(message: str) -> EpistemeError:
    return EpistemeError(INVALID_ARGUMENT, message)
