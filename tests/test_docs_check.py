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
    "/docs/x": (200, "<!doctype html><html></html>"),
    "/docs/x.md": (200, "# X\n\nBody.\n"),
    "/docs/html-only": (200, "<html><body>shell</body></html>"),
    "/docs/api.txt": (200, "plain api text\n"),
    "/docs/spec.json": (200, '{"openapi": "3.1"}'),
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
        ("https://d.io/docs/api.txt", None),
        ("https://d.io/docs/spec.json", None),
        ("https://d.io/docs/a.html", "https://d.io/docs/a.md"),
        ("https://d.io/docs/a.htm?x=1", "https://d.io/docs/a.md"),
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


def _existing(check: ModuleType, base: str, tmp_path: Path, path: str, text: str) -> dict:
    page = check.Page(f"{base}{path}", check.body_hash(text), "p.md", "stable")
    return check.diff([page], tmp_path / "inbox", [], [])


def test_existing_page_without_md_compares_its_markdown_variant(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    same = _existing(check, base, tmp_path, "/docs/x", "# X\n\nBody.\n")
    changed = _existing(check, base, tmp_path, "/docs/x", "# X\n")

    assert same["unchanged"] == 1 and same["changed"] == []
    [entry] = changed["changed"]
    assert Path(entry["file"]).read_text(encoding="utf-8") == "# X\n\nBody.\n"


def test_existing_page_that_only_serves_html_is_an_error_not_a_change(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    report = _existing(check, base, tmp_path, "/docs/html-only", "# Old\n")

    assert report["errors"] == [
        {"source": f"{base}/docs/html-only", "error": "HTML instead of Markdown"}
    ]
    assert report["changed"] == [] and report["unchanged"] == 0
    assert list((tmp_path / "inbox").iterdir()) == []


@pytest.mark.parametrize(
    ("path", "text"),
    [("/docs/api.txt", "plain api text\n"), ("/docs/spec.json", '{"openapi": "3.1"}')],
)
def test_existing_txt_and_json_pages_are_downloaded_as_they_are(
    check: ModuleType, base: str, tmp_path: Path, path: str, text: str
) -> None:
    report = _existing(check, base, tmp_path, path, text)

    assert report["unchanged"] == 1
    assert report["errors"] == []


def test_new_page_that_only_serves_html_is_an_error(
    check: ModuleType, base: str, tmp_path: Path
) -> None:
    report = _new_pages(check, base, tmp_path, "/docs/html-only", [])

    assert report["new"] == []
    assert [e["error"] for e in report["errors"]] == ["HTML instead of Markdown"]
    assert list((tmp_path / "inbox").iterdir()) == []


@pytest.mark.parametrize("listed", ["/docs/x.md", "/docs/x/", "/docs/x/index.md", "/docs/x#sec"])
def test_listed_variants_of_a_known_page_are_not_new(
    check: ModuleType, base: str, tmp_path: Path, listed: str
) -> None:
    known = [check.Page(f"{base}/docs/x", "0" * 16, "x.md", "stable")]

    report = _new_pages(check, base, tmp_path, listed, known)

    assert report["new"] == []


def test_variants_of_the_same_new_page_come_out_once(check: ModuleType, base: str) -> None:
    suffixes = ("#top", "/", ".md", "/index.md")
    _Handler.llms = "\n".join(f"- [A]({base}/docs/a{s})" for s in suffixes)
    report: dict = {"errors": []}

    urls = check.upstream_urls([f"{base}/llms.txt"], [f"{base}/docs/"], set(), report)

    assert urls == [f"{base}/docs/a"]


@pytest.mark.parametrize(
    "listed",
    [
        "/docs/{query}",
        "/docs/.well-known/ai-plugin",
        "/docs/openapi.json",
        "/docs/llms-full.txt",
        "/docs/llms.txt",
        "/docs/llms-api.txt",
    ],
)
def test_urls_that_are_not_pages_are_not_listed_as_new(
    check: ModuleType, base: str, listed: str
) -> None:
    _Handler.llms = f"- [P]({base}{listed})\n"
    report: dict = {"errors": []}

    urls = check.upstream_urls([f"{base}/llms.txt"], [], set(), report)

    assert urls == []


def test_new_entry_has_an_excerpt(check: ModuleType, base: str, tmp_path: Path) -> None:
    report = _new_pages(check, base, tmp_path, "/docs/a", [])

    assert report["new"][0]["excerpt"] == "Markdown."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "# T\n\n> quote\n\n```\ncode\n```\n\nFirst line\nsecond line.\n\nOther.\n",
            "First line second line.",
        ),
        ("# T\n\n- [Link](x)\n- [Link2](y)\n\nReal text.\n", "Real text."),
        ("# T\n\n## Sub\n\n> only quote\n", None),
        ("", None),
    ],
)
def test_excerpt_is_the_first_paragraph_of_prose(
    check: ModuleType, text: str, expected: str | None
) -> None:
    assert check._excerpt(text) == expected


def test_excerpt_is_cut_at_300_characters(check: ModuleType) -> None:
    excerpt = check._excerpt("# T\n\n" + "word " * 100)

    assert excerpt is not None
    assert 300 <= len(excerpt) <= 301 and excerpt.endswith("…")


def test_excerpt_skips_frontmatter_and_tables(check: ModuleType) -> None:
    text = "---\ntitle: X\n---\n\n| a | b |\n|---|---|\n\nReal text.\n"

    assert check._excerpt(text) == "Real text."


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://d.io/docs/v1.2", "https://d.io/docs/v1.2.md"),
        ("https://d.io", "https://d.io/index.md"),
    ],
)
def test_md_variant_edge_cases(check: ModuleType, url: str, expected: str) -> None:
    assert check.md_variant(url) == expected


def test_non_pages_are_matched_without_regard_to_case(check: ModuleType) -> None:
    assert not check._is_page("https://d.io/openapi.JSON")
    assert not check._is_page("https://d.io/LLMS-full.txt")
    assert not check._is_page("https://d.io/.well-known")
