"""Check docs suites against their sources for /episteme:docs. Standard library only.

    docs_check.py context7 <id>...
        JSON {id: lastUpdateDate | null} from Context7's public search API.
    docs_check.py diff --pages <tsv> --inbox <dir> [--upstream <url>...] [--include <prefix>...]
                       [--markdown <template>]
        Downloads every source of the TSV that docs_status(suite, pages=true) returns, saves
        each changed or new page as <dir>/<body hash>.md (<dir> is the "inbox" docs_status
        gives) and prints JSON with the changed, gone, new and failed pages, each changed or
        new one with its "hash". docs_write takes the body from the inbox with body_ref, so no
        page text passes through the model. episteme itself has no HTTP: this script runs on
        the person's machine. With --markdown (the suite.markdown template, with {path} or
        {page}), each page is fetched only from the expanded template; the source stays the
        public URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

HASH_LEN = 16
WORKERS = 8
TIMEOUT = 30
RETRIES = 2
RETRY_DELAY = 1.0
MAX_BYTES = 2 * 1024 * 1024
USER_AGENT = "episteme-docs-check"
GONE_STATUSES = (404, 410)
CONTEXT7_SEARCH = "https://context7.com/api/v2/libs/search"
URL_RE = re.compile(r"https?://[^\s)\]>\"'`]+")
SCHEMES = ("http", "https")
INBOX_FILE_RE = re.compile(rf"[0-9a-f]{{{HASH_LEN}}}\.md")
HTML_ERROR = "HTML instead of Markdown"
JSON_ERROR = "JSON instead of Markdown"
EMPTY_ERROR = "empty page"
HTML_START_RE = re.compile(
    r"<(?:!doctype|(?:html|head|body)(?=[\s>/])|\?xml|svg(?=[\s>/]))", re.IGNORECASE
)
LEADING_COMMENTS_RE = re.compile(r"\A(?:\s*<!--.*?-->)*\s*", re.DOTALL)
MARKUP_TYPES = ("text/html", "application/xhtml+xml", "application/json")
PAGE_EXTENSIONS = (".html", ".htm", ".md")
EXCERPT_MAX = 300
PAGE_SUFFIX_RE = re.compile(r"(?:/index)?\.(?:md|html?)$", re.IGNORECASE)
NON_PAGE_PATH = "/.well-known/"
NON_PAGE_SUFFIXES = (".json", ".txt")
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
NON_PROSE_STARTS = (">", "|", "<", "![", ":::")
LINK_ITEM_RE = re.compile(r"(?:[-*+]|\d+\.)\s+\[")


def body_hash(body: str) -> str:
    """Same as episteme.docs.body_hash: change both at once."""
    text = body.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_LEN]


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s) URLs."""

    # @CodeScene(disable:"Excess Number of Function Arguments")
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if urllib.parse.urlsplit(newurl).scheme not in SCHEMES:
            raise urllib.error.HTTPError(newurl, code, "redirect to a non-http URL", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpOnlyRedirects)


@dataclass(frozen=True)
class Fetched:
    url: str
    status: int | None  # HTTP status, None when the request itself failed
    text: str | None = None
    error: str | None = None
    content_type: str = ""


def _request(url: str, headers: dict[str, str] | None = None) -> Fetched:
    """One GET of an http(s) URL, without retries."""
    if urllib.parse.urlsplit(url).scheme not in SCHEMES:
        return Fetched(url, None, error="not an http(s) URL")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        # The scheme is checked above and _OPENER refuses redirects to other schemes.
        with _OPENER.open(req, timeout=TIMEOUT) as resp:  # nosec B310
            data = resp.read(MAX_BYTES + 1)
            status = resp.status
            ctype = resp.headers.get_content_type() if resp.headers else ""
    except urllib.error.HTTPError as exc:
        return Fetched(url, exc.code, error=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return Fetched(url, None, error=str(getattr(exc, "reason", exc)))
    if len(data) > MAX_BYTES:
        return Fetched(url, status, error=f"larger than {MAX_BYTES // 1024 // 1024} MB")
    return Fetched(url, status, data.decode("utf-8", errors="replace"), content_type=ctype)


def _retryable(result: Fetched) -> bool:
    return result.status is None or result.status >= 500


def fetch(url: str, headers: dict[str, str] | None = None) -> Fetched:
    """GET with up to ``RETRIES`` retries on a network error or a 5xx."""
    result = _request(url, headers)
    for attempt in range(RETRIES):
        if not _retryable(result) or result.error == "not an http(s) URL":
            break
        time.sleep(RETRY_DELAY * (attempt + 1))
        result = _request(url, headers)
    return result


# -- context7 ---------------------------------------------------------------------------------


def _results(payload: object) -> list[dict]:
    items = payload.get("results", []) if isinstance(payload, dict) else payload
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def context7_date(library_id: str) -> str | None:
    """``lastUpdateDate`` of a Context7 library, or None when it is not found."""
    name = library_id.rstrip("/").rsplit("/", 1)[-1]
    query = urllib.parse.urlencode({"libraryName": name, "query": "docs"})
    key = os.environ.get("CONTEXT7_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else None
    result = fetch(f"{CONTEXT7_SEARCH}?{query}", headers)
    if result.text is None:
        return None
    try:
        payload = json.loads(result.text)
    except ValueError:
        return None
    match = next((i for i in _results(payload) if i.get("id") == library_id), None)
    return match.get("lastUpdateDate") if match else None


# -- diff -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    source: str
    hash: str
    path: str
    status: str


def read_pages(tsv: Path) -> list[Page]:
    """The lines of ``docs_status(pages=true)``: source, hash, path and status."""
    pages = []
    for line in tsv.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and parts[0]:
            pages.append(Page(*parts))
    return pages


def file_for(inbox: Path, digest: str) -> Path:
    return inbox / f"{digest}.md"


def _save(inbox: Path, text: str) -> tuple[str, str]:
    """Write ``text`` to ``<inbox>/<body hash>.md``; the hash and the path."""
    digest = body_hash(text)
    path = file_for(inbox, digest)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return digest, str(path)


def _outside_fences(text: str) -> Iterable[str]:
    """The lines of ``text`` that are not inside a fenced code block."""
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            yield line


def _first_heading(text: str) -> str | None:
    """The text of the first ``# `` heading outside code fences, or None."""
    matches = (re.fullmatch(r"# +(.+?)(?:\s+#+)?\s*", line) for line in _outside_fences(text))
    return next((m.group(1) for m in matches if m), None)


def prepare_inbox(inbox: Path) -> None:
    """Create the inbox and delete the ``<hash>.md`` files of a previous run, nothing else."""
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in inbox.iterdir():
        if INBOX_FILE_RE.fullmatch(entry.name) and entry.is_file():
            entry.unlink()


def suggested_path(url: str, include: Iterable[str]) -> str:
    """The URL without its include prefix, with ``/index.md`` turned into ``.md``."""
    parts = urllib.parse.urlsplit(url)
    clean = parts._replace(query="", fragment="").geturl()
    prefix = max((p for p in include if clean.startswith(p)), key=len, default=None)
    rest = clean.removeprefix(prefix) if prefix else parts.path  # no prefix: drop the host
    rest = "/".join(p for p in rest.split("/") if p) or "index.md"
    if rest.endswith("/index.md"):
        rest = rest.removesuffix("/index.md") + ".md"
    return rest if rest.lower().endswith(".md") else rest + ".md"


def upstream_urls(
    upstream: Iterable[str], include: list[str], known: set[str], report: dict
) -> list[str]:
    """URLs listed in the ``llms.txt`` indexes, under ``include`` and not in the suite yet.

    A URL is known when its page key (``_page_key``) is the key of a ``known`` source or of an
    index, so ``X``, ``X/``, ``X.md``, ``X/index.md`` and ``X#sec`` are the same page. The
    URLs that are not pages (``_is_page``) are dropped, and the rest are deduplicated by key
    (the first URL wins, without query or fragment). An index that cannot be read goes to
    ``report["errors"]``, so the suite is not marked synced.
    """
    indexes = list(upstream)
    skip = {_page_key(u) for u in known | set(indexes)}
    found: dict[str, str] = {}
    for index in indexes:
        for url in _listed(index, report):
            key = _page_key(url)
            if key not in skip and key not in found and _is_candidate(url, include):
                found[key] = _without_query(url)
    return list(found.values())


def _is_candidate(url: str, include: list[str]) -> bool:
    return _is_page(url) and _included(url, include)


def _without_query(url: str) -> str:
    return urllib.parse.urlsplit(url)._replace(query="", fragment="").geturl()


def _page_key(url: str) -> str:
    """The URL without scheme, query, fragment, ``index.md``/``.md``/``.html`` or final ``/``."""
    parts = urllib.parse.urlsplit(url)
    path = PAGE_SUFFIX_RE.sub("", parts.path).rstrip("/")
    return f"{parts.netloc}{path}"


def _is_page(url: str) -> bool:
    """False for templates, ``.well-known`` files, JSON and ``.txt`` files (``llms*.txt``…)."""
    if "{" in url or "}" in url:
        return False
    path = urllib.parse.urlsplit(url).path.lower()
    return not (NON_PAGE_PATH in path + "/" or path.endswith(NON_PAGE_SUFFIXES))


def md_variant(url: str) -> str | None:
    """The ``.md`` twin of a page URL, or None when there is none to ask for.

    None when the URL already ends in ``.md`` or its last segment has another extension
    (``.txt``, ``.json``…); ``.html``/``.htm`` is replaced by ``.md``.
    """
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    suffix = PurePosixPath(path).suffix.lower()
    if path.endswith("/"):
        path += "index.md"
    elif suffix in (".html", ".htm"):
        path = path[: -len(suffix)] + ".md"
    elif suffix.lstrip(".").isalpha():  # .txt, .json…; not a version like v1.2
        return None
    else:
        path += ".md"
    return urllib.parse.urlunsplit(parts._replace(path=path, query="", fragment=""))


def _is_json(text: str) -> bool:
    if not text.startswith(("{", "[")):
        return False
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _is_json_url(url: str) -> bool:
    """A source that is a JSON file itself (``spec.json``): its body is kept as it is."""
    return urllib.parse.urlsplit(url).path.lower().endswith(".json")


def _markup_type(content_type: str) -> bool:
    return content_type in MARKUP_TYPES or content_type.endswith("xml")


def _not_markdown_reason(result: Fetched) -> str | None:
    """Why a fetch with text is not Markdown (HTML, JSON or empty), or None when it is.

    A BOM, blank space and leading ``<!-- -->`` comments are skipped first. A markup
    ``Content-Type`` (HTML, XHTML, JSON, XML) does not decide alone: only with a body that
    starts with ``<``: Markdown served as ``text/html`` passes unless it opens with a tag.
    """
    text = (result.text or "").lstrip("\ufeff")
    text = LEADING_COMMENTS_RE.sub("", text, count=1)
    if not text:
        return EMPTY_ERROR
    if HTML_START_RE.match(text):
        return HTML_ERROR
    if _is_json(text.rstrip()) and not _is_json_url(result.url):
        return JSON_ERROR
    if _markup_type(result.content_type) and text.startswith("<"):
        return HTML_ERROR
    return None


def _is_markdown(result: Fetched) -> bool:
    """A successful fetch whose text looks like Markdown."""
    return result.text is not None and _not_markdown_reason(result) is None


def _is_html(result: Fetched) -> bool:
    """A fetch that has text but looks like an HTML document."""
    return result.text is not None and not _is_markdown(result)


def expand_template(template: str, url: str) -> str:
    """``template`` with ``{path}`` (the URL path) and ``{page}`` (it without the leading ``/``
    and the ``.html``/``.htm``/``.md`` extension, ``index`` for a final ``/``), both quoted."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path) or "/"
    page = path.lstrip("/")
    if not page or page.endswith("/"):
        page += "index"
    else:
        suffix = PurePosixPath(page).suffix.lower()
        page = page[: -len(suffix)] if suffix in PAGE_EXTENSIONS else page
    quoted = {k: urllib.parse.quote(v, safe="/") for k, v in (("path", path), ("page", page))}
    return template.replace("{path}", quoted["path"]).replace("{page}", quoted["page"])


def _fetch_markdown(url: str, markdown: str | None = None) -> Fetched:
    """The Markdown of ``url``: from the ``markdown`` template only when there is one; else
    its ``.md`` variant when it answers with Markdown, or ``url`` itself."""
    if markdown is not None:
        return replace(fetch(expand_template(markdown, url)), url=url)
    variant = md_variant(url)
    if variant is not None:
        result = fetch(variant)
        if _is_markdown(result):
            return result
    return fetch(url)


def _listed(index: str, report: dict) -> list[str]:
    """The URLs in one ``llms.txt``; an index that cannot be read is reported as an error."""
    result = fetch(index)
    if result.text is None:
        report["errors"].append({"source": index, "error": result.error})
        return []
    return [url.rstrip(".,;:") for url in URL_RE.findall(result.text)]


def _included(url: str, include: list[str]) -> bool:
    return not include or any(url.startswith(p) for p in include)


def _classify(page: Page, result: Fetched, inbox: Path, report: dict) -> None:
    if result.status in GONE_STATUSES:
        report["gone"].append(
            {"source": page.source, "path": page.path, "http_status": result.status}
        )
    elif result.text is None:
        report["errors"].append({"source": page.source, "error": result.error})
    elif (reason := _not_markdown_reason(result)) is not None:
        report["errors"].append({"source": page.source, "error": reason})
    elif body_hash(result.text) == page.hash:
        report["unchanged"] += 1
    else:
        digest, file = _save(inbox, result.text)
        report["changed"].append(
            {"source": page.source, "path": page.path, "hash": digest, "file": file}
        )


def _new_entry(result: Fetched, include: list[str], inbox: Path, report: dict) -> None:
    text = result.text
    reason = result.error if text is None else _not_markdown_reason(result)
    if text is None or reason is not None:
        report["skipped"].append({"source": result.url, "reason": reason})
        return
    digest, file = _save(inbox, text)
    report["new"].append(
        {
            "source": result.url,
            "hash": digest,
            "file": file,
            "title": _first_heading(text),
            "excerpt": _excerpt(text),
            "suggested_path": suggested_path(result.url, include),
        }
    )


def _paragraphs(text: str) -> Iterable[list[str]]:
    """Blocks of consecutive non-blank, non-heading lines outside code fences."""
    block: list[str] = []
    for line in _outside_fences(text):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            block.append(stripped)
        elif block:
            yield block
            block = []
    if block:
        yield block


def _is_prose(block: list[str]) -> bool:
    """A block that is not a quote or a list of links."""
    return not (block[0].startswith(NON_PROSE_STARTS) or LINK_ITEM_RE.match(block[0]))


def _excerpt(text: str) -> str | None:
    """The first paragraph of prose on one line, cut to ``EXCERPT_MAX`` characters, or None."""
    body = FRONTMATTER_RE.sub("", text, count=1)
    block = next((b for b in _paragraphs(body) if _is_prose(b)), None)
    if block is None:
        return None
    line = " ".join(block)
    return line if len(line) <= EXCERPT_MAX else line[:EXCERPT_MAX].rstrip() + "…"


def diff(
    pages: list[Page],
    inbox: Path,
    upstream: list[str],
    include: list[str],
    markdown: str | None = None,
) -> dict:
    """Download the suite pages and the new ones in its upstream indexes; classify them.

    A ``deprecated`` page is not downloaded: it counts as unchanged. A new page that fails
    goes to ``skipped`` (it is tried again next run); ``errors`` is for the suite pages and
    the indexes that cannot be read. With ``markdown`` (a URL template), every page, also the
    new ones, is fetched only from the expanded template; a 404/410 there is ``gone``.
    """
    prepare_inbox(inbox)
    report: dict = {
        "changed": [],
        "unchanged": 0,
        "gone": [],
        "new": [],
        "skipped": [],
        "errors": [],
    }
    new = upstream_urls(upstream, include, {p.source for p in pages}, report)
    active = [p for p in pages if p.status != "deprecated"]
    report["unchanged"] += len(pages) - len(active)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def get(url: str) -> Fetched:
            return _fetch_markdown(url, markdown)

        results = pool.map(get, [p.source for p in active])
        for page, result in zip(active, results, strict=True):
            _classify(page, result, inbox, report)
        for result in pool.map(get, new):
            _new_entry(result, include, inbox, report)
    return report


# -- command line -----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check docs suites for /episteme:docs.")
    sub = parser.add_subparsers(dest="command", required=True)
    c7 = sub.add_parser("context7", help="lastUpdateDate of Context7 libraries")
    c7.add_argument("ids", nargs="+")
    d = sub.add_parser("diff", help="compare a suite with its sources")
    d.add_argument("--pages", type=Path, required=True)
    d.add_argument("--inbox", type=Path, required=True)
    d.add_argument("--upstream", nargs="*", default=[])
    d.add_argument("--include", nargs="*", default=[])
    d.add_argument("--markdown", default=None, help="suite.markdown URL template")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "context7":
        report: dict = {i: context7_date(i) for i in args.ids}
    else:
        report = diff(
            read_pages(args.pages), args.inbox, args.upstream, args.include, args.markdown
        )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
