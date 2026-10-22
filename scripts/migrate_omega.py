"""Migrate an OMEGA ``export-obsidian`` folder into episteme memories.

    uv run scripts/migrate_omega.py --export <omega-memories> --vault <vault> \
        --project fabrik [--omega-db ~/.omega/omega.db] \
        [--map-project /home/ana/src/fabrik=fabrik] [--dry-run]

Writes with the same validation and duplicate detection as ``remember``, so a second run
creates nothing new. ``--omega-db`` is opened read-only (``mode=ro``): it supplies the
``priority`` the export lacks and the pending reminders (``metadata.reminder_status``).
Nothing under ``~/.omega`` is ever written.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from episteme import memory
from episteme.engine import Engine
from episteme.errors import EpistemeError, StartupError
from episteme.markdown import load_frontmatter, split_frontmatter

TYPE_MAP = {
    "decision": "decision",
    "lesson_learned": "lesson",
    "error_pattern": "error",
    "constraint": "constraint",
    "user_preference": "preference",
    "session_summary": "session",
    "memory": "insight",
    "task_completion": "insight",
}
DISCARDED = {"checkpoint", "project_status"}
TITLE_MAX = 80
SOURCE_PREFIX = "omega:"
RELATED_RE = re.compile(r"^\s*-\s*\[\[(mem-[0-9a-f]+)\]\]")
# «fabrik (05-10-2026): », «GI (x), 03-09-2026: », «vigilia, 23-09-2026: »
DATE_PREFIX_RE = re.compile(
    r"^[^\W\d_][\w .\-/]{0,40}?\s*[(,][^:\n]{0,100}?\b\d{1,2}-\d{1,2}-\d{4}\b[^:\n]{0,100}:\s+"
)
TYPE_PREFIX_RE = re.compile(r"^(?:Decisi[oó]n|Decision|Lesson|Assistant fix)\s*:\s*", re.IGNORECASE)
AUTO_TEXT_RE = re.compile(r"^(?:Project:\s.*\|\s*Key decisions:|Session summary:)")
# Text the Claude Code harness wraps around messages (a subagent's report, another session's
# message), saved as if it were a memory.
HARNESS_TEXT_RE = re.compile(
    r"^<(?:agent-message|cross-session-message|system-reminder|task-notification)\b"
)


@dataclass
class OmegaMemory:
    id: str
    omega_type: str
    tags: list[str]
    created: dt.date | None
    text: str
    related: list[str] = field(default_factory=list)
    source: str | None = None
    project: str | None = None
    priority: int | None = None
    status: str | None = None
    due: dt.date | None = None
    file: Path | None = None

    @property
    def title(self) -> str:
        for line in self.text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:TITLE_MAX].rstrip()
        return self.id


def clean_text(text: str) -> str:
    """Drop the «fabrik (fecha):», «Decision:», «Lesson:» and «Assistant fix:» prefixes."""
    out = text.strip()
    for _ in range(3):
        new = TYPE_PREFIX_RE.sub("", out, count=1)
        new = DATE_PREFIX_RE.sub("", new, count=1)
        if new == out:
            break
        out = new
    return out.strip() or text.strip()


def is_auto_capture(text: str, source: str | None) -> bool:
    """Captures made by OMEGA's own hooks (session stop), not written on purpose."""
    src = (source or "").strip()
    if src.startswith("session_stop") or src.endswith("_auto"):
        return True
    return bool(AUTO_TEXT_RE.match(text.strip()))


def split_tags(tags: list[str], roots: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Split OMEGA tags into episteme ``tags`` and ``files``.

    ``dominio:auth`` becomes the tag ``dominio/auth``; a tag with a path (``/rules/x.md``)
    becomes the project-relative file ``rules/x.md``; bare words are dropped.
    """
    out: list[str] = []
    files: list[str] = []
    for tag in tags:
        tag = str(tag).strip()
        if tag.startswith("/"):
            path = tag.rstrip("/")
            for root in roots:
                root = root.rstrip("/")
                if path == root:
                    path = ""
                    break
                if path.startswith(root + "/"):
                    path = path[len(root) :]
                    break
            path = path.lstrip("/")
            if path and path not in files:
                files.append(path)
            continue
        if ":" not in tag:
            continue
        new = "/".join(part.strip() for part in tag.split(":") if part.strip())
        new = re.sub(r"[\s#]+", "-", new)
        if new and new not in out:
            out.append(new)
    return out, files


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


def _priority(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        return None
    return value


def parse_export_note(path: Path) -> OmegaMemory | None:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    raw, fm_end = split_frontmatter(lines)
    fm, ok, _ = load_frontmatter(raw)
    if not ok or "id" not in fm:
        return None
    text: list[str] = []
    related: list[str] = []
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
            m = re.match(r"^\s*-\s*Source:\s*(.+?)\s*$", line)
            if m:
                source = m.group(1)
    tags = fm.get("tags") or []
    project = fm.get("project")
    return OmegaMemory(
        id=str(fm["id"]),
        omega_type=str(fm.get("type", "")),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [str(tags)],
        created=_date(fm.get("created")),
        text="\n".join(text).strip(),
        related=related,
        source=source,
        project=str(project) if project else None,
        priority=_priority(fm.get("priority")),
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


def load_db(path: Path) -> dict[str, OmegaMemory]:
    """Read ``memories`` from an OMEGA database, read-only. Keys are the ``mem-…`` ids."""
    uri = f"file:{path.resolve()}?mode=ro"
    rows: dict[str, OmegaMemory] = {}
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("pragma query_only = on")
        query = (
            "select node_id, content, metadata, created_at, event_type, project, priority, status"
            " from memories order by id"
        )
        for node_id, content, meta, created, event, project, priority, status in conn.execute(
            query
        ):
            try:
                data = json.loads(meta) if meta else {}
            except ValueError:
                data = {}
            data = data if isinstance(data, dict) else {}
            tags = data.get("tags")
            remind_at = data.get("remind_at")
            text = str(content or "").strip()
            if data.get("context") and event == "reminder":
                text = f"{text}\n\nContexto: {str(data['context']).strip()}"
            rows[str(node_id)] = OmegaMemory(
                id=str(node_id),
                omega_type=str(event or ""),
                tags=[str(t) for t in tags] if isinstance(tags, list) else [],
                created=_date(created),
                text=text,
                source=str(data["source"]) if data.get("source") else None,
                project=str(project) if project else None,
                priority=_priority(priority),
                status=str(data["reminder_status"]) if event == "reminder" else str(status or ""),
                due=_date(remind_at),
            )
    return rows


def _project_for(value: str | None, project: str, mapping: dict[str, str]) -> str | None:
    """Destination project of a note; ``None`` when it is neither ``project`` nor mapped."""
    if not value:
        return project
    value = value.rstrip("/") or value
    if value in mapping:
        return mapping[value]
    return project if value == project else None


def _existing_by_source(engine: Engine, source: str) -> str | None:
    row = engine.index.conn.execute(
        "select path from props where key = 'source' and value = ? order by path",
        (json.dumps(source),),
    ).fetchone()
    return row["path"] if row else None


def migrate(
    export: Path,
    vault: Path,
    project: str,
    dry_run: bool = False,
    out: TextIO = sys.stdout,
    *,
    omega_db: Path | None = None,
    project_map: dict[str, str] | None = None,
) -> Counter[str]:
    engine = Engine(vault, project)
    engine.index.refresh()
    mapping = {k.rstrip("/") or k: v for k, v in (project_map or {}).items()}
    db = load_db(omega_db) if omega_db is not None else {}
    done: Counter[str] = Counter()
    paths: dict[str, str] = {}
    candidates: list[tuple[str, str, OmegaMemory]] = []  # (destination project, type, note)

    def skip(note: OmegaMemory, reason: str, key: str | None = None) -> None:
        print(f"- {note.omega_type} ({reason}) {note.id}", file=out)
        done[f"{'omitida' if key == 'proyecto' else 'descartada'}:{key or note.omega_type}"] += 1

    notes = [n for n in load_export(export) if n.omega_type != "reminder"]
    notes += [n for n in db.values() if n.omega_type == "reminder"]
    for note in notes:
        row = db.get(note.id)
        if row is not None and row is not note:
            note.priority = note.priority or row.priority
            note.project = note.project or row.project
            note.status = row.status
            note.source = note.source or row.source
        if note.omega_type == "reminder":
            if note.status != "pending":
                skip(note, f"reminder {note.status or 'sin estado'}", "reminder")
                continue
            type_ = "reminder"
        elif note.omega_type in DISCARDED:
            skip(note, "descartada")
            continue
        elif note.omega_type not in TYPE_MAP:
            skip(note, "tipo desconocido")
            continue
        else:
            type_ = TYPE_MAP[note.omega_type]
        if note.text.lower().startswith("edit pattern"):
            skip(note, "edit pattern", "edit-pattern")
            continue
        if is_auto_capture(note.text, note.source):
            skip(note, "captura automática", "captura-automatica")
            continue
        if HARNESS_TEXT_RE.match(note.text.strip()):
            skip(note, "texto del harness", "harness")
            continue
        if note.status == "superseded":
            skip(note, "reemplazada en OMEGA", "superseded")
            continue
        dest = _project_for(note.project, project, mapping)
        if dest is None:
            skip(note, f"proyecto {note.project}", "proyecto")
            continue
        note.text = clean_text(note.text)
        candidates.append((dest, type_, note))

    # Duplicates inside the batch: the most recent by date stays (ties: the larger id).
    kept: list[tuple[str, str, OmegaMemory]] = []
    tokens: dict[tuple[str, str], list[tuple[set[str], OmegaMemory]]] = {}
    newest_first = sorted(
        candidates, key=lambda c: (c[2].created or dt.date.min, c[2].id), reverse=True
    )
    for dest, type_, note in newest_first:
        mine = memory.dedup_tokens(note.title, note.text)
        winner = next(
            (
                other
                for theirs, other in tokens.get((dest, type_), [])
                if memory.similarity(mine, theirs) >= memory.DUPLICATE
            ),
            None,
        )
        if winner is not None:
            print(f"= {type_} {note.id} (duplicada de {winner.id}, más reciente)", file=out)
            done[f"duplicada:{type_}"] += 1
            paths[note.id] = winner.id  # resolved to a path below
            continue
        tokens.setdefault((dest, type_), []).append((mine, note))
        kept.append((dest, type_, note))
    kept.sort(key=lambda c: (c[2].created or dt.date.min, c[2].id))

    pending: list[tuple[str, OmegaMemory]] = []
    aliases = {k: v for k, v in paths.items()}
    paths.clear()
    for dest, type_, note in kept:
        roots = tuple(
            dict.fromkeys([r for r in [note.project, *mapping] if r and r.startswith("/")])
        )
        tags, files = split_tags(note.tags, roots)
        source = f"{SOURCE_PREFIX}{note.id}"
        existing = _existing_by_source(engine, source)
        if existing is not None:
            paths[note.id] = existing
            print(f"= {type_} → {existing} (ya existe)", file=out)
            done[f"existente:{type_}"] += 1
        else:
            try:
                res = memory.remember(
                    engine,
                    type_,
                    note.title,
                    note.text,
                    project=dest,
                    priority=note.priority,
                    tags=tags,
                    files=files,
                    source=source,
                    due=note.due.isoformat() if type_ == "reminder" and note.due else None,
                    created=note.created,
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
    for dropped, winner in aliases.items():
        if winner in paths:
            paths[dropped] = paths[winner]

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


def _parse_map(values: list[str]) -> dict[str, str]:
    mapping = {}
    for value in values:
        old, sep, new = value.partition("=")
        if not sep or not old.strip() or not new.strip():
            raise ValueError(f"--map-project {value!r} must be OLD=NEW, e.g. /home/me/app=app.")
        mapping[old.strip()] = new.strip()
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate an OMEGA export into episteme.")
    parser.add_argument("--export", required=True, help="the omega-memories/ folder")
    parser.add_argument("--vault", required=True, help="destination vault (with episteme.toml)")
    parser.add_argument("--project", required=True, help="project of the memories, e.g. fabrik")
    parser.add_argument(
        "--omega-db",
        help="omega.db, opened read-only: gives priority and the pending reminders",
    )
    parser.add_argument(
        "--map-project",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="OMEGA project (name or path) to destination project; repeatable",
    )
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
    db = Path(args.omega_db).expanduser() if args.omega_db else None
    if db is not None and not db.is_file():
        print(f"migrate_omega: {db} is not a file. Pass the path of omega.db.", file=sys.stderr)
        return 2
    try:
        mapping = _parse_map(args.map_project)
        migrate(export, vault, args.project, args.dry_run, omega_db=db, project_map=mapping)
    except ValueError as exc:
        print(f"migrate_omega: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"migrate_omega: cannot read {db}: {exc}. Pass a copy of omega.db.", file=sys.stderr)
        return 2
    except StartupError as exc:
        print(f"migrate_omega: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
