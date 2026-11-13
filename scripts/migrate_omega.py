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
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, NamedTuple, TextIO

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
SOURCE_RE = re.compile(r"^\s*-\s*Source:\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+(Related|Metadata)\s*$")
SPACE_OR_HASH_RE = re.compile(r"[\s#]+")
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
# A label before the title, «[MEMORIA GI - feedback] …»; not a wikilink or a Markdown link.
LABEL_RE = re.compile(r"^\[[^\[\]\n]{1,60}\](?!\()\s*")
DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
UNASSIGNED = ("include", "skip")
CLEAN_PASSES = 3
PRIORITY_MIN = 1
PRIORITY_MAX = 5


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
            line = LABEL_RE.sub("", line, count=1) or line
            if line:
                return line[:TITLE_MAX].rstrip()
        return self.id


def clean_text(text: str) -> str:
    """Drop the «fabrik (fecha):», «Decision:», «Lesson:» and «Assistant fix:» prefixes."""
    out = text.strip()
    for _ in range(CLEAN_PASSES):
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


def is_path(value: str) -> bool:
    """An absolute path, POSIX (``/home/…``) or Windows (``C:\\Users\\…``)."""
    return value.startswith("/") or bool(DRIVE_RE.match(value))


def path_key(value: str) -> str:
    """A project name or path in a comparable form.

    Paths use "/", lose the trailing separator and, on a Windows drive, the case.
    """
    value = value.strip()
    if not is_path(value):
        return value
    out = value.replace("\\", "/").rstrip("/") or "/"
    return out.casefold() if DRIVE_RE.match(out) else out


def _relative_file(tag: str, keys: list[str]) -> str:
    """A path tag as a project-relative file; empty when it is a project root itself."""
    path = tag.replace("\\", "/").rstrip("/")
    cmp = path_key(path)
    for root in keys:
        prefix = root.rstrip("/")
        if cmp == root:
            path = ""
            break
        if cmp.startswith(prefix + "/"):
            path = path[len(prefix) :]
            break
    if DRIVE_RE.match(path):
        path = path[2:]
    return path.lstrip("/")


def _tag_name(tag: str) -> str:
    """``dominio:auth`` as the tag ``dominio/auth``."""
    name = "/".join(part.strip() for part in tag.split(":") if part.strip())
    return SPACE_OR_HASH_RE.sub("-", name)


def _root_keys(roots: tuple[str, ...]) -> list[str]:
    """The comparable form of the roots that are paths."""
    return [path_key(root) for root in roots if is_path(root)]


def _classify_tag(tag: str, keys: list[str]) -> tuple[str, str] | None:
    """``("files", path)`` or ``("tags", name)`` for a tag worth keeping, else ``None``."""
    if is_path(tag):
        path = _relative_file(tag, keys)
        return ("files", path) if path else None
    if ":" in tag:
        name = _tag_name(tag)
        return ("tags", name) if name else None
    return None


def split_tags(tags: list[str], roots: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Split OMEGA tags into episteme ``tags`` and ``files``.

    ``dominio:auth`` becomes the tag ``dominio/auth``; a tag with a path (``/rules/x.md``,
    ``C:\\app\\rules\\x.md``) becomes the project-relative file ``rules/x.md``; bare words
    are dropped.
    """
    found: dict[str, list[str]] = {"tags": [], "files": []}
    keys = _root_keys(roots)
    for tag in map(str, tags):
        kept = _classify_tag(tag.strip(), keys)
        if kept is None:
            continue
        bucket, value = kept
        if value not in found[bucket]:
            found[bucket].append(value)
    return found["tags"], found["files"]


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
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if PRIORITY_MIN <= value <= PRIORITY_MAX else None


class _Body(NamedTuple):
    text: str
    related: list[str]
    source: str | None


def _related_id(line: str) -> str | None:
    """The ``mem-…`` id of a «Related» bullet, if the line is one."""
    m = RELATED_RE.match(line)
    return m.group(1) if m else None


def _source_of(line: str) -> str | None:
    """The value of a «Source:» bullet in «Metadata», if the line is one."""
    m = SOURCE_RE.match(line)
    return m.group(1) if m else None


def _split_body(lines: list[str]) -> _Body:
    """Split the note body into its text, the «Related» ids and the «Metadata» source."""
    text: list[str] = []
    related: list[str] = []
    source = None
    section = None
    for line in lines:
        heading = SECTION_RE.match(line.strip())
        if heading:
            section = heading.group(1)
        elif section is None:
            text.append(line)
        elif section == "Related":
            related.extend(filter(None, [_related_id(line)]))
        else:
            source = _source_of(line) or source
    return _Body("\n".join(text).strip(), related, source)


def _fm_tags(value: object) -> list[str]:
    """The frontmatter ``tags`` as a list of strings."""
    value = value or []
    return [str(t) for t in value] if isinstance(value, list) else [str(value)]


def parse_export_note(path: Path) -> OmegaMemory | None:
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    raw, fm_end = split_frontmatter(lines)
    fm, ok, _ = load_frontmatter(raw)
    if not ok or "id" not in fm:
        return None
    body = _split_body(lines[fm_end:])
    project = fm.get("project")
    return OmegaMemory(
        id=str(fm["id"]),
        omega_type=str(fm.get("type", "")),
        tags=_fm_tags(fm.get("tags")),
        created=_date(fm.get("created")),
        text=body.text,
        related=body.related,
        source=body.source,
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


DB_QUERY = (
    "select node_id, content, metadata, created_at, event_type, project, priority, status"
    " from memories order by id"
)


def _load_meta(meta: Any) -> dict[str, object]:
    """The JSON ``metadata`` column as a dict; empty when missing or malformed."""
    try:
        data = json.loads(meta) if meta else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _row_text(content: object, data: dict[str, object], event: object) -> str:
    """The memory text, with the context of a reminder appended."""
    text = str(content or "").strip()
    if data.get("context") and event == "reminder":
        text = f"{text}\n\nContexto: {str(data['context']).strip()}"
    return text


def _row_to_memory(row: tuple[Any, ...]) -> OmegaMemory:
    """One ``memories`` row as an :class:`OmegaMemory`."""
    node_id, content, meta, created, event, project, priority, status = row
    data = _load_meta(meta)
    tags = data.get("tags")
    return OmegaMemory(
        id=str(node_id),
        omega_type=str(event or ""),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        created=_date(created),
        text=_row_text(content, data, event),
        source=str(data["source"]) if data.get("source") else None,
        project=str(project) if project else None,
        priority=_priority(priority),
        status=str(data["reminder_status"]) if event == "reminder" else str(status or ""),
        due=_date(data.get("remind_at")),
    )


def load_db(path: Path) -> dict[str, OmegaMemory]:
    """Read ``memories`` from an OMEGA database, read-only. Keys are the ``mem-…`` ids."""
    uri = f"file:{path.resolve()}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("pragma query_only = on")
        memories = [_row_to_memory(row) for row in conn.execute(DB_QUERY)]
    return {note.id: note for note in memories}


def _project_for(value: str | None, project: str, mapping: dict[str, str]) -> str | None:
    """Destination project of a note; ``None`` when it is neither ``project`` nor mapped."""
    if not value:
        return project
    key = path_key(value)
    if key in mapping:
        return mapping[key]
    return project if value == project else None


def _existing_by_source(engine: Engine, source: str) -> str | None:
    row = engine.index.conn.execute(
        "select path from props where key = 'source' and value = ? order by path",
        (json.dumps(source),),
    ).fetchone()
    return row["path"] if row else None


class Candidate(NamedTuple):
    dest: str  # destination project
    type_: str  # episteme memory type
    note: OmegaMemory


class Pending(NamedTuple):
    rel: str  # path of the written memory
    note: OmegaMemory


class Skip(NamedTuple):
    reason: str
    key: str | None = None


class Classified(NamedTuple):
    candidates: list[Candidate]
    skipped_projects: Counter[str]
    unassigned: int


@dataclass(frozen=True)
class _Routing:
    project: str
    mapping: dict[str, str]
    unassigned: str


@dataclass(frozen=True)
class _Report:
    done: Counter[str]
    out: TextIO

    def skip(self, note: OmegaMemory, skip: Skip) -> None:
        """Print a skipped note and count it."""
        print(f"- {note.omega_type} ({skip.reason}) {note.id}", file=self.out)
        kind = "omitida" if skip.key in ("proyecto", "sin-proyecto") else "descartada"
        self.done[f"{kind}:{skip.key or note.omega_type}"] += 1


@dataclass(frozen=True)
class _WriteCtx:
    engine: Engine
    mapping: dict[str, str]
    dry_run: bool
    report: _Report


@dataclass(frozen=True)
class MigrateOptions:
    dry_run: bool = False
    omega_db: Path | None = None
    project_map: dict[str, str] | None = None
    unassigned: str = "include"


def _merge_db_row(note: OmegaMemory, row: OmegaMemory | None) -> OmegaMemory:
    """The export note completed with the priority, project, status and source from the DB."""
    if row is None or row is note:
        return note
    return replace(
        note,
        priority=note.priority or row.priority,
        project=note.project or row.project,
        status=row.status,
        source=note.source or row.source,
    )


def _type_or_skip(note: OmegaMemory) -> str | Skip:
    """The episteme type of a note, or why it is not migrated."""
    if note.omega_type == "reminder":
        if note.status != "pending":
            return Skip(f"reminder {note.status or 'sin estado'}", "reminder")
        return "reminder"
    if note.omega_type in DISCARDED:
        return Skip("descartada")
    if note.omega_type not in TYPE_MAP:
        return Skip("tipo desconocido")
    return TYPE_MAP[note.omega_type]


def _is_edit_pattern(note: OmegaMemory) -> bool:
    return note.text.lower().startswith("edit pattern")


def _is_auto(note: OmegaMemory) -> bool:
    return is_auto_capture(note.text, note.source)


def _is_harness(note: OmegaMemory) -> bool:
    return bool(HARNESS_TEXT_RE.match(clean_text(note.text)))  # also after «Decision:»


def _is_superseded(note: OmegaMemory) -> bool:
    return note.status == "superseded"


# In order: the first predicate that matches decides.
CONTENT_SKIPS: list[tuple[Callable[[OmegaMemory], bool], Skip]] = [
    (_is_edit_pattern, Skip("edit pattern", "edit-pattern")),
    (_is_auto, Skip("captura automática", "captura-automatica")),
    (_is_harness, Skip("texto del harness", "harness")),
    (_is_superseded, Skip("reemplazada en OMEGA", "superseded")),
]


def _content_skip(note: OmegaMemory) -> Skip | None:
    return next((skip for matches, skip in CONTENT_SKIPS if matches(note)), None)


def _note_skip(note: OmegaMemory, unassigned: str) -> Skip | None:
    """Why a note with a valid type is not migrated, from its content or lack of project."""
    skip = _content_skip(note)
    if skip is None and not note.project and unassigned == "skip":
        return Skip("sin proyecto", "sin-proyecto")
    return skip


def _classify_one(note: OmegaMemory, routing: _Routing) -> Candidate | Skip:
    """A merged note as a candidate, or the reason it is skipped."""
    type_ = _type_or_skip(note)
    if isinstance(type_, Skip):
        return type_
    skip = _note_skip(note, routing.unassigned)
    if skip is not None:
        return skip
    dest = _project_for(note.project, routing.project, routing.mapping)
    if dest is None:
        return Skip(f"proyecto {note.project}", "proyecto")
    return Candidate(dest, type_, replace(note, text=clean_text(note.text)))


def _classify(
    notes: list[OmegaMemory],
    db: dict[str, OmegaMemory],
    routing: _Routing,
    report: _Report,
) -> Classified:
    """Decide which notes migrate and where; count and report the rest."""
    candidates: list[Candidate] = []
    skipped_projects: Counter[str] = Counter()
    unassigned_in = 0
    for original in notes:
        note = _merge_db_row(original, db.get(original.id))
        result = _classify_one(note, routing)
        if isinstance(result, Skip):
            report.skip(note, result)
            if result.key == "proyecto":
                skipped_projects[note.project or ""] += 1
            continue
        unassigned_in += not note.project
        candidates.append(result)
    return Classified(candidates, skipped_projects, unassigned_in)


def _drop_batch_duplicates(
    candidates: list[Candidate], report: _Report
) -> tuple[list[Candidate], dict[str, str]]:
    """Keep the most recent of the near-duplicates in the batch (ties: the larger id).

    Returns the kept candidates, oldest first, and the dropped id -> winner id.
    """
    kept: list[Candidate] = []
    aliases: dict[str, str] = {}
    tokens: dict[tuple[str, str], list[tuple[set[str], OmegaMemory]]] = {}
    newest_first = sorted(
        candidates, key=lambda c: (c.note.created or dt.date.min, c.note.id), reverse=True
    )
    for cand in newest_first:
        dest, type_, note = cand
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
            print(f"= {type_} {note.id} (duplicada de {winner.id}, más reciente)", file=report.out)
            report.done[f"duplicada:{type_}"] += 1
            aliases[note.id] = winner.id
            continue
        tokens.setdefault((dest, type_), []).append((mine, note))
        kept.append(cand)
    kept.sort(key=lambda c: (c.note.created or dt.date.min, c.note.id))
    return kept, aliases


def _roots_for(note: OmegaMemory, mapping: dict[str, str]) -> tuple[str, ...]:
    """The project roots (paths) a note's file tags can be relative to."""
    return tuple(dict.fromkeys([r for r in [note.project, *mapping] if r and is_path(r)]))


def _existing_result(ctx: _WriteCtx, type_: str, path: str) -> str:
    """Report a memory that already exists and return its path."""
    print(f"= {type_} → {path} (ya existe)", file=ctx.report.out)
    ctx.report.done[f"existente:{type_}"] += 1
    return path


def _log_created(ctx: _WriteCtx, type_: str, res: dict[str, Any]) -> str:
    """Report the result of ``remember``; return the path of the new or similar memory."""
    if not res["created"]:
        return _existing_result(ctx, type_, res["similar"][0]["path"])
    print(f"+ {type_} → {res['path']}", file=ctx.report.out)
    ctx.report.done[type_] += 1
    return res["path"]


def _write_one(ctx: _WriteCtx, cand: Candidate) -> str | None:
    """Write one memory unless it exists; return its path, or ``None`` on error."""
    dest, type_, note = cand
    tags, files = split_tags(note.tags, _roots_for(note, ctx.mapping))
    source = f"{SOURCE_PREFIX}{note.id}"
    existing = _existing_by_source(ctx.engine, source)
    if existing is not None:
        return _existing_result(ctx, type_, existing)
    try:
        res = memory.remember(
            ctx.engine,
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
            dry_run=ctx.dry_run,
        )
    except EpistemeError as exc:
        print(f"! {note.omega_type} {note.id}: {exc}", file=ctx.report.out)
        ctx.report.done[f"error:{type_}"] += 1
        return None
    return _log_created(ctx, type_, res)


def _write_all(ctx: _WriteCtx, kept: list[Candidate]) -> tuple[dict[str, str], list[Pending]]:
    """Write the kept memories; return OMEGA id -> path and those with relations to link."""
    paths: dict[str, str] = {}
    pending: list[Pending] = []
    for cand in kept:
        path = _write_one(ctx, cand)
        if path is None:
            continue
        paths[cand.note.id] = path
        if cand.note.related:
            pending.append(Pending(path, cand.note))
    return paths, pending


def _resolve_ids(paths: dict[str, str], aliases: dict[str, str]) -> dict[str, str]:
    """OMEGA id -> path, including the ids dropped as duplicates (they point at the winner)."""
    return {**paths, **{old: paths[win] for old, win in aliases.items() if win in paths}}


def _resolved_targets(note: OmegaMemory, rel: str, resolved: dict[str, str]) -> list[str]:
    """Paths of the notes ``note`` relates to, without itself."""
    return [resolved[r] for r in note.related if r in resolved and resolved[r] != rel]


def _merge_links(engine: Engine, current: list[Any], targets: list[str]) -> list[Any]:
    """``current`` plus the wikilinks to ``targets`` that are not in it yet."""
    links = list(current)
    for target in targets:
        link = memory.wikilink(engine, target)
        if link not in links:
            links.append(link)
    return links


def _add_links(engine: Engine, rel: str, targets: list[str]) -> None:
    """Add wikilinks to ``targets`` in the ``related`` field of the memory at ``rel``."""
    nf = memory.NoteFile(engine, rel)
    current = nf.fm.get("related") or []
    current = current if isinstance(current, list) else [current]
    links = _merge_links(engine, current, targets)
    if links != current:
        nf.set_fields({"related": links})
        nf.save()


def _link_related(ctx: _WriteCtx, pending: list[Pending], resolved: dict[str, str]) -> None:
    """Second pass: OMEGA ids → wikilinks to the new files."""
    if ctx.dry_run:
        return
    for rel, note in pending:
        targets = _resolved_targets(note, rel, resolved)
        if targets:
            _add_links(ctx.engine, rel, targets)


def _print_summary(classified: Classified, project: str, dry_run: bool, report: _Report) -> None:
    out = report.out
    if classified.skipped_projects:
        listed = ", ".join(f"{p} ({n})" for p, n in classified.skipped_projects.most_common())
        print(
            f"Proyectos omitidos: {listed}. Para migrarlos, añade --map-project "
            f"'<proyecto>={project}' (repetible).",
            file=out,
        )
    if classified.unassigned:
        print(
            f"Sin proyecto en OMEGA: {classified.unassigned}, migradas a {project}. Revísalas, "
            "u omítelas con --unassigned skip.",
            file=out,
        )
    summary = ", ".join(f"{k} {v}" for k, v in sorted(report.done.items())) or "nada"
    prefix = "Resumen (dry-run)" if dry_run else "Resumen"
    print(f"{prefix}: {summary}", file=out)


def migrate(
    export: Path,
    vault: Path,
    project: str,
    options: MigrateOptions = MigrateOptions(),
    out: TextIO = sys.stdout,
) -> Counter[str]:
    if options.unassigned not in UNASSIGNED:
        raise ValueError(f"--unassigned must be include or skip, got {options.unassigned!r}.")
    engine = Engine(vault, project)
    engine.index.refresh()
    mapping = {path_key(k): v for k, v in (options.project_map or {}).items()}
    db = load_db(options.omega_db) if options.omega_db is not None else {}
    report = _Report(Counter(), out)
    notes = [n for n in load_export(export) if n.omega_type != "reminder"]
    notes += [n for n in db.values() if n.omega_type == "reminder"]
    routing = _Routing(project, mapping, options.unassigned)
    classified = _classify(notes, db, routing, report)
    kept, aliases = _drop_batch_duplicates(classified.candidates, report)
    ctx = _WriteCtx(engine, mapping, options.dry_run, report)
    paths, pending = _write_all(ctx, kept)
    _link_related(ctx, pending, _resolve_ids(paths, aliases))
    _print_summary(classified, project, options.dry_run, report)
    return report.done


def _split_pair(value: str) -> tuple[str, str] | None:
    """``OLD=NEW`` as a stripped pair; ``None`` when it is not a valid pair."""
    old, sep, new = value.partition("=")
    if not sep or not old.strip() or not new.strip():
        return None
    return old.strip(), new.strip()


def _parse_map(values: list[str]) -> dict[str, str]:
    mapping = {}
    for value in values:
        pair = _split_pair(value)
        if pair is None:
            raise ValueError(f"--map-project {value!r} must be OLD=NEW, e.g. /home/me/app=app.")
        mapping[pair[0]] = pair[1]
    return mapping


def _fail(message: str) -> int:
    """Print ``message`` to stderr and return the exit code for a usage error."""
    print(f"migrate_omega: {message}", file=sys.stderr)
    return 2


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
    parser.add_argument(
        "--unassigned",
        choices=UNASSIGNED,
        default="include",
        help="memories without a project in OMEGA: migrate them to --project (default) or skip",
    )
    parser.add_argument("--dry-run", action="store_true", help="show what would be done")
    args = parser.parse_args(argv)
    export = Path(args.export).expanduser()
    vault = Path(args.vault).expanduser().resolve()
    if not export.is_dir():
        return _fail(f"{export} is not a folder.")
    if not (vault / "episteme.toml").is_file():
        return _fail(f"{vault} has no episteme.toml.")
    db = Path(args.omega_db).expanduser() if args.omega_db else None
    if db is not None and not db.is_file():
        return _fail(f"{db} is not a file. Pass the path of omega.db.")
    try:
        mapping = _parse_map(args.map_project)
        options = MigrateOptions(args.dry_run, db, mapping, args.unassigned)
        migrate(export, vault, args.project, options)
    except (ValueError, StartupError) as exc:
        return _fail(str(exc))
    except sqlite3.Error as exc:
        return _fail(f"cannot read {db}: {exc}. Pass a copy of omega.db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
