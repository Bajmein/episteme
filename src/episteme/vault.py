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
DOCS = "docs"
SESSION = "session"
MODES = (READ_ONLY, READ_WRITE, MEMORY, DOCS, SESSION)
# Zones that only their own tool writes: mode -> that tool. revise refuses them.
TOOL_MODES: dict[str, str] = {DOCS: "docs_write", SESSION: "session"}
# The session zone load_config adds when episteme.toml declares none.
SESSION_ZONE = "sesiones"
CONFIG_FILE = "episteme.toml"
INDEX_DIR = ".index"
DEFAULT_EVERY_DAYS = 1
DEFAULT_BACKUP_KEEP = 14
DEFAULT_ARCHIVE_DAYS = 7
DEFAULT_NUDGE_EVERY = 12
SESSION_KEYS = ("extract", "block_manual_compact", "archive_days", "nudge_every")


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


@dataclass(frozen=True)
class Maintenance:
    every_days: int = DEFAULT_EVERY_DAYS
    notify: bool = True
    archive_expired: bool = False


@dataclass(frozen=True)
class Backup:
    dir: Path | None = None
    keep: int = DEFAULT_BACKUP_KEEP


@dataclass(frozen=True)
class Session:
    extract: bool = True
    block_manual_compact: bool = True
    archive_days: int = DEFAULT_ARCHIVE_DAYS
    nudge_every: int = DEFAULT_NUDGE_EVERY


@dataclass
class Config:
    zones: list[Zone] = field(default_factory=list)
    state_glob: str | None = None
    maintenance: Maintenance = field(default_factory=Maintenance)
    backup: Backup = field(default_factory=Backup)
    session: Session = field(default_factory=Session)


def _table(data: dict, name: str, allowed: tuple[str, ...]) -> dict:
    """Return ``[name]`` from the TOML data, rejecting non-tables and unknown keys."""
    table = data.get(name, {})
    if not isinstance(table, dict):
        raise StartupError(f"[{name}] in episteme.toml must be a table.")
    for key in table:
        if key not in allowed:
            raise StartupError(
                f'[{name}] has unknown key "{key}"; valid keys are {", ".join(allowed)}.'
            )
    return table


def _is_positive_int(value: object) -> bool:
    """True for an int >= 1; ``bool`` is excluded."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _int_min1(table: dict, name: str, key: str, default: int) -> int:
    value = table.get(key, default)
    if not _is_positive_int(value):
        raise StartupError(f"[{name}] {key} must be an integer >= 1.")
    return value


def _flag(table: dict, name: str, key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise StartupError(f"[{name}] {key} must be true or false.")
    return value


def _load_maintenance(data: dict) -> Maintenance:
    table = _table(data, "maintenance", ("every_days", "notify", "archive_expired"))
    return Maintenance(
        every_days=_int_min1(table, "maintenance", "every_days", DEFAULT_EVERY_DAYS),
        notify=_flag(table, "maintenance", "notify", True),
        archive_expired=_flag(table, "maintenance", "archive_expired", False),
    )


def _load_session(data: dict) -> Session:
    table = _table(data, "session", SESSION_KEYS)
    return Session(
        extract=_flag(table, "session", "extract", True),
        block_manual_compact=_flag(table, "session", "block_manual_compact", True),
        archive_days=_int_min1(table, "session", "archive_days", DEFAULT_ARCHIVE_DAYS),
        nudge_every=_int_min1(table, "session", "nudge_every", DEFAULT_NUDGE_EVERY),
    )


def _backup_dir(raw: str) -> Path:
    """Expand ``raw`` into an absolute backup directory or raise StartupError."""
    try:
        target = Path(raw).expanduser()
    except RuntimeError as exc:
        raise StartupError(f'[backup] dir "{raw}" cannot be expanded: {exc}.') from exc
    if not target.is_absolute():
        raise StartupError(f'[backup] dir "{raw}" must be an absolute path.')
    return target


def _check_outside_vault(target: Path, raw: str, root: Path) -> None:
    """Raise StartupError when ``target`` is the vault or lies inside it."""
    real = Path(os.path.normcase(os.path.realpath(target)))
    real_root = Path(os.path.normcase(os.path.realpath(root)))
    if real == real_root or real_root in real.parents:
        raise StartupError(f'[backup] dir "{raw}" must be outside the vault.')


def _load_backup(data: dict, root: Path) -> Backup:
    table = _table(data, "backup", ("dir", "keep"))
    if "backup" not in data:
        return Backup()
    raw = table.get("dir")
    if not isinstance(raw, str) or not raw.strip():
        raise StartupError("[backup] dir must be a non-empty string.")
    target = _backup_dir(raw)
    _check_outside_vault(target, raw, root)
    return Backup(dir=target, keep=_int_min1(table, "backup", "keep", DEFAULT_BACKUP_KEEP))


def _zone_name(key: str) -> str:
    """Normalise a zone key into a vault-relative path or raise StartupError."""
    name = key.strip().strip("/")
    if not name or ".." in PurePosixPath(name).parts or key.startswith("/"):
        raise StartupError(f'zone "{key}" must be a path relative to the vault root.')
    return name


def _zone_mode(name: str, value: object) -> str:
    """The valid ``mode`` of a zone table or raise StartupError."""
    mode = value.get("mode") if isinstance(value, dict) else None
    if mode not in MODES:
        raise StartupError(f'zone "{name}" has mode {mode!r}; use one of {", ".join(MODES)}.')
    return mode


def _load_zones(data: dict) -> list[Zone]:
    zones: list[Zone] = []
    seen: set[str] = set()
    raw_zones = data.get("zones", {})
    if not isinstance(raw_zones, dict):
        raise StartupError("[zones] in episteme.toml must be a table of zone paths.")
    for key, value in raw_zones.items():
        name = _zone_name(key)
        if name in seen:
            raise StartupError(f'zone "{name}" is declared twice in episteme.toml.')
        seen.add(name)
        zones.append(Zone(name, _zone_mode(name, value)))
    return _with_session_zone(zones)


def _with_session_zone(zones: list[Zone]) -> list[Zone]:
    """``zones`` plus the implicit ``sesiones`` zone when none has mode ``session``."""
    if any(z.mode == SESSION for z in zones):
        return zones
    if any(z.path == SESSION_ZONE for z in zones):
        raise StartupError(
            f'zone "{SESSION_ZONE}" must have mode "{SESSION}" (the session state lives there). '
            f'Set its mode to "{SESSION}" or declare another zone with that mode.'
        )
    return [*zones, Zone(SESSION_ZONE, SESSION)]


def _load_state_glob(data: dict) -> str | None:
    checkpoint = data.get("checkpoint", {})
    if not isinstance(checkpoint, dict) or checkpoint.get("state_glob") is None:
        return None
    state_glob = checkpoint["state_glob"]
    if not isinstance(state_glob, str) or not state_glob:
        raise StartupError("[checkpoint] state_glob must be a non-empty string.")
    return state_glob


def load_config(root: Path) -> Config:
    """Parse ``episteme.toml``; any invalid value raises StartupError."""
    path = root / CONFIG_FILE
    if path.is_symlink():
        raise StartupError(f"{CONFIG_FILE} must be a regular file, not a symlink. Replace it.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StartupError(f"cannot read {path}: {exc}. Fix the file and restart.") from exc
    return Config(
        _load_zones(data),
        _load_state_glob(data),
        _load_maintenance(data),
        _load_backup(data, root),
        _load_session(data),
    )


def today() -> dt.date:
    """Today's local date, or ``EPISTEME_TODAY`` (YYYY-MM-DD) when set."""
    fixed = os.environ.get("EPISTEME_TODAY")
    if fixed:
        return dt.date.fromisoformat(fixed)
    return dt.date.today()


def _is_absolute_like(rel: str, pure: PurePosixPath) -> bool:
    """True for POSIX-absolute, ``~`` home or drive-letter (``C:``) paths."""
    return pure.is_absolute() or rel.startswith("~") or (len(rel) > 1 and rel[1] == ":")


def _relative_parts(rel: str) -> tuple[str, PurePosixPath]:
    """Check a path that arrives from a tool; return it with ``/`` separators, and its parts."""
    if not isinstance(rel, str) or not rel.strip():
        raise invalid("empty path. Pass a path relative to the vault.")
    if "\x00" in rel:
        raise invalid("path has a null character. Use a plain path relative to the vault.")
    rel = rel.replace("\\", "/")
    pure = PurePosixPath(rel)
    if _is_absolute_like(rel, pure):
        raise EpistemeError(
            OUTSIDE_VAULT, f'"{rel}" is absolute. Use a path relative to the vault.'
        )
    if ".." in pure.parts:
        raise EpistemeError(
            OUTSIDE_VAULT, f'"{rel}" leaves the vault. Use a path relative to the vault.'
        )
    return rel, pure


def _real_path(root: Path, rel: str, pure: PurePosixPath) -> Path:
    """``realpath`` of ``root / pure``; an unusable path is ``invalid_argument``, not a crash."""
    try:
        return Path(os.path.realpath(root / pure))
    except OSError, ValueError:
        raise invalid(f'"{rel}" is not a usable path. Use a shorter plain path.') from None


def is_ignored(rel: str) -> bool:
    """Dot folders (.obsidian, .index, .git…) and non-Markdown files are invisible."""
    parts = PurePosixPath(rel).parts
    return any(p.startswith(".") for p in parts[:-1]) or not rel.lower().endswith(".md")


def _dir_mtime(base: Path) -> int | None:
    """Directory mtime in ns, or None if it cannot be stat-ed."""
    try:
        return base.stat().st_mtime_ns
    except OSError:
        return None


class Vault:
    """A vault root with its zones. All paths handed out are relative and use ``/``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.realpath(root))
        self.config = load_config(self.root)

    # -- paths -------------------------------------------------------------

    def resolve(self, rel: str) -> Path:
        """Turn a vault-relative path into an absolute one, confined to the vault."""
        rel, pure = _relative_parts(rel)
        full = _real_path(self.root, rel, pure)
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
            dir_mtime = _dir_mtime(base)
            if dir_mtime is None:
                continue
            seen.add(reldir)
            listing = cache.get(reldir)
            if listing is None or listing.mtime_ns != dir_mtime:
                listing = self._list_dir(base, reldir, dir_mtime)
                cache[reldir] = listing
            stack.extend(reversed(listing.subdirs))
            for rel in listing.notes:
                st = self._stat_note(rel)
                if st is not None:
                    yield rel, st
        for gone in set(cache) - seen:
            del cache[gone]

    def _stat_note(self, rel: str) -> os.stat_result | None:
        """Stat of the note at ``rel``, or None if it vanished."""
        try:
            return (self.root / rel).stat()
        except OSError:
            return None

    def _note_visible(self, rel: str) -> bool:
        """False for a symlinked note that leaves the vault."""
        try:
            self.resolve(rel)
        except EpistemeError:
            return False
        return True

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
                continue
            if not entry.name.lower().endswith(".md"):
                continue
            if entry.is_symlink() and not self._note_visible(rel):
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

    @property
    def docs_zones(self) -> list[Zone]:
        return [z for z in self.config.zones if z.mode == DOCS]

    @property
    def session_zone(self) -> Zone:
        """The zone of the session state; load_config always leaves one."""
        return next(z for z in self.config.zones if z.mode == SESSION)

    # -- writes ------------------------------------------------------------

    def _stage(self, rel: str, text: str) -> tuple[Path, str]:
        """Resolve ``rel`` and write ``text`` to a temporary file beside it."""
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The parent may have been created through a symlink: check again.
        self.resolve(rel)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path, tmp

    def write_atomic(self, rel: str, text: str) -> Path:
        """Write ``text`` to ``rel`` through a temporary file in the same folder."""
        path, tmp = self._stage(rel, text)
        try:
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    def create_exclusive(self, rel: str, text: str) -> bool:
        """Create ``rel`` only if it does not exist yet; False if it already does."""
        path, tmp = self._stage(rel, text)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        finally:
            os.unlink(tmp)
        return True

    def remove(self, rel: str) -> None:
        """Delete ``rel``. Only ``revise`` uses it, to move a memory to its new folder."""
        os.unlink(self.resolve(rel))
