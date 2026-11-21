"""Revising memories: ``revise`` and its helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.errors import NOT_FOUND, READ_ONLY_ZONE, EpistemeError, invalid
from episteme.index import as_int
from episteme.markdown import (
    find_section,
    parse,
)
from episteme.memory.schema import (
    ACTIONS,
    FOLDERS,
    MEMORY_ACTIONS,
    TYPES,
    NoteFile,
    check_files,
    kind_for,
    validate,
    wikilink,
)
from episteme.memory.secrets import _reject_secrets, has_new_secrets
from episteme.vault import MEMORY, TOOL_MODES

if TYPE_CHECKING:
    from episteme.engine import Engine


FEEDBACK_VALUES = ("helpful", "unhelpful", "outdated")


def _reject_tool_zone(rel: str, mode: str) -> None:
    """``read_only_zone`` for a zone that only its own tool writes (``vault.TOOL_MODES``)."""
    tool = TOOL_MODES.get(mode)
    if tool is not None:
        raise EpistemeError(READ_ONLY_ZONE, f"{rel} is in a {mode} zone. Use {tool}.")


def _edit(nf: NoteFile, old: str | None, new: str | None) -> list[str]:
    if not old or new is None:
        raise invalid("edit needs old (text to replace) and new.")
    if has_new_secrets(new, old):  # editing around an old false positive is fine
        _reject_secrets("new", new)
    count = nf.body.count(old)
    if count != 1:
        raise invalid(
            f"old appears {count} times in {nf.rel}; it must appear exactly once. "
            "Include more surrounding text."
        )
    nf.body = nf.body.replace(old, new, 1)
    return ["body"]


def _append_text(nf: NoteFile, text: str | None, heading: str | None) -> list[str]:
    if not text:
        raise invalid("append needs text.")
    _reject_secrets("text", text)
    nf.body = _append(nf, text, heading)
    return ["body"]


def _reject_field_secrets(fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        _reject_secrets(f"fields.{key}", value)


def _needs_move(changed: list[str], is_memory: bool) -> bool:
    """True when a memory's type or project changed, so its folder may change."""
    return is_memory and bool({"type", "project"} & set(changed))


def _sync_kind(nf: NoteFile, changed: list[str]) -> list[str]:
    """Set ``kind`` from the new ``type`` when the type changed to a known one."""
    if "type" in changed and nf.fm.get("type") in TYPES:
        return nf.set_fields({"kind": kind_for(nf.fm["type"])})
    return []


def _set(
    engine: Engine, nf: NoteFile, fields: dict[str, Any] | None, is_memory: bool
) -> tuple[list[str], str]:
    """Set frontmatter fields; return what changed and the path the note ends up at."""
    if not fields:
        raise invalid('set needs fields, e.g. {"priority": 5}.')
    _reject_field_secrets(fields)
    if "files" in fields:
        check_files(fields["files"])
    changed = nf.set_fields({k: _coerce(k, v) for k, v in fields.items()})
    if not _needs_move(changed, is_memory):
        return changed, nf.rel
    changed += _sync_kind(nf, changed)
    return changed, _move_memory(engine, nf)


def _resolve_replacement(engine: Engine, nf: NoteFile, by: str | None) -> tuple[str, NoteFile]:
    """The memory that replaces ``nf``: its path and loaded note."""
    if not by:
        raise invalid("supersede needs by (the note that replaces this one).")
    by_rel = engine.resolve_note(by)
    if by_rel == nf.rel:
        raise invalid("a note cannot supersede itself.")
    if engine.vault.check_writable(by_rel) != MEMORY:
        raise invalid(f"{by_rel} is not a memory. Create the replacement with remember.")
    return by_rel, NoteFile(engine, by_rel)


def _merged_supersedes(current: Any, link: str) -> Any:
    """The ``supersedes`` value of the replacement once ``link`` is added."""
    if current and current != link:
        current = current if isinstance(current, list) else [current]
        return current + ([link] if link not in current else [])
    return link


def _supersede(engine: Engine, nf: NoteFile, by: str | None) -> tuple[list[str], str]:
    """Mark the note as superseded by ``by``, save both notes and return the path of ``by``."""
    by_rel, newer = _resolve_replacement(engine, nf, by)
    link = wikilink(engine, nf.rel)
    link_value = _merged_supersedes(newer.fm.get("supersedes"), link)
    changed = nf.set_fields({"status": "superseded"})
    newer.set_fields({"supersedes": link_value})
    validate(nf.fm)
    validate(newer.fm)
    nf.save()
    newer.save()
    return changed, by_rel


def _feedback(nf: NoteFile, value: str | None) -> list[str]:
    if value not in FEEDBACK_VALUES:
        raise invalid('feedback value must be "helpful", "unhelpful" or "outdated".')
    helpful = as_int(nf.fm.get("helpful")) or 0
    if value == "helpful":
        return nf.set_fields({"helpful": helpful + 1})
    if value == "unhelpful":
        return nf.set_fields({"helpful": max(0, helpful - 1)})
    return nf.set_fields({"flagged": True})


def _archive(nf: NoteFile) -> list[str]:
    return nf.set_fields({"status": "archived"})


def _dismiss(nf: NoteFile) -> list[str]:
    if nf.fm.get("type") != "reminder":
        raise invalid(f"dismiss only applies to reminders, and {nf.rel} is not one.")
    return _archive(nf)


def revise(
    engine: Engine,
    note: str,
    action: str,
    old: str | None = None,
    new: str | None = None,
    text: str | None = None,
    heading: str | None = None,
    fields: dict[str, Any] | None = None,
    by: str | None = None,
    value: str | None = None,
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise invalid(f"action must be one of {', '.join(ACTIONS)}, got {action!r}.")
    rel = engine.resolve_note(note)
    mode = engine.vault.check_writable(rel)
    _reject_tool_zone(rel, mode)
    if action in MEMORY_ACTIONS and mode != MEMORY:
        raise invalid(f'action "{action}" only applies to memories, and {rel} is not one.')
    nf = NoteFile(engine, rel)
    result: dict[str, Any] = {"path": rel, "action": action, "changed": []}

    match action:
        case "edit":
            result["changed"] = _edit(nf, old, new)
        case "append":
            result["changed"] = _append_text(nf, text, heading)
        case "set":
            result["changed"], moved = _set(engine, nf, fields, mode == MEMORY)
            if moved != rel:  # _move_memory already saved it at the new path
                return {**result, "path": moved, "moved_from": rel}
        case "supersede":
            result["changed"], result["by"] = _supersede(engine, nf, by)
            return result  # both notes are already saved
        case "feedback":
            result["changed"] = _feedback(nf, value)
        case "archive":
            result["changed"] = _archive(nf)
        case "dismiss":
            result["changed"] = _dismiss(nf)

    nf.save()
    return result


def _move_memory(engine: Engine, nf: NoteFile) -> str:
    """Save a memory whose type or project changed in ``<zone>/<project>/<type folder>/``.

    The file name stays, so ``[[name]]`` links keep resolving. Links written as a path would
    break, so they block the move, and so does a file with the same name in the new folder.
    """
    validate(nf.fm)
    zone = engine.vault.memory_zone
    assert zone is not None  # nf is in a memory zone
    name = PurePosixPath(nf.rel).name
    new_rel = f"{zone.path}/{nf.fm['project']}/{FOLDERS[nf.fm['type']]}/{name}"
    if new_rel == nf.rel:
        return nf.rel  # revise saves it in place
    by_path = sorted(
        {
            r["src"]
            for r in engine.index.conn.execute(
                "select src, dst_raw from links where dst_path = ? and src != ?",
                (nf.rel, nf.rel),
            )
            if "/" in (r["dst_raw"] or "")
        }
    )
    if by_path:
        raise invalid(
            f"{', '.join(by_path)} link to {nf.rel} by path, and moving it to {new_rel} would "
            f"break them. Change those links to [[{name.removesuffix('.md')}]] first."
        )
    engine.vault.check_writable(new_rel)
    if not engine.vault.create_exclusive(new_rel, nf.text()):
        raise invalid(
            f"{new_rel} already exists, so {nf.rel} cannot move there. "
            "Supersede one of them, or rename one in Obsidian."
        )
    engine.vault.remove(nf.rel)
    engine.index.reindex(nf.rel)
    engine.index.reindex(new_rel)
    return new_rel


def _coerce(key: str, value: Any) -> Any:
    """Dates given as strings in ``set`` are stored as YAML dates; a blank description goes."""
    if key == "description" and isinstance(value, str):
        return value.strip() or None
    if key in ("created", "due", "valid_until") and isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return value
    return value


def _append(nf: NoteFile, text: str, heading: str | None) -> str:
    addition = text.strip("\n")
    lines = nf.body.rstrip("\n").split("\n") if nf.body.strip() else []
    if heading is None:
        return "\n".join(lines + ([""] if lines else []) + [addition]) + "\n"
    parsed = parse(nf.head + nf.body, nf.rel)
    rng = find_section(parsed, heading)
    if rng is None:
        names = ", ".join(f'"{h.text}"' for h in parsed.headings)
        raise EpistemeError(
            NOT_FOUND, f'no heading "{heading}" in {nf.rel}. Headings are: {names or "none"}.'
        )
    start, end = rng[0] - nf.fm_end, min(rng[1] - nf.fm_end, len(lines))
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    tail = lines[end:]
    insert = ["", addition] + ([""] if tail else [])
    return "\n".join(lines[:last] + insert + tail) + "\n"
