"""Memory: schema, remember, revise, review, welcome and surface."""

from __future__ import annotations

import datetime as dt
import fnmatch
import math
import os
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from episteme_mcp.errors import INVALID_SCHEMA, NOT_FOUND, EpistemeError, invalid
from episteme_mcp.index import as_date
from episteme_mcp.markdown import (
    body_without_title,
    clip,
    compose,
    dump_frontmatter,
    find_section,
    first_sentence,
    load_frontmatter,
    parse,
    slugify,
    split_frontmatter,
    tokens,
)
from episteme_mcp.vault import MEMORY, today

if TYPE_CHECKING:
    from episteme_mcp.engine import Engine

FOLDERS = {
    "decision": "decisions",
    "lesson": "lessons",
    "error": "errors",
    "constraint": "constraints",
    "preference": "preferences",
    "session": "sessions",
    "reminder": "reminders",
    "insight": "insights",
}
TYPES = tuple(FOLDERS)
STATUSES = ("active", "superseded", "speculative", "archived")
KEY_ORDER = (
    "type",
    "kind",
    "project",
    "priority",
    "status",
    "created",
    "valid_until",
    "tags",
    "files",
    "supersedes",
    "related",
    "contradicts",
    "source",
    "helpful",
    "due",
    "flagged",
)
OMIT_WHEN_EMPTY = {
    "valid_until",
    "due",
    "source",
    "supersedes",
    "related",
    "contradicts",
    "tags",
    "files",
}
DUPLICATE = 0.8
SIMILAR = 0.5
ACTIONS = ("edit", "append", "set", "supersede", "feedback", "archive")
MEMORY_ACTIONS = ("supersede", "feedback", "archive")


def kind_for(type_: str) -> str:
    if type_ == "session":
        return "episodic"
    if type_ in ("lesson", "error", "constraint"):
        return "procedural"
    return "semantic"


def default_priority(type_: str) -> int:
    return 4 if type_ in ("decision", "constraint") else 3


def schema_error(message: str) -> EpistemeError:
    return EpistemeError(INVALID_SCHEMA, message)


def _is_date(value: Any) -> bool:
    return isinstance(value, dt.date) or (
        isinstance(value, str) and as_date(value) is not None and len(value.strip()) == 10
    )


def validate(fm: dict[str, Any]) -> None:
    """Check a memory's frontmatter; raise ``invalid_schema`` naming the field."""
    type_ = fm.get("type")
    if type_ not in TYPES:
        raise schema_error(f"type must be one of {', '.join(TYPES)}, got {type_!r}.")
    project = fm.get("project")
    if not isinstance(project, str) or not project.strip():
        raise schema_error("project is required.")
    if "/" in project or "\\" in project or project in (".", ".."):
        raise schema_error(f'project must be a plain name without "/" or "..", got {project!r}.')
    priority = fm.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
        raise schema_error(f"priority must be 1-5, got {priority!r}.")
    if fm.get("status") not in STATUSES:
        raise schema_error(
            f"status must be one of {', '.join(STATUSES)}, got {fm.get('status')!r}."
        )
    if not _is_date(fm.get("created")):
        raise schema_error(f"created must be a date YYYY-MM-DD, got {fm.get('created')!r}.")
    for key in ("due", "valid_until"):
        if fm.get(key) is not None and not _is_date(fm[key]):
            raise schema_error(f"{key} must be a date YYYY-MM-DD, got {fm[key]!r}.")
    if type_ == "reminder" and fm.get("due") is None:
        raise schema_error("reminder needs due (YYYY-MM-DD).")
    for key in ("files", "tags"):
        value = fm.get(key)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(v, str) for v in value)
        ):
            raise schema_error(f"{key} must be a list of strings.")
    for tag in fm.get("tags") or []:
        if not tag or any(c in tag for c in ": #\t"):
            raise schema_error(
                f'tag "{tag}" has ":", "#" or spaces. Nest tags with "/", e.g. dominio/auth.'
            )
    helpful = fm.get("helpful")
    if helpful is not None and (
        isinstance(helpful, bool) or not isinstance(helpful, int) or helpful < 0
    ):
        raise schema_error(f"helpful must be an integer >= 0, got {helpful!r}.")
    if fm.get("flagged") is not None and not isinstance(fm["flagged"], bool):
        raise schema_error("flagged must be true or false.")


def ordered(fm: dict[str, Any]) -> dict[str, Any]:
    """Schema key order; empty optional keys dropped; unknown keys kept at the end."""
    out: dict[str, Any] = {}
    for key in KEY_ORDER:
        if key not in fm:
            continue
        value = fm[key]
        if key in OMIT_WHEN_EMPTY and value in (None, "", []):
            continue
        if key == "flagged" and value is False:
            continue
        out[key] = value
    for key, value in fm.items():
        if key not in out and key not in KEY_ORDER:
            out[key] = value
    return out


def _date_arg(name: str, value: str | None) -> dt.date | None:
    if value is None or value == "":
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except (ValueError, AttributeError) as exc:
        raise schema_error(f"{name} must be a date YYYY-MM-DD, got {value!r}.") from exc


def similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_tokens(title: str, body: str) -> set[str]:
    return set(tokens(f"{title}\n{body}", min_len=3))


def wikilink(engine: Engine, rel: str) -> str:
    """``[[name]]`` when the bare name resolves back to ``rel``, else ``[[path]]``."""
    stem = PurePosixPath(rel).name.removesuffix(".md")
    target = stem if engine.index.resolver().resolve_quiet(stem) == rel else rel[:-3]
    return f"[[{target}]]"


# -- writing notes -------------------------------------------------------


class NoteFile:
    """A note split into raw frontmatter and body, so a body edit keeps the YAML byte-exact."""

    def __init__(self, engine: Engine, rel: str) -> None:
        self.engine = engine
        self.rel = rel
        text = engine.vault.resolve(rel).read_text(encoding="utf-8")
        text = text.replace("\r\n", "\n")
        lines = text.split("\n")
        raw, fm_end = split_frontmatter(lines)
        self.fm_end = fm_end
        self.head = "\n".join(lines[:fm_end]) + "\n" if fm_end else ""
        self.body = "\n".join(lines[fm_end:])
        self.fm, self.fm_valid, self.fm_error = load_frontmatter(raw)
        self.fm_changed = False

    def set_fields(self, fields: dict[str, Any]) -> list[str]:
        if not self.fm_valid:
            raise invalid(
                f"{self.rel} has invalid frontmatter ({self.fm_error}). Fix the YAML by hand first."
            )
        changed = []
        for key, value in fields.items():
            if value is None:
                if key in self.fm:
                    del self.fm[key]
                    changed.append(key)
            elif self.fm.get(key) != value:
                self.fm[key] = value
                changed.append(key)
        self.fm_changed = self.fm_changed or bool(changed)
        return changed

    def text(self) -> str:
        if self.fm_changed:
            fm = ordered(self.fm) if self.engine.vault.mode_for(self.rel) == MEMORY else self.fm
            head = dump_frontmatter(fm) if fm else ""
        else:
            head = self.head
        return head + self.body

    def save(self) -> None:
        if self.engine.vault.mode_for(self.rel) == MEMORY:
            validate(self.fm)
        self.engine.vault.write_atomic(self.rel, self.text())
        self.engine.index.reindex(self.rel)


# -- remember ------------------------------------------------------------


def remember(
    engine: Engine,
    type: str,
    title: str,
    body: str,
    project: str | None = None,
    priority: int | None = None,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    related: list[str] | None = None,
    supersedes: str | None = None,
    source: str | None = None,
    due: str | None = None,
    valid_until: str | None = None,
    status: str = "active",
    force: bool = False,
) -> dict[str, Any]:
    project = engine.need_project(project)
    zone = engine.vault.memory_zone
    if zone is None:
        raise invalid('the vault has no zone with mode = "memory". Declare one in episteme.toml.')
    if type not in TYPES:
        raise schema_error(f"type must be one of {', '.join(TYPES)}, got {type!r}.")
    title = " ".join((title or "").split())
    if not title:
        raise invalid("title is empty. Pass a short title.")
    if not (body or "").strip():
        raise invalid("body is empty. Describe the memory and name the files or tools involved.")

    related_links = [wikilink(engine, engine.resolve_note(r)) for r in related or []]
    old_rel = None
    old_note = None
    if supersedes:
        old_rel = engine.resolve_note(supersedes)
        if engine.vault.check_writable(old_rel) != MEMORY:
            raise invalid(f"{old_rel} is not a memory, so it cannot be superseded.")
        old_note = NoteFile(engine, old_rel)
        old_note.set_fields({"status": "superseded"})
        validate(old_note.fm)

    created = today()
    fm = ordered(
        {
            "type": type,
            "kind": kind_for(type),
            "project": project,
            "priority": priority if priority is not None else default_priority(type),
            "status": status,
            "created": created,
            "valid_until": _date_arg("valid_until", valid_until),
            "tags": [t.strip().lstrip("#") for t in tags or []],
            "files": list(files or []),
            "supersedes": wikilink(engine, old_rel) if old_rel else None,
            "related": related_links,
            "source": source,
            "helpful": 0,
            "due": _date_arg("due", due),
        }
    )
    validate(fm)

    text_body = body.strip()
    first = text_body.split("\n", 1)[0].strip()
    if first.startswith("# "):
        text_body = body_without_title(text_body)
    mine = dedup_tokens(title, text_body)
    similar = []
    for row in engine.index.memories(
        "project = ? and type = ? and status = 'active'", (project, type)
    ):
        if row["path"] == old_rel:
            continue
        theirs = dedup_tokens(row["title"] or "", body_without_title(row["body"]))
        score = similarity(mine, theirs)
        if score >= SIMILAR:
            similar.append(
                {"path": row["path"], "title": row["title"], "similarity": round(score, 3)}
            )
    similar.sort(key=lambda s: (-s["similarity"], s["path"]))
    if similar and similar[0]["similarity"] >= DUPLICATE and not force:
        return {"created": False, "path": None, "similar": similar}

    content = compose(fm, f"# {title}\n\n{text_body}\n")
    folder = f"{zone.path}/{project}/{FOLDERS[type]}"
    base = f"{created.isoformat()}-{slugify(title)}"
    engine.vault.check_writable(f"{folder}/{base}.md")
    n = 1
    while True:
        rel = f"{folder}/{base}.md" if n == 1 else f"{folder}/{base}-{n}.md"
        if not engine.vault.resolve(rel).exists() and engine.vault.create_exclusive(rel, content):
            break
        n += 1
    engine.index.reindex(rel)

    if old_note is not None:
        old_note.save()
    return {"created": True, "path": rel, "similar": similar}


# -- revise --------------------------------------------------------------


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
        nf.body = _append(nf, text, heading)
        result["changed"] = ["body"]
    elif action == "set":
        if not fields:
            raise invalid("set needs fields, e.g. {\"priority\": 5}.")
        fields = {k: _coerce(k, v) for k, v in fields.items()}
        result["changed"] = nf.set_fields(fields)
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
        helpful = nf.fm.get("helpful") if isinstance(nf.fm.get("helpful"), int) else 0
        if value == "helpful":
            result["changed"] = nf.set_fields({"helpful": helpful + 1})
        elif value == "unhelpful":
            result["changed"] = nf.set_fields({"helpful": max(0, helpful - 1)})
        else:
            result["changed"] = nf.set_fields({"flagged": True})
    elif action == "archive":
        result["changed"] = nf.set_fields({"status": "archived"})

    nf.save()
    return result


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


# -- scoring helpers (welcome, task context) -----------------------------


def days_since(created: str | None, now: dt.date) -> int:
    if not created:
        return 0
    try:
        return max(0, (now - dt.date.fromisoformat(created)).days)
    except ValueError:
        return 0


def recency(created: str | None, now: dt.date) -> float:
    return math.exp(-days_since(created, now) / 30)


def welcome_score(row: Any, now: dt.date) -> float:
    priority = row["priority"] or 1
    helpful = row["helpful"] or 0
    return (
        0.45 * (priority - 1) / 4
        + 0.35 * recency(row["created"], now)
        + 0.20 * min(helpful, 10) / 10
    )


def entry_line(row: Any) -> str:
    sentence = first_sentence(row["body"] or "")
    tail = f" — {sentence}" if sentence else ""
    return f"- [{row['type']} p{row['priority']}] {row['title']} ({row['path']}){tail}"


def welcome(engine: Engine, project: str | None) -> tuple[str, list[dict[str, Any]]]:
    """The welcome text: overdue reminders, then the best memories (10 entries, 4000 chars)."""
    project = engine.need_project(project)
    now = today()
    iso = now.isoformat()
    rows = engine.index.memories(
        "project in (?, '_shared') and status = 'active'", (project,)
    )
    reminders = sorted(
        (r for r in rows if r["type"] == "reminder" and r["due"] and r["due"] <= iso),
        key=lambda r: (r["due"], r["path"]),
    )
    candidates = [
        r
        for r in rows
        if r["type"] not in ("session", "reminder")
        and not (r["valid_until"] and r["valid_until"] < iso)
    ]
    scored = sorted(
        ((welcome_score(r, now), r) for r in candidates),
        key=lambda x: (-x[0], _neg_date(x[1]["created"]), x[1]["path"]),
    )
    header = f"episteme · memoria de {project}"
    lines = [header]
    entries: list[dict[str, Any]] = []
    budget = 4000 - len(header) - 1

    def add(line: str, section: str | None) -> bool:
        nonlocal budget
        extra = len(line) + 1 + (len(section) + 1 if section else 0)
        if len(entries) >= 10 or extra > budget:
            return False
        if section:
            lines.append(section)
        lines.append(line)
        budget -= extra
        return True

    first = True
    for r in reminders:
        line = f"- [{r['due']}] {r['title']} ({r['path']})"
        if not add(line, "Recordatorios vencidos:" if first else None):
            break
        first = False
        entries.append({"path": r["path"], "score": None, "kind": "reminder"})
    first = True
    for score, r in scored:
        if not add(entry_line(r), "Memorias:" if first else None):
            break
        first = False
        entries.append({"path": r["path"], "score": round(score, 4), "kind": "memory"})
    if not entries:
        return "", []
    return "\n".join(lines), entries


def _neg_date(value: str | None) -> int:
    """Sort key for 'most recent first'."""
    try:
        return -dt.date.fromisoformat(value or "").toordinal()
    except ValueError:
        return 0


# -- files: surface and constraints -------------------------------------


def project_relative(file: str, project_dir: str | None) -> str:
    """The project-relative form of ``file`` when ``project_dir`` contains it."""
    f = file.replace("\\", "/")
    if project_dir and os.path.isabs(f):
        for base, target in (
            (os.path.normpath(project_dir), os.path.normpath(f)),
            (os.path.realpath(project_dir), os.path.realpath(f)),
        ):
            if target.startswith(base.rstrip("/") + "/"):
                return os.path.relpath(target, base).replace("\\", "/")
    return f.removeprefix("./")


def file_matches(file: str, rel: str, entry: str) -> bool:
    """Match a ``files`` entry against a file (see «Casado de file con files»)."""
    entry = entry.strip().replace("\\", "/").removeprefix("./")
    if not entry:
        return False
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatchcase(rel, entry)
    file = file.replace("\\", "/")
    return rel == entry or file.endswith("/" + entry) or rel.endswith("/" + entry)


def _files_of(engine: Engine, rel: str) -> list[str]:
    files = engine.index.props(rel).get("files")
    if isinstance(files, str):
        return [files]
    return [f for f in files if isinstance(f, str)] if isinstance(files, list) else []


def _by_priority(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda r: (-(r["priority"] or 0), _neg_date(r["created"]), r["path"]))


def surface(
    engine: Engine, file: str, project_dir: str | None, project: str | None, limit: int
) -> tuple[str, dict[str, Any]]:
    if not (1 <= limit <= 50):
        raise invalid(f"limit must be 1-50, got {limit}.")
    if not file or not file.strip():
        raise invalid("file is empty. Pass the path of the file being edited.")
    project = engine.need_project(project)
    rel = project_relative(file, project_dir)
    rows = engine.index.memories(
        "project in (?, '_shared') and status = 'active' and type != 'constraint'", (project,)
    )
    by_files = _by_priority(
        [r for r in rows if any(file_matches(file, rel, e) for e in _files_of(engine, r["path"]))]
    )
    seen = {r["path"] for r in by_files}
    name = PurePosixPath(rel).name
    query = f'"{rel}"' + (f' "{name}"' if name != rel else "")
    hits, _ = engine.index.search(
        query, any_term=True, mode=MEMORY, project=[project, "_shared"], limit=1000
    )
    hit_paths = {h.path for h in hits}
    by_mention = _by_priority(
        [r for r in rows if r["path"] in hit_paths and r["path"] not in seen]
    )
    chosen = [(r, "files") for r in by_files] + [(r, "mention") for r in by_mention]
    chosen = chosen[:limit]
    text = ""
    if chosen:
        text = "\n".join([f"Memories about {rel}:"] + [entry_line(r) for r, _ in chosen])
    data = {
        "file": rel,
        "memories": [
            {
                "path": r["path"],
                "title": r["title"],
                "type": r["type"],
                "priority": r["priority"],
                "match": match,
            }
            for r, match in chosen
        ],
    }
    return text, data


def constraints(
    engine: Engine, file: str, project_dir: str | None, project: str | None
) -> tuple[str, dict[str, Any]]:
    if not file or not file.strip():
        raise invalid("file is empty. Pass the path of the file being edited.")
    project = engine.need_project(project)
    rel = project_relative(file, project_dir)
    rows = engine.index.memories(
        "project in (?, '_shared') and status = 'active' and type = 'constraint'", (project,)
    )
    found = _by_priority(
        [r for r in rows if any(file_matches(file, rel, e) for e in _files_of(engine, r["path"]))]
    )
    items = [
        {
            "path": r["path"],
            "title": r["title"],
            "priority": r["priority"],
            "body": clip(body_without_title(r["body"] or ""), 600),
        }
        for r in found
    ]
    text = ""
    if items:
        parts = [f"Constraints that apply to {rel}:"]
        for item in items:
            parts.append(f"- {item['title']} ({item['path']})")
            parts.append(item["body"])
        text = "\n".join(parts)
    return text, {"file": rel, "constraints": items}


def task_context(
    engine: Engine, task: str, project: str | None, budget_tokens: int
) -> tuple[str, list[dict[str, Any]]]:
    raise invalid('mode "task" is not available yet.')
