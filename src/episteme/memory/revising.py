"""Revising memories: ``revise`` and its helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.errors import NOT_FOUND, EpistemeError, invalid
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
    kind_for,
    validate,
    wikilink,
)
from episteme.memory.secrets import _reject_secrets, find_secrets
from episteme.vault import MEMORY

if TYPE_CHECKING:
    from episteme.engine import Engine


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
    if action in MEMORY_ACTIONS and mode != MEMORY:
        raise invalid(f'action "{action}" only applies to memories, and {rel} is not one.')
    nf = NoteFile(engine, rel)
    result: dict[str, Any] = {"path": rel, "action": action, "changed": []}

    if action == "edit":
        if not old or new is None:
            raise invalid("edit needs old (text to replace) and new.")
        if find_secrets(new) != find_secrets(old):  # editing around an old false positive is fine
            _reject_secrets("new", new)
        count = nf.body.count(old)
        if count != 1:
            raise invalid(
                f"old appears {count} times in {rel}; it must appear exactly once. "
                "Include more surrounding text."
            )
        nf.body = nf.body.replace(old, new, 1)
        result["changed"] = ["body"]
    elif action == "append":
        if not text:
            raise invalid("append needs text.")
        _reject_secrets("text", text)
        nf.body = _append(nf, text, heading)
        result["changed"] = ["body"]
    elif action == "set":
        if not fields:
            raise invalid('set needs fields, e.g. {"priority": 5}.')
        for key, value_ in fields.items():
            _reject_secrets(f"fields.{key}", value_)
        fields = {k: _coerce(k, v) for k, v in fields.items()}
        result["changed"] = nf.set_fields(fields)
        if mode == MEMORY and {"type", "project"} & set(result["changed"]):
            if "type" in result["changed"] and nf.fm.get("type") in TYPES:
                result["changed"] += nf.set_fields({"kind": kind_for(nf.fm["type"])})
            moved = _move_memory(engine, nf)
            if moved != rel:
                result["path"] = moved
                result["moved_from"] = rel
                return result
    elif action == "supersede":
        if not by:
            raise invalid("supersede needs by (the note that replaces this one).")
        by_rel = engine.resolve_note(by)
        if by_rel == rel:
            raise invalid("a note cannot supersede itself.")
        if engine.vault.check_writable(by_rel) != MEMORY:
            raise invalid(f"{by_rel} is not a memory. Create the replacement with remember.")
        newer = NoteFile(engine, by_rel)
        link = wikilink(engine, rel)
        current = newer.fm.get("supersedes")
        if current and current != link:
            current = current if isinstance(current, list) else [current]
            link_value: Any = current + ([link] if link not in current else [])
        else:
            link_value = link
        result["changed"] = nf.set_fields({"status": "superseded"})
        newer.set_fields({"supersedes": link_value})
        validate(nf.fm)
        validate(newer.fm)
        nf.save()
        newer.save()
        result["by"] = by_rel
        return result
    elif action == "feedback":
        if value not in ("helpful", "unhelpful", "outdated"):
            raise invalid('feedback value must be "helpful", "unhelpful" or "outdated".')
        current = nf.fm.get("helpful")
        helpful = as_int(current) or 0
        if value == "helpful":
            result["changed"] = nf.set_fields({"helpful": helpful + 1})
        elif value == "unhelpful":
            result["changed"] = nf.set_fields({"helpful": max(0, helpful - 1)})
        else:
            result["changed"] = nf.set_fields({"flagged": True})
    elif action == "archive":
        result["changed"] = nf.set_fields({"status": "archived"})
    elif action == "dismiss":
        if nf.fm.get("type") != "reminder":
            raise invalid(f"dismiss only applies to reminders, and {rel} is not one.")
        result["changed"] = nf.set_fields({"status": "archived"})

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
    """Dates given as strings in ``set`` are stored as YAML dates."""
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
