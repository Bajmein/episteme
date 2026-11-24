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

from episteme import __version__, hookmode, maintenance, prompting
from episteme import session as sessions
from episteme.activity import Activity
from episteme.engine import Engine
from episteme.errors import INVALID_ARGUMENT, EpistemeError
from episteme.tools import docs, hooks, memories, plans, reading
from episteme.tools import session as session_tool
from episteme.tools.args import CLIENT

INSTRUCTIONS = """\
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- Look before you answer or act. When you start work, call context(mode="task", task="<what you are about to do>"). When the user asks what is known about a person, client, decision or past event, call search, even without a mention of the vault; then read the best hits in one call with read(notes=[...]).
- search is literal: whole words only. To look up several names, or a word with its plural, abbreviation and proper name (mkt marketing, a surname), put them in one query with match="any" instead of one search per word; add zone="memory" when you want memories, not documentation. tags follow a topic across projects; project is optional.
- Before deciding something that may already have been decided, call search, then read the best hit. Follow links with read(note, links="out"|"in"|"both").
- Save without being asked, with remember, when: a decision is closed; a plan is agreed; the user corrects something you said; you learn a lesson or hit an error worth remembering; you had to get a fact elsewhere because the vault lacked it; or the user says "remember". Name the files, tools, commands and people in the body: it is searched later. Pass description="<one line>", link=true. Save project knowledge with remember, not in the agent's own memory (MEMORY.md, or rule files such as AGENTS.md or GEMINI.md).
- When a memory is wrong or replaced, call revise (action="supersede" or "archive"), never remember a contradiction next to it.
- Keep the session state current with session(action="save"), following its template: when a plan is agreed, a phase ends, the approach changes, before a risky step, and when the user asks. If a hook asks you to launch the episteme:extractor agent, launch it in the background.
- Read-only zones (docs/claude-code) cannot be changed. Errors say what to do."""  # noqa: E501

# Tools of earlier versions that were folded into others; calling one answers with its replacement.
REMOVED_TOOLS = {
    "surface": 'context(mode="surface")',
    "constraints": 'context(mode="constraints")',
    "links": "read(note, links=...)",
    "docs_status": 'docs(action="status")',
    "docs_write": 'docs(action="write")',
}

DOCS_INSTRUCTIONS = "\n- docs/ suites change only via /episteme-docs:docs."


def _removed_error(name: str) -> str:
    """The ``not_found`` message for a tool that was removed, naming its replacement."""
    return (
        f'not_found: tool "{name}" was removed. Use {REMOVED_TOOLS[name]} instead, '
        "and re-run /episteme:setup to update hooks and permissions."
    )


def _removed_hook_text(name: str) -> str:
    """The hook-mode notice for a removed tool: it says what replaces it and never blocks."""
    return (
        f'The episteme tool "{name}" no longer exists: use {REMOVED_TOOLS[name]} instead. '
        "Re-run /episteme:setup to update this project's hooks and permissions."
    )


def _removed_result(name: str, arguments: dict[str, Any]) -> tuple[CallToolResult, str, bool]:
    """``(result, text, ok)`` for a call to a removed tool; nothing is executed."""
    event = arguments.get("hook_event")
    if isinstance(event, str):
        try:
            text = hookmode.render(event, _removed_hook_text(name))
        except EpistemeError:
            text = None
        if text is not None:
            return CallToolResult(content=[TextContent(type="text", text=text)]), text, True
    text = _removed_error(name)
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True), text, False


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
    """Whether a ``docs`` write result wrote the note (changed: false wrote nothing)."""
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


def _is_docs_write(name: str, arguments: dict[str, Any]) -> bool:
    """Whether the call is ``docs`` with action ``write``."""
    return name == "docs" and arguments.get("action") == "write"


def _track_docs_write(name: str, arguments: dict[str, Any], text: str) -> None:
    """A ``docs`` write that changed a note joins the trail; it is not a memory write."""
    if not _is_docs_write(name, arguments):
        return
    if _changed(text):
        _track_paths(text, "written")


def _track_session_save(name: str, arguments: dict[str, Any], text: str) -> None:
    """A ``session`` save joins the trail as written and counts in ``STATE_SAVES`` when the
    agent made it; it is not a memory write."""
    if name == "session" and arguments.get("action") == "save":
        if "hook_event" not in arguments:
            prompting.STATE_SAVES += 1
        for path in _result_paths(text):
            prompting.track(path, "written")


def _track_paths(text: str, how: str) -> None:
    """Add the note paths of a tool result to the trail as ``how`` (written or read)."""
    for path in _result_paths(text):
        prompting.track(path, how)


def _is_agent_memory_write(name: str, arguments: dict[str, Any], text: str) -> bool:
    """Whether the agent (not a hook) wrote a memory with ``remember`` or ``revise``."""
    if name not in ("remember", "revise") or "hook_event" in arguments:
        return False
    return name == "revise" or _created(text)


def _track_result(name: str, arguments: dict[str, Any], text: str) -> None:
    """Count writes and track the notes written or read by a successful tool call."""
    if name == "read":
        _track_paths(text, "read")
    elif _is_agent_memory_write(name, arguments, text):
        prompting.WRITES += 1
        _track_paths(text, "written")


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
        if name in REMOVED_TOOLS:
            removed, text, ok = _removed_result(name, arguments)
            self._log(name, arguments, text, start, ok, caller)
            return removed
        try:
            token = CLIENT.set(caller[0])
            try:
                result = await super().call_tool(name, arguments, context)
            finally:
                CLIENT.reset(token)
        except ToolError as exc:
            text = _error_text(exc)
            if text is None:
                raise
            self._log(name, arguments, text, start, False, caller)
            return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        text = _result_text(result)
        _track_result(name, arguments, text)
        _track_docs_write(name, arguments, text)
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
            # Agent calls carry no session id; the one the hooks of this process passed is it.
            session = session or sessions.IDS.get("session")
            self.activity.record(name, arguments, text, ms, ok, client=client, session=session)


def build_server(vault: Path, project: str | None = None) -> MCPServer:
    """Create the MCP server for ``vault``; raises StartupError on a bad episteme.toml."""
    engine = Engine(vault, project)
    has_docs = bool(engine.vault.docs_zones)
    instructions = INSTRUCTIONS + DOCS_INSTRUCTIONS if has_docs else INSTRUCTIONS
    server = EpistemeServer("episteme", instructions=instructions, version=__version__)
    server.activity = Activity(engine.vault.root)
    store = maintenance.Store(engine.vault.root)
    reading.register(server, engine)
    memories.register(server, engine)
    hooks.register(server, engine, store)
    if has_docs:
        docs.register(server, engine)
    session_tool.register(server, engine)
    plans.register(server, engine)
    return server
