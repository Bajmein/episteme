"""Reading tools: search, read and links."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme.engine import Engine
from episteme.errors import invalid
from episteme.tools.args import READ_ONLY, NoteArg, dump

_QueryArg = Annotated[
    str | None,
    Field(
        description='Words that must all appear (AND; any of them with match="any"); '
        '"quoted text" is a phrase; '
        "`a-b` is the words a and b; `word*` matches any word starting with it. "
        "Case and accents are ignored. "
        "Optional when tags, type, project, zone or facets is given."
    ),
]
_PathArg = Annotated[str | None, Field(description="Path prefix, e.g. docs/claude-code.")]
_TypeArg = Annotated[
    str | None,
    Field(
        description="Frontmatter type. Memories: decision, lesson, error, constraint, "
        "preference, session, reminder, insight. Documentation uses others, "
        "e.g. reference."
    ),
]
_TagsArg = Annotated[
    list[str] | None,
    Field(
        description="Tags the note must all have; `dominio:x` is read as `dominio/x`. "
        "Tags span projects: use them without project to follow a topic across projects."
    ),
]
_ProjectArg = Annotated[
    str | None,
    Field(description='Frontmatter project; "_shared" memories are included. Optional.'),
]
_StatusArg = Annotated[
    str | None,
    Field(
        description="active, speculative, superseded or archived. Default: everything "
        "except superseded and archived memories; \"any\" includes them "
        "(rows then carry status and superseded_by)."
    ),
]
_LimitArg = Annotated[int, Field(description="1-100.")]
_ZoneArg = Annotated[
    str | None,
    Field(
        description="Only notes of this zone, as in episteme.toml, "
        'e.g. "memory" (memories) or "docs/claude-code".'
    ),
]
_FacetsArg = Annotated[
    bool,
    Field(
        description="Also return counts by zone, project, type, status and tag; "
        "alone, it lists what the vault has."
    ),
]
_MatchArg = Annotated[
    str,
    Field(
        description='"all" (default): every word must appear. "any": notes with any of '
        'the words, best first, each row listing the ones it has in "matched". Use "any" '
        "to look up several names or variants of a word in one call."
    ),
]


def _register_search(server: MCPServer, engine: Engine) -> None:
    """Register the search tool."""

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def search(
        query: _QueryArg = None,
        path: _PathArg = None,
        type: _TypeArg = None,
        tags: _TagsArg = None,
        project: _ProjectArg = None,
        status: _StatusArg = None,
        limit: _LimitArg = 20,
        zone: _ZoneArg = None,
        facets: _FacetsArg = False,
        match: _MatchArg = "all",
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


_NoteOrNameArg = Annotated[
    str | None,
    Field(
        description="Vault-relative path (with or without .md) or a note name / alias. "
        "For several notes use notes."
    ),
]
_HeadingArg = Annotated[
    str | None, Field(description="Return only this section (case-insensitive).")
]
_LinesArg = Annotated[
    str | None, Field(description='1-based inclusive line range of the file, "10-40".')
]
_OutlineArg = Annotated[
    bool | None,
    Field(description="Include the heading outline. Default: only when reading the whole note."),
]
_ContentArg = Annotated[
    bool,
    Field(
        description="false returns only frontmatter and outline (each heading with its "
        "line and end), to pick a section before reading."
    ),
]
_NotesArg = Annotated[
    list[str] | None,
    Field(
        description="Several notes to read whole in one call (up to 20), instead of "
        "note. heading and lines do not apply."
    ),
]


def _register_read(server: MCPServer, engine: Engine) -> None:
    """Register the read tool."""

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def read(
        note: _NoteOrNameArg = None,
        heading: _HeadingArg = None,
        lines: _LinesArg = None,
        outline: _OutlineArg = None,
        content: _ContentArg = True,
        notes: _NotesArg = None,
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


def _register_links(server: MCPServer, engine: Engine) -> None:
    """Register the links tool."""

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


def register(server: MCPServer, engine: Engine) -> None:
    """Register the reading tools on ``server``."""
    _register_search(server, engine)
    _register_read(server, engine)
    _register_links(server, engine)
