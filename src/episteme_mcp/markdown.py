"""Markdown parsing: frontmatter, headings, tags, wikilinks, comments and excerpts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
TAG_RE = re.compile(r"(?:^|(?<=\s))#([\w/-]+)")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
# ``%% nav:start %%`` … ``%% nav:end %%``: the whole block is treated as a comment.
MARKER_RE = re.compile(r"^\s*%%\s*([\w-]+):(start|end)\s*%%\s*$")
SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s")


@dataclass
class Heading:
    level: int
    text: str
    line: int


@dataclass
class Link:
    target: str  # destination as written, without heading or alias ("" = same note)
    kind: str  # "body" or the frontmatter key
    line: int
    heading: str | None = None
    block: str | None = None
    alias: str | None = None


@dataclass
class ParsedNote:
    frontmatter: dict[str, Any]
    fm_valid: bool
    fm_error: str | None
    fm_end: int  # number of file lines taken by the frontmatter block (0 if none)
    lines: list[str]  # every line of the file
    search_lines: list[str]  # same length; frontmatter and %% comments blanked
    title: str
    headings: list[Heading] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines[self.fm_end :])

    @property
    def search_text(self) -> str:
        return "\n".join(self.search_lines)


# -- frontmatter -------------------------------------------------------------


def split_frontmatter(lines: list[str]) -> tuple[str | None, int]:
    """Return the raw YAML and the number of lines the block takes, or (None, 0)."""
    if not lines or lines[0].rstrip() != "---":
        return None, 0
    for i in range(1, len(lines)):
        if lines[i].rstrip() in ("---", "..."):
            return "\n".join(lines[1:i]), i + 1
    return None, 0


def load_frontmatter(raw: str | None) -> tuple[dict[str, Any], bool, str | None]:
    if raw is None:
        return {}, True, None
    try:
        data = yaml.safe_load(raw) if raw.strip() else {}
    except Exception as exc:  # YAMLError, or a ValueError from an impossible date
        return {}, False, " ".join(str(exc).split())
    if data is None:
        return {}, True, None
    if not isinstance(data, dict):
        return {}, False, f"frontmatter is a {type(data).__name__}, not a mapping"
    return {str(k): v for k, v in data.items()}, True, None


def dump_frontmatter(data: dict[str, Any]) -> str:
    text = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000
    )
    return f"---\n{text}---\n"


def compose(frontmatter: dict[str, Any] | None, body: str) -> str:
    head = dump_frontmatter(frontmatter) if frontmatter else ""
    if body and not body.endswith("\n"):
        body += "\n"
    return head + body


# -- tags --------------------------------------------------------------------


def normalize_tag(tag: str) -> str:
    return tag.strip().lstrip("#").strip("/").lower()


def expand_tags(tags: list[str]) -> list[str]:
    """Nested tags also count for each prefix: dominio/auth → dominio/auth, dominio."""
    out: list[str] = []
    for tag in tags:
        parts = tag.split("/")
        for i in range(len(parts), 0, -1):
            t = "/".join(parts[:i])
            if t and t not in out:
                out.append(t)
    return out


def frontmatter_tags(fm: dict[str, Any]) -> list[str]:
    raw = fm.get("tags")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else re.split(r"[,\s]+", str(raw))
    return [t for t in (normalize_tag(str(i)) for i in items if i is not None) if t]


# -- body scanning -----------------------------------------------------------


def _split_comments(line: str, in_comment: bool) -> tuple[str, str, bool]:
    """Split a line into its visible text and its ``%% … %%`` text.

    A ``%%`` inside an inline code span is plain text, not a comment marker.
    """
    code = [m.span() for m in INLINE_CODE_RE.finditer(line)]
    visible: list[str] = []
    hidden: list[str] = []
    start = 0
    for m in re.finditer("%%", line):
        if any(a <= m.start() < b for a, b in code):
            continue
        (hidden if in_comment else visible).append(line[start : m.start()])
        in_comment = not in_comment
        start = m.end()
    (hidden if in_comment else visible).append(line[start:])
    return " ".join(visible), " ".join(hidden), in_comment


def _strip_inline_code(text: str) -> str:
    return INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def parse_wikilink(inner: str) -> tuple[str, str | None, str | None, str | None]:
    """``dest#Heading|alias`` → (dest, heading, block, alias)."""
    inner = inner.replace("\\|", "|")
    target, _, alias = inner.partition("|")
    dest, _, sub = target.partition("#")
    heading = block = None
    if sub.startswith("^"):
        block = sub[1:].strip() or None
    elif sub:
        heading = sub.strip() or None
    return dest.strip(), heading, block, (alias.strip() or None)


def _links_in(text: str, kind: str, line: int) -> list[Link]:
    out = []
    for m in WIKILINK_RE.finditer(text):
        dest, heading, block, alias = parse_wikilink(m.group(1))
        if dest or heading or block:
            out.append(Link(dest, kind, line, heading, block, alias))
    return out


def _property_links(fm: dict[str, Any], fm_lines: list[str]) -> list[Link]:
    links: list[Link] = []

    def walk(value: Any, key: str, line: int) -> None:
        if isinstance(value, str):
            links.extend(_links_in(value, key, line))
        elif isinstance(value, list):
            for v in value:
                walk(v, key, line)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v, key, line)

    for key, value in fm.items():
        line = 1
        for i, text in enumerate(fm_lines):
            if re.match(rf"^{re.escape(key)}\s*:", text):
                line = i + 2  # first frontmatter line is file line 2
                break
        walk(value, key, line)
    return links


def parse(text: str, rel: str) -> ParsedNote:
    """Parse a note. Never raises on bad YAML: the note is flagged instead."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    raw_fm, fm_end = split_frontmatter(lines)
    fm, fm_valid, fm_error = load_frontmatter(raw_fm)

    search_lines = [""] * len(lines)
    headings: list[Heading] = []
    body_tags: list[str] = []
    links: list[Link] = _property_links(fm, lines[1 : max(fm_end - 1, 1)]) if fm else []

    fence: str | None = None
    in_comment = False
    region: str | None = None  # name of an open ``%% name:start %%`` block
    for i in range(fm_end, len(lines)):
        line = lines[i]
        lineno = i + 1
        if fence is None and not in_comment:
            marker = MARKER_RE.match(line)
            if marker and marker.group(2) == "start" and region is None:
                region = marker.group(1)
                continue
            if marker and marker.group(2) == "end" and marker.group(1) == region:
                region = None
                continue
            if region is not None:
                links.extend(_links_in(_strip_inline_code(line), "body", lineno))
                continue
            m = FENCE_RE.match(line)
            if m:
                fence = m.group(1)
                search_lines[i] = line
                continue
        elif fence is not None:
            stripped = line.strip()
            if stripped.startswith(fence[0] * len(fence)) and set(stripped) == {fence[0]}:
                fence = None
            search_lines[i] = line
            continue

        visible, hidden, in_comment = _split_comments(line, in_comment)
        search_lines[i] = visible
        if hidden:
            links.extend(_links_in(_strip_inline_code(hidden), "body", lineno))
        if not visible.strip():
            continue
        h = HEADING_RE.match(visible)
        if h:
            headings.append(Heading(len(h.group(1)), (h.group(2) or "").strip(), lineno))
        code_free = _strip_inline_code(visible)
        links.extend(_links_in(code_free, "body", lineno))
        no_links = WIKILINK_RE.sub(" ", code_free)
        for t in TAG_RE.findall(no_links):
            tag = normalize_tag(t)
            if tag and not tag.replace("/", "").isdigit():
                body_tags.append(tag)

    tags = expand_tags(frontmatter_tags(fm) + body_tags)
    title = fm.get("title") if isinstance(fm.get("title"), str) and fm["title"].strip() else None
    if title is None:
        title = next((h.text for h in headings if h.level == 1 and h.text), None)
    if title is None:
        title = PurePosixPath(rel).name.removesuffix(".md")
    return ParsedNote(
        frontmatter=fm,
        fm_valid=fm_valid,
        fm_error=fm_error,
        fm_end=fm_end,
        lines=lines,
        search_lines=search_lines,
        title=title.strip(),
        headings=headings,
        tags=tags,
        links=links,
    )


# -- sections ----------------------------------------------------------------


def normalize_heading(text: str) -> str:
    """Compare headings like Obsidian links do: case, spaces and ``: # | ^`` are ignored."""
    text = re.sub(r"[:#|^\[\]%]", " ", re.sub(r"[`*]", "", text))
    return " ".join(text.split()).casefold()


def find_section(note: ParsedNote, heading: str) -> tuple[int, int] | None:
    """0-based [start, end) file-line range of ``heading``'s section."""
    want = normalize_heading(heading.lstrip("#"))
    for idx, h in enumerate(note.headings):
        if normalize_heading(h.text) == want:
            end = len(note.lines)
            for nxt in note.headings[idx + 1 :]:
                if nxt.level <= h.level:
                    end = nxt.line - 1
                    break
            return h.line - 1, end
    return None


def section_text(note: ParsedNote, heading: str) -> str | None:
    rng = find_section(note, heading)
    if rng is None:
        return None
    return "\n".join(note.lines[rng[0] : rng[1]]).rstrip("\n")


# -- text helpers ------------------------------------------------------------


def fold(text: str) -> str:
    """Lowercase and strip diacritics."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def fold_with_map(text: str) -> tuple[str, list[int]]:
    """``fold`` plus, for every folded character, the index of its source character."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            for f in c.casefold():
                out.append(f)
                index.append(i)
    return "".join(out), index


def tokens(text: str, min_len: int = 1) -> list[str]:
    return [t for t in re.findall(r"\w+", fold(text)) if len(t) >= min_len and t != "_"]


def body_without_title(body: str) -> str:
    """Body text without its leading ``# Title`` line."""
    lines = body.lstrip("\n").split("\n")
    if lines and HEADING_RE.match(lines[0]) and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def first_sentence(body: str, limit: int = 160) -> str:
    """First sentence of the body (after the title), at most ``limit`` characters."""
    text = body_without_title(body)
    paragraph = ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block and not block.startswith("#"):
            paragraph = block
            break
    paragraph = " ".join(re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", ln) for ln in paragraph.split("\n"))
    paragraph = " ".join(paragraph.split())
    sentence = SENTENCE_END_RE.split(paragraph, maxsplit=1)[0]
    return clip(sentence, limit)


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def clip_at_newline(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` characters at a line break."""
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit + 1)
    return text[: cut if cut > 0 else limit]


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    slug = slug[:limit].strip("-")
    return slug or "note"
