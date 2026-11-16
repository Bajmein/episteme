"""Measure whether an Ollama embedding model finds memories that keyword search misses.

    uv run scripts/measure_semantic.py --vault <vault> [--zone memory] [--url <url>] \
        [--model bge-m3] [--queries-file <file>] [--days 30] [--top-k 5] [--min-score 0.5] \
        [--strong-score 0.65] [--examples 15] [--link-score 0.7]

Read-only: walks the vault with ``Vault.iter_notes`` and ``parse``; it never opens or creates
the index and writes nothing in the vault. The queries come from ``--queries-file`` (one per
line) plus the ``search`` queries and ``context`` tasks of the last ``--days`` days in
``<vault>/.index/activity.db`` (opened with ``mode=ro``). Vectors come from Ollama's
``POST /api/embed`` on localhost; the provider is injectable (``measure(..., embed=...)``).

The keyword side imitates ``search`` with its defaults: notes holding every useful word of
the query or, when none does, notes holding any of them, ranked by how many they hold, cut
at ``SEARCH_LIMIT``. It ranks by matched words, not BM25, so it is an approximation.
Neighbours at ``--strong-score`` or more count as clear hits; the rest are reported apart.

It also lists the orphans (active memories with no links in or out, sessions and reminders
left out) with the memories of their project or ``_shared`` at ``--link-score`` or more, and
says which of those ``review`` already offers (a shared file or 2+ shared tags). Without an
index a link resolves by exact path or by a base name unique in the vault. ``--days 0``
without ``--queries-file`` skips the queries and leaves only the pairs and the orphans.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from episteme.errors import INVALID_ARGUMENT, NOT_FOUND, EpistemeError
from episteme.index import STOPWORDS_ES
from episteme.markdown import frontmatter_tags, parse, tokens
from episteme.memory import dedup_tokens, shared_reason, similarity
from episteme.vault import INDEX_DIR, MEMORY, Vault

if TYPE_CHECKING:
    from collections.abc import Callable

type Embed = Callable[[list[str]], list[list[float]]]

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "bge-m3"
DEFAULT_DAYS = 30
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.5
DEFAULT_STRONG_SCORE = 0.65
DEFAULT_EXAMPLES = 15
BATCH_SIZE = 32
MAX_NOTE_CHARS = 2000
REQUEST_TIMEOUT_S = 120
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
# search's default limit.
SEARCH_LIMIT = 20


# No proxies (ignores http_proxy): the request never leaves localhost. urllib does not
# resend a POST body on redirects.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# Pairs this close in meaning but under this token similarity are "missed" duplicates.
PAIR_MIN_SCORE = 0.8
PAIR_MAX_TOKEN_SIM = 0.3
PAIR_STRONG_SCORE = 0.9
PAIRS_SHOWN = 10
# Orphans: like review, active memories that are not sessions or reminders, each with up to
# this many candidates of its project or _shared at --link-score or more.
DEFAULT_LINK_SCORE = 0.7
ORPHAN_CANDIDATES = 3
ORPHAN_BANDS = (0.75, 0.85)
NOT_LINKABLE_TYPES = ("session", "reminder")
SHARED = "_shared"


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
        raise EpistemeError(
            INVALID_ARGUMENT,
            f"url {url!r} is not local. Use http://localhost:11434 (scheme http, host "
            "localhost, 127.0.0.1 or ::1).",
        )
    return url.rstrip("/")


def _unavailable(model: str, reason: str) -> EpistemeError:
    return EpistemeError(
        NOT_FOUND,
        f"cannot get embeddings from Ollama ({reason}). Start it with `ollama serve` and "
        f"download the model with `ollama pull {model}`.",
    )


def make_embedder(url: str, model: str) -> Embed:
    """An embed callable that posts batches to Ollama's ``/api/embed``."""
    endpoint = _check_url(url) + "/api/embed"

    def embed(texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            # The URL is validated to be http on a local host.
            with _OPENER.open(req, timeout=REQUEST_TIMEOUT_S) as resp:  # nosec B310
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise _unavailable(model, str(e)) from e
        vectors = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise _unavailable(model, "unexpected response")
        return vectors

    return embed


def _zone_prefix(vault: Vault, zone: str | None) -> str:
    if zone is None:
        z = vault.memory_zone
        if z is None:
            raise EpistemeError(
                INVALID_ARGUMENT,
                f"the vault has no zone with mode {MEMORY!r}. Pass --zone <zone path>.",
            )
        return z.path
    return zone.replace("\\", "/").strip("/")


def _useful(text: str) -> set[str]:
    return {t for t in tokens(text, min_len=2) if t not in STOPWORDS_ES}


@dataclass(frozen=True)
class _Note:
    """What the measurement needs of one note of the zone."""

    text: str  # what is embedded
    useful: set[str]
    dedup: set[str]
    title: str
    project: str
    linkable: bool  # active and not a session or a reminder, like review's orphans
    files: set[str]
    tags: set[str]
    targets: list[str]  # raw link targets, body and frontmatter


def _str_set(value: object) -> set[str]:
    return {str(v) for v in value} if isinstance(value, list) else set()


def _note(rel: str, text: str) -> _Note:
    note = parse(text, rel)
    fm = note.frontmatter
    full = note.title + "\n" + note.search_text
    return _Note(
        text=full[:MAX_NOTE_CHARS],
        useful=_useful(full),
        dedup=dedup_tokens(note.title, note.search_text),
        title=note.title,
        project=str(fm.get("project") or ""),
        linkable=fm.get("status") == "active" and fm.get("type") not in NOT_LINKABLE_TYPES,
        files=_str_set(fm.get("files")),
        tags=set(frontmatter_tags(fm)),
        targets=[link.target for link in note.links if link.target],
    )


def _load_notes(vault: Vault, zone: str) -> tuple[dict[str, _Note], list[str]]:
    """The notes of the zone by path, and every note path of the vault."""
    notes: dict[str, _Note] = {}
    paths: list[str] = []
    for rel, _stat in vault.iter_notes():
        paths.append(rel)
        if not (rel == zone or rel.startswith(zone + "/")):
            continue
        try:
            text = (vault.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"skipping {rel}: {e}", file=sys.stderr)
            continue
        notes[rel] = _note(rel, text)
    return notes, paths


def load_activity_queries(vault_root: Path, days: int, now: datetime | None = None) -> list[str]:
    """``search`` queries and ``context`` tasks from the last ``days`` days, read-only."""
    db = Path(vault_root) / INDEX_DIR / "activity.db"
    if not db.is_file():
        return []
    since = ((now or datetime.now(UTC)) - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "select tool, args from calls where at >= ? and ok = 1"
                " and tool in ('search', 'context') order by at, id",
                (since,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(f"cannot read {db}: {e}", file=sys.stderr)
        return []
    return [q for tool, args in rows if (q := _query_of(tool, args))]


def _query_of(tool: str, raw: str | None) -> str | None:
    try:
        args = json.loads(raw or "{}")
    except ValueError:
        return None
    if not isinstance(args, dict):
        return None
    value = args.get("query" if tool == "search" else "task")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class _Timed:
    """Wraps an embed callable and records the latency of each call."""

    def __init__(self, embed: Embed) -> None:
        self.embed = embed
        self.latencies: list[float] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        start = time.perf_counter()
        out = self.embed(texts)
        self.latencies.append(time.perf_counter() - start)
        return out


def _embed_all(embed: Embed, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        vectors += embed(texts[i : i + BATCH_SIZE])
    return vectors


def _keyword_hits(query: str, notes: dict[str, _Note]) -> list[str]:
    """What search would return: every word, else any word ranked by how many match."""
    want = _useful(query)
    if not want:
        return []
    every = sorted(rel for rel, n in notes.items() if want <= n.useful)
    if every:
        return every[:SEARCH_LIMIT]
    counted = ((len(want & n.useful), rel) for rel, n in notes.items())
    ranked = sorted((-n, rel) for n, rel in counted if n)
    return [rel for _n, rel in ranked[:SEARCH_LIMIT]]


@dataclass(frozen=True)
class Options:
    """Settings of one measurement."""

    zone: str | None = None
    top_k: int = DEFAULT_TOP_K
    min_score: float = DEFAULT_MIN_SCORE
    strong_score: float = DEFAULT_STRONG_SCORE
    link_score: float = DEFAULT_LINK_SCORE


@dataclass(frozen=True)
class _Corpus:
    """Memory paths with their vectors, in the same order."""

    rels: list[str]
    vectors: list[list[float]]
    notes: dict[str, _Note]


def _neighbours(qvec: list[float], corpus: _Corpus, opts: Options) -> list[tuple[str, float]]:
    pairs = zip(corpus.rels, corpus.vectors, strict=True)
    scored = sorted(((rel, _dot(qvec, v)) for rel, v in pairs), key=lambda p: (-p[1], p[0]))
    return [(rel, s) for rel, s in scored[: opts.top_k] if s >= opts.min_score]


def _missed_pairs(
    rels: list[str], vectors: list[list[float]], dedup: list[set[str]]
) -> list[tuple[str, str, float, float]]:
    pairs = []
    for i in range(len(rels)):
        for j in range(i + 1, len(rels)):
            score = _dot(vectors[i], vectors[j])
            if score < PAIR_MIN_SCORE:
                continue
            tok_sim = similarity(dedup[i], dedup[j])
            if tok_sim < PAIR_MAX_TOKEN_SIM:
                pairs.append((rels[i], rels[j], score, tok_sim))
    return sorted(pairs, key=lambda p: -p[2])


def _resolver(paths: list[str]) -> Callable[[str], str | None]:
    """Link target -> note path without an index: exact path, or a base name unique in the vault."""
    exact = set(paths)
    by_base: dict[str, list[str]] = {}
    for p in paths:
        by_base.setdefault(Path(p).stem, []).append(p)

    def resolve(target: str) -> str | None:
        t = target.replace("\\", "/").strip().strip("/")
        for candidate in (t, t + ".md"):
            if t and candidate in exact:
                return candidate
        base = t.removesuffix(".md")
        found = by_base.get(base, []) if base and "/" not in base else []
        return found[0] if len(found) == 1 else None

    return resolve


def _linked(notes: dict[str, _Note], paths: list[str]) -> set[str]:
    """Notes of the zone with a link out to another note, or a link in from the zone."""
    resolve = _resolver(paths)
    linked: set[str] = set()
    for rel, n in notes.items():
        targets = {dst for t in n.targets if (dst := resolve(t)) and dst != rel}
        if targets:
            linked.add(rel)
            linked |= targets
    return linked


def _semantic_candidates(i: int, pool: list[int], corpus: _Corpus, floor: float) -> list[dict]:
    """Up to ORPHAN_CANDIDATES memories of the orphan's project or _shared, closest first."""
    me = corpus.notes[corpus.rels[i]]
    scored = []
    for j in pool:
        other = corpus.notes[corpus.rels[j]]
        if j == i or other.project not in (me.project, SHARED):
            continue
        score = _dot(corpus.vectors[i], corpus.vectors[j])
        if score >= floor:
            scored.append((-score, corpus.rels[j], other))
    return [
        {
            "path": rel,
            "title": other.title,
            "score": -neg,
            "tokens": similarity(me.dedup, other.dedup),
            # Set when review already offers it: a shared file or 2+ shared tags.
            "reason": shared_reason(me.files, me.tags, other.files, other.tags),
        }
        for neg, rel, other in sorted(scored, key=lambda s: s[:2])[:ORPHAN_CANDIDATES]
    ]


def _orphans(corpus: _Corpus, paths: list[str], floor: float) -> list[dict]:
    """Linkable memories with no links, each with its semantic candidates, best first."""
    notes = corpus.notes
    linked = _linked(notes, paths)
    pool = [i for i, rel in enumerate(corpus.rels) if notes[rel].linkable]
    orphans = [
        {
            "path": corpus.rels[i],
            "title": notes[corpus.rels[i]].title,
            "project": notes[corpus.rels[i]].project,
            "candidates": _semantic_candidates(i, pool, corpus, floor),
        }
        for i in pool
        if corpus.rels[i] not in linked
    ]
    return sorted(orphans, key=lambda o: (-_best(o), o["path"]))


def _best(orphan: dict) -> float:
    return orphan["candidates"][0]["score"] if orphan["candidates"] else 0.0


def _load_zone(vault_root: Path, zone: str | None) -> tuple[dict[str, _Note], list[str]]:
    vault = Vault(Path(vault_root))
    prefix = _zone_prefix(vault, zone)
    notes, paths = _load_notes(vault, prefix)
    if not notes:
        raise EpistemeError(
            INVALID_ARGUMENT,
            f"no notes found under zone {prefix!r}. Pass --zone with a folder of the vault.",
        )
    return notes, paths


def _query_rows(
    queries: list[tuple[str, list[float]]], notes: dict, corpus: _Corpus, opts: Options
) -> list[dict]:
    rows = []
    for query, qvec in queries:
        keyword = _keyword_hits(query, notes)
        near = _neighbours(qvec, corpus, opts)
        new = [(r, s) for r, s in near if r not in keyword]
        rows.append({
            "query": query,
            "keyword": keyword,
            "semantic": near,
            "new": new,
            "strong": [(r, s) for r, s in new if s >= opts.strong_score],
        })
    return rows


def _latencies(lat: list[float], n_corpus: int) -> dict:
    return {
        "first_s": lat[0] if lat else 0.0,
        "median_s": statistics.median(lat[1:]) if len(lat) > 1 else 0.0,
        "query_s": statistics.median(lat[n_corpus:]) if len(lat) > n_corpus else 0.0,
    }


def measure(
    vault_root: Path,
    embed: Embed,
    queries: list[str] | None = None,
    opts: Options = Options(),
) -> dict:
    """Keyword hits vs semantic neighbours per query, missed pairs and latencies."""
    notes, paths = _load_zone(vault_root, opts.zone)
    unique = list(dict.fromkeys(q for q in (queries or []) if q.strip()))
    timed = _Timed(embed)
    rels = list(notes)
    start = time.perf_counter()
    corpus = _Corpus(rels, _embed_all(timed, [notes[r].text for r in rels]), notes)
    corpus_s = time.perf_counter() - start
    n_corpus = len(timed.latencies)
    qvectors = _embed_all(timed, unique) if unique else []
    queried = list(zip(unique, qvectors, strict=True))
    return {
        "docs": len(notes),
        "rows": _query_rows(queried, notes, corpus, opts),
        "pairs": _missed_pairs(rels, corpus.vectors, [notes[r].dedup for r in rels]),
        "orphans": _orphans(corpus, paths, opts.link_score),
        "link_score": opts.link_score,
        "corpus_s": corpus_s,
        "top_k": opts.top_k,
        "min_score": opts.min_score,
        "strong_score": opts.strong_score,
        **_latencies(timed.latencies, n_corpus),
    }


def _render_queries(rows: list[dict], examples: int) -> list[str]:
    out = ["", "## Por consulta", ""]
    if not rows:
        return [*out, "- (sin consultas: usa `--queries-file` o el registro de actividad)"]
    ranked = sorted(rows, key=lambda r: (-len(r["strong"]), -len(r["new"]), r["query"]))
    for r in ranked[:examples]:
        out.append(f"- «{r['query']}»: palabras {len(r['keyword'])}, vecinos {len(r['semantic'])}, "
                   f"nuevos {len(r['new'])}, claros {len(r['strong'])}")
        out += [f"    - {rel} ({score:.2f})" for rel, score in r["new"]]
    return out


def _render_pairs(pairs: list[tuple[str, str, float, float]]) -> list[str]:
    out = ["", "## Pares parecidos que los tokens no detectan", ""]
    if not pairs:
        return [*out, "- (ninguno)"]
    strong = sum(1 for p in pairs if p[2] >= PAIR_STRONG_SCORE)
    out.append(f"{len(pairs)} pares con coseno de {PAIR_MIN_SCORE} o más y similitud por tokens "
               f"bajo {PAIR_MAX_TOKEN_SIM}; de ellos, {strong} con {PAIR_STRONG_SCORE} o más.")
    out.append("")
    out += [f"- {a} / {b}: coseno {s:.2f}, tokens {t:.2f}" for a, b, s, t in pairs[:PAIRS_SHOWN]]
    return out


def _band_counts(orphans: list[dict], floor: float) -> str:
    """How many orphans have their best candidate in each cosine band."""
    edges = [floor, *[b for b in ORPHAN_BANDS if b > floor]]
    parts = []
    for k, low in enumerate(edges):
        high = edges[k + 1] if k + 1 < len(edges) else None
        n = sum(1 for o in orphans if _best(o) >= low and (high is None or _best(o) < high))
        parts.append(f"{low:.2f} o más: {n}" if high is None else f"{low:.2f} a {high:.2f}: {n}")
    return " · ".join(parts)


def _render_orphan(orphan: dict) -> list[str]:
    out = [f"- [{orphan['project']}] {orphan['title']} ({orphan['path']})"]
    for c in orphan["candidates"]:
        offered = f"review: {c['reason']}" if c["reason"] else "review no la ofrece"
        out.append(f"    - {c['score']:.2f} · tokens {c['tokens']:.2f} · {c['title']} "
                   f"({c['path']}) · {offered}")
    return out


def _render_orphans(orphans: list[dict], floor: float, examples: int) -> list[str]:
    found = [o for o in orphans if o["candidates"]]
    fresh = [o for o in found if any(c["reason"] is None for c in o["candidates"])]
    out = [
        "",
        "## Huérfanas y candidatas por significado",
        "",
        f"Memorias activas sin enlaces (sin sesiones ni recordatorios) y hasta "
        f"{ORPHAN_CANDIDATES} memorias de su proyecto o de {SHARED} con coseno de {floor} o más.",
        "",
        f"- Huérfanas: {len(orphans)}",
        f"- Con alguna candidata: {len(found)}",
        f"- Con alguna candidata que review no ofrece: {len(fresh)}",
    ]
    if found:
        out.append(f"- Mejor candidata por tramo de coseno: {_band_counts(found, floor)}")
    out.append("")
    for o in found[:examples]:
        out += _render_orphan(o)
    return out


def render(result: dict, examples: int) -> str:
    rows = result["rows"]
    gaining = sum(1 for r in rows if r["new"])
    clear = sum(1 for r in rows if r["strong"])
    n_new = sum(len(r["new"]) for r in rows)
    n_strong = sum(len(r["strong"]) for r in rows)
    strong = result["strong_score"]
    out = [
        "# Medición de embeddings",
        "",
        f"- Memorias: {result['docs']}",
        f"- Consultas: {len(rows)}",
        f"- Vecinos: top {result['top_k']} con puntaje de {result['min_score']} o más; "
        f"claros desde {strong}",
        f"- Palabras: lo que daría search (todas las palabras o, si ninguna nota las tiene, "
        f"alguna), hasta {SEARCH_LIMIT}",
        "",
        "## Resumen",
        "",
        f"- Consultas que ganan algo sobre la búsqueda por palabras: {gaining} de {len(rows)}",
        f"- Consultas con algún vecino nuevo claro (desde {strong}): {clear} de {len(rows)}",
        f"- Vecinos nuevos: {n_new} ({n_strong} claros, {n_new - n_strong} bajo {strong})",
    ]
    out += _render_queries(rows, examples)
    out += _render_pairs(result["pairs"])
    out += _render_orphans(result["orphans"], result["link_score"], examples)
    out += [
        "",
        "## Latencia",
        "",
        f"- Primera llamada: {result['first_s'] * 1000:.0f} ms",
        f"- Mediana de las siguientes: {result['median_s'] * 1000:.0f} ms",
        f"- Mediana de las llamadas de consultas: {result['query_s'] * 1000:.0f} ms",
        f"- Vectores de todas las memorias: {result['corpus_s']:.1f} s",
    ]
    return "\n".join(out) + "\n"


def _bad_numbers(args: argparse.Namespace) -> bool:
    """True when ``--top-k`` is below 1 or ``--days`` or ``--examples`` is negative."""
    return args.top_k < 1 or args.days < 0 or args.examples < 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--zone", default=None, help="zone path (default: the memory zone)")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--queries-file", type=Path, default=None, help="one query per line")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--strong-score", type=float, default=DEFAULT_STRONG_SCORE)
    ap.add_argument("--examples", type=int, default=DEFAULT_EXAMPLES)
    ap.add_argument("--link-score", type=float, default=DEFAULT_LINK_SCORE,
                    help="minimum cosine of a candidate to link an orphan")
    args = ap.parse_args(argv)
    if _bad_numbers(args):
        print(
            f"{INVALID_ARGUMENT}: --top-k must be 1 or more and --days and --examples 0 or "
            "more. Fix the flag.",
            file=sys.stderr,
        )
        return 1

    try:
        embed = make_embedder(args.url, args.model)
        queries: list[str] = []
        if args.queries_file:
            queries += args.queries_file.read_text(encoding="utf-8").splitlines()
        queries += load_activity_queries(args.vault, args.days)
        opts = Options(args.zone, args.top_k, args.min_score, args.strong_score, args.link_score)
        result = measure(args.vault, embed, queries, opts)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as e:
        print(f"{INVALID_ARGUMENT}: cannot read the queries file ({e}). Check --queries-file.",
              file=sys.stderr)
        return 1
    out = render(result, args.examples)
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
