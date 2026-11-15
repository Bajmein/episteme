"""Measure whether an Ollama embedding model finds memories that keyword search misses.

    uv run scripts/measure_semantic.py --vault <vault> [--zone memory] [--url <url>] \
        [--model bge-m3] [--queries-file <file>] [--days 30] [--top-k 5] [--min-score 0.5] \
        [--examples 15]

Read-only: walks the vault with ``Vault.iter_notes`` and ``parse``; it never opens or creates
the index and writes nothing in the vault. The queries come from ``--queries-file`` (one per
line) plus the ``search`` queries and ``context`` tasks of the last ``--days`` days in
``<vault>/.index/activity.db`` (opened with ``mode=ro``). Vectors come from Ollama's
``POST /api/embed`` on localhost; the provider is injectable (``measure(..., embed=...)``).
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
from episteme.markdown import parse, tokens
from episteme.memory import dedup_tokens, similarity
from episteme.vault import INDEX_DIR, MEMORY, Vault

if TYPE_CHECKING:
    from collections.abc import Callable

type Embed = Callable[[list[str]], list[list[float]]]

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "bge-m3"
DEFAULT_DAYS = 30
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.5
DEFAULT_EXAMPLES = 15
BATCH_SIZE = 32
MAX_NOTE_CHARS = 2000
REQUEST_TIMEOUT_S = 120
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


# No proxies (ignores http_proxy): the request never leaves localhost. urllib does not
# resend a POST body on redirects.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# Pairs this close in meaning but under this token similarity are "missed" duplicates.
PAIR_MIN_SCORE = 0.8
PAIR_MAX_TOKEN_SIM = 0.3
PAIRS_SHOWN = 10


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


def _load_notes(vault: Vault, zone: str) -> dict[str, tuple[str, set[str], set[str]]]:
    """Path -> (text to embed, useful tokens, dedup tokens)."""
    notes: dict[str, tuple[str, set[str], set[str]]] = {}
    for rel, _stat in vault.iter_notes():
        if not (rel == zone or rel.startswith(zone + "/")):
            continue
        try:
            text = (vault.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"skipping {rel}: {e}", file=sys.stderr)
            continue
        note = parse(text, rel)
        full = note.title + "\n" + note.search_text
        dedup = dedup_tokens(note.title, note.search_text)
        notes[rel] = (full[:MAX_NOTE_CHARS], _useful(full), dedup)
    return notes


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


def _keyword_hits(query: str, notes: dict[str, tuple[str, set[str], set[str]]]) -> list[str]:
    want = _useful(query)
    if not want:
        return []
    return [rel for rel, (_t, toks, _d) in notes.items() if want <= toks]


@dataclass(frozen=True)
class Options:
    """Settings of one measurement."""

    zone: str | None = None
    top_k: int = DEFAULT_TOP_K
    min_score: float = DEFAULT_MIN_SCORE


@dataclass(frozen=True)
class _Corpus:
    """Memory paths with their vectors, in the same order."""

    rels: list[str]
    vectors: list[list[float]]


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


def _load_zone(vault_root: Path, zone: str | None) -> dict[str, tuple[str, set[str], set[str]]]:
    vault = Vault(Path(vault_root))
    prefix = _zone_prefix(vault, zone)
    notes = _load_notes(vault, prefix)
    if not notes:
        raise EpistemeError(
            INVALID_ARGUMENT,
            f"no notes found under zone {prefix!r}. Pass --zone with a folder of the vault.",
        )
    return notes


def _query_rows(
    queries: list[str], vectors: list[list[float]], notes: dict, corpus: _Corpus, opts: Options
) -> list[dict]:
    rows = []
    for query, qvec in zip(queries, vectors, strict=True):
        keyword = _keyword_hits(query, notes)
        near = _neighbours(qvec, corpus, opts)
        rows.append({
            "query": query,
            "keyword": keyword,
            "semantic": near,
            "new": [(r, s) for r, s in near if r not in keyword],
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
    notes = _load_zone(vault_root, opts.zone)
    unique = list(dict.fromkeys(q for q in (queries or []) if q.strip()))
    timed = _Timed(embed)
    rels = list(notes)
    start = time.perf_counter()
    corpus = _Corpus(rels, _embed_all(timed, [notes[r][0] for r in rels]))
    corpus_s = time.perf_counter() - start
    n_corpus = len(timed.latencies)
    qvectors = _embed_all(timed, unique) if unique else []
    return {
        "docs": len(notes),
        "rows": _query_rows(unique, qvectors, notes, corpus, opts),
        "pairs": _missed_pairs(rels, corpus.vectors, [notes[r][2] for r in rels]),
        "corpus_s": corpus_s,
        "top_k": opts.top_k,
        "min_score": opts.min_score,
        **_latencies(timed.latencies, n_corpus),
    }


def _render_queries(rows: list[dict], examples: int) -> list[str]:
    out = ["", "## Por consulta", ""]
    if not rows:
        return [*out, "- (sin consultas: usa `--queries-file` o el registro de actividad)"]
    ranked = sorted(rows, key=lambda r: (-len(r["new"]), r["query"]))
    for r in ranked[:examples]:
        out.append(f"- «{r['query']}»: palabras {len(r['keyword'])}, vecinos {len(r['semantic'])}, "
                   f"nuevos {len(r['new'])}")
        out += [f"    - {rel} ({score:.2f})" for rel, score in r["new"]]
    return out


def _render_pairs(pairs: list[tuple[str, str, float, float]]) -> list[str]:
    out = ["", "## Pares parecidos que los tokens no detectan", ""]
    if not pairs:
        return [*out, "- (ninguno)"]
    out.append(f"{len(pairs)} pares con coseno de {PAIR_MIN_SCORE} o más y similitud por tokens "
               f"bajo {PAIR_MAX_TOKEN_SIM}.")
    out.append("")
    out += [f"- {a} / {b}: coseno {s:.2f}, tokens {t:.2f}" for a, b, s, t in pairs[:PAIRS_SHOWN]]
    return out


def render(result: dict, examples: int) -> str:
    rows = result["rows"]
    gaining = sum(1 for r in rows if r["new"])
    out = [
        "# Medición de embeddings",
        "",
        f"- Memorias: {result['docs']}",
        f"- Consultas: {len(rows)}",
        f"- Vecinos: top {result['top_k']} con puntaje de {result['min_score']} o más",
        "",
        "## Resumen",
        "",
        f"- Consultas que ganan algo sobre la búsqueda por palabras: {gaining} de {len(rows)}",
        f"- Vecinos nuevos en total: {sum(len(r['new']) for r in rows)}",
    ]
    out += _render_queries(rows, examples)
    out += _render_pairs(result["pairs"])
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
    ap.add_argument("--examples", type=int, default=DEFAULT_EXAMPLES)
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
        result = measure(args.vault, embed, queries, Options(args.zone, args.top_k, args.min_score))
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
