"""episteme.toml, zones, path confinement and atomic writes."""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from episteme_mcp.errors import (
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
INDEX_DIR = ".episteme"


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
    """Dot folders (.obsidian, .episteme, .git…) and non-Markdown files are invisible."""
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
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            base = Path(dirpath)
            for name in sorted(filenames):
                if not name.lower().endswith(".md"):
                    continue
                path = base / name
                rel = path.relative_to(self.root).as_posix()
                if path.is_symlink():
                    try:
                        self.resolve(rel)
                    except EpistemeError:
                        continue
                try:
                    st = path.stat()
                except OSError:
                    continue
                yield rel, st

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
        """Return the zone mode of ``rel`` or raise ``read_only_zone``."""
        mode = self.mode_for(rel)
        if mode == READ_ONLY:
            where = "a read-only zone" if self.zone_for(rel) else "no zone, so it is read-only"
            raise EpistemeError(
                READ_ONLY_ZONE,
                f"{rel} is in {where}. Notes there are changed outside this server.",
            )
        return mode

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
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
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
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
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
