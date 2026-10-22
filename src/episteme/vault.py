"""episteme.toml, zones, path confinement and atomic writes."""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from episteme.errors import (
    OUTSIDE_VAULT,
    READ_ONLY_ZONE,
    EpistemeError,
    StartupError,
    invalid,
)

READ_ONLY = "read-only"
READ_WRITE = "read-write"
MEMORY = "memory"
MODES = (READ_ONLY, READ_WRITE, MEMORY)
CONFIG_FILE = "episteme.toml"
INDEX_DIR = ".index"


@dataclass
class DirListing:
    """A cached directory listing: visible subdirectories and ``.md`` notes (relative paths)."""

    mtime_ns: int
    subdirs: list[str]
    notes: list[str]


@dataclass(frozen=True)
class Zone:
    path: str
    mode: str


@dataclass
class Config:
    zones: list[Zone] = field(default_factory=list)
    state_glob: str | None = None


def load_config(root: Path) -> Config:
    """Parse ``episteme.toml``; any invalid value raises StartupError."""
    path = root / CONFIG_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StartupError(f"cannot read {path}: {exc}. Fix the file and restart.") from exc

    zones: list[Zone] = []
    seen: set[str] = set()
    raw_zones = data.get("zones", {})
    if not isinstance(raw_zones, dict):
        raise StartupError("[zones] in episteme.toml must be a table of zone paths.")
    for key, value in raw_zones.items():
        name = key.strip().strip("/")
        if not name or ".." in PurePosixPath(name).parts or key.startswith("/"):
            raise StartupError(f'zone "{key}" must be a path relative to the vault root.')
        if name in seen:
            raise StartupError(f'zone "{name}" is declared twice in episteme.toml.')
        seen.add(name)
        mode = value.get("mode") if isinstance(value, dict) else None
        if mode not in MODES:
            raise StartupError(
                f'zone "{name}" has mode {mode!r}; use one of {", ".join(MODES)}.'
            )
        zones.append(Zone(name, mode))

    state_glob = None
    checkpoint = data.get("checkpoint", {})
    if isinstance(checkpoint, dict) and checkpoint.get("state_glob") is not None:
        state_glob = checkpoint["state_glob"]
        if not isinstance(state_glob, str) or not state_glob:
            raise StartupError("[checkpoint] state_glob must be a non-empty string.")
    return Config(zones, state_glob)


def today() -> dt.date:
    """Today's date in UTC, or ``EPISTEME_TODAY`` (YYYY-MM-DD) when set."""
    fixed = os.environ.get("EPISTEME_TODAY")
    if fixed:
        return dt.date.fromisoformat(fixed)
    return dt.datetime.now(dt.UTC).date()


def is_ignored(rel: str) -> bool:
    """Dot folders (.obsidian, .index, .git…) and non-Markdown files are invisible."""
    parts = PurePosixPath(rel).parts
    return any(p.startswith(".") for p in parts[:-1]) or not rel.lower().endswith(".md")


class Vault:
    """A vault root with its zones. All paths handed out are relative and use ``/``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.realpath(root))
        self.config = load_config(self.root)

    # -- paths -------------------------------------------------------------

    def resolve(self, rel: str) -> Path:
        """Turn a vault-relative path into an absolute one, confined to the vault."""
        if not isinstance(rel, str) or not rel.strip():
            raise invalid("empty path. Pass a path relative to the vault.")
        rel = rel.replace("\\", "/")
        pure = PurePosixPath(rel)
        if pure.is_absolute() or rel.startswith("~") or (len(rel) > 1 and rel[1] == ":"):
            raise EpistemeError(
                OUTSIDE_VAULT, f'"{rel}" is absolute. Use a path relative to the vault.'
            )
        if ".." in pure.parts:
            raise EpistemeError(
                OUTSIDE_VAULT, f'"{rel}" leaves the vault. Use a path relative to the vault.'
            )
        full = Path(os.path.realpath(self.root / pure))
        if full != self.root and self.root not in full.parents:
            raise EpistemeError(
                OUTSIDE_VAULT,
                f'"{rel}" resolves outside the vault through a symlink. '
                "Use a path inside the vault.",
            )
        return full

    def rel(self, path: Path) -> str:
        return Path(os.path.realpath(path)).relative_to(self.root).as_posix()

    def iter_notes(self) -> Iterator[tuple[str, os.stat_result]]:
        """Every visible ``.md`` note with its stat, skipping symlinks that leave the vault."""
        yield from self.scan_notes({})

    def scan_notes(self, cache: dict[str, DirListing]) -> Iterator[tuple[str, os.stat_result]]:
        """Like ``iter_notes``, reusing a directory's listing while its mtime is unchanged.

        A directory's mtime moves when an entry is added, removed or renamed (also on atomic
        replace), so the listing is only rebuilt then. Files are always stat-ed: an in-place
        edit does not touch the directory. ``cache`` (keyed by relative dir, ``""`` for the root)
        is updated in place and pruned of directories that no longer exist.
        """
        seen: set[str] = set()
        stack = [""]
        while stack:
            reldir = stack.pop()
            base = self.root / reldir if reldir else self.root
            try:
                dir_mtime = base.stat().st_mtime_ns
            except OSError:
                continue
            seen.add(reldir)
            listing = cache.get(reldir)
            if listing is None or listing.mtime_ns != dir_mtime:
                listing = self._list_dir(base, reldir, dir_mtime)
                cache[reldir] = listing
            stack.extend(reversed(listing.subdirs))
            for rel in listing.notes:
                try:
                    st = (self.root / rel).stat()
                except OSError:
                    continue
                yield rel, st
        for gone in set(cache) - seen:
            del cache[gone]

    def _list_dir(self, base: Path, reldir: str, mtime_ns: int) -> DirListing:
        subdirs: list[str] = []
        notes: list[str] = []
        try:
            entries = sorted(os.scandir(base), key=lambda e: e.name)
        except OSError:
            return DirListing(mtime_ns, [], [])
        for entry in entries:
            rel = f"{reldir}/{entry.name}" if reldir else entry.name
            if entry.is_dir(follow_symlinks=False):
                if not entry.name.startswith("."):
                    subdirs.append(rel)
            elif entry.name.lower().endswith(".md"):
                if entry.is_symlink():
                    try:
                        self.resolve(rel)
                    except EpistemeError:
                        continue
                notes.append(rel)
        return DirListing(mtime_ns, subdirs, notes)

    # -- zones -------------------------------------------------------------

    def zone_for(self, rel: str) -> Zone | None:
        """The most specific zone containing ``rel``, or None."""
        best: Zone | None = None
        for zone in self.config.zones:
            if rel == zone.path or rel.startswith(zone.path + "/"):
                if best is None or len(zone.path) > len(best.path):
                    best = zone
        return best

    def mode_for(self, rel: str) -> str:
        zone = self.zone_for(rel)
        return zone.mode if zone else READ_ONLY

    def check_writable(self, rel: str) -> str:
        """Return the zone mode of ``rel`` or raise ``read_only_zone``.

        Both ``rel`` and the path it resolves to must be writable: a symlink in a
        writable zone must not reach a read-only one.
        """
        real = self.rel(self.resolve(rel))
        for path in (rel, real):
            if self.mode_for(path) != READ_ONLY:
                continue
            where = "a read-only zone" if self.zone_for(path) else "no zone, so it is read-only"
            via = f"{rel} resolves to {real}, which is in " if path != rel else f"{rel} is in "
            raise EpistemeError(
                READ_ONLY_ZONE, f"{via}{where}. Notes there are changed outside this server."
            )
        return self.mode_for(real)

    @property
    def memory_zone(self) -> Zone | None:
        return next((z for z in self.config.zones if z.mode == MEMORY), None)

    # -- writes ------------------------------------------------------------

    def write_atomic(self, rel: str, text: str) -> Path:
        """Write ``text`` to ``rel`` through a temporary file in the same folder."""
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The parent may have been created through a symlink: check again.
        self.resolve(rel)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    def create_exclusive(self, rel: str, text: str) -> bool:
        """Create ``rel`` only if it does not exist yet; False if it already does."""
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.resolve(rel)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            try:
                os.link(tmp, path)
            except FileExistsError:
                return False
            return True
        finally:
            os.unlink(tmp)
