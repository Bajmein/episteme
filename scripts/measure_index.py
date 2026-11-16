"""Measure how long the indexer takes, on a copy of the vault.

    uv run scripts/measure_index.py --vault <vault> [--runs 5]

Never writes in the vault: ``Index`` creates ``<vault>/.index/index.db``, so the script
copies the vault (without the entries whose name starts with a dot, such as ``.index`` or
``.obsidian``) to a temporary directory and works there. It times, with
``time.perf_counter``:

1. a full index (opening ``Index`` and the first ``refresh()`` with no ``.index``);
2. a ``refresh()`` with nothing changed (what every tool call pays);
3. an incremental ``refresh()`` with 1 and with 10 notes changed (their mtime moved).

Each measure runs ``--runs`` times and the report gives the median, plus the number of
notes and the size of ``index.db``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from episteme.errors import INVALID_ARGUMENT, NOT_FOUND, EpistemeError
from episteme.index import Index
from episteme.vault import INDEX_DIR, Vault

DEFAULT_RUNS = 5
CHANGED = (1, 10)
NOOP_LIMIT_MS = 20  # the criterion in docs/desarrollo.md: touch the indexer above this
FULL_LIMIT_S = 3


@dataclass(frozen=True)
class Result:
    notes: int
    db_bytes: int
    runs: int
    full_ms: float
    noop_ms: float
    incremental_ms: dict[int, float]


def _copy_vault(src: Path, dst: Path) -> Path:
    """Copy ``src`` into ``dst/vault``, leaving out every entry whose name starts with a dot."""
    target = dst / "vault"
    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".*"))
    return target


def _timed(fn: Callable[[], object]) -> float:
    """Milliseconds ``fn`` takes."""
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def _full_once(root: Path) -> float:
    """Milliseconds to build the index from scratch."""
    shutil.rmtree(root / INDEX_DIR, ignore_errors=True)
    holder: list[Index] = []

    def build() -> None:
        ix = Index(Vault(root))
        ix.refresh()
        holder.append(ix)

    ms = _timed(build)
    holder[0].close()
    return ms


def _touch(root: Path, rels: list[str], step: int) -> None:
    """Move the mtime of each note so that its signature changes."""
    for rel in rels:
        path = root / rel
        ns = path.stat().st_mtime_ns + step * 1_000_000_000
        os.utime(path, ns=(ns, ns))


def _incremental(ix: Index, root: Path, rels: list[str], runs: int) -> float:
    """Median milliseconds of a refresh() after changing ``rels``."""
    times = []
    for step in range(1, runs + 1):
        _touch(root, rels, step)
        times.append(_timed(ix.refresh))
    return median(times)


def _check_vault(vault_root: Path) -> None:
    if not vault_root.is_dir():
        raise EpistemeError(NOT_FOUND, f"no vault at {vault_root}. Pass --vault <dir>.")


def measure(vault_root: Path, runs: int = DEFAULT_RUNS) -> Result:
    """Time the indexer on a temporary copy of ``vault_root``; the vault is not touched."""
    _check_vault(vault_root)
    if runs < 1:
        raise EpistemeError(INVALID_ARGUMENT, f"--runs must be positive, got {runs}.")
    with tempfile.TemporaryDirectory(prefix="episteme-measure-index-") as tmp:
        root = _copy_vault(vault_root, Path(tmp))
        full = median(_full_once(root) for _ in range(runs))
        ix = Index(Vault(root))
        try:
            ix.refresh()
            noop = median(_timed(ix.refresh) for _ in range(runs))
            rels = [r["path"] for r in ix.conn.execute("select path from notes order by path")]
            incremental = {n: _incremental(ix, root, rels[:n], runs) for n in CHANGED}
        finally:
            ix.close()
        db_bytes = (root / INDEX_DIR / "index.db").stat().st_size
    return Result(len(rels), db_bytes, runs, full, noop, incremental)


def _verdict(r: Result) -> str:
    if r.noop_ms > NOOP_LIMIT_MS or r.full_ms > FULL_LIMIT_S * 1000:
        return "Conviene revisar el indexador: pasa alguno de los umbrales."
    return "No hace falta tocar el indexador: ningún umbral se pasa."


def render(r: Result) -> str:
    """The report, in Spanish."""
    lines = [
        "# Medición del indexador",
        "",
        f"- Notas: {r.notes}",
        f"- Tamaño de index.db: {r.db_bytes / 1024:.0f} KiB",
        f"- Repeticiones por medida: {r.runs} (se informa la mediana)",
        "",
        "| Medida | Mediana |",
        "|---|---|",
        f"| Indexado completo | {r.full_ms:.1f} ms |",
        f"| refresh() sin cambios | {r.noop_ms:.2f} ms |",
    ]
    lines += [
        f"| refresh() con {n} nota{'s' if n > 1 else ''} cambiada{'s' if n > 1 else ''} "
        f"| {ms:.1f} ms |"
        for n, ms in r.incremental_ms.items()
    ]
    lines += [
        "",
        f"Umbrales: refresh() sin cambios hasta {NOOP_LIMIT_MS} ms; indexado completo hasta "
        f"{FULL_LIMIT_S} s. {_verdict(r)}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="repetitions per measure")
    args = ap.parse_args(argv)
    try:
        result = measure(args.vault, args.runs)
    except EpistemeError as e:
        print(e, file=sys.stderr)
        return 1
    sys.stdout.buffer.write(render(result).encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
