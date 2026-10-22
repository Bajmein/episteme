"""Wikilink resolution (Obsidian subset) and graph traversal."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

from episteme.errors import AMBIGUOUS, NOT_FOUND, EpistemeError


def _strip_md(name: str) -> str:
    return name[:-3] if name.lower().endswith(".md") else name


class Resolver:
    """Resolves a link destination or note name to a vault path.

    Order: exact path (with or without ``.md``), then base name (or path suffix when the
    target has folders), then ``aliases``. Several candidates at one step is ambiguous,
    unless a ``source`` note is given and exactly one candidate sits in its folder: like
    Obsidian, a repeated name prefers the note in the same folder as the link.
    """

    def __init__(self, notes: Iterable[tuple[str, Iterable[str]]]) -> None:
        self.by_path: dict[str, str] = {}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.by_alias: dict[str, list[str]] = defaultdict(list)
        self.paths: list[str] = []
        for path, aliases in notes:
            self.paths.append(path)
            self.by_path[path.lower()] = path
            self.by_path[_strip_md(path).lower()] = path
            self.by_name[_strip_md(PurePosixPath(path).name).lower()].append(path)
            for alias in aliases:
                key = alias.strip().lower()
                if key and path not in self.by_alias[key]:
                    self.by_alias[key].append(path)

    @staticmethod
    def _prefer_same_folder(found: list[str], source: str | None) -> list[str]:
        if source is None or len(found) < 2:
            return found
        folder = PurePosixPath(source).parent
        near = [p for p in found if PurePosixPath(p).parent == folder]
        return near if len(near) == 1 else found

    def candidates(self, target: str, source: str | None = None) -> list[str]:
        t = target.strip().replace("\\", "/").strip("/")
        if not t:
            return []
        key = t.lower()
        if key in self.by_path:
            return [self.by_path[key]]
        stem = _strip_md(key)
        if "/" in stem:
            suffix = "/" + stem
            found = [p for p in self.paths if _strip_md(p).lower().endswith(suffix)]
        else:
            found = list(self.by_name.get(stem, []))
        if found:
            return self._prefer_same_folder(sorted(found), source)
        return self._prefer_same_folder(sorted(self.by_alias.get(key, [])), source)

    def resolve(self, target: str, source: str | None = None) -> str:
        """Resolve ``target`` or raise ``not_found`` / ``ambiguous``."""
        found = self.candidates(target, source)
        if not found:
            raise EpistemeError(NOT_FOUND, f'no note "{target}". Use search to find the path.')
        if len(found) > 1:
            raise EpistemeError(
                AMBIGUOUS,
                f'note name "{target}" matches {len(found)} notes: {", ".join(found)}. '
                "Pass the full path.",
            )
        return found[0]

    def resolve_quiet(self, target: str, source: str | None = None) -> str | None:
        found = self.candidates(target, source)
        return found[0] if len(found) == 1 else None


def reachable(
    start: str, outgoing: Callable[[str], Iterable[str]], depth: int
) -> list[tuple[str, int]]:
    """Notes reachable from ``start`` following outgoing links, up to ``depth`` hops."""
    seen = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        dist = seen[node]
        if dist >= depth:
            continue
        for nxt in outgoing(node):
            if nxt not in seen:
                seen[nxt] = dist + 1
                queue.append(nxt)
    return sorted(((p, d) for p, d in seen.items() if p != start), key=lambda x: (x[1], x[0]))
