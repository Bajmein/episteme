"""Memory tools: remember, revise and review."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from episteme import memory
from episteme.engine import Engine
from episteme.tools.args import READ_ONLY, NoteArg, dump


def register(server: MCPServer, engine: Engine) -> None:
    """Register the memory tools on ``server``."""

    @server.tool(structured_output=False)
    def remember(
        type: Annotated[
            str,
            Field(
                description="decision | lesson | error | constraint | preference | session | "
                "reminder | insight"
            ),
        ],
        title: Annotated[
            str, Field(description="Short title (5-8 words); the file name is derived from it.")
        ],
        body: Annotated[
            str,
            Field(
                description="The memory. Name the files, tools or commands involved: "
                "that is what is searched later."
            ),
        ],
        project: Annotated[
            str | None,
            Field(description='Project; defaults to --project. "_shared" for all projects.'),
        ] = None,
        priority: Annotated[
            int | None,
            Field(
                description="1-5. 5 = rule every session must know; 4 = technical decision "
                "(default for decision/constraint); 3 = record (default); 1-2 = minor."
            ),
        ] = None,
        tags: Annotated[
            list[str],
            Field(
                description='Nested with "/", e.g. dominio/auth; no ":". Use persona/<surname> '
                "for people and tema/<topic> for a subject that spans projects."
            ),
        ] = [],  # noqa: B006
        keywords: Annotated[
            list[str],
            Field(
                description="Other words people use for this: synonyms, abbreviations, full "
                'names (mkt, marketing, "Ana Pérez"). Searched with the weight of the '
                "title."
            ),
        ] = [],  # noqa: B006
        files: Annotated[
            list[str],
            Field(description="Project-relative files this memory is about (globs allowed)."),
        ] = [],  # noqa: B006
        related: Annotated[list[str], Field(description="Related notes (paths or names).")] = [],  # noqa: B006
        supersedes: Annotated[
            str | None, Field(description="Memory this one replaces; it becomes superseded.")
        ] = None,
        source: Annotated[str | None, Field(description="Commit sha or PR.")] = None,
        due: Annotated[str | None, Field(description="YYYY-MM-DD; required for reminders.")] = None,
        valid_until: Annotated[
            str | None, Field(description="YYYY-MM-DD after which the memory no longer holds.")
        ] = None,
        status: Annotated[
            str, Field(description="active | speculative | superseded | archived.")
        ] = "active",
        force: Annotated[
            bool, Field(description="Create it even if a near-duplicate exists.")
        ] = False,
        slug: Annotated[
            str | None,
            Field(
                description="File-name slug: 1-40 lowercase letters, digits and hyphens, without "
                "the date. Derived from the title when omitted."
            ),
        ] = None,
    ) -> str:
        """Store a memory as memory/<project>/<type folder>/YYYY-MM-DD-<slug>.md.

        The date is local. The slug is the title cut to its first 3-5 useful words (no stopwords,
        nothing already in the path, at most 40 characters) unless you pass slug; the full title
        stays in the H1. A name that already exists gets -2, -3...

        Validates the schema and looks for near-duplicates of the same project and type: at
        similarity >= 0.8 nothing is created (created: false) and the answer carries a "hint":
        revise(action="feedback", value="helpful") if it happened again, remember again with
        supersedes=<path> if it changed, force=true only for a genuinely different memory.
        `similar` also lists active memories of any type in the project or _shared (they only
        warn). title, body, keywords and source are refused (invalid_argument) when they look
        like a credential (private key, cloud/API token, JWT, password in a URL): say where
        the secret is stored instead.
        Returns JSON {"created", "path", "similar": [{"path", "title", "similarity", "type",
        "project"}], "new_tags": [{"tag", "similar"}] (tags no other note has, with close
        spellings), "link_candidates": [{"path", "title", "reason"}] (up to 5 memories sharing
        a file or 2 tags; consider related)}. The last two appear only when non-empty.
        """
        with engine.session():
            return dump(
                memory.remember(
                    engine,
                    type,
                    title,
                    body,
                    project,
                    priority,
                    tags,
                    files,
                    related,
                    supersedes,
                    source,
                    due,
                    valid_until,
                    status,
                    force,
                    slug=slug,
                    keywords=keywords,
                )
            )

    @server.tool(structured_output=False)
    def revise(
        note: NoteArg,
        action: Annotated[
            str,
            Field(
                description="edit (old, new) | append (text, heading?) | set (fields) | "
                "supersede (by) | feedback (value) | archive | dismiss (reminders)"
            ),
        ],
        old: Annotated[str | None, Field(description="edit: text that appears once.")] = None,
        new: Annotated[str | None, Field(description="edit: replacement text.")] = None,
        text: Annotated[str | None, Field(description="append: text to add.")] = None,
        heading: Annotated[
            str | None, Field(description="append: add at the end of this section.")
        ] = None,
        fields: Annotated[
            dict[str, Any] | None,
            Field(description="set: frontmatter keys to merge; null deletes a key."),
        ] = None,
        by: Annotated[
            str | None, Field(description="supersede: the memory that replaces this one.")
        ] = None,
        value: Annotated[
            str | None, Field(description="feedback: helpful | unhelpful | outdated.")
        ] = None,
    ) -> str:
        """Change a note in a read-write or memory zone. Read-only zones are refused.

        supersede, feedback, archive and dismiss (archives a reminder) only apply to memories.
        Memories are validated against the schema before anything is written. Incoming text
        (new, text, string values in fields) that looks like a credential is refused. set on a
        memory that changes type or project moves the file to memory/<project>/<type folder>/
        (same name, so [[name]] links keep working) and returns the new path with "moved_from".
        Returns JSON {"path", "action", "changed"}.
        """
        with engine.session():
            return dump(
                memory.revise(engine, note, action, old, new, text, heading, fields, by, value)
            )

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def review(
        path: Annotated[str | None, Field(description="Path prefix to limit the review.")] = None,
        project: Annotated[
            str | None,
            Field(
                description="Limit memory checks to this project (and _shared). "
                '"*" reviews every project.'
            ),
        ] = None,
        limit: Annotated[int, Field(description="Maximum items per category.")] = 50,
        zone: Annotated[
            str | None,
            Field(description='Only notes of this zone, as in episteme.toml (e.g. "memory").'),
        ] = None,
    ) -> str:
        """Vault health: stale memories, expired memories, possible contradictions, groups of
        similar memories, cut titles, orphans, broken links, invalid frontmatter and memories
        flagged as outdated.

        Returns JSON {"totals", "stale", "expired", "contradictions", "similar", "cut_titles",
        "orphans", "broken_links", "invalid_frontmatter", "flagged", "read_only"}.
        "similar" lists groups {"paths", "similarity"} of active memories (any type or
        project, not session or reminder) to merge; "cut_titles" lists memories whose
        first body line repeats the title and goes on. "expired" lists active memories
        {"path", "title", "type", "valid_until"} whose valid_until is before today
        (checkpoints are left out: checkpoint manages them); it only reports, so for each
        one call revise(action="archive"), or remember a new memory with supersedes if it
        still applies in updated form. "totals" counts every item per
        category (the lists are cut at limit). Problems in read-only zones (you cannot fix
        them here; in practice broken links and invalid frontmatter, since memories live in
        memory zones) are not mixed in: they go under "read_only", with the same categories
        and their own "totals".
        """
        with engine.session():
            return dump(memory.review(engine, path, project, limit, zone))
