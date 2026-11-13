"""Hook-facing tools: context, surface, constraints and checkpoint."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import checkpoint as checkpoints
from episteme import hookmode, maintenance, memory, prompting
from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import (
    READ_ONLY,
    FileArg,
    HookEvent,
    ProjectArg,
    ProjectDir,
    RelativePathArg,
    dump,
)


def register(server: MCPServer, engine: Engine, store: maintenance.Store) -> None:
    """Register the hook-facing tools on ``server``."""

    @server.tool(structured_output=False)
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
        source: Annotated[
            str | None,
            Field(description="Only for the SessionStart hook: ${source} (compact or clear)."),
        ] = None,
    ) -> str:
        """Load project memory: the session welcome, or a context pack for a task.

        welcome: overdue reminders, the active priority-5 norms, reminders due within 7 days,
        then the highest-scoring active memories (at most 3 from _shared); sent once per session
        (not repeated on --resume, whose context already has it; resent on SessionStart
        compact|clear, followed by up to 8 memories the agent wrote or read before it, kind
        "trail", and with a coloured systemMessage telling the person what was recovered).
        With session, later calls add: overdue reminders every 10 messages; with
        prompt, up to 5 memories whose title, tags or keywords hold a rare word of the message;
        and a nudge to save when the session has written no memory.
        task: decisions, constraints and lessons matching the task (Spanish and English stopwords
        ignored; with 3+ words a memory must hold 2 of them and score >= 25% of the best hit;
        constraints on files always enter), up to 3 memories linked to them by related, and up
        to 5 related notes to open with read, within budget_tokens.
        Returns JSON {"text", "entries": [{"path", "score", "kind"}]}; score is 0-1, or null for
        norms, reminders, recalled and linked memories (welcome adds "already_sent").
        The first welcome of a session may run the maintenance configured in episteme.toml
        (notice of pending review items, archiving of expired memories, vault backup), so
        this tool is not read-only.
        """
        hookmode.check(hook_event)
        with engine.session():
            if mode == "welcome":
                return _welcome(engine, store, session, project, prompt, hook_event, source)
            if mode == "task":
                return _task(engine, task, project, budget_tokens, hook_event)
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
                description="Hooks pass ${session_id}: a memory already shown by surface in"
                " this session is not repeated."
            ),
        ] = None,
    ) -> str:
        """Memories (not constraints) about a file: listed in its files, or mentioned in the body.

        Returns JSON {"file", "memories": [{"path", "title", "type", "priority", "match"}]}.
        """
        hookmode.check(hook_event)
        st = prompting.state(session) if session else None
        skip = st.surfaced if st is not None and hook_event else None
        with engine.session():
            text, data = memory.surface(
                engine, file, project_dir, project, limit, relative_path, skip
            )
        if st is not None:
            paths = [m["path"] for m in data["memories"]]
            st.delivered.update(paths)
            if hook_event:
                st.surfaced.update(paths)
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
        notice = ""
        with engine.session():
            if action == "save":
                data = checkpoints.save(engine, project_dir, project)
                text = f"episteme · checkpoint saved: {data['path']}" if data["saved"] else ""
            elif action == "restore":
                data = checkpoints.restore(engine, project, project_dir, task_title)
                text = data["content"]
                if data["found"]:
                    origin = "estado.md" if data["source"] == "state" else "checkpoint guardado"
                    notice = f"episteme · tarea retomada: «{data['task_title']}» ({origin})"
            else:
                raise invalid(f'action must be "save" or "restore", got "{action}".')
        return hookmode.render(hook_event, text, notice) if hook_event else dump(data)


def _maintenance_note(engine: Engine, store: maintenance.Store, project: str) -> str:
    """Run the configured maintenance of a first welcome and return its notice."""
    try:
        note = maintenance.run(engine, store, project)
    except Exception:
        note = ""
    try:
        maintenance.start_backup(engine.vault, store)
    except Exception:  # nosec B110
        pass
    return note


def _welcome(
    engine: Engine,
    store: maintenance.Store,
    session: str | None,
    project: str | None,
    prompt: str | None,
    hook_event: str | None,
    source: str | None,
) -> str:
    """Build the session welcome: norms, reminders, recalled memories and the trail."""
    project = engine.need_project(project)
    blocks: list[str] = []
    entries: list[dict[str, Any]] = []
    already_sent = False
    welcomed = True
    resend = False
    if session:
        resend = hook_event == "SessionStart"
        fresh = engine.index.mark_welcomed(session)
        st = prompting.reset(session) if resend else prompting.state(session)
        if st.baseline is None:
            st.baseline = prompting.WRITES
        if not resend:
            st.prompts += 1
        welcomed = fresh or resend
        if welcomed:
            st.reminded_at = st.prompts
        else:
            already_sent = True
        note = _maintenance_note(engine, store, project) if fresh else ""
    else:
        st = prompting.SessionState()
        note = ""
    if welcomed:
        text, found = memory.welcome(engine, project)
        blocks.append(text)
        if note:
            blocks.append(note)
        entries += found
        st.delivered.update(e["path"] for e in found)
    elif st.prompts - st.reminded_at >= prompting.REMIND_EVERY:
        text, found = prompting.overdue_block(engine, project)
        blocks.append(text)
        entries += found
        st.delivered.update(e["path"] for e in found)
        st.reminded_at = st.prompts
    if prompt:
        text, found = prompting.recall(
            engine, prompt, project, st, {e["path"] for e in entries}
        )
        blocks.append(text)
        entries += found
    if session and not welcomed:
        blocks.append(prompting.nudge(st))
    notice = ""
    if session and resend:
        listed = len(entries)
        text, found = prompting.trail_block(engine, {e["path"] for e in entries})
        blocks.append(text)
        entries += found
        st.delivered.update(e["path"] for e in found)
        notice = prompting.recovered_notice(source, listed, len(found))
    text = "\n\n".join(b for b in blocks if b)
    if hook_event:
        return hookmode.render(hook_event, text, notice)
    return dump({"text": text, "entries": entries, "already_sent": already_sent})


def _task(
    engine: Engine,
    task: str | None,
    project: str | None,
    budget_tokens: int,
    hook_event: str | None,
) -> str:
    """Build the context pack for a task."""
    if not task or not task.strip():
        raise invalid('mode "task" needs task.')
    text, entries = memory.task_context(engine, task, project, budget_tokens)
    if hook_event:
        return hookmode.render(hook_event, text)
    return dump({"text": text, "entries": entries})
