"""Measure what stemming or SQLite trigrams would add to search on a vault.

    uv run scripts/measure_recall.py --vault <vault> [--zone memory] [--terms a,b,c] \
        [--terms-file <file>] [--top 200] [--min-len 4] [--examples 15]

Read-only: walks the vault with ``Vault.iter_notes`` and ``parse``; it never opens or
creates the index and writes nothing in the vault. For each term it counts the documents
matched by four strategies: ``exact`` (a token equals the term), ``prefix`` (a token starts
with it), ``stem`` (a token has the same Spanish Snowball stem) and ``trigram`` (the folded
text contains it as a substring).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from episteme.errors import EpistemeError
from episteme.index import STOPWORDS_ES
from episteme.markdown import fold, parse, tokens
from episteme.vault import MEMORY, Vault

NOISE_EXAMPLES = 10


def _stemmer():
    import snowballstemmer

    return snowballstemmer.stemmer("spanish")


def _zone_prefix(vault: Vault, zone: str | None) -> str:
    if zone is None:
        z = vault.memory_zone
        if z is None:
            raise EpistemeError(
                "invalid_argument",
                f"the vault has no zone with mode {MEMORY!r}. Pass --zone <zone path>.",
            )
        return z.path
    return zone.replace("\\", "/").strip("/")


def _load_corpus(vault: Vault, zone: str) -> dict[str, tuple[set[str], str]]:
    """Relative path -> (token set without stopwords, folded text)."""
    corpus: dict[str, tuple[set[str], str]] = {}
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
        toks = {t for t in tokens(full, min_len=2) if t not in STOPWORDS_ES}
        corpus[rel] = (toks, fold(full))
    return corpus


def measure(
    vault_root: Path,
    zone: str | None = None,
    terms: list[str] | None = None,
    top: int = 200,
    min_len: int = 4,
) -> dict:
    """Document sets per term and strategy, plus corpus statistics."""
    vault = Vault(Path(vault_root))
    corpus = _load_corpus(vault, _zone_prefix(vault, zone))
    if not corpus:
        raise EpistemeError(
            "invalid_argument",
            f"no notes found under zone {zone!r}. Pass --zone with a folder of the vault.",
        )
    stem = _stemmer()

    token_docs: dict[str, set[str]] = defaultdict(set)
    for rel, (toks, _folded) in corpus.items():
        for t in toks:
            token_docs[t].add(rel)

    stem_forms: dict[str, set[str]] = defaultdict(set)
    stem_docs: dict[str, set[str]] = defaultdict(set)
    for t, docs in token_docs.items():
        s = stem.stemWord(t)
        stem_forms[s].add(t)
        stem_docs[s] |= docs
    families = {s: f for s, f in stem_forms.items() if len(f) >= 2}

    if terms:
        chosen = list(dict.fromkeys(fold(t.strip()) for t in terms if t.strip()))
    else:
        alpha = [t for t in token_docs if t.isalpha() and len(t) >= min_len]
        alpha.sort(key=lambda t: (-len(token_docs[t]), t))
        chosen = alpha[:top]

    results: dict[str, dict] = {}
    for term in chosen:
        exact = set(token_docs.get(term, ()))
        prefix = set(exact)
        for t, docs in token_docs.items():
            if t.startswith(term):
                prefix |= docs
        results[term] = {
            "exact": exact,
            "prefix": prefix,
            "stem": set(stem_docs.get(stem.stemWord(term), ())) | exact,
            # SQLite's trigram tokenizer cannot match terms shorter than 3 characters.
            "trigram": (
                {rel for rel, (_t, folded) in corpus.items() if term in folded} | exact
                if len(term) >= 3
                else set(exact)
            ),
        }

    return {
        "docs": len(corpus),
        "vocabulary": len(token_docs),
        "families": families,
        "family_docs": {s: set().union(*(token_docs[t] for t in f)) for s, f in families.items()},
        "terms": results,
        "token_docs": token_docs,
    }


def _gain(r: dict, key: str) -> float:
    return len(r[key] - r["exact"]) / len(r["exact"])


def _noise(result: dict) -> tuple[int, list[tuple[str, str]]]:
    vocab = sorted(result["token_docs"])
    total = 0
    examples: list[tuple[str, str]] = []
    for term, r in result["terms"].items():
        extra = r["trigram"] - r["prefix"] - r["stem"]
        total += len(extra)
        if extra and len(examples) < NOISE_EXAMPLES:
            host = next(
                (
                    t
                    for t in vocab
                    if term in t and not t.startswith(term) and result["token_docs"][t] & extra
                ),
                None,
            )
            if host:
                examples.append((term, host))
    return total, examples


def render(result: dict, examples: int) -> str:
    terms = result["terms"]
    family_docs = set().union(*result["family_docs"].values()) if result["family_docs"] else set()
    out = [
        "# Medición de variantes de búsqueda",
        "",
        f"- Documentos: {result['docs']}",
        f"- Vocabulario: {result['vocabulary']} tokens",
        f"- Términos medidos: {len(terms)}",
        "",
        "## Familias de raíz",
        "",
        f"{len(result['families'])} raíces con 2 formas o más; "
        f"tocan {len(family_docs)} documentos.",
        "",
    ]
    biggest = sorted(result["families"].items(), key=lambda kv: (-len(kv[1]), kv[0]))[:10]
    for s, forms in biggest:
        out.append(
            f"- `{s}`: {', '.join(sorted(forms))} ({len(result['family_docs'][s])} documentos)"
        )
    out += ["", "## Mayor ganancia por término", ""]
    out += ["| término | exact | +stem | +prefix | +trigram |", "|---|---|---|---|---|"]

    def best(item: tuple[str, dict]) -> tuple[int, str]:
        r = item[1]
        return (-max(len(r[k] - r["exact"]) for k in ("stem", "prefix", "trigram")), item[0])

    for term, r in sorted(terms.items(), key=best)[:examples]:
        out.append(
            f"| {term} | {len(r['exact'])} | +{len(r['stem'] - r['exact'])} "
            f"| +{len(r['prefix'] - r['exact'])} | +{len(r['trigram'] - r['exact'])} |"
        )
    out += ["", "## Ganancia relativa (sobre `exact`, solo términos con `exact` > 0)", ""]
    out += ["| estrategia | media | mediana |", "|---|---|---|"]
    for key in ("stem", "prefix", "trigram"):
        gains = [_gain(r, key) for r in terms.values() if r["exact"]]
        mean = statistics.fmean(gains) if gains else 0.0
        med = statistics.median(gains) if gains else 0.0
        out.append(f"| {key} | {mean:.1%} | {med:.1%} |")
    total, ex = _noise(result)
    out += [
        "",
        "## Ruido estimado del trigrama",
        "",
        "Documentos que solo añade el trigrama (ni prefijo ni raíz), "
        f"sumados por término: {total}.",
        "",
    ]
    out += [f"- {term} → {host}" for term, host in ex] or ["- (sin ejemplos)"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--zone", default=None, help="zone path (default: the memory zone)")
    ap.add_argument("--terms", default=None, help="comma-separated terms")
    ap.add_argument("--terms-file", type=Path, default=None, help="one term per line")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--min-len", type=int, default=4)
    ap.add_argument("--examples", type=int, default=15)
    args = ap.parse_args(argv)

    try:
        import snowballstemmer  # noqa: F401
    except ImportError:
        print(
            "snowballstemmer is not installed. Run `uv run scripts/measure_recall.py` from the "
            "repo (it is a dev dependency) or `uv pip install snowballstemmer`.",
            file=sys.stderr,
        )
        return 2

    terms: list[str] | None = None
    if args.terms or args.terms_file:
        terms = []
        if args.terms:
            terms += args.terms.split(",")
        if args.terms_file:
            terms += args.terms_file.read_text(encoding="utf-8").splitlines()
    try:
        result = measure(args.vault, args.zone, terms, args.top, args.min_len)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1
    out = render(result, args.examples)
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
