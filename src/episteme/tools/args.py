"""Shared annotations and the JSON dump used by the tools."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

READ_ONLY = ToolAnnotations(read_only_hint=True)

NoteArg = Annotated[
    str,
    Field(description="Vault-relative path (with or without .md) or a note name / alias."),
]

HookEvent = Annotated[
    str | None,
    Field(description="Only for Claude Code hooks: ${hook_event_name}. Omit otherwise."),
]
ProjectArg = Annotated[str | None, Field(description="Project; defaults to --project.")]
FileArg = Annotated[
    str,
    Field(
        description="File being edited: absolute or relative to the project. "
        "Needs this or relative_path; a hook call with neither returns an empty result."
    ),
]
RelativePathArg = Annotated[
    str | None,
    Field(description="Serena edits pass relative_path instead of file; used when file is empty."),
]


def dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
