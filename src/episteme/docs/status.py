"""``docs_status``: the docs zones with their counts, and the page list a suite check needs."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from episteme.docs.hashing import body_hash, split_note
from episteme.docs.inbox import inbox_dir
from episteme.docs.schema import MANIFEST, SUITE_KEYS, is_url, manifest_errors, note_errors
from episteme.errors import AMBIGUOUS, NOT_FOUND, READ_ONLY_ZONE, EpistemeError, invalid
from episteme.vault import Vault, Zone

if TYPE_CHECKING:
    from episteme.engine import Engine

def _suite_name(suite: str) -> str:
    name = suite.strip().strip("/") if isinstance(suite, str) else ""
    if not name:
        raise invalid("suite is empty. Pass a docs zone such as docs/mise, or mise.")
    return name


def _named(zone: Zone, name: str) -> bool:
    return name in (zone.path, zone.path.rsplit("/", 1)[-1])


def find_zone(vault: Vault, suite: str) -> Zone:
    """The docs zone named by its path (``docs/mise``) or its last segment (``mise``)."""
    name = _suite_name(suite)
    found = [z for z in vault.docs_zones if _named(z, name)]
    if len(found) > 1:
        paths = ", ".join(z.path for z in found)
        raise EpistemeError(AMBIGUOUS, f'suite "{name}" matches {paths}. Pass the full path.')
    if not found:
        raise _not_a_suite(vault, name)
    return found[0]


def _not_a_suite(vault: Vault, name: str) -> EpistemeError:
    """``read_only_zone`` for a zone of another mode, else ``not_found``."""
    other = next((z for z in vault.config.zones if z.path == name), None)
    if other is not None:
        return EpistemeError(
            READ_ONLY_ZONE,
            f'{name} is a {other.mode} zone, not a docs zone. Only zones with mode = "docs" '
            "in episteme.toml are suites.",
        )
    return EpistemeError(NOT_FOUND, f'no docs zone "{name}". Call docs_status() to list them.')


def manifest_path(zone: Zone) -> str:
    return f"{zone.path}/{MANIFEST}"


def suite_notes(engine: Engine, zone: Zone) -> dict[str, dict[str, Any] | None]:
    """Every indexed note of the zone with its frontmatter (None when it does not parse)."""
    conn = engine.index.conn
    notes: dict[str, dict[str, Any] | None] = {
        r["path"]: {} if r["fm_valid"] else None
        for r in conn.execute(
            "select path, fm_valid from notes where zone = ? order by path", (zone.path,)
        )
    }
    rows = conn.execute(
        "select p.path, p.key, p.value from props p join notes n on n.path = p.path "
        "where n.zone = ?",
        (zone.path,),
    )
    for r in rows:
        fm = notes.get(r["path"])
        if fm is not None:
            fm[r["key"]] = json.loads(r["value"])
    return notes


def _is_invalid(fm: dict[str, Any] | None) -> bool:
    return fm is None or bool(note_errors(fm))


def _manifest_fields(fm: dict[str, Any] | None) -> dict[str, Any]:
    suite = fm.get("suite") if fm else None
    if not isinstance(suite, dict):
        suite = {}
    return {key: suite.get(key) for key in SUITE_KEYS}


def _has_source(fm: dict[str, Any]) -> bool:
    return is_url(fm.get("source"))


def _is_deprecated(fm: dict[str, Any]) -> bool:
    return fm.get("status") == "deprecated"


def _manifest_valid(manifest: dict[str, Any] | None) -> bool:
    return manifest is not None and not manifest_errors(manifest)


def _summary(vault: Vault, zone: Zone, notes: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    notes = dict(notes)
    manifest = notes.pop(manifest_path(zone), None)
    pages = [fm for fm in notes.values() if fm is not None]
    return {
        "suite": zone.path,
        "inbox": os.fspath(inbox_dir(vault, zone)),
        "notes": len(notes),
        "with_source": len(list(filter(_has_source, pages))),
        "deprecated": len(list(filter(_is_deprecated, pages))),
        "invalid": len(list(filter(_is_invalid, notes.values()))),
        "manifest_valid": _manifest_valid(manifest),
        **_manifest_fields(manifest),
    }


def _page_line(engine: Engine, zone: Zone, rel: str, fm: dict[str, Any]) -> str | None:
    """``<source>\\t<hash>\\t<path in the suite>\\t<status>``, or None if the note vanished."""
    try:
        text = engine.vault.resolve(rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    digest = body_hash(split_note(text).body)
    inner = rel.removeprefix(zone.path + "/")
    return f"{fm['source']}\t{digest}\t{inner}\t{fm.get('status', '')}"


def _pages(engine: Engine, zone: Zone, notes: dict[str, dict[str, Any] | None]) -> str:
    lines = []
    for rel, fm in notes.items():
        if fm and is_url(fm.get("source")):
            line = _page_line(engine, zone, rel, fm)
            if line is not None:
                lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def docs_status(engine: Engine, suite: str | None = None, pages: bool = False) -> dict[str, Any]:
    """The docs zones with their counts; one zone, plus its pages as TSV when asked."""
    if suite is None:
        if pages:
            raise invalid("pages needs a suite. Pass suite, e.g. docs_status(suite=\"mise\").")
        zones = engine.vault.docs_zones
        return {"suites": [_summary(engine.vault, z, suite_notes(engine, z)) for z in zones]}
    zone = find_zone(engine.vault, suite)
    notes = suite_notes(engine, zone)
    result = _summary(engine.vault, zone, notes)
    if pages:
        result["pages"] = _pages(engine, zone, notes)
    return result
