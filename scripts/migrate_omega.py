"""Migrate an OMEGA ``export-obsidian`` folder into episteme memories.

    uv run scripts/migrate_omega.py --export <omega-memories> --vault <vault> \
        --project fabrik [--dry-run]

Writes with the same validation and duplicate detection as ``remember``, so a second run
creates nothing new.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from episteme_mcp import memory
from episteme_mcp.engine import Engine
from episteme_mcp.errors import EpistemeError, StartupError
from episteme_mcp.markdown import load_frontmatter, split_frontmatter

TYPE_MAP = {
    "decision": "decision",
    "lesson_learned": "lesson",
    "error_pattern": "error",
    "constraint": "constraint",
    "user_preference": "preference",
    "session_summary": "session",
    "project_status": "insight",
    "memory": "insight",
    "task_completion": "insight",
}
DISCARDED = {"checkpoint"}
TITLE_MAX = 80
RELATED_RE = re.compile(r"^\s*-\s*\[\[(mem-[0-9a-f]+)\]\]")


@dataclass
class OmegaMemory:
    id: str
    omega_type: str
    tags: list[str]
    created: dt.date | None
    text: str
    related: list[str] = field(default_factory=list)
    access_count: int = 0
    source: str | None = None
    file: Path | None = None

    @property
    def title(self) -> str:
        for line in self.text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:TITLE_MAX].rstrip()
        return self.id


def convert_tags(tags: list[str]) -> list[str]:
    """Keep prefixed tags (``dominio:auth`` → ``dominio/auth``); drop paths and bare words."""
    out = []
    for tag in tags:
        tag = str(tag).strip()
        if tag.startswith("/") or ":" not in tag:
            continue
        new = "/".join(part.strip() for part in tag.split(":") if part.strip())
        new = re.sub(r"[\s#]+", "-", new)
        if new and new not in out:
            out.append(new)
    return out


def _date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def parse_export_note(path: Path) -> OmegaMemory | None:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    raw, fm_end = split_frontmatter(lines)
    fm, ok, _ = load_frontmatter(raw)
    if not ok or "id" not in fm:
        return None
    text: list[str] = []
    related: list[str] = []
    access = 0
    source = None
    section = None
    for line in lines[fm_end:]:
        heading = re.match(r"^##\s+(Related|Metadata)\s*$", line.strip())
        if heading:
            section = heading.group(1)
            continue
        if section is None:
            text.append(line)
        elif section == "Related":
            m = RELATED_RE.match(line)
            if m:
                related.append(m.group(1))
        elif section == "Metadata":
            m = re.match(r"^\s*-\s*Access count:\s*(\d+)", line)
            if m:
                access = int(m.group(1))
            m = re.match(r"^\s*-\s*Source:\s*(.+?)\s*$", line)
            if m:
                source = m.group(1)
    tags = fm.get("tags") or []
    return OmegaMemory(
        id=str(fm["id"]),
        omega_type=str(fm.get("type", "")),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [str(tags)],
        created=_date(fm.get("created")),
        text="\n".join(text).strip(),
        related=related,
        access_count=access,
        source=source,
        file=path,
    )


def load_export(export: Path) -> list[OmegaMemory]:
    notes = []
    for path in sorted(export.rglob("*.md")):
        if path.name == "_index.md":
            continue
        note = parse_export_note(path)
        if note is not None:
            notes.append(note)
    return notes


def migrate(
    export: Path, vault: Path, project: str, dry_run: bool = False, out: TextIO = sys.stdout
) -> Counter[str]:
    engine = Engine(vault, project)
    engine.index.refresh()
    done: Counter[str] = Counter()
    paths: dict[str, str] = {}
    pending: list[tuple[str, OmegaMemory]] = []

    for note in load_export(export):
        if note.omega_type in DISCARDED or note.omega_type not in TYPE_MAP:
            reason = "descartada" if note.omega_type in DISCARDED else "tipo desconocido"
            print(f"- {note.omega_type} ({reason}) {note.id}", file=out)
            done[f"descartada:{note.omega_type}"] += 1
            continue
        type_ = TYPE_MAP[note.omega_type]
        try:
            res = memory.remember(
                engine,
                type_,
                note.title,
                note.text,
                tags=convert_tags(note.tags),
                source=note.source,
                created=note.created,
                helpful=note.access_count,
                dry_run=dry_run,
            )
        except EpistemeError as exc:
            print(f"! {note.omega_type} {note.id}: {exc}", file=out)
            done[f"error:{type_}"] += 1
            continue
        if res["created"]:
            paths[note.id] = res["path"]
            print(f"+ {type_} → {res['path']}", file=out)
            done[type_] += 1
        else:
            paths[note.id] = res["similar"][0]["path"]
            print(f"= {type_} → {paths[note.id]} (ya existe)", file=out)
            done[f"existente:{type_}"] += 1
        if note.related:
            pending.append((paths[note.id], note))

    # Second pass: OMEGA ids → wikilinks to the new files.
    for rel, note in pending:
        targets = [paths[r] for r in note.related if r in paths and paths[r] != rel]
        if not targets or dry_run:
            continue
        nf = memory.NoteFile(engine, rel)
        current = nf.fm.get("related") or []
        current = current if isinstance(current, list) else [current]
        links = list(current)
        for target in targets:
            link = memory.wikilink(engine, target)
            if link not in links:
                links.append(link)
        if links != current:
            nf.set_fields({"related": links})
            nf.save()

    summary = ", ".join(f"{k} {v}" for k, v in sorted(done.items())) or "nada"
    prefix = "Resumen (dry-run)" if dry_run else "Resumen"
    print(f"{prefix}: {summary}", file=out)
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate an OMEGA export into episteme.")
    parser.add_argument("--export", required=True, help="the omega-memories/ folder")
    parser.add_argument("--vault", required=True, help="destination vault (with episteme.toml)")
    parser.add_argument("--project", required=True, help="project of the memories, e.g. fabrik")
    parser.add_argument("--dry-run", action="store_true", help="show what would be done")
    args = parser.parse_args(argv)
    export = Path(args.export).expanduser()
    vault = Path(args.vault).expanduser().resolve()
    if not export.is_dir():
        print(f"migrate_omega: {export} is not a folder.", file=sys.stderr)
        return 2
    if not (vault / "episteme.toml").is_file():
        print(f"migrate_omega: {vault} has no episteme.toml.", file=sys.stderr)
        return 2
    try:
        migrate(export, vault, args.project, args.dry_run)
    except StartupError as exc:
        print(f"migrate_omega: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
