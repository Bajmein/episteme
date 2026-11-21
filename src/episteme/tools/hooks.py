"""Hook-facing tool: context (welcome, task, surface and constraints modes)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Annotated, Any, NamedTuple

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import hookmode, maintenance, memory, prompting
from episteme import session as sessions
from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import (
    FileArg,
    HookEvent,
    ProjectArg,
    RelativePathArg,
    dump,
)

_ModeArg = Annotated[
    str,
    Field(
        description='"welcome" (session start), "task" (needs task), "surface" or '
        '"constraints" (both need file or relative_path).'
    ),
]
_WelcomeSessionArg = Annotated[
    str | None,
    Field(
        description="welcome: session id; the welcome is sent once per session. surface:"
        " a memory already delivered in this session is not repeated."
    ),
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
_WelcomeDirArg = Annotated[
    str | None,
    Field(
        description="Absolute project directory (hooks pass ${cwd}): welcome picks the "
        "worktree whose session state a new session is told about; surface and "
        "constraints resolve a relative file against it."
    ),
]
_TranscriptArg = Annotated[
    str | None,
    Field(description="Only for hooks: ${transcript_path}, kept with the session state."),
]
_LimitArg = Annotated[int, Field(description="surface: maximum memories, 1-50.")]
SURFACE_LIMIT = 3  # surface: default number of memories per file


def register(server: MCPServer, engine: Engine, store: maintenance.Store) -> None:
    """Register the hook-facing tools on ``server``."""
    _register_context(server, engine, store)


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
        project_dir: _WelcomeDirArg = None,
        transcript: _TranscriptArg = None,
        file: FileArg = "",
        relative_path: RelativePathArg = None,
        limit: _LimitArg = SURFACE_LIMIT,
    ) -> str:
        """Load project memory: the session welcome, a context pack for a task, or what a file has.

        welcome: overdue reminders, the active priority-5 norms, reminders due within 7 days,
        then the 8 highest-scoring active memories (at most 1 from _shared); sent once per
        session (not repeated on --resume, whose context already has it; resent on SessionStart
        compact|clear, only overdue reminders and norms after compact, followed by up to 8
        memories the agent wrote or read before it, kind "trail", and with a coloured
        systemMessage telling the person what was recovered).
        The first welcome of a session also names, in one line, the newest active session
        state a previous session left in the worktree of project_dir, without loading it.
        With session, later calls add: overdue reminders every 10 messages; with
        prompt, up to 5 memories whose title, tags or keywords hold a rare word of the message;
        and a nudge to save when the session has written no memory.
        task: decisions, constraints and lessons matching the task (Spanish and English stopwords
        ignored; with 3+ words a memory must hold 2 of them and score >= 25% of the best hit;
        constraints on files always enter; norms this session already got are left out), up to
        3 memories one link (any kind) from them, and up to 5 related notes to open with read,
        within budget_tokens.
        Returns JSON {"text", "entries": [{"path", "score", "kind"}]}; score is 0-1, or null for
        norms, reminders, recalled and linked memories (welcome adds "already_sent").
        surface: memories (not constraints) about a file (file or relative_path, plus project_dir),
        listed in its files or mentioned in the body; a match by mention needs priority >= 4 and
        at most 2 come in one answer; with a hook_event and a session, memories this session
        already got are left out; limit caps them. Returns JSON {"file", "memories": [{"path",
        "title", "type", "priority", "match"}]}.
        constraints: active constraints whose files match the file; warns before editing, never
        blocks. Returns JSON {"file", "constraints": [{"path", "title", "priority", "body"}]}.
        The first welcome of a session may run the maintenance configured in episteme.toml
        (notice of pending review items, archiving of expired memories, vault backup), so
        this tool is not read-only.
        """
        hookmode.check(hook_event)
        sessions.track_ids(hook_event, session, transcript, project_dir)
        with engine.session():
            if mode == "welcome":
                call = _Call(engine, store, session, project, hook_event, project_dir)
                return _welcome(call, prompt, source)
            if mode == "task":
                return _task(engine, _TaskArgs(task, project, budget_tokens, hook_event))
            if mode in _FILE_MODES:
                where = _FileArgs(
                    file, relative_path, project_dir, project, hook_event, session, limit
                )
                return _FILE_MODES[mode](engine, where)
            raise invalid(
                f'mode must be "welcome", "task", "surface" or "constraints", got "{mode}".'
            )


def _reply(hook_event: str | None, text: str, data: Any, notice: str = "") -> str:
    """Render for a hook when hook_event is set, else dump the JSON data."""
    if hook_event:
        return hookmode.render(hook_event, text, notice)
    return dump(data)


@dataclass(frozen=True)
class _FileArgs:
    """Arguments of a context call in surface or constraints mode."""

    file: str
    relative_path: str | None
    project_dir: str | None
    project: str | None
    hook_event: str | None
    session: str | None = None
    limit: int = SURFACE_LIMIT


def _surface(engine: Engine, args: _FileArgs) -> str:
    """Surface mode: memories about a file. Call it inside engine.session()."""
    if not _need_file(args, "surface"):
        return ""
    st, skip = _surface_skip(args.session, args.hook_event)
    text, data = memory.surface(
        engine, args.file, args.project_dir, args.project, args.limit, args.relative_path, skip
    )
    _track_surfaced(st, data)
    return _reply(args.hook_event, text, data)


def _constraints(engine: Engine, args: _FileArgs) -> str:
    """Constraints mode: active constraints matching a file. Call it inside engine.session()."""
    if not _need_file(args, "constraints"):
        return ""
    text, data = memory.constraints(
        engine, args.file, args.project_dir, args.project, args.relative_path
    )
    return _reply(args.hook_event, text, data)


_FILE_MODES = {"surface": _surface, "constraints": _constraints}


def _need_file(args: _FileArgs, mode: str) -> bool:
    """Say whether a file mode has a file to work on.

    Raises ``invalid`` for an agent call without file or relative_path; a hook call
    (Serena tools that carry no path) just answers empty, so a hook never fails.
    """
    if args.file or args.relative_path:
        return True
    if args.hook_event:
        return False
    raise invalid(f'mode "{mode}" needs file or relative_path.')


def _surface_skip(
    session: str | None, hook_event: str | None
) -> tuple[prompting.SessionState | None, set[str] | None]:
    """Return the session state and the paths surface must not repeat."""
    st = prompting.state(session) if session else None
    skip = st.delivered if st is not None and hook_event else None
    return st, skip


def _track_surfaced(st: prompting.SessionState | None, data: dict[str, Any]) -> None:
    """Record the memories surface returned as delivered to the session."""
    if st is not None:
        st.delivered.update(m["path"] for m in data["memories"])


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
    fresh: bool = False


@dataclass(frozen=True)
class _Call:
    """Arguments of a context call shared by its helpers."""

    engine: Engine
    store: maintenance.Store
    session: str | None
    project: str | None
    hook_event: str | None
    project_dir: str | None = None


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
        return _Turn(prompting.SessionState(), welcomed=True, resend=False, note="", fresh=False)
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
    return _Turn(st, welcomed, resend, note, fresh)


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
        _head_block(engine, project, turn, out, brief=resend and source == "compact")
        if turn.fresh and not resend:
            out.blocks.append(_previous_state_line(engine, project, call))
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


def _head_block(engine: Engine, project: str, turn: _Turn, out: _Blocks, brief: bool) -> None:
    """Add the welcome (``brief``: overdue reminders and norms only), then the maintenance note."""
    out.add(*memory.welcome(engine, project, brief=brief), turn.state)
    if turn.note:
        out.blocks.append(turn.note)


def _previous_state_line(engine: Engine, project: str, call: _Call) -> str:
    """One line naming the state a previous session left in the worktree, or ``""``.

    Never its content; see ``sessions.previous`` for which states count.
    """
    rel = sessions.previous(engine, project, call.project_dir, call.session)
    if rel is None:
        return ""
    props = engine.index.props(rel)
    title = hookmode.clean_line(props.get("task_title") or rel)
    saved = hookmode.clean_line(props.get("saved_at") or props.get("compacted_at") or "?")
    return (
        f"episteme · hay un estado de sesión de una sesión anterior: «{title}» (guardado "
        f"{saved}; `{rel}`). No está cargado: para seguir con él, /episteme:sesion retomar."
    )


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
    sid = sessions.IDS.get("session")
    skip = prompting.state(sid).delivered if sid else None
    text, entries = memory.task_context(
        engine, args.task, args.project, args.budget_tokens, skip=skip
    )
    if args.hook_event:
        return hookmode.render(args.hook_event, text)
    return dump({"text": text, "entries": entries})
