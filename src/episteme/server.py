"""MCP server: tools, annotations and instructions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

from episteme import checkpoint as checkpoints
from episteme import hookmode, memory
from episteme.engine import Engine
from episteme.errors import INVALID_ARGUMENT, EpistemeError, invalid

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

HookEvent = Annotated[
    str | None,
    Field(description="Only for Claude Code hooks: ${hook_event_name}. Omit otherwise."),
]
ProjectArg = Annotated[str | None, Field(description="Project; defaults to --project.")]
ProjectDir = Annotated[
    str | None,
    Field(description="Absolute project directory (hooks pass ${cwd}); used to relativize file."),
]
FileArg = Annotated[
    str, Field(description="File being edited: absolute or relative to the project.")
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
            str | None,
            Field(
                description='Words that must all appear (AND); "quoted text" is a phrase; '
                "`word*` matches any word starting with it. Case and accents are ignored. "
                "Optional when tags or type is given."
            ),
        ] = None,
        path: Annotated[
            str | None, Field(description="Path prefix, e.g. docs/claude-code.")
        ] = None,
        type: Annotated[
            str | None, Field(description="Frontmatter type, e.g. decision or reference.")
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(description="Tags the note must all have; `dominio:x` is read as `dominio/x`."),
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

        With no query, lists the notes matching tags and/or type. If no note has all the words,
        retries with any of them and says so ("match": "or", "note").
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

    @server.tool(structured_output=False)
    def remember(
        type: Annotated[
            str,
            Field(
                description="decision | lesson | error | constraint | preference | session | "
                "reminder | insight"
            ),
        ],
        title: Annotated[str, Field(description="Short title; also names the file.")],
        body: Annotated[
            str,
            Field(
                description="The memory. Name the files, tools or commands involved: "
                "that is what is searched later."
            ),
        ],
        project: Annotated[
            str | None,
            Field(description='Project; defaults to --project. "_shared" for all projects.'),
        ] = None,
        priority: Annotated[
            int | None,
            Field(
                description="1-5. 5 = rule every session must know; 4 = technical decision "
                "(default for decision/constraint); 3 = record (default); 1-2 = minor."
            ),
        ] = None,
        tags: Annotated[
            list[str], Field(description='Nested with "/", e.g. dominio/auth; no ":".')
        ] = [],  # noqa: B006
        files: Annotated[
            list[str],
            Field(description="Project-relative files this memory is about (globs allowed)."),
        ] = [],  # noqa: B006
        related: Annotated[list[str], Field(description="Related notes (paths or names).")] = [],  # noqa: B006
        supersedes: Annotated[
            str | None, Field(description="Memory this one replaces; it becomes superseded.")
        ] = None,
        source: Annotated[str | None, Field(description="Commit sha or PR.")] = None,
        due: Annotated[str | None, Field(description="YYYY-MM-DD; required for reminders.")] = None,
        valid_until: Annotated[
            str | None, Field(description="YYYY-MM-DD after which the memory no longer holds.")
        ] = None,
        status: Annotated[
            str, Field(description="active | speculative | superseded | archived.")
        ] = "active",
        force: Annotated[
            bool, Field(description="Create it even if a near-duplicate exists.")
        ] = False,
    ) -> str:
        """Store a memory as memory/<project>/<type folder>/YYYY-MM-DD-<slug>.md.

        Validates the schema and looks for near-duplicates of the same project and type: at
        similarity >= 0.8 nothing is created (created: false) unless force=true.
        Returns JSON {"created", "path", "similar": [{"path", "title", "similarity"}]}.
        """
        with engine.session():
            return dump(
                memory.remember(
                    engine,
                    type,
                    title,
                    body,
                    project,
                    priority,
                    tags,
                    files,
                    related,
                    supersedes,
                    source,
                    due,
                    valid_until,
                    status,
                    force,
                )
            )

    @server.tool(structured_output=False)
    def revise(
        note: NoteArg,
        action: Annotated[
            str,
            Field(
                description="edit (old, new) | append (text, heading?) | set (fields) | "
                "supersede (by) | feedback (value) | archive"
            ),
        ],
        old: Annotated[str | None, Field(description="edit: text that appears once.")] = None,
        new: Annotated[str | None, Field(description="edit: replacement text.")] = None,
        text: Annotated[str | None, Field(description="append: text to add.")] = None,
        heading: Annotated[
            str | None, Field(description="append: add at the end of this section.")
        ] = None,
        fields: Annotated[
            dict[str, Any] | None,
            Field(description="set: frontmatter keys to merge; null deletes a key."),
        ] = None,
        by: Annotated[
            str | None, Field(description="supersede: the memory that replaces this one.")
        ] = None,
        value: Annotated[
            str | None, Field(description="feedback: helpful | unhelpful | outdated.")
        ] = None,
    ) -> str:
        """Change a note in a read-write or memory zone. Read-only zones are refused.

        supersede, feedback and archive only apply to memories. Memories are validated against
        the schema before anything is written. Returns JSON {"path", "action", "changed"}.
        """
        with engine.session():
            return dump(
                memory.revise(engine, note, action, old, new, text, heading, fields, by, value)
            )

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def review(
        path: Annotated[str | None, Field(description="Path prefix to limit the review.")] = None,
        project: Annotated[
            str | None,
            Field(description="Limit memory checks to this project (and _shared)."),
        ] = None,
        limit: Annotated[int, Field(description="Maximum items per category.")] = 50,
        zone: Annotated[
            str | None,
            Field(description='Only notes of this zone, as in episteme.toml (e.g. "memory").'),
        ] = None,
    ) -> str:
        """Vault health: stale memories, possible contradictions, orphans, broken links,
        invalid frontmatter and memories flagged as outdated.

        Returns JSON {"totals", "stale", "contradictions", "orphans", "broken_links",
        "invalid_frontmatter", "flagged", "read_only"}. "totals" counts every item per
        category (the lists are cut at limit). Problems in read-only zones (broken links and
        invalid frontmatter you cannot fix here) are not mixed in: they go under "read_only",
        with their own "totals".
        """
        with engine.session():
            return dump(memory.review(engine, path, project, limit, zone))

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def context(
        mode: Annotated[
            str, Field(description='"welcome" (session start) or "task" (needs task).')
        ] = "welcome",
        session: Annotated[
            str | None,
            Field(description="welcome: session id; the welcome is sent once per session."),
        ] = None,
        project: ProjectArg = None,
        task: Annotated[
            str | None, Field(description="task: what you are about to do, in a few words.")
        ] = None,
        budget_tokens: Annotated[
            int, Field(description="task: size of the context pack (1 token ~ 4 chars).")
        ] = 2000,
        hook_event: HookEvent = None,
    ) -> str:
        """Load project memory: the session welcome, or a context pack for a task.

        welcome: overdue reminders, then the highest-scoring active memories.
        task: decisions, constraints and lessons matching the task (Spanish stopwords ignored,
        weak matches dropped), within budget_tokens, plus up to 5 related notes to open with read.
        Returns JSON {"text", "entries": [{"path", "score", "kind"}]} with every score on a 0-1
        scale (welcome adds "already_sent").
        """
        hookmode.check(hook_event)
        with engine.session():
            if mode == "welcome":
                text, entries = memory.welcome(engine, project)
                sent = bool(session) and not engine.index.mark_welcomed(session)
                if sent:
                    text, entries = "", []
                if hook_event:
                    return hookmode.render(hook_event, text)
                return dump({"text": text, "entries": entries, "already_sent": sent})
            if mode == "task":
                if not task or not task.strip():
                    raise invalid('mode "task" needs task.')
                text, entries = memory.task_context(engine, task, project, budget_tokens)
                if hook_event:
                    return hookmode.render(hook_event, text)
                return dump({"text": text, "entries": entries})
            raise invalid(f'mode must be "welcome" or "task", got "{mode}".')

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def surface(
        file: FileArg,
        project_dir: ProjectDir = None,
        project: ProjectArg = None,
        limit: Annotated[int, Field(description="Maximum memories, 1-50.")] = 5,
        hook_event: HookEvent = None,
    ) -> str:
        """Memories (not constraints) about a file: listed in its files, or mentioned in the body.

        Returns JSON {"file", "memories": [{"path", "title", "type", "priority", "match"}]}.
        """
        hookmode.check(hook_event)
        with engine.session():
            text, data = memory.surface(engine, file, project_dir, project, limit)
        return hookmode.render(hook_event, text) if hook_event else dump(data)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def constraints(
        file: FileArg,
        project_dir: ProjectDir = None,
        project: ProjectArg = None,
        hook_event: HookEvent = None,
    ) -> str:
        """Active constraints whose files match a file. Warns before editing; never blocks.

        Returns JSON {"file", "constraints": [{"path", "title", "priority", "body"}]}.
        """
        hookmode.check(hook_event)
        with engine.session():
            text, data = memory.constraints(engine, file, project_dir, project)
        return hookmode.render(hook_event, text) if hook_event else dump(data)

    @server.tool(structured_output=False)
    def checkpoint(
        action: Annotated[str, Field(description='"save" or "restore".')],
        project_dir: Annotated[
            str | None,
            Field(description="Absolute project directory (hooks pass ${cwd})."),
        ] = None,
        project: ProjectArg = None,
        hook_event: HookEvent = None,
    ) -> str:
        """Save the active task state (estado.md) as a session memory, or restore the latest.

        save: {"saved", "path", "task_title"}; saved is false when no state is active.
        restore: {"found", "path", "task_title", "content"}. Never blocks compaction.
        """
        hookmode.check(hook_event)
        with engine.session():
            if action == "save":
                data = checkpoints.save(engine, project_dir, project)
                text = f"episteme · checkpoint saved: {data['path']}" if data["saved"] else ""
            elif action == "restore":
                data = checkpoints.restore(engine, project)
                text = data["content"]
            else:
                raise invalid(f'action must be "save" or "restore", got "{action}".')
        return hookmode.render(hook_event, text) if hook_event else dump(data)

    return server
