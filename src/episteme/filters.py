"""The search filters as one value: validation, the arguments for the index and hint probes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from episteme.errors import invalid
from episteme.vault import today

PRIORITY_MAX = 5
VALID_VALUES = ("current", "expired")


def _project_scope(project: str | None) -> str | list[str] | None:
    """A project also sees the ``_shared`` memories."""
    if project and project != "_shared":
        return [project, "_shared"]
    return project


@dataclass(frozen=True)
class SearchFilters:
    """The search filters as the caller gave them (``project`` not yet expanded)."""

    path: str | None = None
    type: str | None = None
    tags: list[str] | None = None
    project: str | None = None
    status: str | None = None
    zone: str | None = None
    priority_min: int | None = None
    valid: str | None = None
    linked_to: str | None = None

    def check(self) -> None:
        """Reject values out of range with ``invalid_argument``."""
        if self.priority_min is not None and not (1 <= self.priority_min <= PRIORITY_MAX):
            raise invalid(f"priority_min must be 1-{PRIORITY_MAX}, got {self.priority_min}.")
        if self.valid is not None and self.valid not in VALID_VALUES:
            raise invalid(f'valid must be "current" or "expired", got "{self.valid}".')

    def as_kwargs(self) -> dict[str, Any]:
        """The keyword arguments of ``Index.search`` and ``Index.facets``."""
        return {
            "path": self.path,
            "type": self.type,
            "tags": self.tags,
            "project": _project_scope(self.project),
            "status": self.status,
            "zone": self.zone,
            "priority_min": self.priority_min,
            "valid": self.valid,
            "linked_to": self.linked_to,
            "today": today().isoformat(),
        }

    def is_empty(self) -> bool:
        text_filters = (self.path, self.type, self.tags, self.project, self.zone, self.status)
        return not any(text_filters) and not self.selects_extra()

    def selects_extra(self) -> bool:
        """Whether priority_min, valid or linked_to is set."""
        return self.priority_min is not None or bool(self.valid or self.linked_to)

    def selects(self) -> bool:
        """Whether a filter that can replace the query is set."""
        return bool(self.tags or self.type or self.project or self.zone) or self.selects_extra()

    def probes(self) -> list[tuple[str, dict[str, Any]]]:
        """For each of priority_min, valid and linked_to: its hint and the filter alone."""
        out: list[tuple[str, dict[str, Any]]] = []
        if self.priority_min is not None:
            hint = f"no note has priority {self.priority_min} or more."
            out.append((hint, {"priority_min": self.priority_min}))
        if self.valid:
            hint = f'no note is "{self.valid}" by valid_until.'
            out.append((hint, {"valid": self.valid, "today": today().isoformat()}))
        if self.linked_to:
            out.append(
                (f'no note links to or from "{self.linked_to}".', {"linked_to": self.linked_to})
            )
        return out
