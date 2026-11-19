"""The session tool: keep the session state, and its hook actions (gate, capture, end)."""

from __future__ import annotations

from typing import Annotated, Any, NamedTuple

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import hookmode
from episteme import session as sessions
from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import HookEvent, ProjectArg, dump

ACTIONS = ("save", "show", "restore", "template", "archive", "capture", "end", "gate")

_ActionArg = Annotated[str, Field(description=f"One of: {', '.join(ACTIONS)}.")]
_TitleArg = Annotated[
    str | None, Field(description="save: the task in a few words; needed to create a state.")
]
_BodyArg = Annotated[
    str | None,
    Field(description="save: the whole state, following the session template (replaces it)."),
]
_NoteArg = Annotated[
    str | None,
    Field(description="save, archive: path of a state; default is the current state."),
]
_FilesArg = Annotated[
    list[str] | None, Field(description="save: files the task touches (globs allowed).")
]
_DirArg = Annotated[
    str | None,
    Field(description="Absolute project directory (hooks pass ${cwd}); picks the worktree."),
]
_OriginArg = Annotated[
    str | None, Field(description='save: "agent" (default) or "extractor"; goes to saved_by.')
]
_UntilArg = Annotated[
    str | None,
    Field(
        description='save with origin="extractor": the digest\'s "hasta" (ISO); the next '
        "extraction starts there."
    ),
]
_SessionArg = Annotated[
    str | None,
    Field(description="Claude Code session id (hooks pass ${session_id}); metadata for save."),
]
_SummaryArg = Annotated[
    str | None, Field(description="capture: the compaction summary (${compact_summary}).")
]
_TranscriptArg = Annotated[
    str | None,
    Field(description="end, restore: path of the session transcript (${transcript_path})."),
]
_TriggerArg = Annotated[str | None, Field(description='gate: "manual" or "auto" (${trigger}).')]
_ReasonArg = Annotated[str | None, Field(description="end: why the session ended (${reason}).")]
_SourceArg = Annotated[
    str | None, Field(description='restore: "compact" or "clear" (${source}) from the hook.')
]
_PlanArg = Annotated[
    str | None,
    Field(description="save: slug of the plan of the task; default keeps the state's plan."),
]
_TypeArg = Annotated[
    str | None, Field(description='template: memory type; default "session".')
]


def register(server: MCPServer, engine: Engine) -> None:
    """Register the session tool on ``server``."""
    _register_session(server, engine)


class _Hook(NamedTuple):
    """Arguments only the hooks pass."""

    summary: str | None = None
    transcript: str | None = None
    trigger: str | None = None
    source: str | None = None
    session: str | None = None
    event: str | None = None


class _Args:
    """Arguments of a session call shared by the actions."""

    def __init__(self, engine: Engine, project: str | None, project_dir: str | None) -> None:
        self.engine = engine
        self.project = engine.need_project(project)
        self.project_dir = project_dir


def _register_session(server: MCPServer, engine: Engine) -> None:
    """Register the session tool on ``server``."""

    @server.tool(structured_output=False)
    def session(
        action: _ActionArg,
        title: _TitleArg = None,
        body: _BodyArg = None,
        note: _NoteArg = None,
        files: _FilesArg = None,
        project: ProjectArg = None,
        project_dir: _DirArg = None,
        origin: _OriginArg = None,
        until: _UntilArg = None,
        session: _SessionArg = None,
        plan: _PlanArg = None,
        type: _TypeArg = None,
        summary: _SummaryArg = None,
        transcript: _TranscriptArg = None,
        trigger: _TriggerArg = None,
        reason: _ReasonArg = None,
        source: _SourceArg = None,
        hook_event: HookEvent = None,
    ) -> str:
        """Keep the session state: one living note per line of work in sesiones/<project>/.

        Only this tool writes there (revise and remember refuse it). The state in use is the
        one this process saved or restored, else the newest active state of the same
        worktree (project_dir).
        save: create or rewrite the whole state. Target: note, else the current state, else a
        new one (needs title); to start another line of work, archive the current state
        first. A note that was archived becomes active again. body replaces the body (a
        leading "# title" line is dropped);
        a credential in title, body, files or session is refused (invalid_argument). Returns
        {"path", "created", "missing_sections"} plus "template_hint" when a long body lacks
        template sections; it never refuses for format. plan (a slug of the plan tool) links
        the state to its plan; without it the state keeps its plan, else takes the plan this
        process saved last for the worktree. The extractor passes until (the last transcript
        time it read) and the next extraction order starts there, not at saved_at; any
        later save drops it.
        show: {"found", "path", "task_title", "saved_at", "content"} (plus "extracted_until"
        when the extractor saved last). Never writes.
        restore: the state as context, made current: {"found", "path", "task_title",
        "saved_at", "content", "source"}. Without a state it falls back to the deprecated
        checkpoint when [checkpoint] state_glob is set (adds "deprecated").
        template: {"type", "sections", "skeleton"} of type (default "session").
        archive: set status archived on note (default the current state); never deletes.
        Returns {"path", "changed"}. States more than [session] archive_days (7) days after
        their saved_at are archived by the maintenance of the first welcome.
        Hook actions: gate (only with hook_event="PreCompact") blocks a manual /compact once
        when the state was not saved in 5+ messages; capture (PostCompact) puts
        summary in the "Resumen de compactación" section of the state, credentials redacted,
        creating «Sesión <date>» if there is none; end (SessionEnd) keeps transcript for the
        next restore after /clear (only when reason is "clear" or empty). restore with source
        and a transcript adds "extract", the order to launch the episteme:extractor agent, when
        [session] extract is on.
        """
        hookmode.check(hook_event)
        if action not in ACTIONS:
            raise invalid(f'action must be one of {", ".join(ACTIONS)}, got "{action}".')
        if action == "template":
            return dump(sessions.template(type))
        if action == "end":
            return _reply(hook_event, sessions.end(transcript, reason))
        save = sessions.SaveArgs(title, body, note, files, origin, session, plan, until)
        hook = _Hook(summary, transcript, trigger, source, session, hook_event)
        with engine.session():
            return _run(_Args(engine, project, project_dir), action, save, hook)


def _reply(hook_event: str | None, data: dict[str, Any]) -> str:
    """JSON for the agent; for a hook, what its event shows (nothing for the silent ones)."""
    return hookmode.render(hook_event, "") if hook_event else dump(data)


def _run(args: _Args, action: str, save: sessions.SaveArgs, hook: _Hook) -> str:
    """Run every action but template and end. Call it inside engine.session()."""
    engine, project, project_dir = args.engine, args.project, args.project_dir
    match action:
        case "save":
            return dump(sessions.save(engine, project, project_dir, save))
        case "show":
            return dump(sessions.show(engine, project, project_dir))
        case "restore":
            return _restore(args, hook)
        case "capture":
            data = sessions.capture(engine, project, project_dir, hook.summary, hook.session)
            return _reply(hook.event, data)
        case "gate":
            return _gate(args, hook)
        case _:
            return dump(_archive(args, save.note))


def _gate(args: _Args, hook: _Hook) -> str:
    """Run gate from the PreCompact hook: a block decision, or nothing."""
    if hook.event != "PreCompact":
        raise invalid(
            'action "gate" is for the PreCompact hook. Pass hook_event="PreCompact", or save '
            'the state with action="save".'
        )
    reason = sessions.gate(args.engine, args.project, args.project_dir, hook.trigger, hook.session)
    return hookmode.render_block(reason) if reason else ""


def _restore(args: _Args, hook: _Hook) -> str:
    """Run restore and render it for a hook or as JSON."""
    data = sessions.restore(
        args.engine, args.project, args.project_dir, hook.source, hook.transcript
    )
    if not hook.event:
        return dump(data)
    notice = ""
    if data["found"]:
        title = hookmode.clean_line(data["task_title"])
        notice = f"episteme · estado de sesión recuperado: «{title}»"
    text = "\n\n".join(t for t in (data["content"], data.get("extract", "")) if t)
    return hookmode.render(hook.event, text, notice)


def _archive(args: _Args, note: str | None) -> dict[str, Any]:
    """Archive ``note`` or the current state."""
    if note:
        rel = sessions.note_path(args.engine, note)
    else:
        rel = sessions.current(args.engine, args.project, args.project_dir)
        if rel is None:
            raise invalid("there is no current session state to archive. Pass note.")
    return {"path": rel, "changed": sessions.archive(args.engine, rel)}
