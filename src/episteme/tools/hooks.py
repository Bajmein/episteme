"""Hook-facing tools: context, surface and constraints."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Any, NamedTuple

from mcp.server.mcpserver import MCPServer
from pydantic import Field

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

_ModeArg = Annotated[str, Field(description='"welcome" (session start) or "task" (needs task).')]
_WelcomeSessionArg = Annotated[
    str | None,
    Field(description="welcome: session id; the welcome is sent once per session."),
]
_TaskArg = Annotated[
    str | None, Field(description="task: what you are about to do, in a few words.")
]
_PromptArg = Annotated[
    str | None,
    Field(
        description="welcome, from the UserPromptSubmit hook: the user's message "
        "(${prompt}); adds up to 5 memories that match its rare words."
    ),
]
_BudgetArg = Annotated[
    int, Field(description="task: size of the context pack (1 token ~ 4 chars).")
]
_SourceArg = Annotated[
    str | None,
    Field(description="Only for the SessionStart hook: ${source} (compact or clear)."),
]
_LimitArg = Annotated[int, Field(description="Maximum memories, 1-50.")]
_SurfaceSessionArg = Annotated[
    str | None,
    Field(
        description="Hooks pass ${session_id}: a memory already shown by surface in"
        " this session is not repeated."
    ),
]


def register(server: MCPServer, engine: Engine, store: maintenance.Store) -> None:
    """Register the hook-facing tools on ``server``."""
    _register_context(server, engine, store)
    _register_surface(server, engine)
    _register_constraints(server, engine)


def _register_context(server: MCPServer, engine: Engine, store: maintenance.Store) -> None:
    """Register the context tool on ``server``."""

    @server.tool(structured_output=False)
    def context(
        mode: _ModeArg = "welcome",
        session: _WelcomeSessionArg = None,
        project: ProjectArg = None,
        task: _TaskArg = None,
        prompt: _PromptArg = None,
        budget_tokens: _BudgetArg = 2000,
        hook_event: HookEvent = None,
        source: _SourceArg = None,
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
        constraints on files always enter), up to 3 memories one link (any kind) from them, and up
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
                call = _Call(engine, store, session, project, hook_event)
                return _welcome(call, prompt, source)
            if mode == "task":
                return _task(engine, _TaskArgs(task, project, budget_tokens, hook_event))
            raise invalid(f'mode must be "welcome" or "task", got "{mode}".')


def _register_surface(server: MCPServer, engine: Engine) -> None:
    """Register the surface tool on ``server``."""

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def surface(
        file: FileArg = "",
        project_dir: ProjectDir = None,
        project: ProjectArg = None,
        relative_path: RelativePathArg = None,
        limit: _LimitArg = 5,
        hook_event: HookEvent = None,
        session: _SurfaceSessionArg = None,
    ) -> str:
        """Memories (not constraints) about a file: listed in its files, or mentioned in the body.

        Returns JSON {"file", "memories": [{"path", "title", "type", "priority", "match"}]}.
        """
        hookmode.check(hook_event)
        st, skip = _surface_skip(session, hook_event)
        with engine.session():
            text, data = memory.surface(
                engine, file, project_dir, project, limit, relative_path, skip
            )
        _track_surfaced(st, data, hook_event)
        return _reply(hook_event, text, data)


def _register_constraints(server: MCPServer, engine: Engine) -> None:
    """Register the constraints tool on ``server``."""

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
        return _reply(hook_event, text, data)


def _reply(hook_event: str | None, text: str, data: Any, notice: str = "") -> str:
    """Render for a hook when hook_event is set, else dump the JSON data."""
    if hook_event:
        return hookmode.render(hook_event, text, notice)
    return dump(data)


def _surface_skip(
    session: str | None, hook_event: str | None
) -> tuple[prompting.SessionState | None, set[str] | None]:
    """Return the session state and the paths surface must not repeat."""
    st = prompting.state(session) if session else None
    skip = st.surfaced if st is not None and hook_event else None
    return st, skip


def _track_surfaced(
    st: prompting.SessionState | None, data: dict[str, Any], hook_event: str | None
) -> None:
    """Record the memories surface returned in the session state."""
    if st is None:
        return
    paths = [m["path"] for m in data["memories"]]
    st.delivered.update(paths)
    if hook_event:
        st.surfaced.update(paths)


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


class _Turn(NamedTuple):
    """Where a context call falls in its session."""

    state: prompting.SessionState
    welcomed: bool
    resend: bool
    note: str


@dataclass(frozen=True)
class _Call:
    """Arguments of a context call shared by its helpers."""

    engine: Engine
    store: maintenance.Store
    session: str | None
    project: str | None
    hook_event: str | None


@dataclass(frozen=True)
class _TaskArgs:
    """Arguments of a context call in task mode."""

    task: str | None
    project: str | None
    budget_tokens: int
    hook_event: str | None


def _turn(call: _Call, project: str) -> _Turn:
    """Advance the session counters and say whether this call carries the welcome."""
    engine, session, hook_event = call.engine, call.session, call.hook_event
    if not session:
        return _Turn(prompting.SessionState(), welcomed=True, resend=False, note="")
    resend = hook_event == "SessionStart"
    fresh = engine.index.mark_welcomed(session)
    st = prompting.reset(session) if resend else prompting.state(session)
    if st.baseline is None:
        st.baseline = prompting.WRITES
    if not resend:
        st.prompts += 1
    prompting.sync_state_saves(st)
    welcomed = fresh or resend
    if welcomed:
        st.reminded_at = st.prompts
    note = _maintenance_note(engine, call.store, project) if fresh else ""
    return _Turn(st, welcomed, resend, note)


def _welcome(call: _Call, prompt: str | None, source: str | None) -> str:
    """Build the session welcome: norms, reminders, recalled memories and the trail.

    Call it inside engine.session().
    """
    engine, hook_event = call.engine, call.hook_event
    project = engine.need_project(call.project)
    call = replace(call, project=project)
    turn = _turn(call, project)
    st, welcomed, resend = turn.state, turn.welcomed, turn.resend
    out = _Blocks()
    if welcomed:
        _head_block(engine, project, turn, out)
    elif st.prompts - st.reminded_at >= prompting.REMIND_EVERY:
        out.add(*prompting.overdue_block(engine, project), st)
        st.reminded_at = st.prompts
    if prompt:
        out.add(*prompting.recall(engine, prompt, project, st, out.paths()))
    if not welcomed:
        out.blocks.append(prompting.nudge(st))
        every = engine.vault.config.session.nudge_every
        out.blocks.append(prompting.state_nudge(st, every))
    notice = _trail_block(engine, st, out, source) if resend else ""
    text = "\n\n".join(b for b in out.blocks if b)
    if hook_event:
        return hookmode.render(hook_event, text, notice)
    return dump({"text": text, "entries": out.entries, "already_sent": not welcomed})


class _Blocks:
    """Text blocks of a welcome and the entries they list."""

    def __init__(self) -> None:
        self.blocks: list[str] = []
        self.entries: list[dict[str, Any]] = []

    def add(
        self, text: str, found: list[dict[str, Any]], st: prompting.SessionState | None = None
    ) -> None:
        """Append a block and its entries; mark them delivered when st is given."""
        self.blocks.append(text)
        self.entries += found
        if st is not None:
            st.delivered.update(e["path"] for e in found)

    def paths(self) -> set[str]:
        """Paths of the entries listed so far."""
        return {e["path"] for e in self.entries}


def _head_block(engine: Engine, project: str, turn: _Turn, out: _Blocks) -> None:
    """Add the welcome proper, then the maintenance note."""
    out.add(*memory.welcome(engine, project), turn.state)
    if turn.note:
        out.blocks.append(turn.note)


def _trail_block(
    engine: Engine, st: prompting.SessionState, out: _Blocks, source: str | None
) -> str:
    """Add the trail of a resent welcome and return the recovered notice."""
    listed = len(out.entries)
    text, found = prompting.trail_block(engine, out.paths())
    out.add(text, found, st)
    return prompting.recovered_notice(source, listed, len(found))


def _task(engine: Engine, args: _TaskArgs) -> str:
    """Build the context pack for a task. Call it inside engine.session()."""
    if not args.task or not args.task.strip():
        raise invalid('mode "task" needs task.')
    text, entries = memory.task_context(engine, args.task, args.project, args.budget_tokens)
    if args.hook_event:
        return hookmode.render(args.hook_event, text)
    return dump({"text": text, "entries": entries})
