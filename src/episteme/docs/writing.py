"""``docs(action="write")``: create or update one note of a docs suite from downloaded pages."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.docs.hashing import body_hash, page_body, split_note
from episteme.docs.inbox import check_ref, discard, read_body
from episteme.docs.schema import DATE_KEYS, as_day, is_url, ordered, validate
from episteme.docs.status import find_zone, manifest_path
from episteme.errors import NOT_FOUND, OUTSIDE_VAULT, READ_ONLY_ZONE, EpistemeError, invalid
from episteme.index import NOTE_MAX_BYTES, to_json
from episteme.markdown import compose
from episteme.memory import find_secrets
from episteme.vault import DOCS, Zone, is_ignored, today

if TYPE_CHECKING:
    from episteme.engine import Engine


@dataclass(frozen=True)
class Target:
    """The note docs(action="write") works on: its path and what it holds now (None if new)."""

    rel: str
    fm: dict[str, Any] | None
    body: str | None


def _strings(value: Any) -> list[str]:
    """Every string in ``value``, going into lists and dicts (keys included)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = [*value.keys(), *value.values()]
    if not isinstance(value, list | tuple):
        return []
    return [s for item in value for s in _strings(item)]


def _check_secrets(fields: dict[str, Any]) -> None:
    for text in _strings(fields):
        found = find_secrets(text)
        if found:
            raise invalid(
                f"fields look like a secret ({found}). "
                "Remove it and say where it is stored instead."
            )


def _bad_source(source: str | None) -> bool:
    return source is not None and not is_url(source)


def _bad_path(path: str | None) -> bool:
    return path is not None and not path.lower().endswith(".md")


def _too_big(body: str | None) -> bool:
    return body is not None and len(body.encode("utf-8")) > NOTE_MAX_BYTES


def _check_target(path: str | None, source: str | None) -> None:
    if path is None and source is None:
        raise invalid("docs(action='write') needs source or path. Pass the page URL or its path.")
    if _bad_source(source):
        raise invalid(f"source {source!r} is not an http(s) URL. Pass the page URL.")
    if _bad_path(path):
        raise invalid(f"path {path!r} must end in .md. Pass a path relative to the suite.")


def _check_arguments(
    path: str | None, source: str | None, body: str | None, body_ref: str | None
) -> None:
    _check_target(path, source)
    if body is not None and body_ref is not None:
        raise invalid("pass body or body_ref, not both. Use body_ref for a downloaded page.")
    check_ref(body_ref)
    if _too_big(body):
        limit = NOTE_MAX_BYTES // 1024 // 1024
        raise invalid(f"body is over the {limit} MB limit; episteme would not index it. Skip it.")


def _resolve_body(
    engine: Engine, zone: Zone, body: str | None, body_ref: str | None
) -> tuple[str | None, Path | None]:
    """The body to write, without the frontmatter a page brings, and the inbox file it came
    from (None when it was passed inline)."""
    file = None
    if body_ref is not None:
        body, file = read_body(engine.vault, zone, body_ref)
    return (None if body is None else page_body(body)), file


def _consume(file: Path | None) -> None:
    if file is not None:
        discard(file)


def _by_source(engine: Engine, zone: Zone, source: str) -> str | None:
    row = engine.index.conn.execute(
        "select p.path from props p join notes n on n.path = p.path "
        "where n.zone = ? and p.key = 'source' and p.value = ? order by p.path",
        (zone.path, to_json(source)),
    ).fetchone()
    return row["path"] if row else None


def _joined(zone: Zone, path: str) -> str:
    """``zone/path`` with ``./`` and doubled slashes dropped; an absolute path fails."""
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute():
        raise EpistemeError(OUTSIDE_VAULT, f'"{path}" is absolute. Pass a path inside the suite.')
    return f"{zone.path}/{pure.as_posix()}"


def _inside(engine: Engine, zone: Zone, path: str) -> str:
    """``zone/path`` once it is checked to stay in this docs zone."""
    rel = _joined(zone, path)
    real = engine.vault.rel(engine.vault.resolve(rel))
    if is_ignored(real):
        raise invalid(f'"{path}" is in a hidden folder the index skips. Pick another path.')
    if not real.startswith(zone.path + "/"):
        raise EpistemeError(OUTSIDE_VAULT, f'"{path}" leaves {zone.path}. Pass a path inside it.')
    engine.vault.check_writable(rel)
    if engine.vault.zone_for(real) != zone:
        raise EpistemeError(
            READ_ONLY_ZONE, f"{real} is in another zone, not in {zone.path}. Pick another path."
        )
    return rel


def _load(engine: Engine, rel: str) -> Target:
    try:
        text = engine.vault.resolve(rel).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return Target(rel, None, None)
    note = split_note(text)
    # A frontmatter that does not parse is rebuilt from fields alone.
    return Target(rel, note.frontmatter if note.fm_valid else {}, note.body)


def _found_by_source(engine: Engine, found: str, rel: str | None, source: str | None) -> Target:
    """The note that already has ``source``; ``path``, if given, must name the same note."""
    if rel is not None and rel != found:
        raise invalid(f"{source} is already {found}, not {rel}. Drop path or fix it.")
    return _load(engine, found)


def _other_source(target: Target, source: str | None) -> Any:
    """The source the note at ``path`` already has when the call brings a different one."""
    if source is None or not target.fm:
        return None
    return target.fm.get("source")


def _find(engine: Engine, zone: Zone, path: str | None, source: str | None) -> Target:
    """The note named by ``source`` (else ``path``); a missing one is new at ``path``."""
    found = _by_source(engine, zone, source) if source else None
    rel = _inside(engine, zone, path) if path is not None else None
    if found is not None:
        return _found_by_source(engine, found, rel, source)
    if rel is None:
        raise EpistemeError(
            NOT_FOUND, f"no note with source {source} in {zone.path}. Pass path to create it."
        )
    target = _load(engine, rel)
    other = _other_source(target, source)
    if other:
        raise invalid(
            f"{rel} exists with source {other}. Pass that source, or another path for the new page."
        )
    return target


def _coerce(fields: dict[str, Any]) -> dict[str, Any]:
    """Dates given as ``YYYY-MM-DD`` strings are stored as YAML dates."""
    out = dict(fields)
    for key in DATE_KEYS:
        day = as_day(out.get(key))
        if day is not None:
            out[key] = day
    suite = out.get("suite")
    if isinstance(suite, dict) and as_day(suite.get("synced")) is not None:
        out["suite"] = {**suite, "synced": as_day(suite["synced"])}
    return out


def _merge(old: dict[str, Any], fields: dict[str, Any], source: str | None) -> dict[str, Any]:
    fm = dict(old)
    for key, value in _coerce(fields).items():
        if value is None:
            fm.pop(key, None)
        else:
            fm[key] = value
    if source is not None:
        fm["source"] = source
    return fm


def _new_source(target: Target, fm: dict[str, Any]) -> str | None:
    """The source of ``fm`` when it is a string the note did not have before."""
    source = fm.get("source")
    if not isinstance(source, str):
        return None
    return None if (target.fm or {}).get("source") == source else source


def _check_unique_source(engine: Engine, zone: Zone, target: Target, fm: dict[str, Any]) -> None:
    """``invalid_argument`` when a new or changed source already belongs to another note."""
    source = _new_source(target, fm)
    if source is None:
        return
    other = _by_source(engine, zone, source)
    if other not in (None, target.rel):
        raise invalid(f"source {source} is already used by {other}. Update that note instead.")


def _stamp(fm: dict[str, Any], fields: dict[str, Any], created: bool, day: dt.date) -> None:
    """Fill ``created``/``updated`` of a new note and bump ``updated`` on a change."""
    if created:
        fm.setdefault("created", day)
        fm.setdefault("updated", day)
    elif "updated" not in fields:
        fm["updated"] = day


# @CodeScene(disable:"Excess Number of Function Arguments")
def docs_write(
    engine: Engine,
    suite: str,
    path: str | None = None,
    source: str | None = None,
    body: str | None = None,
    body_ref: str | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update one note of a docs suite; write only when something changed."""
    zone = find_zone(engine.vault, suite)
    fields = fields or {}
    _check_arguments(path, source, body, body_ref)
    _check_secrets(fields)
    text, inbox_file = _resolve_body(engine, zone, body, body_ref)
    target = _find(engine, zone, path, source)
    change = _change(target, fields, source, text)
    result = {"path": target.rel, "created": False, "changed": False, "hash": change.hash}
    if not change.changed:
        _consume(inbox_file)
        return result
    fm = _finish(change, fields)
    validate(fm, target.rel, target.rel == manifest_path(zone))
    _check_unique_source(engine, zone, target, fm)
    _save(engine, target.rel, compose(fm, change.body), change.created)
    _consume(inbox_file)
    return {**result, "created": change.created, "changed": True}


@dataclass(frozen=True)
class Change:
    """What docs(action="write") would leave in the note: frontmatter, body, if it differs."""

    fm: dict[str, Any]
    body: str
    created: bool
    changed: bool

    @property
    def hash(self) -> str:
        return body_hash(self.body)


def _new_body(old: str, body: str | None) -> str:
    """``body`` when its hash differs from the current one, else the current body."""
    if body is None or body_hash(body) == body_hash(old):
        return old
    return body


def _change(target: Target, fields: dict[str, Any], source: str | None, body: str | None) -> Change:
    created = target.fm is None
    old_fm = target.fm or {}
    old_body = target.body or ""
    new_body = _new_body(old_body, body)
    fm = _merge(old_fm, fields, source)
    changed = created or fm != old_fm or new_body != old_body
    return Change(fm, new_body, created, changed)


def _finish(change: Change, fields: dict[str, Any]) -> dict[str, Any]:
    """The frontmatter to write: dates stamped, and the key order of a new note."""
    fm = dict(change.fm)
    _stamp(fm, fields, change.created, today())
    return ordered(fm) if change.created else fm


def _save(engine: Engine, rel: str, text: str, created: bool) -> None:
    if engine.vault.check_writable(rel) != DOCS:
        raise EpistemeError(READ_ONLY_ZONE, f"{rel} is not in a docs zone. Pick another path.")
    if created:
        if not engine.vault.create_exclusive(rel, text):
            raise invalid(
                f"{rel} was created meanwhile. Call docs(action='write') again to update it."
            )
    else:
        engine.vault.write_atomic(rel, text)
    engine.index.reindex(rel)

