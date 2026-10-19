"""MCP server: tools, annotations and instructions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

from episteme_mcp.engine import Engine
from episteme_mcp.errors import INVALID_ARGUMENT, EpistemeError

INSTRUCTIONS = """\
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- At the start of a task, call context(mode="task", task="<what you are about to do>") to load relevant decisions, constraints and lessons.
- Before deciding something that may already have been decided, call search, then read the best hit.
- When you close a decision, learn a lesson, hit an error worth remembering, or the user says "remember", call remember. Name the files, tools or commands involved in the body: that is what is searched later.
- When a memory is wrong or replaced, call revise (action="supersede" or "archive"), never remember a contradiction next to it.
- Notes under read-only zones (docs/claude-code) cannot be changed. Errors say what failed and what to do."""  # noqa: E501

READ_ONLY = ToolAnnotations(read_only_hint=True)

NoteArg = Annotated[
    str,
    Field(description="Vault-relative path (with or without .md) or a note name / alias."),
]


def dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "arguments"
        parts.append(f"{loc}: {err['msg']}")
    return (
        f"{INVALID_ARGUMENT}: {'; '.join(parts)}. "
        "Check the parameter names and types in the tool schema."
    )


class EpistemeServer(MCPServer):
    """MCPServer whose tool errors read ``<code>: <what failed>. <what to do>``."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context | None = None
    ) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, EpistemeError):
                text = str(cause)
            elif isinstance(cause, ValidationError):
                text = _validation_message(cause)
            else:
                raise
            return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


def build_server(vault: Path, project: str | None = None) -> MCPServer:
    """Create the MCP server for ``vault``; raises StartupError on a bad episteme.toml."""
    engine = Engine(vault, project)
    server = EpistemeServer("episteme", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def search(
        query: Annotated[
            str,
            Field(
                description='Words that must all appear (AND); "quoted text" is a phrase. '
                "Case and accents are ignored."
            ),
        ],
        path: Annotated[
            str | None, Field(description="Path prefix, e.g. docs/claude-code.")
        ] = None,
        type: Annotated[
            str | None, Field(description="Frontmatter type, e.g. decision or reference.")
        ] = None,
        tags: Annotated[
            list[str] | None, Field(description="Tags the note must all have.")
        ] = None,
        project: Annotated[str | None, Field(description="Frontmatter project.")] = None,
        status: Annotated[
            str | None,
            Field(
                description="Frontmatter status. By default superseded and archived memories "
                'are left out; "any" disables the filter.'
            ),
        ] = None,
        limit: Annotated[int, Field(description="1-100.")] = 20,
    ) -> str:
        """Full-text search over the vault (notes and memories), best matches first.

        Returns JSON {"results": [{"path", "title", "line", "snippet", "score"}], "total"}.
        `line` is the 1-based line of the first match; open it with read(path, lines=...).
        """
        with engine.session():
            return dump(engine.search(query, path, type, tags, project, status, limit))

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def read(
        note: NoteArg,
        heading: Annotated[
            str | None, Field(description="Return only this section (case-insensitive).")
        ] = None,
        lines: Annotated[
            str | None, Field(description='1-based inclusive line range of the file, "10-40".')
        ] = None,
    ) -> str:
        """Read a note: frontmatter, outline and body (or one section / line range).

        The whole body is cut at 20,000 characters (truncated: true); then use heading or lines.
        Returns JSON {"path", "frontmatter", "fm_valid", "outline", "content", "truncated",
        "total_lines"}.
        """
        with engine.session():
            return dump(engine.read(note, heading, lines))

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def links(
        note: NoteArg,
        direction: Annotated[str, Field(description='"out", "in" or "both".')] = "both",
        depth: Annotated[
            int, Field(description="1-3; above 1 also lists notes reachable via outgoing links.")
        ] = 1,
    ) -> str:
        """Outgoing links, backlinks and (depth > 1) reachable notes of a note.

        Property links (supersedes, related, up…) carry their key as kind; body links are
        "body". Unresolved links have path null and resolved false.
        """
        with engine.session():
            return dump(engine.links(note, direction, depth))

    return server
