"""MCP server: tools, annotations and instructions."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from episteme_mcp.vault import Vault

INSTRUCTIONS = """\
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- At the start of a task, call context(mode="task", task="<what you are about to do>") to load relevant decisions, constraints and lessons.
- Before deciding something that may already have been decided, call search, then read the best hit.
- When you close a decision, learn a lesson, hit an error worth remembering, or the user says "remember", call remember. Name the files, tools or commands involved in the body: that is what is searched later.
- When a memory is wrong or replaced, call revise (action="supersede" or "archive"), never remember a contradiction next to it.
- Notes under read-only zones (docs/claude-code) cannot be changed. Errors say what failed and what to do."""  # noqa: E501


def build_server(vault: Path, project: str | None = None) -> MCPServer:
    """Create the MCP server for ``vault``; raises StartupError on a bad episteme.toml."""
    Vault(vault)
    return MCPServer("episteme", instructions=INSTRUCTIONS)
