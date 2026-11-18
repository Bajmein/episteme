"""Digest of a Claude Code transcript for the episteme extractor: what was asked, said and done.

Standard library only; it runs with ``uv run --no-project --python 3.14 python -I``. It reads one
``.jsonl`` under a ``projects`` folder and prints Markdown to stdout:

    transcript_digest.py <transcript.jsonl> [--since <ISO date|inicio>] [--max-chars N]

Kept: the person's messages (up to 2000 characters each), the assistant's text (1500), one line
per tool call, failed tool results (500) and the compaction summary whole, without its leading
<analysis> block. Dropped: system reminders, local command output, task notifications and the
content of successful tool results. Over --max-chars the newest entries stay.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

USER_MAX = 2000
ASSISTANT_MAX = 1500
ERROR_MAX = 500
ARG_MAX = 120
DEFAULT_MAX_CHARS = 80000
SINCE_ALL = "inicio"
NOTHING = "sin novedades"

_NOISE = re.compile(
    r"<(system-reminder|local-command-[a-z-]+|task-notification)>.*?</\1>", re.DOTALL
)
_ANALYSIS = re.compile(r"\A\s*<analysis>.*?</analysis>\s*", re.DOTALL)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " […]"


def _clean(text: str) -> str:
    return _NOISE.sub("", text).strip()


def _parse_time(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return " ".join(str(b.get("text", "")) for b in _blocks(content))


def _tool_line(block: dict[str, Any]) -> str:
    given = block.get("input")
    args: dict[str, Any] = given if isinstance(given, dict) else {}
    target = args.get("file_path") or args.get("command") or args.get("relative_path") or ""
    target = " ".join(str(target).split())
    return f"- {block.get('name', '?')}({_clip(target, ARG_MAX)})"


def _summary_entry(blocks: list[dict[str, Any]]) -> str:
    """The compaction summary whole, without its leading <analysis> block."""
    text = " ".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
    return f"### Resumen de compactación\n\n{_ANALYSIS.sub('', text, count=1).strip()}"


def _user_block(block: dict[str, Any]) -> str:
    """A message of the person, a failed tool result, or nothing."""
    if block.get("type") == "text":
        text = _clean(str(block.get("text", "")))
        return f"**Persona:** {_clip(text, USER_MAX)}" if text else ""
    if block.get("type") == "tool_result" and block.get("is_error"):
        text = _clean(_result_text(block.get("content")))
        return f"- error: {_clip(text, ERROR_MAX)}"
    return ""


def _user_entries(record: dict[str, Any], blocks: list[dict[str, Any]]) -> Iterator[str]:
    if record.get("isCompactSummary"):
        yield _summary_entry(blocks)
    elif not record.get("isMeta"):
        yield from filter(None, (_user_block(b) for b in blocks))


def _assistant_entries(blocks: list[dict[str, Any]]) -> Iterator[str]:
    for block in blocks:
        if block.get("type") == "text":
            text = _clean(str(block.get("text", "")))
            if text:
                yield f"**Asistente:** {_clip(text, ASSISTANT_MAX)}"
        elif block.get("type") == "tool_use":
            yield _tool_line(block)


def entries(record: dict[str, Any]) -> list[str]:
    """The digest lines of one transcript record."""
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    blocks = _blocks(message.get("content"))
    if record.get("type") == "user":
        return list(_user_entries(record, blocks))
    if record.get("type") == "assistant":
        return list(_assistant_entries(blocks))
    return []


def _records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def _is_after(stamp: str, since: dt.datetime | None) -> bool:
    """True when the record's timestamp is after ``since`` (always, without ``since``)."""
    if since is None:
        return True
    when = _parse_time(stamp) if stamp else None
    return when is not None and when > since


def digest(path: Path, since: dt.datetime | None) -> tuple[list[str], str, str]:
    """The entries after ``since``, and the first and last timestamps they cover."""
    out: list[str] = []
    first = last = ""
    for record in _records(path):
        stamp = str(record.get("timestamp") or "")
        if not _is_after(stamp, since):
            continue
        found = entries(record)
        if found:
            first = first or stamp
            last = stamp or last
            out.extend(found)
    return out, first, last


def cap(items: list[str], max_chars: int) -> list[str]:
    """The newest ``items`` that fit in ``max_chars``, after a mark with how many were left out."""
    kept: list[str] = []
    size = 0
    for item in reversed(items):
        size += len(item) + 2
        if size > max_chars and kept:
            break
        kept.append(item)
    kept.reverse()
    dropped = len(items) - len(kept)
    return ([f"[… {dropped} entradas anteriores omitidas]"] if dropped else []) + kept


def checked_path(raw: str) -> Path | None:
    """The real path of the transcript when it is a ``.jsonl`` under a ``projects`` folder."""
    real = Path(os.path.realpath(raw))
    return real if _is_transcript(real) else None


def _is_transcript(real: Path) -> bool:
    return real.suffix == ".jsonl" and _under_claude_projects(real) and real.is_file()


def _under_claude_projects(real: Path) -> bool:
    """True when some ancestor is ``projects`` inside a ``.claude*`` folder (the config dir)."""
    parts = real.parent.parts
    return any(
        part == "projects" and parts[i - 1].startswith(".claude")
        for i, part in enumerate(parts)
        if i > 0
    )


def _since(value: str) -> dt.datetime | None:
    if value == SINCE_ALL:
        return None
    parsed = _parse_time(value)
    if parsed is None:
        raise SystemExit(f'--since must be an ISO date or "{SINCE_ALL}", got "{value}"')
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("transcript")
    parser.add_argument("--since", default=SINCE_ALL)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args(argv)
    # -I ignores PYTHONIOENCODING, and a Windows console may be cp1252: never fail on a "→".
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    path = checked_path(args.transcript)
    if path is None:
        print("transcript must be a .jsonl file under a .claude*/projects folder", file=sys.stderr)
        return 2
    items, first, last = digest(path, _since(args.since))
    if not items:
        print(NOTHING)
        return 0
    body = cap(items, max(args.max_chars, 1))
    head = (
        f"# Transcript\n\n- desde: {first or '?'}\n- hasta: {last or '?'}\n"
        f"- entradas: {len(items)}"
    )
    print("\n\n".join([head, *body]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
