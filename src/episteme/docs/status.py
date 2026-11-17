"""``docs_status``: the docs zones with their counts, and the page list a suite check needs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from episteme.docs.hashing import body_hash, split_note
from episteme.docs.schema import MANIFEST, is_url, manifest_errors, note_errors
from episteme.errors import AMBIGUOUS, NOT_FOUND, READ_ONLY_ZONE, EpistemeError, invalid
from episteme.vault import Vault, Zone

if TYPE_CHECKING:
    from episteme.engine import Engine

SUITE_FIELDS = ("upstream", "include", "context7", "synced")


def find_zone(vault: Vault, suite: str) -> Zone:
    """The docs zone named by its path (``docs/mise``) or its last segment (``mise``)."""
    if not isinstance(suite, str) or not suite.strip("/ "):
        raise invalid("suite is empty. Pass a docs zone such as docs/mise, or mise.")
    name = suite.strip().strip("/")
    found = [z for z in vault.docs_zones if name in (z.path, z.path.rsplit("/", 1)[-1])]
    if len(found) > 1:
        paths = ", ".join(z.path for z in found)
        raise EpistemeError(AMBIGUOUS, f'suite "{name}" matches {paths}. Pass the full path.')
    if found:
        return found[0]
    other = next((z for z in vault.config.zones if z.path == name), None)
    if other is not None:
        raise EpistemeError(
            READ_ONLY_ZONE,
            f'{name} is a {other.mode} zone, not a docs zone. Only zones with mode = "docs" '
            "in episteme.toml are suites.",
        )
    raise EpistemeError(NOT_FOUND, f'no docs zone "{name}". Call docs_status() to list them.')


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
    return {key: suite.get(key) for key in SUITE_FIELDS}


def _summary(engine: Engine, zone: Zone) -> dict[str, Any]:
    notes = suite_notes(engine, zone)
    manifest = notes.pop(manifest_path(zone), None)
    pages = [fm for fm in notes.values() if fm is not None]
    return {
        "suite": zone.path,
        "notes": len(notes),
        "with_source": sum(1 for fm in pages if fm.get("source")),
        "deprecated": sum(1 for fm in pages if fm.get("status") == "deprecated"),
        "invalid": sum(1 for fm in notes.values() if _is_invalid(fm)),
        "manifest_valid": manifest is not None and not manifest_errors(manifest),
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


def _pages(engine: Engine, zone: Zone) -> str:
    lines = []
    for rel, fm in suite_notes(engine, zone).items():
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
        return {"suites": [_summary(engine, z) for z in engine.vault.docs_zones]}
    zone = find_zone(engine.vault, suite)
    result = _summary(engine, zone)
    if pages:
        result["pages"] = _pages(engine, zone)
    return result
