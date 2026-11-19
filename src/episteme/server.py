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
from episteme.tools import docs, hooks, memories, plans, reading
from episteme.tools import session as session_tool

INSTRUCTIONS = """\
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- Look before you answer or act. When you start work, call context(mode="task", task="<what you are about to do>"). When the user asks what is known about a person, a client, a decision or a past event, call search, even if they did not mention the vault; then read the best hits in one call with read(notes=[...]).
- search is literal: it matches whole words. To look up several names, or a word with its plural, abbreviation and proper name (mkt marketing, a surname), put them in one query with match="any" instead of one search per word; add zone="memory" when you want memories, not documentation. tags follow a topic across projects; project is optional.
- Before deciding something that may already have been decided, call search, then read the best hit.
- Save without being asked, with remember, when: a decision is closed; a plan is agreed; the user corrects something you said; you learn a lesson or hit an error worth remembering; you had to get a fact from another source because the vault did not have it; or the user says "remember". Name the files, tools, commands and people involved in the body: that is what is searched later. Save project knowledge with remember, not in the agent's own memory (Claude Code's MEMORY.md, or rule files such as AGENTS.md or GEMINI.md).
- When a memory is wrong or replaced, call revise (action="supersede" or "archive"), never remember a contradiction next to it.
- Keep the session state current with session(action="save"), following its template: when a plan is agreed, a phase ends, the approach changes, before a risky step, and when the user asks. If a hook asks you to launch the episteme:extractor agent, launch it in the background.
- Notes under read-only zones (docs/claude-code) cannot be changed. docs/ suites change only via /episteme:docs. Errors say what failed and what to do."""  # noqa: E501


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


def _changed(text: str) -> bool:
    """Whether a ``docs_write`` result wrote the note (changed: false wrote nothing)."""
    try:
        return json.loads(text).get("changed") is True
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


def _track_docs_write(name: str, text: str) -> None:
    """A ``docs_write`` that changed a note joins the trail; it is not a memory write."""
    if name == "docs_write" and _changed(text):
        for path in _result_paths(text):
            prompting.track(path, "written")


def _track_session_save(name: str, arguments: dict[str, Any], text: str) -> None:
    """A ``session`` save joins the trail as written and counts in ``STATE_SAVES`` when the
    agent made it; it is not a memory write."""
    if name == "session" and arguments.get("action") == "save":
        if "hook_event" not in arguments:
            prompting.STATE_SAVES += 1
        for path in _result_paths(text):
            prompting.track(path, "written")


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


_CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
_AGY_SESSION_KEY = "antigravity.google/root_conversation_id"


def _meta_text(meta: Any, key: str) -> str | None:
    value = meta.get(key) if isinstance(meta, dict) else None
    return value if isinstance(value, str) and value else None


def _client_name(request: Any, meta: Any) -> str | None:
    """The client name from ``initialize``, else from the request's ``_meta`` clientInfo."""
    params = getattr(getattr(request, "session", None), "client_params", None)
    name = getattr(getattr(params, "client_info", None), "name", None)
    if isinstance(name, str) and name:
        return name
    info = meta.get(_CLIENT_INFO_KEY) if isinstance(meta, dict) else None
    return _meta_text(info, "name")


def caller_identity(context: Context | None) -> tuple[str | None, str | None]:
    """``(client, session)`` from the request context; ``(None, None)`` when there is none."""
    try:
        request = context.request_context if context is not None else None
        meta = getattr(request, "meta", None)
        return _client_name(request, meta), _meta_text(meta, _AGY_SESSION_KEY)
    # Best-effort: logging never breaks a tool call.
    except Exception:  # nosec B110
        return None, None


class EpistemeServer(MCPServer):
    """MCPServer whose tool errors read ``<code>: <what failed>. <what to do>``."""

    activity: Activity | None = None

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context | None = None
    ) -> Any:
        start = time.perf_counter()
        caller = caller_identity(context)
        try:
            result = await super().call_tool(name, arguments, context)
        except ToolError as exc:
            text = _error_text(exc)
            if text is None:
                raise
            self._log(name, arguments, text, start, False, caller)
            return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        text = _result_text(result)
        _track_result(name, arguments, text)
        _track_docs_write(name, text)
        _track_session_save(name, arguments, text)
        self._log(name, arguments, text, start, True, caller)
        return result

    def _log(
        self,
        name: str,
        arguments: Any,
        text: str,
        start: float,
        ok: bool,
        caller: tuple[str | None, str | None] = (None, None),
    ) -> None:
        if self.activity is not None:
            ms = round((time.perf_counter() - start) * 1000)
            client, session = caller
            self.activity.record(name, arguments, text, ms, ok, client=client, session=session)


def build_server(vault: Path, project: str | None = None) -> MCPServer:
    """Create the MCP server for ``vault``; raises StartupError on a bad episteme.toml."""
    engine = Engine(vault, project)
    server = EpistemeServer("episteme", instructions=INSTRUCTIONS)
    server.activity = Activity(engine.vault.root)
    store = maintenance.Store(engine.vault.root)
    reading.register(server, engine)
    memories.register(server, engine)
    hooks.register(server, engine, store)
    docs.register(server, engine)
    session_tool.register(server, engine)
    plans.register(server, engine)
    return server
