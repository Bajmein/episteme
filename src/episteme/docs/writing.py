"""``docs_write``: create or update one note of a docs suite with what the skill downloaded."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme.docs.hashing import body_hash, split_note
from episteme.docs.schema import DATE_KEYS, as_day, is_url, ordered, validate
from episteme.docs.status import find_zone, manifest_path
from episteme.errors import NOT_FOUND, OUTSIDE_VAULT, READ_ONLY_ZONE, EpistemeError, invalid
from episteme.index import NOTE_MAX_BYTES, to_json
from episteme.markdown import compose
from episteme.memory import find_secrets
from episteme.vault import DOCS, Zone, today

if TYPE_CHECKING:
    from episteme.engine import Engine


@dataclass(frozen=True)
class Target:
    """The note docs_write works on: its path and what it holds now (None if it is new)."""

    rel: str
    fm: dict[str, Any] | None
    body: str | None


def _strings(value: Any) -> list[str]:
    """Every string in ``value``, going into lists and dicts (keys included)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list | tuple):
        return [s for item in value for s in _strings(item)]
    return []


def _check_secrets(fields: dict[str, Any]) -> None:
    for text in _strings(fields):
        found = find_secrets(text)
        if found:
            raise invalid(
                f"fields look like a secret ({found}). "
                "Remove it and say where it is stored instead."
            )


def _check_arguments(path: str | None, source: str | None, body: str | None) -> None:
    if path is None and source is None:
        raise invalid("docs_write needs source or path. Pass the page URL or its path.")
    if source is not None and not is_url(source):
        raise invalid(f"source {source!r} is not an http(s) URL. Pass the page URL.")
    if path is not None and not path.lower().endswith(".md"):
        raise invalid(f"path {path!r} must end in .md. Pass a path relative to the suite.")
    if body is not None and len(body.encode("utf-8")) > NOTE_MAX_BYTES:
        limit = NOTE_MAX_BYTES // 1024 // 1024
        raise invalid(f"body is over the {limit} MB limit; episteme would not index it. Skip it.")


def _by_source(engine: Engine, zone: Zone, source: str) -> str | None:
    row = engine.index.conn.execute(
        "select p.path from props p join notes n on n.path = p.path "
        "where n.zone = ? and p.key = 'source' and p.value = ? order by p.path",
        (zone.path, to_json(source)),
    ).fetchone()
    return row["path"] if row else None


def _inside(engine: Engine, zone: Zone, path: str) -> str:
    """``zone/path`` once it is checked to stay in this docs zone."""
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute():
        raise EpistemeError(OUTSIDE_VAULT, f'"{path}" is absolute. Pass a path inside the suite.')
    rel = f"{zone.path}/{pure.as_posix()}"  # PurePosixPath drops "./" and doubled slashes
    real = engine.vault.rel(engine.vault.resolve(rel))
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


def _find(engine: Engine, zone: Zone, path: str | None, source: str | None) -> Target:
    """The note named by ``source`` (else ``path``); a missing one is new at ``path``."""
    found = _by_source(engine, zone, source) if source else None
    rel = _inside(engine, zone, path) if path is not None else None
    if found is not None:
        if rel is not None and rel != found:
            raise invalid(f"{source} is already {found}, not {rel}. Drop path or fix it.")
        return _load(engine, found)
    if rel is None:
        raise EpistemeError(
            NOT_FOUND, f"no note with source {source} in {zone.path}. Pass path to create it."
        )
    target = _load(engine, rel)
    if source is not None and target.fm and target.fm.get("source"):
        raise invalid(
            f"{rel} exists with source {target.fm.get('source')}. "
            "Pass that source, or another path for the new page."
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


def _check_unique_source(engine: Engine, zone: Zone, target: Target, fm: dict[str, Any]) -> None:
    """``invalid_argument`` when a new or changed source already belongs to another note."""
    source = fm.get("source")
    if not isinstance(source, str) or (target.fm or {}).get("source") == source:
        return
    rel = target.rel
    other = _by_source(engine, zone, source)
    if other is not None and other != rel:
        raise invalid(f"source {source} is already used by {other}. Update that note instead.")


def _stamp(fm: dict[str, Any], fields: dict[str, Any], created: bool, day: dt.date) -> None:
    """Fill ``created``/``updated`` of a new note and bump ``updated`` on a change."""
    if created:
        fm.setdefault("created", day)
        fm.setdefault("updated", day)
    elif "updated" not in fields:
        fm["updated"] = day


def docs_write(
    engine: Engine,
    suite: str,
    path: str | None = None,
    source: str | None = None,
    body: str | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update one note of a docs suite; write only when something changed."""
    zone = find_zone(engine.vault, suite)
    fields = fields or {}
    _check_arguments(path, source, body)
    _check_secrets(fields)
    target = _find(engine, zone, path, source)
    created = target.fm is None
    old_fm = target.fm or {}
    old_body = target.body or ""
    new_body = old_body if body is None else body
    fm = _merge(old_fm, fields, source)
    body_changed = created or body_hash(new_body) != body_hash(old_body)
    fields_changed = fm != old_fm
    digest = body_hash(new_body)
    if not (body_changed or fields_changed):
        return {"path": target.rel, "created": False, "changed": False, "hash": digest}
    _stamp(fm, fields, created, today())
    if created:
        fm = ordered(fm)
    validate(fm, target.rel, target.rel == manifest_path(zone))
    _check_unique_source(engine, zone, target, fm)
    _save(engine, target.rel, compose(fm, new_body if body_changed else old_body), created)
    return {"path": target.rel, "created": created, "changed": True, "hash": digest}


def _save(engine: Engine, rel: str, text: str, created: bool) -> None:
    if engine.vault.check_writable(rel) != DOCS:
        raise EpistemeError(READ_ONLY_ZONE, f"{rel} is not in a docs zone. Pick another path.")
    if created:
        if not engine.vault.create_exclusive(rel, text):
            raise invalid(f"{rel} was created meanwhile. Call docs_write again to update it.")
    else:
        engine.vault.write_atomic(rel, text)
    engine.index.reindex(rel)

