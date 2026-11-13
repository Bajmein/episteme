"""MCP server: instructions, error formatting and build_server; the tools are in episteme.tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from episteme import maintenance, prompting
from episteme.activity import Activity
from episteme.engine import Engine
from episteme.errors import INVALID_ARGUMENT, EpistemeError
from episteme.tools import hooks, memories, reading

INSTRUCTIONS = """\
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- Look before you answer or act. When you start work, call context(mode="task", task="<what you are about to do>"). When the user asks what is known about a person, a client, a decision or a past event, call search, even if they did not mention the vault; then read the best hits in one call with read(notes=[...]).
- search is literal: it matches whole words. To look up several names, or a word with its plural, abbreviation and proper name (mkt marketing, a surname), put them in one query with match="any" instead of one search per word; add zone="memory" when you want memories, not documentation. tags follow a topic across projects; project is optional.
- Before deciding something that may already have been decided, call search, then read the best hit.
- Save without being asked, with remember, when: a decision is closed; a plan is agreed; the user corrects something you said; you learn a lesson or hit an error worth remembering; you had to get a fact from another source because the vault did not have it; or the user says "remember". Name the files, tools, commands and people involved in the body: that is what is searched later. Save project knowledge with remember, not in Claude Code's auto memory (MEMORY.md).
- When a memory is wrong or replaced, call revise (action="supersede" or "archive"), never remember a contradiction next to it.
- Notes under read-only zones (docs/claude-code) cannot be changed. Errors say what failed and what to do."""  # noqa: E501


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "arguments"
        parts.append(f"{loc}: {err['msg']}")
    return (
        f"{INVALID_ARGUMENT}: {'; '.join(parts)}. "
        "Check the parameter names and types in the tool schema."
    )


def _created(text: str) -> bool:
    """Whether a ``remember`` result wrote a note (a blocked duplicate has created: false)."""
    try:
        return json.loads(text).get("created") is True
    except (ValueError, AttributeError):
        return False


def _result_paths(text: str) -> list[str]:
    """The note paths of a ``remember``, ``revise`` or ``read`` result (one note or several)."""
    try:
        data = json.loads(text)
        notes = data.get("notes") if isinstance(data.get("notes"), list) else [data]
        return [n["path"] for n in notes if isinstance(n, dict) and isinstance(n.get("path"), str)]
    except (ValueError, AttributeError):
        return []


def _error_text(exc: ToolError) -> str | None:
    """The message for a tool error caused by episteme or validation, else None."""
    cause = exc.__cause__
    if isinstance(cause, EpistemeError):
        return str(cause)
    if isinstance(cause, ValidationError):
        return _validation_message(cause)
    return None


def _result_text(result: Any) -> str:
    """The concatenated text blocks of a tool result."""
    return "".join(getattr(b, "text", "") for b in getattr(result, "content", None) or [])


def _track_result(name: str, arguments: dict[str, Any], text: str) -> None:
    """Count writes and track the notes written or read by a successful tool call."""
    if name in ("remember", "revise") and "hook_event" not in arguments:
        if name == "revise" or _created(text):
            prompting.WRITES += 1
            for path in _result_paths(text):
                prompting.track(path, "written")
    elif name == "read":
        for path in _result_paths(text):
            prompting.track(path, "read")


class EpistemeServer(MCPServer):
    """MCPServer whose tool errors read ``<code>: <what failed>. <what to do>``."""

    activity: Activity | None = None

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context | None = None
    ) -> Any:
        start = time.perf_counter()
        try:
            result = await super().call_tool(name, arguments, context)
        except ToolError as exc:
            text = _error_text(exc)
            if text is None:
                raise
            self._log(name, arguments, text, start, False)
            return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        text = _result_text(result)
        _track_result(name, arguments, text)
        self._log(name, arguments, text, start, True)
        return result

    def _log(self, name: str, arguments: Any, text: str, start: float, ok: bool) -> None:
        if self.activity is not None:
            ms = round((time.perf_counter() - start) * 1000)
            self.activity.record(name, arguments, text, ms, ok)


def build_server(vault: Path, project: str | None = None) -> MCPServer:
    """Create the MCP server for ``vault``; raises StartupError on a bad episteme.toml."""
    engine = Engine(vault, project)
    server = EpistemeServer("episteme", instructions=INSTRUCTIONS)
    server.activity = Activity(engine.vault.root)
    store = maintenance.Store(engine.vault.root)
    reading.register(server, engine)
    memories.register(server, engine)
    hooks.register(server, engine, store)
    return server
