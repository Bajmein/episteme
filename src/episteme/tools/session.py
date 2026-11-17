"""The session tool: save, show, restore, template and archive the session state."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import hookmode
from episteme import session as sessions
from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import HookEvent, ProjectArg, dump

ACTIONS = ("save", "show", "restore", "template", "archive")

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
_SessionArg = Annotated[
    str | None, Field(description="save: Claude Code session id, kept as metadata only.")
]
_TypeArg = Annotated[
    str | None, Field(description='template: memory type; default "session".')
]


def register(server: MCPServer, engine: Engine) -> None:
    """Register the session tool on ``server``."""
    _register_session(server, engine)


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
        session: _SessionArg = None,
        type: _TypeArg = None,
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
        template sections; it never refuses for format.
        show: {"found", "path", "task_title", "saved_at", "content"}. Never writes.
        restore: the state as context, made current: {"found", "path", "task_title",
        "saved_at", "content", "source"}. Without a state it falls back to the deprecated
        checkpoint when [checkpoint] state_glob is set (adds "deprecated").
        template: {"type", "sections", "skeleton"} of type (default "session").
        archive: set status archived on note (default the current state); never deletes.
        Returns {"path", "changed"}. States more than [session] archive_days (7) days after
        their saved_at are archived by the maintenance of the first welcome.
        """
        hookmode.check(hook_event)
        if action not in ACTIONS:
            raise invalid(f'action must be one of {", ".join(ACTIONS)}, got "{action}".')
        if action == "template":
            return dump(sessions.template(type))
        save = sessions.SaveArgs(title, body, note, files, origin, session)
        with engine.session():
            return _run(_Args(engine, project, project_dir), action, save, hook_event)


def _run(args: _Args, action: str, save: sessions.SaveArgs, hook_event: str | None) -> str:
    """Run a save, show, restore or archive action. Call it inside engine.session()."""
    match action:
        case "save":
            return dump(sessions.save(args.engine, args.project, args.project_dir, save))
        case "show":
            return dump(sessions.show(args.engine, args.project, args.project_dir))
        case "restore":
            return _restore(args, hook_event)
        case _:
            return dump(_archive(args, save.note))


def _restore(args: _Args, hook_event: str | None) -> str:
    """Run restore and render it for a hook or as JSON."""
    data = sessions.restore(args.engine, args.project, args.project_dir)
    if not hook_event:
        return dump(data)
    notice = ""
    if data["found"]:
        title = hookmode.clean_line(data["task_title"])
        notice = f"episteme · estado de sesión recuperado: «{title}»"
    return hookmode.render(hook_event, data["content"], notice)


def _archive(args: _Args, note: str | None) -> dict[str, Any]:
    """Archive ``note`` or the current state."""
    if note:
        rel = sessions.note_path(args.engine, note)
    else:
        rel = sessions.current(args.engine, args.project, args.project_dir)
        if rel is None:
            raise invalid("there is no current session state to archive. Pass note.")
    return {"path": rel, "changed": sessions.archive(args.engine, rel)}
