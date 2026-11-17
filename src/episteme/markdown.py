"""Markdown parsing: frontmatter, headings, tags, wikilinks, comments and excerpts."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
TAG_RE = re.compile(r"(?:^|(?<=\s))#([\w/-]+)")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
# ``#fff``, ``#a1b2c3`` and ``#a1b2c3ff`` are colors, not tags. Hex letters alone also spell
# words (``#bad``, ``#cafe``, ``#decade``), so a color needs a digit or a single repeated letter.
HEX_COLOR_RE = re.compile(r"(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
INDENTED_RE = re.compile(r"^(?: {4}|\t)")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
# ``%% nav:start %%`` … ``%% nav:end %%``: the whole block is treated as a comment.
MARKER_RE = re.compile(r"^\s*%%\s*([\w-]+):(start|end)\s*%%\s*$")
SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s")
SENTENCE_LIMIT = 160
SLUG_LIMIT = 60


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int


@dataclass(frozen=True)
class Link:
    target: str  # destination as written, without heading or alias ("" = same note)
    kind: str  # "body" or the frontmatter key
    line: int
    heading: str | None = None
    block: str | None = None
    alias: str | None = None


@dataclass(frozen=True)
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


FRONTMATTER_MAX_BYTES = 64 * 1024


class _NoAliasLoader(yaml.SafeLoader):
    """A safe loader that refuses ``*alias``: aliases share nodes and can blow up the walks."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.events.AliasEvent):
            event = self.peek_event()
            raise yaml.YAMLError(f"YAML aliases are not supported (*{event.anchor})")
        return super().compose_node(parent, index)


def load_frontmatter(raw: str | None) -> tuple[dict[str, Any], bool, str | None]:
    if raw is None:
        return {}, True, None
    if len(raw) > FRONTMATTER_MAX_BYTES:
        return {}, False, f"frontmatter is larger than {FRONTMATTER_MAX_BYTES // 1024} KB"
    try:
        # _NoAliasLoader subclasses yaml.SafeLoader: as safe as safe_load, minus aliases.
        data: Any = {}
        if raw.strip():
            data = yaml.load(raw, Loader=_NoAliasLoader)  # nosec B506
    except Exception as exc:  # YAMLError, or a ValueError from an impossible date
        return {}, False, " ".join(str(exc).split())
    if data is None:
        return {}, True, None
    if not isinstance(data, dict):
        return {}, False, f"frontmatter is a {type(data).__name__}, not a mapping"
    return {str(k): v for k, v in data.items()}, True, None


class _FrontmatterDumper(yaml.SafeDumper):
    """One key per line; lists inline (``tags: [a, b]``), as Obsidian writes them."""

    def ignore_aliases(self, data: Any) -> bool:
        # A value shared by two keys (created and updated set to the same date) would be
        # written as &id001 / *id001, and load_frontmatter refuses aliases.
        return True


_FrontmatterDumper.add_representer(
    list,
    lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True),
)


def dump_frontmatter(data: dict[str, Any]) -> str:
    # default_flow_style=None would also inline a mapping made only of scalars, so a memory
    # without lists got its whole frontmatter on one line.
    text = yaml.dump(
        data,
        Dumper=_FrontmatterDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1000,
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
        if any((dest, heading, block)):
            out.append(Link(dest, kind, line, heading, block, alias))
    return out


def _key_line(key: str, fm_lines: list[str]) -> int:
    """File line of the frontmatter ``key`` (1 if it is not found)."""
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for i, text in enumerate(fm_lines):
        if pattern.match(text):
            return i + 2  # first frontmatter line is file line 2
    return 1


def _walk_links(value: Any, key: str, line: int) -> Iterator[Link]:
    """Wikilinks in a frontmatter value, descending into lists and mappings."""
    if isinstance(value, str):
        yield from _links_in(value, key, line)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_links(v, key, line)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_links(v, key, line)


def _property_links(fm: dict[str, Any], fm_lines: list[str]) -> list[Link]:
    links: list[Link] = []
    for key, value in fm.items():
        links.extend(_walk_links(value, key, _key_line(key, fm_lines)))
    return links


def is_hex_color(tag: str) -> bool:
    """True for ``a1b2c3``-style tags that are colors rather than words made of hex letters."""
    if not HEX_COLOR_RE.fullmatch(tag):
        return False
    return any(c.isdigit() for c in tag) or len(set(tag.lower())) == 1


def _body_links(text: str, lineno: int) -> list[Link]:
    """Wikilinks of ``text`` outside inline code, as body links."""
    return _links_in(_strip_inline_code(text), "body", lineno)


@dataclass
class _Scanner:
    """Walks the body line by line, tracking fences, comments, regions and code blocks."""

    search_lines: list[str]
    links: list[Link]
    headings: list[Heading] = field(default_factory=list)
    body_tags: list[str] = field(default_factory=list)
    fence: str | None = None
    in_comment: bool = False
    in_indented: bool = False  # inside an indented code block (not a list continuation)
    prev_blank: bool = True
    in_list: bool = False
    region: str | None = None  # name of an open ``%% name:start %%`` block

    def feed(self, i: int, line: str) -> None:
        if self.fence is not None:
            self._fenced_line(i, line, self.fence)
        elif self.in_comment or not self._structural_line(i, line):
            self._text_line(i, line)

    def _fenced_line(self, i: int, line: str, fence: str) -> None:
        self.prev_blank, self.in_indented = False, False
        stripped = line.strip()
        if stripped.startswith(fence[0] * len(fence)) and set(stripped) == {fence[0]}:
            self.fence = None
        self.search_lines[i] = line

    def _structural_line(self, i: int, line: str) -> bool:
        """Handle region markers, region content and fence openings; True if consumed."""
        marker = MARKER_RE.match(line)
        if marker and self._handle_marker(marker):
            return True
        if self.region is not None:
            self.links.extend(_body_links(line, i + 1))
            return True
        m = FENCE_RE.match(line)
        if not m:
            return False
        self._open_fence(i, line, m.group(1))
        return True

    def _handle_marker(self, marker: re.Match[str]) -> bool:
        """Open or close a region on its marker line; False if the marker changes nothing."""
        name, kind = marker.group(1), marker.group(2)
        if kind == "start" and self.region is None:
            self.region = name
            return True
        if kind == "end" and name == self.region:
            self.region = None
            return True
        return False

    def _open_fence(self, i: int, line: str, fence: str) -> None:
        self.fence = fence
        self.search_lines[i] = line
        self.prev_blank, self.in_indented = False, False

    def _text_line(self, i: int, line: str) -> None:
        lineno = i + 1
        visible, hidden, self.in_comment = _split_comments(line, self.in_comment)
        self.search_lines[i] = visible
        if hidden:
            self.links.extend(_body_links(hidden, lineno))
        if not visible.strip():
            self.prev_blank = True
            return
        h = HEADING_RE.match(visible)
        if h:
            self.headings.append(Heading(len(h.group(1)), (h.group(2) or "").strip(), lineno))
        code_free = _strip_inline_code(visible)
        self.links.extend(_links_in(code_free, "body", lineno))
        self._update_block_state(line, h is not None)
        if not self.in_indented:
            self._collect_tags(code_free)

    def _update_block_state(self, line: str, heading_found: bool) -> None:
        """Track indented code blocks and list items after a non-blank text line."""
        if INDENTED_RE.match(line):
            self.in_indented = (self.prev_blank and not self.in_list) or self.in_indented
        else:
            self.in_indented = False
            # A column-0 line right after a list line is a lazy continuation of the item.
            lazy = self.in_list and not self.prev_blank and not heading_found
            self.in_list = bool(LIST_ITEM_RE.match(line)) or lazy
        self.prev_blank = False

    def _collect_tags(self, code_free: str) -> None:
        no_links = WIKILINK_RE.sub(" ", code_free)
        for t in TAG_RE.findall(no_links):
            tag = normalize_tag(t)
            if _is_real_tag(tag):
                self.body_tags.append(tag)


def _is_real_tag(tag: str) -> bool:
    """False for empty, numeric-only (``#12``, ``#1/2``) and hex-color tags."""
    return bool(tag) and not tag.replace("/", "").isdigit() and not is_hex_color(tag)


def _split_lines(text: str) -> list[str]:
    """Split text into lines, normalizing line endings and dropping the trailing empty one."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _note_title(fm: dict[str, Any], headings: list[Heading], rel: str) -> str:
    """Frontmatter title, else the first level-1 heading, else the file name."""
    title = fm.get("title")
    if not (isinstance(title, str) and title.strip()):
        title = next((h.text for h in headings if h.level == 1 and h.text), None)
    if title is None:
        title = PurePosixPath(rel).name.removesuffix(".md")
    return title.strip()


def parse(text: str, rel: str) -> ParsedNote:
    """Parse a note. Never raises on bad YAML: the note is flagged instead."""
    lines = _split_lines(text)
    raw_fm, fm_end = split_frontmatter(lines)
    fm, fm_valid, fm_error = load_frontmatter(raw_fm)

    scanner = _Scanner(
        search_lines=[""] * len(lines),
        links=_property_links(fm, lines[1 : max(fm_end - 1, 1)]) if fm else [],
    )
    for i in range(fm_end, len(lines)):
        scanner.feed(i, lines[i])
    headings = scanner.headings

    tags = expand_tags(frontmatter_tags(fm) + scanner.body_tags)
    return ParsedNote(
        frontmatter=fm,
        fm_valid=fm_valid,
        fm_error=fm_error,
        fm_end=fm_end,
        lines=lines,
        search_lines=scanner.search_lines,
        title=_note_title(fm, headings, rel),
        headings=headings,
        tags=tags,
        links=scanner.links,
    )


# -- sections ----------------------------------------------------------------


def normalize_heading(text: str) -> str:
    """Compare headings like Obsidian links do: case, spaces and ``: # | ^`` are ignored."""
    text = re.sub(r"[:#|^\[\]%]", " ", re.sub(r"[`*]", "", text))
    return " ".join(text.split()).casefold()


def section_end(note: ParsedNote, idx: int) -> int:
    """Last 1-based line of the section of ``note.headings[idx]``."""
    h = note.headings[idx]
    for nxt in note.headings[idx + 1 :]:
        if nxt.level <= h.level:
            return nxt.line - 1
    return len(note.lines)


def find_section(note: ParsedNote, heading: str) -> tuple[int, int] | None:
    """0-based [start, end) file-line range of ``heading``'s section."""
    want = normalize_heading(heading.lstrip("#"))
    for idx, h in enumerate(note.headings):
        if normalize_heading(h.text) == want:
            return h.line - 1, section_end(note, idx)
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


_FOLD_CHUNK_RE = re.compile(r"[\x00-\x7f]+|[^\x00-\x7f]")


def fold_with_map(text: str) -> tuple[str, list[int]]:
    """``fold`` plus, for every folded character, the index of its source character."""
    out: list[str] = []
    index: list[int] = []
    # ASCII folds one character to one, so a whole run is folded at once; only the other
    # characters need NFKD one by one. A note body is mostly ASCII, and `search` folds one
    # per hit.
    for m in _FOLD_CHUNK_RE.finditer(text):
        chunk = m.group()
        i = m.start()
        if chunk.isascii():
            out.append(chunk.casefold())
            index.extend(range(i, m.end()))
            continue
        for c in unicodedata.normalize("NFKD", chunk):
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


def first_sentence(body: str, limit: int = SENTENCE_LIMIT) -> str:
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


def slugify(text: str, limit: int = SLUG_LIMIT) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    slug = slug[:limit].strip("-")
    return slug or "note"
