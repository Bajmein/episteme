"""The plan tool: keep a copy of each plan of plan mode in planes/, and point to it after /clear."""

from __future__ import annotations

from typing import Annotated, Any, NamedTuple

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import hookmode, plans
from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import HookEvent, ProjectArg, dump

ACTIONS = ("save", "show", "archive", "restore")
QUIET_EVENT = "PreToolUse"  # save from the ExitPlanMode hook: always "", never blocks

_ActionArg = Annotated[str, Field(description=f"One of: {', '.join(ACTIONS)}.")]
_PlanArg = Annotated[
    str | None, Field(description="save: the plan text (hooks pass ${tool_input.plan}).")
]
_PlanPathArg = Annotated[
    str | None,
    Field(description="save: the plan file path (${tool_input.planFilePath}); gives the slug."),
]
_SlugArg = Annotated[
    str | None, Field(description="show, archive: slug of a plan (show without it lists them).")
]
_DirArg = Annotated[
    str | None,
    Field(description="Absolute project directory (hooks pass ${cwd}); picks the worktree."),
]
_SessionArg = Annotated[
    str | None, Field(description="save: Claude Code session id (${session_id}); metadata.")
]
_SourceArg = Annotated[
    str | None, Field(description='restore: "compact" or "clear" (${source}) from the hook.')
]


class _Call(NamedTuple):
    """The arguments of one plan call."""

    action: str
    plan: str | None
    plan_path: str | None
    slug: str | None
    project: str | None
    project_dir: str | None
    session: str | None
    source: str | None
    event: str | None


def register(server: MCPServer, engine: Engine) -> None:
    """Register the plan tool on ``server``."""
    _register_plan(server, engine)


def _register_plan(server: MCPServer, engine: Engine) -> None:
    """Register the plan tool on ``server``."""

    @server.tool(structured_output=False)
    def plan(
        action: _ActionArg,
        plan: _PlanArg = None,
        plan_path: _PlanPathArg = None,
        slug: _SlugArg = None,
        project: ProjectArg = None,
        project_dir: _DirArg = None,
        session: _SessionArg = None,
        source: _SourceArg = None,
        hook_event: HookEvent = None,
    ) -> str:
        """Keep a copy of each plan of plan mode in planes/<project>/<slug>.md.

        Only this tool writes there (revise and remember refuse it); Claude Code's own plan
        files are never read or touched. search and read find the copies; archived ones are
        hidden from search by default.
        save: write the copy of plan (one note per slug, the basename of plan_path; a save of
        the same slug overwrites it) and make it the current plan. Credentials are redacted
        and the text is cut at 200,000 characters. A hook variable left unsubstituted saves
        nothing. Returns {"path", "saved", "slug", "title", "created"}. With
        hook_event="PreToolUse" (the ExitPlanMode hook) it always returns "", errors included.
        show: without slug, {"plans": [...]} active plans of the project, newest first; with
        slug, that plan with its "content".
        archive: set status archived on slug, even when a session state links it; never
        deletes. Returns {"path", "changed"}.
        Plans more than [plans] archive_days (7) days after their saved_at are archived by the
        maintenance of the first welcome, except the one an active session state links.
        restore (SessionStart hook): only with source="clear", a short pointer to the plan of
        the task (this process's current plan, else the one the session state links, else the
        newest active plan of the worktree).
        """
        call = _Call(
            action, plan, plan_path, slug, project, project_dir, session, source, hook_event
        )
        if action == "save" and hook_event == QUIET_EVENT:
            return _save_quietly(engine, call)
        hookmode.check(hook_event)
        if action not in ACTIONS:
            raise invalid(f'action must be one of {", ".join(ACTIONS)}, got "{action}".')
        with engine.session():
            return _run(engine, call)


def _save_quietly(engine: Engine, call: _Call) -> str:
    """Save from the ExitPlanMode hook: nothing goes back as context, and nothing blocks it."""
    try:
        with engine.session():
            _save(engine, call)
    except Exception:  # nosec B110
        pass  # a failed copy must never stop ExitPlanMode nor reach the model
    return ""


def _save(engine: Engine, call: _Call) -> dict[str, Any]:
    args = plans.SaveArgs(call.plan, call.plan_path, call.session)
    return plans.save(engine, engine.need_project(call.project), call.project_dir, args)


def _run(engine: Engine, call: _Call) -> str:
    """Run an action. Call it inside engine.session()."""
    match call.action:
        case "save":
            return _reply(call.event, _save(engine, call))
        case "show":
            return dump(plans.show(engine, engine.need_project(call.project), call.slug))
        case "archive":
            return dump(_archive(engine, call))
        case _:
            return _restore(engine, call)


def _reply(event: str | None, data: dict[str, Any]) -> str:
    """JSON for the agent; for a hook, nothing."""
    return hookmode.render(event, "") if event else dump(data)


def _archive(engine: Engine, call: _Call) -> dict[str, Any]:
    if not call.slug:
        raise invalid('archive needs slug. plan(action="show") lists the plans.')
    rel = plans.plan_path(engine, engine.need_project(call.project), call.slug)
    return {"path": rel, "changed": plans.archive(engine, rel)}


def _restore(engine: Engine, call: _Call) -> str:
    """Run restore and render it for a hook (a pointer to the note) or as JSON."""
    project = engine.need_project(call.project)
    data = plans.restore(engine, project, call.project_dir, call.source)
    if not call.event:
        return dump(data)
    if not data["found"]:
        return hookmode.render(call.event, "")
    title = hookmode.clean_line(data["title"] or data["path"])
    saved = (data["saved_at"] or "").replace("T", " ")[:16]
    text = (
        f"Plan de esta tarea en episteme: `{data['path']}` — {title} (guardado {saved}). "
        "Léelo con read si necesitas volver a él."
    )
    return hookmode.render(call.event, text)
