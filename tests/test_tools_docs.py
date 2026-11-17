"""docs_status and docs_write through MCP: docs zones, the suite schema and the manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from conftest import TODAY, mcp_client

pytestmark = pytest.mark.anyio

SUITE = "docs/mise"
URL = "https://mise.jdx.dev"
PAGE = "getting-started.md"
BODY = "> ## Documentation Index\n\n# Getting started\n\nInstall mise.\n"
MANIFEST = """\
---
title: mise
type: index
status: stable
lang: en
created: 2026-10-01
updated: 2026-10-01
tags: [mise]
suite:
  upstream: ["https://mise.jdx.dev/llms.txt"]
  include: ["https://mise.jdx.dev/"]
  context7: /jdx/mise
  synced: 2026-10-10
---
# mise
"""
NEW_FIELDS = {"title": "Tasks", "type": "guide", "status": "stable", "lang": "en", "tags": []}


def _note(source: str, body: str = BODY, extra: str = "") -> str:
    return (
        f"---\ntitle: Getting started\ntype: guide\nstatus: stable\nlang: en\n"
        f"source: {source}\ncreated: 2026-10-01\nupdated: 2026-10-01\ntags: [mise]\n{extra}"
        f"---\n{body}"
    )


def _hash(body: str) -> str:
    text = body.replace("\r\n", "\n").strip() + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _fm(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


@pytest.fixture
def suite(vault: Path) -> Path:
    """The test vault plus a docs zone docs/mise with a manifest, two pages and a bad note."""
    with (vault / "episteme.toml").open("a", encoding="utf-8") as fh:
        fh.write(f'\n[zones."{SUITE}"]\nmode = "docs"\n')
    root = vault / SUITE
    (root / "dev-tools").mkdir(parents=True)
    (root / "README.index.md").write_text(MANIFEST, encoding="utf-8")
    (root / PAGE).write_text(_note(f"{URL}/getting-started.md"), encoding="utf-8")
    (root / "dev-tools/backends.md").write_text(
        _note(f"{URL}/dev-tools/backends.md", "# Backends\n", "category: x\n").replace(
            "status: stable", "status: deprecated"
        ),
        encoding="utf-8",
    )
    (root / "draft.md").write_text("---\ntitle: Draft\n---\n# Draft\n", encoding="utf-8")
    return vault


async def test_docs_status_lists_docs_zones_with_counts(suite: Path) -> None:
    async with mcp_client(suite) as c:
        res = await c.ok("docs_status")

    assert res == {
        "suites": [
            {
                "suite": SUITE,
                "notes": 3,
                "with_source": 2,
                "deprecated": 1,
                "invalid": 1,
                "manifest_valid": True,
                "upstream": [f"{URL}/llms.txt"],
                "include": [f"{URL}/"],
                "context7": "/jdx/mise",
                "synced": "2026-10-10",
            }
        ]
    }


async def test_docs_status_pages_is_a_tsv_with_the_body_hash(suite: Path) -> None:
    async with mcp_client(suite) as c:
        res = await c.ok("docs_status", suite="mise", pages=True)

    assert res["suite"] == SUITE
    assert res["pages"].splitlines() == [
        f"{URL}/dev-tools/backends.md\t{_hash('# Backends')}\tdev-tools/backends.md\tdeprecated",
        f"{URL}/getting-started.md\t{_hash(BODY)}\t{PAGE}\tstable",
    ]


@pytest.mark.parametrize(
    ("suite_arg", "code"),
    [
        ("nope", "not_found:"),
        ("docs/claude-code", "read_only_zone:"),
        ("memory", "read_only_zone:"),
    ],
)
async def test_docs_tools_refuse_zones_that_are_not_docs(
    suite: Path, suite_arg: str, code: str
) -> None:
    async with mcp_client(suite) as c:
        status = await c.error("docs_status", suite=suite_arg)
        write = await c.error("docs_write", suite=suite_arg, path="x.md", fields=NEW_FIELDS)

    assert status.startswith(code) and write.startswith(code)


async def test_docs_write_same_body_changes_nothing(suite: Path) -> None:
    page = suite / SUITE / PAGE
    before = page.stat().st_mtime_ns

    async with mcp_client(suite) as c:
        res = await c.ok("docs_write", suite=SUITE, source=f"{URL}/getting-started.md", body=BODY)

    assert res == {
        "path": f"{SUITE}/{PAGE}", "created": False, "changed": False, "hash": _hash(BODY)
    }  # fmt: skip
    assert page.stat().st_mtime_ns == before


async def test_docs_write_new_body_replaces_it_and_sets_updated(suite: Path) -> None:
    new = "# Getting started\n\nInstall mise with `curl`.\n"

    async with mcp_client(suite) as c:
        res = await c.ok("docs_write", suite=SUITE, source=f"{URL}/getting-started.md", body=new)
        status = await c.ok("docs_status", suite=SUITE, pages=True)

    page = suite / SUITE / PAGE
    assert res["changed"] is True and res["hash"] == _hash(new)
    assert page.read_text(encoding="utf-8").endswith("---\n" + new)
    assert str(_fm(page)["updated"]) == TODAY and str(_fm(page)["created"]) == "2026-10-01"
    assert f"{_hash(new)}\t{PAGE}" in status["pages"]


async def test_docs_write_creates_a_note_with_path(suite: Path) -> None:
    async with mcp_client(suite) as c:
        res = await c.ok(
            "docs_write",
            suite="mise",
            path="tasks/running.md",
            source=f"{URL}/tasks/running.md",
            body="# Tasks\n",
            fields={**NEW_FIELDS, "summary": "Cómo correr tareas."},
        )

    note = suite / SUITE / "tasks/running.md"
    assert res == {
        "path": f"{SUITE}/tasks/running.md",
        "created": True,
        "changed": True,
        "hash": _hash("# Tasks\n"),
    }
    fm = _fm(note)
    assert list(fm)[:2] == ["title", "summary"]
    assert fm["source"] == f"{URL}/tasks/running.md"
    assert str(fm["created"]) == TODAY == str(fm["updated"])


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ({"path": PAGE, "source": f"{URL}/other.md"}, "invalid_argument:"),
        ({"path": "../../plans/x.md", "source": f"{URL}/x.md"}, "outside_vault:"),
        ({"path": "/etc/x.md", "source": f"{URL}/x.md"}, "outside_vault:"),
        ({"path": "x.md", "source": f"{URL}/x.md", "fields": {"title": "X"}}, "invalid_schema:"),
        ({"path": "x.md", "fields": NEW_FIELDS}, "invalid_schema:"),
        ({"path": "x.txt", "source": f"{URL}/x.md"}, "invalid_argument:"),
        ({"source": f"{URL}/missing.md"}, "not_found:"),
        ({}, "invalid_argument:"),
    ],
)
async def test_docs_write_rejects_bad_creations(suite: Path, args: dict, code: str) -> None:
    async with mcp_client(suite) as c:
        text = await c.error("docs_write", suite=SUITE, body="# X\n", **args)

    assert text.startswith(code), text
    assert not (suite / SUITE / "x.md").exists()


async def test_docs_write_refuses_a_source_another_note_has(suite: Path) -> None:
    async with mcp_client(suite) as c:
        text = await c.error(
            "docs_write",
            suite=SUITE,
            path="dev-tools/backends.md",
            fields={"source": f"{URL}/getting-started.md"},
        )

    assert text.startswith("invalid_argument:") and PAGE in text


async def test_docs_write_refuses_source_and_path_of_different_notes(suite: Path) -> None:
    async with mcp_client(suite) as c:
        text = await c.error(
            "docs_write", suite=SUITE, source=f"{URL}/getting-started.md", path="draft.md"
        )

    assert text.startswith("invalid_argument:")


async def test_docs_write_scans_fields_but_not_the_body_for_secrets(suite: Path) -> None:
    key = "AKIA" + "IOSFODNN7EXAMPLE"

    async with mcp_client(suite) as c:
        text = await c.error(
            "docs_write", suite=SUITE, path=PAGE, fields={"summary": f"usa {key}"}
        )
        res = await c.ok(
            "docs_write",
            suite=SUITE,
            source=f"{URL}/getting-started.md",
            body=f"# Getting started\n\nexport AWS_ACCESS_KEY_ID={key}\n",
        )

    assert text.startswith("invalid_argument:") and key not in text
    assert res["changed"] is True


async def test_docs_write_deprecates_with_fields_only(suite: Path) -> None:
    page = suite / SUITE / PAGE
    body_before = page.read_text(encoding="utf-8").split("---\n", 2)[2]

    async with mcp_client(suite) as c:
        res = await c.ok(
            "docs_write",
            suite=SUITE,
            source=f"{URL}/getting-started.md",
            fields={"status": "deprecated"},
        )

    assert res["changed"] is True
    assert _fm(page)["status"] == "deprecated" and str(_fm(page)["updated"]) == TODAY
    assert page.read_text(encoding="utf-8").split("---\n", 2)[2] == body_before


async def test_docs_write_replaces_the_manifest_suite_mapping(suite: Path) -> None:
    new_suite = {"upstream": [], "include": [f"{URL}/"], "context7": None, "synced": TODAY}

    async with mcp_client(suite) as c:
        await c.ok("docs_write", suite=SUITE, path="README.index.md", fields={"suite": new_suite})
        bad = await c.error(
            "docs_write", suite=SUITE, path="README.index.md", fields={"suite": {"upstream": []}}
        )
        res = await c.ok("docs_status", suite=SUITE)

    assert bad.startswith("invalid_schema:")
    assert res["manifest_valid"] is True
    assert res["context7"] is None and res["synced"] == TODAY and res["upstream"] == []


async def test_docs_status_reports_an_invalid_manifest(vault: Path) -> None:
    toml = vault / "episteme.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('mode = "read-only"', 'mode = "docs"'),
        encoding="utf-8",
    )

    async with mcp_client(vault) as c:
        res = await c.ok("docs_status", suite="claude-code")

    assert res["suite"] == "docs/claude-code" and res["manifest_valid"] is False
    assert res["notes"] > 0 and res["invalid"] >= res["notes"] - res["with_source"]


async def test_revise_refuses_a_docs_zone(suite: Path) -> None:
    async with mcp_client(suite) as c:
        text = await c.error("revise", note=f"{SUITE}/{PAGE}", action="append", text="x")

    assert text == f"read_only_zone: {SUITE}/{PAGE} is in a docs zone. Use docs_write."


@pytest.mark.parametrize(("changed", "trail"), [(True, {"docs/mise/a.md": "written"}), (False, {})])
def test_docs_write_enters_the_trail_but_not_the_write_count(
    monkeypatch: pytest.MonkeyPatch, changed: bool, trail: dict
) -> None:
    from episteme import prompting, server

    monkeypatch.setattr(prompting, "TRAIL", {})
    monkeypatch.setattr(prompting, "WRITES", 0)
    text = json.dumps({"path": "docs/mise/a.md", "created": False, "changed": changed})

    server._track_result("docs_write", {"suite": "mise"}, text)

    assert trail == prompting.TRAIL and prompting.WRITES == 0


def test_backup_leaves_docs_zones_out(suite: Path) -> None:
    from episteme import backup
    from episteme.vault import Vault

    members = [rel for rel, _ in backup._members(Vault(suite))]

    assert not any(rel.startswith(SUITE) for rel in members)
    assert any(rel.startswith("memory/") for rel in members)
