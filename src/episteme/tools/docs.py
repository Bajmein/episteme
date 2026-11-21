"""Docs suite tool: ``docs`` with action status (read) and write."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import docs as docs_pkg
from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import dump

STATUS = "status"
WRITE = "write"
# What each action takes: an argument outside its set is refused instead of ignored.
_ALLOWED = {
    STATUS: {"suite", "pages"},
    WRITE: {"suite", "path", "source", "body", "body_ref", "fields"},
}


def register(server: MCPServer, engine: Engine) -> None:
    """Register the docs suite tool on ``server``."""
    _register_docs(server, engine)


def _stray(allowed: set[str], given: dict[str, Any]) -> list[str]:
    """The arguments passed (not None, not False) that the action does not take."""
    return sorted(k for k, v in given.items() if k not in allowed and v not in (None, False))


def _check_args(action: str, given: dict[str, Any]) -> None:
    """Refuse an unknown action, an argument it does not take, or a write without suite."""
    allowed = _ALLOWED.get(action)
    if allowed is None:
        raise invalid(f'unknown action "{action}". Use "status" or "write".')
    if stray := _stray(allowed, given):
        raise invalid(
            f'{", ".join(stray)} does not apply to action="{action}". '
            "Drop it or use the other action."
        )
    if action == WRITE and not given["suite"]:
        raise invalid('action="write" needs suite. Pass the docs zone, e.g. suite="mise".')


def _status(engine: Engine, suite: str | None, pages: bool) -> str:
    with engine.session():
        return dump(docs_pkg.docs_status(engine, suite, pages))


def _write(engine: Engine, given: dict[str, Any]) -> str:
    with engine.session():
        return dump(
            docs_pkg.docs_write(
                engine,
                given["suite"],
                given["path"],
                given["source"],
                given["body"],
                given["body_ref"],
                given["fields"],
            )
        )


def _register_docs(server: MCPServer, engine: Engine) -> None:
    """Register the docs tool on ``server``."""

    @server.tool(structured_output=False)
    def docs(
        action: Annotated[
            str,
            Field(description='"status" lists the suites (never writes); "write" saves a note.'),
        ],
        suite: Annotated[
            str | None,
            Field(
                description='Docs zone: its path ("docs/mise") or its last segment ("mise"). '
                "Needed by write; with status, omit it to list every suite."
            ),
        ] = None,
        pages: Annotated[
            bool, Field(description="status with suite: add the pages of the suite as TSV.")
        ] = False,
        path: Annotated[
            str | None,
            Field(
                description="write: path inside the suite, ending in .md; README.index.md is "
                "the manifest. Needed to create a note."
            ),
        ] = None,
        source: Annotated[
            str | None, Field(description="write: page URL; finds the note before path does.")
        ] = None,
        body: Annotated[
            str | None,
            Field(
                description="write: page text as downloaded, without frontmatter. Omit to keep it."
            ),
        ] = None,
        body_ref: Annotated[
            str | None,
            Field(
                description="write: hash of a body in the suite's inbox (docs_check.py diff), "
                "instead of body. The file is deleted once used."
            ),
        ] = None,
        fields: Annotated[
            dict[str, Any] | None,
            Field(description="write: frontmatter keys to merge; null deletes a key."),
        ] = None,
    ) -> str:
        """Read or write the docs suites (zones with mode "docs"); only write changes anything.

        action="status" lists the suites and their manifests (takes suite and pages only).
        Without suite returns JSON {"suites": [{"suite", "inbox", "notes", "with_source",
        "local", "deprecated", "invalid", "manifest_valid", "upstream", "include",
        "context7", "synced", "markdown", "manual"}]}: notes
        leaves out README.index.md (the manifest), invalid counts notes that fail the suite
        schema, local counts the suite's own notes (origin: local, no source, never in pages),
        markdown is the URL template that serves each page as Markdown (null if none), manual
        is true for a suite kept by hand (/episteme-docs:docs skips it),
        inbox is the absolute path of the suite's inbox (never created here), where
        docs_check.py diff leaves the downloaded bodies that action="write" takes by body_ref.
        With suite returns that one object; pages=true adds "pages", one string with a
        line per note that has a source: <source>\\t<hash>\\t<path in the suite>\\t<status>.
        The hash is what /episteme-docs:docs compares with the downloaded page. Used by the
        /episteme-docs:docs skill; to update docs/, run that skill, never edit by hand.

        action="write" creates or updates one note of a suite (takes suite, path, source,
        body, body_ref and fields; suite is required).
        Finds the note by source, else by path. A missing note is created at path (it must
        not exist, and fields must bring title, type, status, lang and tags; created and
        updated default to today). A body with the same hash as the current one is not
        rewritten; a new body or changed fields set updated to today unless fields has it.
        body_ref (16 lowercase hex digits, never together with body) takes the body from the
        suite's inbox, <vault>/.index/docs-inbox/<suite>/<hash>.md, which docs_check.py diff
        fills: the text must hash to body_ref (invalid_argument), a missing file is not_found,
        and the file is deleted after a successful write or when the body was unchanged (it is
        kept on any error).
        fields={"suite": {...}} replaces the whole manifest mapping (upstream, include,
        context7, synced, and the optional markdown and manual). A note of the suite's own,
        with no upstream page, takes fields={"origin": "local"} and no source.
        The result is checked against the suite schema (invalid_schema);
        string values in fields that look like a credential are refused; the body is not
        scanned. Pages are never deleted: mark a gone one with fields={"status":
        "deprecated"}. Returns JSON {"path", "created", "changed", "hash"}; changed false
        means nothing was written.
        """
        given = {
            "suite": suite,
            "pages": pages,
            "path": path,
            "source": source,
            "body": body,
            "body_ref": body_ref,
            "fields": fields,
        }
        _check_args(action, given)
        if action == STATUS:
            return _status(engine, suite, pages)
        return _write(engine, given)
