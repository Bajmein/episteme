"""plugin/skills/docs/scripts/docs_check.py against a local HTTP server (no real network)."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[1] / "plugin/skills/docs/scripts/docs_check.py"
PAGES = {
    "/docs/same.md": (200, "# Same\n\nText.\n"),
    "/docs/changed.md": (200, "# Changed\n\nNew text.\n"),
    "/docs/gone.md": (404, "not found"),
    "/docs/old.md": (410, "gone"),
    "/docs/broken.md": (500, "boom"),
    "/docs/guide/index.md": (200, "# Guide\n"),
    "/docs/a": (200, "<!DOCTYPE html>\n<html><body>app shell</body></html>"),
    "/docs/a.md": (200, "# A\n\nMarkdown.\n"),
    "/docs/b": (200, "# B\n\nPlain.\n"),
}


@pytest.fixture(scope="module")
def check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docs_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["docs_check"] = module
    spec.loader.exec_module(module)
    return module


class _Handler(BaseHTTPRequestHandler):
    llms = ""

    def do_GET(self) -> None:
        status, text = (200, self.llms) if self.path == "/llms.txt" else PAGES.get(
            self.path, (404, "")
        )
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def base() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    _Handler.llms = (
        f"# Docs\n\n- [Same]({url}/docs/same.md)\n- [Guide]({url}/docs/guide/index.md): new\n"
        f"- [Elsewhere](https://example.org/x.md)\n"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield url
    server.shutdown()
    server.server_close()


def test_body_hash_matches_the_server(check: ModuleType) -> None:
    from episteme.docs import HASH_LEN, body_hash

    for text in ("# A\r\n\r\nb\r\n", "\n\n# A\n", "x", "a\rb\n"):
        assert check.body_hash(text) == body_hash(text)
    assert check.HASH_LEN == HASH_LEN


# @CodeScene(disable:"Excess Number of Function Arguments")
def test_diff_classifies_pages(
    check: ModuleType, base: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(check, "RETRY_DELAY", 0)
    rows = [
        (f"{base}/docs/same.md", check.body_hash("# Same\n\nText.\n"), "same.md", "stable"),
        (f"{base}/docs/changed.md", check.body_hash("# Changed\n"), "changed.md", "stable"),
        (f"{base}/docs/gone.md", "0" * 16, "gone.md", "stable"),
        (f"{base}/docs/old.md", "0" * 16, "old.md", "deprecated"),
        (f"{base}/docs/broken.md", "0" * 16, "broken.md", "stable"),
    ]
    tsv = tmp_path / "pages.tsv"
    tsv.write_text("".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    inbox = tmp_path / "inbox"

    code = check.main(
        ["diff", "--pages", str(tsv), "--inbox", str(inbox), "--upstream", f"{base}/llms.txt",
         "--include", f"{base}/docs/"]
    )  # fmt: skip

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["unchanged"] == 2
    [changed] = report["changed"]
    assert changed["path"] == "changed.md"
    assert Path(changed["file"]).read_text(encoding="utf-8") == "# Changed\n\nNew text.\n"
    assert Path(changed["file"]) == inbox / f"{changed['hash']}.md"
    assert changed["hash"] == check.body_hash("# Changed\n\nNew text.\n")
    assert report["gone"] == [
        {"source": f"{base}/docs/gone.md", "path": "gone.md", "http_status": 404}
    ]
    assert report["errors"] == [{"source": f"{base}/docs/broken.md", "error": "HTTP 500"}]
    [new] = report["new"]
    assert new["source"] == f"{base}/docs/guide/index.md"
    assert new["suggested_path"] == "guide.md"
    assert Path(new["file"]).read_text(encoding="utf-8") == "# Guide\n"
    assert Path(new["file"]) == inbox / f"{new['hash']}.md"
    assert new["hash"] == check.body_hash("# Guide\n")
    assert new["title"] == "Guide"


def _new_pages(check: ModuleType, base: str, tmp_path: Path, listed: str, known: list) -> dict:
    _Handler.llms = f"# Docs\n\n- [P]({base}{listed})\n"
    return check.diff(known, tmp_path / "inbox", [f"{base}/llms.txt"], [f"{base}/docs/"])


def test_diff_uses_the_markdown_variant_of_a_page_listed_without_md(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    report = _new_pages(check, base, tmp_path, "/docs/a", [])

    [new] = report["new"]
    assert new["source"] == f"{base}/docs/a.md"
    assert new["suggested_path"] == "a.md"
    assert Path(new["file"]).read_text(encoding="utf-8") == "# A\n\nMarkdown.\n"
    assert report["errors"] == []


def test_diff_knows_a_page_by_its_markdown_variant(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    known = [check.Page(f"{base}/docs/a.md", "0" * 16, "a.md", "stable")]

    report = _new_pages(check, base, tmp_path, "/docs/a", known)

    assert report["new"] == []


def test_diff_falls_back_to_the_listed_url_without_a_markdown_variant(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    report = _new_pages(check, base, tmp_path, "/docs/b", [])

    [new] = report["new"]
    assert new["source"] == f"{base}/docs/b"
    assert report["errors"] == []


def test_diff_lists_a_page_once_when_the_index_has_both_forms(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    _Handler.llms = f"- [A]({base}/docs/a)\n- [A]({base}/docs/a.md)\n"

    report = check.diff([], tmp_path / "inbox", [f"{base}/llms.txt"], [f"{base}/docs/"])

    assert [n["source"] for n in report["new"]] == [f"{base}/docs/a.md"]


def test_diff_keeps_a_listed_md_url(check: ModuleType, base: str, tmp_path: Path) -> None:
    report = _new_pages(check, base, tmp_path, "/docs/guide/index.md", [])

    [new] = report["new"]
    assert new["source"] == f"{base}/docs/guide/index.md"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://d.io/docs/a", "https://d.io/docs/a.md"),
        ("https://d.io/docs/a/", "https://d.io/docs/a/index.md"),
        ("https://d.io/docs/a?x=1#top", "https://d.io/docs/a.md"),
        ("https://d.io/docs/a.md", None),
        ("https://d.io/docs/a.md?x=1", None),
    ],
)
def test_md_variant(check: ModuleType, url: str, expected: str | None) -> None:
    assert check.md_variant(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://d.io/uv/get/installation/index.md", "get/installation.md"),
        ("https://d.io/uv/reference/cli.md?x=1#top", "reference/cli.md"),
        ("https://d.io/uv/concepts/tools", "concepts/tools.md"),
    ],
)
def test_suggested_path_drops_the_include_prefix(
    check: ModuleType, url: str, expected: str
) -> None:
    assert check.suggested_path(url, ["https://d.io/", "https://d.io/uv/"]) == expected


def test_suggested_path_without_a_matching_prefix_drops_the_host(check: ModuleType) -> None:
    assert check.suggested_path("https://d.io//guide/x/index.md", []) == "guide/x.md"


def test_diff_reports_an_unreadable_upstream_index(
    check: ModuleType, base: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check, "RETRY_DELAY", 0)

    report = check.diff([], tmp_path / "out", [f"{base}/docs/broken.md"], [])

    assert report["errors"] == [{"source": f"{base}/docs/broken.md", "error": "HTTP 500"}]
    assert report["new"] == []


def test_fetch_refuses_other_schemes(check: ModuleType) -> None:
    result = check.fetch("file:///etc/passwd")

    assert result.text is None and result.error == "not an http(s) URL"


def test_context7_picks_the_matching_id(
    check: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "results": [
            {"id": "/other/uv", "lastUpdateDate": "2020-01-01"},
            {"id": "/astral-sh/uv", "lastUpdateDate": "2026-11-16T13:01:47.686Z"},
        ]
    }
    seen: list[tuple[str, dict | None]] = []

    def fake_fetch(url: str, headers: dict | None = None) -> object:
        seen.append((url, headers))
        return check.Fetched(url, 200, json.dumps(payload))

    monkeypatch.setattr(check, "fetch", fake_fetch)
    monkeypatch.setenv("CONTEXT7_API_KEY", "k")

    assert check.context7_date("/astral-sh/uv") == "2026-11-16T13:01:47.686Z"
    assert check.context7_date("/nobody/uv") is None
    assert "libraryName=uv" in seen[0][0] and seen[0][1] == {"Authorization": "Bearer k"}


def test_diff_clears_hash_named_files_of_an_earlier_run_and_keeps_the_rest(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    stale = inbox / f"{'a' * 16}.md"
    stale.write_text("old", encoding="utf-8")
    other = inbox / "notes.md"
    other.write_text("mine", encoding="utf-8")
    longer = inbox / f"{'b' * 17}.md"
    longer.write_text("mine", encoding="utf-8")

    report = _new_pages(check, base, tmp_path, "/docs/a", [])

    assert not stale.exists()
    assert other.exists()
    assert longer.exists()
    assert (inbox / f"{report['new'][0]['hash']}.md").exists()


def test_first_heading_is_none_without_one(check: ModuleType) -> None:
    assert check._first_heading("text\n\n## Sub\n") is None
    assert check._first_heading("intro\n# Title #\n") == "Title"
    assert check._first_heading("# Using C#\n") == "Using C#"
    assert check._first_heading("```sh\n# comment\n```\n# Real\n") == "Real"
