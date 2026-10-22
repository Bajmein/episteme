"""links.py: resolution order, ambiguity and traversal."""

from __future__ import annotations

import pytest

from episteme.errors import EpistemeError
from episteme.links import Resolver, reachable

NOTES = [
    ("docs/best-practices.md", []),
    ("docs/std/best-practices.md", []),
    ("docs/README.index.md", ["Índice", "MOC"]),
    ("memory/a.md", []),
]


def test_resolution_order() -> None:
    r = Resolver(NOTES)
    assert r.resolve("docs/best-practices") == "docs/best-practices.md"
    assert r.resolve("DOCS/Best-Practices.md") == "docs/best-practices.md"
    assert r.resolve("std/best-practices") == "docs/std/best-practices.md"
    assert r.resolve("readme.index") == "docs/README.index.md"
    assert r.resolve("moc") == "docs/README.index.md"
    assert r.resolve("a") == "memory/a.md"


def test_ambiguous_and_missing() -> None:
    r = Resolver(NOTES)
    with pytest.raises(EpistemeError) as err:
        r.resolve("best-practices")
    assert err.value.code == "ambiguous"
    assert "docs/best-practices.md" in str(err.value)
    assert "docs/std/best-practices.md" in str(err.value)
    with pytest.raises(EpistemeError) as err:
        r.resolve("nothing")
    assert err.value.code == "not_found"
    assert r.resolve_quiet("best-practices") is None


def test_same_folder_preferred() -> None:
    r = Resolver(NOTES)
    assert r.resolve("best-practices", "docs/x.md") == "docs/best-practices.md"
    assert r.resolve("best-practices", "docs/std/y.md") == "docs/std/best-practices.md"
    assert r.resolve_quiet("best-practices", "memory/a.md") is None
    assert r.resolve_quiet("best-practices") is None


def test_reachable() -> None:
    graph = {"a": ["b"], "b": ["c", "a"], "c": ["d"]}
    out = reachable("a", lambda n: graph.get(n, []), 2)
    assert out == [("b", 1), ("c", 2)]
