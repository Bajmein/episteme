"""Reading tools: search and read (read also gives the links of a note)."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme.engine import Engine
from episteme.errors import invalid
from episteme.filters import SearchFilters
from episteme.tools.args import READ_ONLY, dump

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
_PriorityMinArg = Annotated[
    int | None, Field(description="1-5: only notes with this priority or higher.")
]
_ValidArg = Annotated[
    str | None,
    Field(
        description='"current": no valid_until or not past; "expired": valid_until before today.'
    ),
]
_LinkedToArg = Annotated[
    str | None,
    Field(description="A note (path or name): only notes that link to it or that it links to."),
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
        priority_min: _PriorityMinArg = None,
        valid: _ValidArg = None,
        linked_to: _LinkedToArg = None,
    ) -> str:
        """Full-text search over the vault (notes and memories), best matches first.

        With no query, lists the notes matching the filters. If no note has all the words,
        retries with any of them ("match": "or", "note"); with 1-2 hits and 2+ words,
        "partial" lists up to 5 more notes with some of the words.
        With match="any" or after that retry, each row carries "matched": the words it has.
        Returns JSON {"results": [{"path", "title", "line", "snippet", "score", and when set
        "zone", "type", "status", "project", "created", "priority", "description" (memories),
        "heading",
        "superseded_by"}], "total"}. `line` is the 1-based line of the first match; open it
        with read(path, lines=...). With no results, "hints" says which filter matches nothing.
        priority_min, valid and linked_to also filter (they can replace the query).
        facets=true adds "facets": counts by zone, project, type, status and tags.
        """
        filters = SearchFilters(
            path, type, tags, project, status, zone, priority_min, valid, linked_to
        )
        with engine.session():
            return dump(
                engine.search(query, filters, limit, facets, match)
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
_LinksArg = Annotated[
    str | None,
    Field(
        description='"out", "in" or "both": also return "links" (outgoing links, backlinks '
        "and, with depth > 1, reachable notes). Property links (supersedes, related, up...) "
        'carry their key as kind; body links are "body"; unresolved ones have path null and '
        "resolved false. Not with notes."
    ),
]
_DepthArg = Annotated[
    int,
    Field(description="1-3, with links: above 1 also lists notes reachable via outgoing links."),
]


def _check_read_args(
    note: str | None, notes: list[str] | None, links: str | None, depth: int
) -> None:
    """Reject the combinations of note, notes, links and depth that make no sense."""
    _check_note_or_notes(note, notes)
    if links is None:
        if depth != 1:
            raise invalid("depth needs links. Pass links (out, in or both) or drop depth.")
    elif notes is not None:
        raise invalid("links works with one note, not with notes. Use note.")


def _check_note_or_notes(note: str | None, notes: list[str] | None) -> None:
    if (note is None) == (notes is None):
        raise invalid(
            "pass note (one note) or notes (several), not both."
            if note is not None
            else "pass note (one note) or notes (several)."
        )


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
        links: _LinksArg = None,
        depth: _DepthArg = 1,
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
        With links ("out", "in" or "both", plus depth 1-3), adds "links": {"path", "outgoing",
        "backlinks", "reachable" (depth > 1)}; with content=false that is frontmatter, outline
        and links without the body.
        """
        with engine.session():
            _check_read_args(note, notes, links, depth)
            if notes is not None:
                return dump(engine.read_many(notes, heading, lines, outline, content))
            assert note is not None  # checked above  # nosec B101
            found = engine.links(note, links, depth) if links is not None else None
            result = engine.read(note, heading, lines, outline, content)
            if found is not None:
                result["links"] = found
            return dump(result)


def register(server: MCPServer, engine: Engine) -> None:
    """Register the reading tools on ``server``."""
    _register_search(server, engine)
    _register_read(server, engine)
