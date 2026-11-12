"""MCP server: tools, annotations and instructions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

from episteme import checkpoint as checkpoints
from episteme import hookmode, memory
from episteme.activity import Activity
from episteme.engine import Engine
from episteme.errors import INVALID_ARGUMENT, EpistemeError, invalid

INSTRUCTIONS = """\
episteme is the project memory and documentation vault. Use only these tools; never read or edit the vault with Bash, Read, Edit or Write.
- Look before you answer or act. When you start work, call context(mode="task", task="<what you are about to do>"). When the user asks what is known about a person, a client, a decision or a past event, call search, even if they did not mention the vault; then read the best hits.
- search is literal: it matches whole words. If it finds little, try the plural, the abbreviation and the proper name (mkt and marketing, a surname) before concluding nothing is stored. tags follow a topic across projects; project is optional.
- Before deciding something that may already have been decided, call search, then read the best hit.
- Save without being asked, with remember, when: a decision is closed; a plan is agreed; the user corrects something you said; you learn a lesson or hit an error worth remembering; you had to get a fact from another source because the vault did not have it; or the user says "remember". Name the files, tools, commands and people involved in the body: that is what is searched later.
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
    str,
    Field(
        description="File being edited: absolute or relative to the project. "
        "Empty (with no relative_path) returns an empty result."
    ),
]
RelativePathArg = Annotated[
    str | None,
    Field(description="Serena edits pass relative_path instead of file; used when file is empty."),
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

    activity: Activity | None = None

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context | None = None
    ) -> Any:
        start = time.perf_counter()
        try:
            result = await super().call_tool(name, arguments, context)
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, EpistemeError):
                text = str(cause)
            elif isinstance(cause, ValidationError):
                text = _validation_message(cause)
            else:
                raise
            self._log(name, arguments, text, start, False)
            return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
        text = "".join(getattr(b, "text", "") for b in getattr(result, "content", None) or [])
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

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def search(
        query: Annotated[
            str | None,
            Field(
                description='Words that must all appear (AND; any of them with match="any"); '
                '"quoted text" is a phrase; '
                "`a-b` is the words a and b; `word*` matches any word starting with it. "
                "Case and accents are ignored. "
                "Optional when tags, type, project, zone or facets is given."
            ),
        ] = None,
        path: Annotated[
            str | None, Field(description="Path prefix, e.g. docs/claude-code.")
        ] = None,
        type: Annotated[
            str | None,
            Field(
                description="Frontmatter type. Memories: decision, lesson, error, constraint, "
                "preference, session, reminder, insight. Documentation uses others, "
                "e.g. reference."
            ),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(
                description="Tags the note must all have; `dominio:x` is read as `dominio/x`. "
                "Tags span projects: use them without project to follow a topic across projects."
            ),
        ] = None,
        project: Annotated[
            str | None,
            Field(description='Frontmatter project; "_shared" memories are included. Optional.'),
        ] = None,
        status: Annotated[
            str | None,
            Field(
                description="active, speculative, superseded or archived. Default: everything "
                "except superseded and archived memories; \"any\" includes them "
                "(rows then carry status and superseded_by)."
            ),
        ] = None,
        limit: Annotated[int, Field(description="1-100.")] = 20,
        zone: Annotated[
            str | None,
            Field(
                description="Only notes of this zone, as in episteme.toml, "
                'e.g. "memory" (memories) or "docs/claude-code".'
            ),
        ] = None,
        facets: Annotated[
            bool,
            Field(
                description="Also return counts by zone, project, type, status and tag; "
                "alone, it lists what the vault has."
            ),
        ] = False,
        match: Annotated[
            str,
            Field(
                description='"all" (default): every word must appear. "any": notes with any of '
                'the words, best first, each row listing the ones it has in "matched". Use "any" '
                "to look up several names or variants of a word in one call."
            ),
        ] = "all",
    ) -> str:
        """Full-text search over the vault (notes and memories), best matches first.

        With no query, lists the notes matching the filters. If no note has all the words,
        retries with any of them ("match": "or", "note"); with 1-2 hits and 2+ words,
        "partial" lists up to 5 more notes with some of the words.
        With match="any" or after that retry, each row carries "matched": the words it has.
        Returns JSON {"results": [{"path", "title", "line", "snippet", "score", and when set
        "zone", "type", "status", "project", "created", "priority", "heading",
        "superseded_by"}], "total"}. `line` is the 1-based line of the first match; open it
        with read(path, lines=...). With no results, "hints" says which filter matches nothing.
        facets=true adds "facets": counts by zone, project, type, status and tags.
        """
        with engine.session():
            return dump(
                engine.search(
                    query, path, type, tags, project, status, limit, zone, facets, match
                )
            )

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def read(
        note: Annotated[
            str | None,
            Field(
                description="Vault-relative path (with or without .md) or a note name / alias. "
                "For several notes use notes."
            ),
        ] = None,
        heading: Annotated[
            str | None, Field(description="Return only this section (case-insensitive).")
        ] = None,
        lines: Annotated[
            str | None, Field(description='1-based inclusive line range of the file, "10-40".')
        ] = None,
        outline: Annotated[
            bool | None,
            Field(
                description="Include the heading outline. "
                "Default: only when reading the whole note."
            ),
        ] = None,
        content: Annotated[
            bool,
            Field(
                description="false returns only frontmatter and outline (each heading with its "
                "line and end), to pick a section before reading."
            ),
        ] = True,
        notes: Annotated[
            list[str] | None,
            Field(
                description="Several notes to read whole in one call (up to 20), instead of "
                "note. heading and lines do not apply."
            ),
        ] = None,
    ) -> str:
        """Read a note: frontmatter, outline and body (or one section / line range).

        The whole body is cut at 20,000 characters (truncated: true); then use heading or lines.
        The outline (each heading with "line" and "end") comes only with the whole note, or
        always with outline=true; content=false returns just frontmatter and outline.
        Returns JSON {"path", "frontmatter", "fm_valid", "outline" (when included), "content",
        "truncated", "total_lines", "range" (with heading or lines: "first-last" file lines)}.
        With notes, returns JSON {"notes": [one object per note as above, without outline
        unless outline=true; a note that fails is {"note", "error"}], "pending": [notes left
        out once the output passes 50,000 characters; call read again with them]}.
        """
        with engine.session():
            if notes is not None:
                if note is not None:
                    raise invalid("pass note or notes, not both.")
                return dump(engine.read_many(notes, heading, lines, outline, content))
            if note is None:
                raise invalid("pass note (one note) or notes (several).")
            return dump(engine.read(note, heading, lines, outline, content))

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
        title: Annotated[
            str, Field(description="Short title (5-8 words); the file name is derived from it.")
        ],
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
            list[str],
            Field(
                description='Nested with "/", e.g. dominio/auth; no ":". Use persona/<surname> '
                "for people and tema/<topic> for a subject that spans projects."
            ),
        ] = [],  # noqa: B006
        keywords: Annotated[
            list[str],
            Field(
                description="Other words people use for this: synonyms, abbreviations, full "
                'names (mkt, marketing, "Ana Pérez"). Searched with the weight of the '
                "title."
            ),
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
        slug: Annotated[
            str | None,
            Field(
                description="File-name slug: 1-40 lowercase letters, digits and hyphens, without "
                "the date. Derived from the title when omitted."
            ),
        ] = None,
    ) -> str:
        """Store a memory as memory/<project>/<type folder>/YYYY-MM-DD-<slug>.md.

        The date is local. The slug is the title cut to its first 3-5 useful words (no stopwords,
        nothing already in the path, at most 40 characters) unless you pass slug; the full title
        stays in the H1. A name that already exists gets -2, -3...

        Validates the schema and looks for near-duplicates of the same project and type: at
        similarity >= 0.8 nothing is created (created: false) unless force=true. `similar` also
        lists active memories of any type in the project or _shared (they only warn).
        Returns JSON {"created", "path", "similar": [{"path", "title", "similarity", "type",
        "project"}], "new_tags": [{"tag", "similar"}] (tags no other note has, with close
        spellings), "link_candidates": [{"path", "title", "reason"}] (up to 5 memories sharing
        a file or 2 tags; consider related)}. The last two appear only when non-empty.
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
                    slug=slug,
                    keywords=keywords,
                )
            )

    @server.tool(structured_output=False)
    def revise(
        note: NoteArg,
        action: Annotated[
            str,
            Field(
                description="edit (old, new) | append (text, heading?) | set (fields) | "
                "supersede (by) | feedback (value) | archive | dismiss (reminders)"
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

        supersede, feedback, archive and dismiss (archives a reminder) only apply to memories.
        Memories are validated against the schema before anything is written. set on a memory
        that changes type or project moves the file to memory/<project>/<type folder>/ (same
        name, so [[name]] links keep working) and returns the new path with "moved_from".
        Returns JSON {"path", "action", "changed"}.
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
            Field(
                description="Limit memory checks to this project (and _shared). "
                '"*" reviews every project.'
            ),
        ] = None,
        limit: Annotated[int, Field(description="Maximum items per category.")] = 50,
        zone: Annotated[
            str | None,
            Field(description='Only notes of this zone, as in episteme.toml (e.g. "memory").'),
        ] = None,
    ) -> str:
        """Vault health: stale memories, possible contradictions, groups of similar
        memories, cut titles, orphans, broken links, invalid frontmatter and memories
        flagged as outdated.

        Returns JSON {"totals", "stale", "contradictions", "similar", "cut_titles",
        "orphans", "broken_links", "invalid_frontmatter", "flagged", "read_only"}.
        "similar" lists groups {"paths", "similarity"} of active memories (any type or
        project, not session or reminder) to merge; "cut_titles" lists memories whose
        first body line repeats the title and goes on. "totals" counts every item per
        category (the lists are cut at limit). Problems in read-only zones (you cannot fix
        them here; in practice broken links and invalid frontmatter, since memories live in
        memory zones) are not mixed in: they go under "read_only", with the same categories
        and their own "totals".
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
        prompt: Annotated[
            str | None,
            Field(
                description="welcome, from the UserPromptSubmit hook: the user's message "
                "(${prompt}); adds up to 5 memories that match its rare words."
            ),
        ] = None,
        budget_tokens: Annotated[
            int, Field(description="task: size of the context pack (1 token ~ 4 chars).")
        ] = 2000,
        hook_event: HookEvent = None,
    ) -> str:
        """Load project memory: the session welcome, or a context pack for a task.

        welcome: overdue reminders, the active priority-5 norms, reminders due within 7 days,
        then the highest-scoring active memories (at most 3 from _shared); sent once per session
        (not repeated on --resume, whose context already has it; resent on SessionStart
        compact|clear). With session, later calls add: overdue reminders every 10 messages; with
        prompt, up to 5 memories whose title, tags or keywords hold a rare word of the message;
        and a nudge to save when the session has written no memory.
        task: decisions, constraints and lessons matching the task (Spanish and English stopwords
        ignored; with 3+ words a memory must hold 2 of them and score >= 25% of the best hit;
        constraints on files always enter), up to 3 memories linked to them by related, and up
        to 5 related notes to open with read, within budget_tokens.
        Returns JSON {"text", "entries": [{"path", "score", "kind"}]}; score is 0-1, or null for
        norms, reminders, recalled and linked memories (welcome adds "already_sent").
        """
        hookmode.check(hook_event)
        with engine.session():
            if mode == "welcome":
                from episteme import prompting

                project = engine.need_project(project)
                blocks: list[str] = []
                entries: list[dict[str, Any]] = []
                already_sent = False
                welcomed = True
                if session:
                    resend = hook_event == "SessionStart"
                    fresh = engine.index.mark_welcomed(session)
                    st = prompting.reset(session) if resend else prompting.state(session)
                    if resend:
                        memory.surface_forget(session)
                    if st.baseline is None:
                        st.baseline = prompting.stamp(engine, project)
                    if not resend:
                        st.prompts += 1
                    welcomed = fresh or resend
                    if welcomed:
                        st.reminded_at = st.prompts
                    else:
                        already_sent = True
                else:
                    st = prompting.SessionState()
                if welcomed:
                    text, found = memory.welcome(engine, project)
                    blocks.append(text)
                    entries += found
                elif st.prompts - st.reminded_at >= prompting.REMIND_EVERY:
                    text, found = prompting.overdue_block(engine, project)
                    blocks.append(text)
                    entries += found
                    st.reminded_at = st.prompts
                if prompt:
                    text, found = prompting.recall(
                        engine, prompt, project, st, {e["path"] for e in entries}
                    )
                    blocks.append(text)
                    entries += found
                if session and not welcomed:
                    blocks.append(prompting.nudge(engine, project, st))
                text = "\n\n".join(b for b in blocks if b)
                if hook_event:
                    return hookmode.render(hook_event, text)
                return dump({"text": text, "entries": entries, "already_sent": already_sent})
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
        file: FileArg = "",
        project_dir: ProjectDir = None,
        project: ProjectArg = None,
        relative_path: RelativePathArg = None,
        limit: Annotated[int, Field(description="Maximum memories, 1-50.")] = 5,
        hook_event: HookEvent = None,
        session: Annotated[
            str | None,
            Field(
                description="Hooks pass ${session_id}: the same memories about a file are not"
                " repeated within 30 minutes."
            ),
        ] = None,
    ) -> str:
        """Memories (not constraints) about a file: listed in its files, or mentioned in the body.

        Returns JSON {"file", "memories": [{"path", "title", "type", "priority", "match"}]}.
        """
        hookmode.check(hook_event)
        with engine.session():
            text, data = memory.surface(engine, file, project_dir, project, limit, relative_path)
        if hook_event and session and text:
            paths = [m["path"] for m in data["memories"]]
            if memory.surface_repeated(session, data["file"], paths):
                text = ""
        return hookmode.render(hook_event, text) if hook_event else dump(data)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def constraints(
        file: FileArg = "",
        project_dir: ProjectDir = None,
        project: ProjectArg = None,
        relative_path: RelativePathArg = None,
        hook_event: HookEvent = None,
    ) -> str:
        """Active constraints whose files match a file. Warns before editing; never blocks.

        Returns JSON {"file", "constraints": [{"path", "title", "priority", "body"}]}.
        """
        hookmode.check(hook_event)
        with engine.session():
            text, data = memory.constraints(engine, file, project_dir, project, relative_path)
        return hookmode.render(hook_event, text) if hook_event else dump(data)

    @server.tool(structured_output=False)
    def checkpoint(
        action: Annotated[str, Field(description='"save" or "restore".')],
        project_dir: Annotated[
            str | None,
            Field(description="Absolute project directory (hooks pass ${cwd})."),
        ] = None,
        project: ProjectArg = None,
        task_title: Annotated[
            str | None,
            Field(
                description="restore only: resume this task (exact title) instead of the branch's."
            ),
        ] = None,
        hook_event: HookEvent = None,
    ) -> str:
        """Save the active task state (estado.md) as a session memory, or restore the latest.

        save: {"saved", "path", "task_title"}; saved is false when no state is active.
        restore: {"found", "path", "task_title", "content", "source"}. It reads the live active
        estado.md first (the branch's change, else the newest), with a flow line (etapa and
        tasks.md progress); without one it falls back to the saved checkpoint. Saved checkpoints
        of tasks with no active state are archived. Never blocks compaction.
        """
        hookmode.check(hook_event)
        with engine.session():
            if action == "save":
                data = checkpoints.save(engine, project_dir, project)
                text = f"episteme · checkpoint saved: {data['path']}" if data["saved"] else ""
            elif action == "restore":
                data = checkpoints.restore(engine, project, project_dir, task_title)
                text = data["content"]
            else:
                raise invalid(f'action must be "save" or "restore", got "{action}".')
        return hookmode.render(hook_event, text) if hook_event else dump(data)

    return server
