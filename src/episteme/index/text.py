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


def _is_droppable_stopword(toks: list[str], phrase: str) -> bool:
    return not phrase and len(toks) == 1 and toks[0] in STOPWORDS_ES


def _is_prefix_part(word: str, n: int, n_parts: int) -> bool:
    return bool(word) and n == n_parts and word.endswith("*")


def _parts(phrase: str, word: str) -> list[str]:
    return [phrase] if phrase else word.split("-")


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
        parts = _parts(phrase, word)
        for n, part in enumerate(parts, 1):
            toks = re.findall(r"[^\W_]+", fold(part))
            if not toks:
                continue
            if drop_stopwords and _is_droppable_stopword(toks, phrase):
                continue
            if _is_prefix_part(word, n, len(parts)):
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


def _earliest(folded: str, patterns: list[re.Pattern[str]]) -> tuple[int, int] | None:
    """Span in ``folded`` of the pattern that matches first (the first pattern wins ties)."""
    spans = [(m.start(), m.end()) for pat in patterns if (m := pat.search(folded))]
    return min(spans, key=lambda s: s[0], default=None)


def _to_source(index: list[int], span: tuple[int, int], base: int = 0) -> tuple[int, int]:
    return base + index[span[0]], base + index[span[1] - 1] + 1


def _first_match_per_line(text: str, patterns: list[re.Pattern[str]]) -> tuple[int, int] | None:
    pos = 0
    for raw in text.split("\n"):
        folded, index = fold_with_map(raw)
        span = _earliest(folded, patterns)
        if span is not None:
            return _to_source(index, span, pos)
        pos += len(raw) + 1
    return None


def _first_match(
    text: str, terms: list[list[str]], patterns: list[re.Pattern[str]]
) -> tuple[int, int] | None:
    """Source offsets [start, end) of the earliest match of any pattern."""
    if not patterns:
        return None
    if all(len(t) == 1 for t in terms):
        # A single-token term cannot span lines: fold line by line and stop at the first hit.
        return _first_match_per_line(text, patterns)
    folded, index = fold_with_map(text)
    span = _earliest(folded, patterns)
    return None if span is None else _to_source(index, span)


def _fallback_snippet(text: str, width: int) -> tuple[int, str]:
    lines = text.split("\n")
    start_line = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
    snippet = " ".join(" ".join(lines[start_line:]).split())[:width]
    return start_line + 1, snippet


def _highlight(window: str, patterns: list[re.Pattern[str]]) -> str:
    wfold, windex = fold_with_map(window)
    spans = sorted(
        (windex[m.start()], windex[m.end() - 1] + 1)
        for pat in patterns
        for m in pat.finditer(wfold)
    )
    out: list[str] = []
    pos = 0
    for s, e in spans:
        if s < pos:
            continue
        out.append(window[pos:s])
        out.append(f"**{window[s:e]}**")
        pos = e
    out.append(window[pos:])
    return " ".join("".join(out).split())


def _ellipsize(snippet: str, lo: int, hi: int, n: int) -> str:
    if lo > 0:
        snippet = "…" + snippet
    if hi < n:
        snippet += "…"
    return snippet


def locate(text: str, terms: list[list[str]], width: int = 200) -> tuple[int, str]:
    """1-based line of the first match in ``text`` and a snippet with ``**match**``."""
    patterns = [_term_regex(t) for t in terms]
    span = _first_match(text, terms, patterns)
    if span is None:
        return _fallback_snippet(text, width)
    start, end = span
    line = text.count("\n", 0, start) + 1
    lo = max(0, start - (width - (end - start)) // 3)
    hi = min(len(text), lo + width)
    snippet = _highlight(text[lo:hi], patterns)
    return line, _ellipsize(snippet, lo, hi, len(text))
