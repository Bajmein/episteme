"""Query parsing and snippet location for full-text search."""

from __future__ import annotations

import re

from episteme.markdown import fold, fold_with_map
from episteme.markdown import normalize_tag as markdown_normalize_tag

# Spanish function words: ignored when matching a task or comparing memories for duplicates.
STOPWORDS_ES = frozenset(
    """a al algo ante con contra cual cuando de del desde donde durante e el ella ellas ellos en
    entre era eran es esa esas ese eso esos esta estaba estan estar este esto estos fue ha han
    hay la las le les lo los me mi mis mucho muy ni no nos nuestro o para pero por porque que
    quien se ser si sin sobre son su sus te tiene tienen todo tu tus un una uno unos unas y ya
    yo como mas hacer hace cada tambien""".split()
)


def _like_prefix(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_tag(tag: str) -> str:
    """A tag as stored: ``#Dominio:Auth`` and ``dominio/auth`` both become ``dominio/auth``."""
    return markdown_normalize_tag(tag).replace(":", "/")


def query_terms(query: str, drop_stopwords: bool = False) -> list[list[str]]:
    """Split a user query into terms (a quoted phrase is one term) of folded tokens.

    Only word characters survive, so the query is never read as FTS5 syntax. A bare word
    with hyphens (``save-clear``) gives one term per part; other punctuation (``ROADMAP.md``)
    keeps the word as a phrase. A bare ``word*`` is a prefix term: its last token keeps a
    trailing ``*``. With ``drop_stopwords``, single Spanish function words are dropped
    (phrases are kept).
    """
    terms = []
    for phrase, word in re.findall(r'"([^"]*)"|(\S+)', query):
        parts = [phrase] if phrase else word.split("-")
        for n, part in enumerate(parts, 1):
            toks = re.findall(r"[^\W_]+", fold(part))
            if not toks:
                continue
            if drop_stopwords and not phrase and len(toks) == 1 and toks[0] in STOPWORDS_ES:
                continue
            if word and n == len(parts) and word.endswith("*"):
                toks[-1] += "*"
            terms.append(toks)
    return terms


def _fts_term(term: list[str]) -> str:
    last = term[-1]
    if last.endswith("*"):
        return '"' + " ".join([*term[:-1], last[:-1]]) + '" *'
    return '"' + " ".join(term) + '"'


def _term_regex(term: list[str]) -> re.Pattern[str]:
    prefix = term[-1].endswith("*")
    toks = [*term[:-1], term[-1].rstrip("*")]
    body = r"[\W_]+".join(re.escape(t) for t in toks)
    return re.compile(rf"(?<![^\W_]){body}" + ("" if prefix else r"(?![^\W_])"))


def _first_match(
    text: str, terms: list[list[str]], patterns: list[re.Pattern[str]]
) -> tuple[int, int] | None:
    """Source offsets [start, end) of the earliest match of any pattern."""
    if not patterns:
        return None
    if all(len(t) == 1 for t in terms):
        # A single-token term cannot span lines: fold line by line and stop at the first hit.
        pos = 0
        for raw in text.split("\n"):
            folded, index = fold_with_map(raw)
            best = None
            for pat in patterns:
                m = pat.search(folded)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), m.end())
            if best is not None:
                return pos + index[best[0]], pos + index[best[1] - 1] + 1
            pos += len(raw) + 1
        return None
    folded, index = fold_with_map(text)
    first = None
    for pat in patterns:
        m = pat.search(folded)
        if m and (first is None or m.start() < first[0]):
            first = (m.start(), m.end())
    if first is None:
        return None
    return index[first[0]], index[first[1] - 1] + 1


def locate(text: str, terms: list[list[str]], width: int = 200) -> tuple[int, str]:
    """1-based line of the first match in ``text`` and a snippet with ``**match**``."""
    patterns = [_term_regex(t) for t in terms]
    span = _first_match(text, terms, patterns)
    if span is None:
        lines = text.split("\n")
        start_line = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
        snippet = " ".join(" ".join(lines[start_line:]).split())[:width]
        return start_line + 1, snippet
    start, end = span
    line = text.count("\n", 0, start) + 1
    lo = max(0, start - (width - (end - start)) // 3)
    hi = min(len(text), lo + width)
    window = text[lo:hi]
    wfold, windex = fold_with_map(window)
    spans: list[tuple[int, int]] = []
    for pat in patterns:
        for m in pat.finditer(wfold):
            spans.append((windex[m.start()], windex[m.end() - 1] + 1))
    spans.sort()
    out: list[str] = []
    pos = 0
    for s, e in spans:
        if s < pos:
            continue
        out.append(window[pos:s])
        out.append(f"**{window[s:e]}**")
        pos = e
    out.append(window[pos:])
    snippet = " ".join("".join(out).split())
    if lo > 0:
        snippet = "…" + snippet
    if hi < len(text):
        snippet += "…"
    return line, snippet
