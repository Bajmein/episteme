"""Docs suite tools: docs_status and docs_write."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import docs
from episteme.engine import Engine
from episteme.tools.args import READ_ONLY, dump

_SuiteArg = Annotated[
    str, Field(description='Docs zone: its path ("docs/mise") or its last segment ("mise").')
]


def register(server: MCPServer, engine: Engine) -> None:
    """Register the docs suite tools on ``server``."""
    _register_docs_status(server, engine)
    _register_docs_write(server, engine)


def _register_docs_status(server: MCPServer, engine: Engine) -> None:
    """Register the docs_status tool on ``server``."""

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def docs_status(
        suite: Annotated[
            str | None,
            Field(description='Docs zone ("docs/mise" or "mise"); omit to list every suite.'),
        ] = None,
        pages: Annotated[
            bool, Field(description="With suite: add the pages of the suite as TSV.")
        ] = False,
    ) -> str:
        """List the docs suites (zones with mode "docs") and their manifests. Never writes.

        Without suite returns JSON {"suites": [{"suite", "inbox", "notes", "with_source",
        "local", "deprecated", "invalid", "manifest_valid", "upstream", "include",
        "context7", "synced", "markdown", "manual"}]}: notes
        leaves out README.index.md (the manifest), invalid counts notes that fail the suite
        schema, local counts the suite's own notes (origin: local, no source, never in pages),
        markdown is the URL template that serves each page as Markdown (null if none), manual
        is true for a suite kept by hand (/episteme-docs:docs skips it),
        inbox is the absolute path of the suite's inbox (never created here), where
        docs_check.py diff leaves the downloaded bodies that docs_write takes by body_ref.
        With suite returns that one object; pages=true adds "pages", one string with a
        line per note that has a source: <source>\\t<hash>\\t<path in the suite>\\t<status>.
        The hash is what /episteme-docs:docs compares with the downloaded page. Used by the
        /episteme-docs:docs skill; to update docs/, run that skill, never edit by hand.
        """
        with engine.session():
            return dump(docs.docs_status(engine, suite, pages))


def _register_docs_write(server: MCPServer, engine: Engine) -> None:
    """Register the docs_write tool on ``server``."""

    @server.tool(structured_output=False)
    def docs_write(
        suite: _SuiteArg,
        path: Annotated[
            str | None,
            Field(
                description="Path inside the suite, ending in .md; README.index.md is the "
                "manifest. Needed to create a note."
            ),
        ] = None,
        source: Annotated[
            str | None, Field(description="Page URL; finds the note before path does.")
        ] = None,
        body: Annotated[
            str | None,
            Field(description="Page text as downloaded, without frontmatter. Omit to keep it."),
        ] = None,
        body_ref: Annotated[
            str | None,
            Field(
                description="Hash of a body in the suite's inbox (docs_check.py diff), "
                "instead of body. The file is deleted once used."
            ),
        ] = None,
        fields: Annotated[
            dict[str, Any] | None,
            Field(description="Frontmatter keys to merge; null deletes a key."),
        ] = None,
    ) -> str:
        """Create or update one note of a docs suite. Only zones with mode "docs" accept it.

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
        with engine.session():
            return dump(docs.docs_write(engine, suite, path, source, body, body_ref, fields))
