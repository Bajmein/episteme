"""Check docs suites against their sources for /episteme:docs. Standard library only.

    docs_check.py context7 <id>...
        JSON {id: lastUpdateDate | null} from Context7's public search API.
    docs_check.py diff --pages <tsv> --out <dir> [--upstream <url>...] [--include <prefix>...]
        Downloads every source of the TSV that docs_status(suite, pages=true) returns, saves
        each page as <dir>/<sha1 of the url>.md and prints JSON with the changed, gone, new
        and failed pages. episteme itself has no HTTP: this script runs on the person's machine
        and the agent writes the results with docs_write.
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
from dataclasses import dataclass
from pathlib import Path

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


def body_hash(body: str) -> str:
    """Same as episteme.docs.body_hash: change both at once."""
    text = body.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_LEN]


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s) URLs."""

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
    except urllib.error.HTTPError as exc:
        return Fetched(url, exc.code, error=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return Fetched(url, None, error=str(getattr(exc, "reason", exc)))
    if len(data) > MAX_BYTES:
        return Fetched(url, status, error=f"larger than {MAX_BYTES // 1024 // 1024} MB")
    return Fetched(url, status, data.decode("utf-8", errors="replace"))


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


def file_for(out: Path, url: str) -> Path:
    return out / f"{hashlib.sha1(url.encode('utf-8'), usedforsecurity=False).hexdigest()}.md"


def _save(out: Path, result: Fetched) -> str:
    path = file_for(out, result.url)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(result.text or "")
    return str(path)


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

    An index that cannot be read goes to ``report["errors"]``, so the suite is not marked synced.
    """
    found: dict[str, None] = {}
    for index in upstream:
        result = fetch(index)
        if result.text is None:
            report["errors"].append({"source": index, "error": result.error})
        for url in URL_RE.findall(result.text or ""):
            url = url.rstrip(".,;:")
            if url in known or url in upstream:
                continue
            if not include or any(url.startswith(p) for p in include):
                found[url] = None
    return list(found)


def _classify(page: Page, result: Fetched, out: Path, report: dict) -> None:
    if result.status in GONE_STATUSES:
        if page.status == "deprecated":
            report["unchanged"] += 1
        else:
            report["gone"].append(
                {"source": page.source, "path": page.path, "http_status": result.status}
            )
    elif result.text is None:
        report["errors"].append({"source": page.source, "error": result.error})
    elif body_hash(result.text) == page.hash:
        report["unchanged"] += 1
    else:
        report["changed"].append(
            {"source": page.source, "path": page.path, "file": _save(out, result)}
        )


def _new_entry(result: Fetched, include: list[str], out: Path, report: dict) -> None:
    if result.text is None:
        report["errors"].append({"source": result.url, "error": result.error})
        return
    report["new"].append(
        {
            "source": result.url,
            "file": _save(out, result),
            "suggested_path": suggested_path(result.url, include),
        }
    )


def diff(pages: list[Page], out: Path, upstream: list[str], include: list[str]) -> dict:
    """Download the suite pages and the new ones in its upstream indexes; classify them."""
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"changed": [], "unchanged": 0, "gone": [], "new": [], "errors": []}
    new = upstream_urls(upstream, include, {p.source for p in pages}, report)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for page, result in zip(pages, pool.map(fetch, [p.source for p in pages]), strict=True):
            _classify(page, result, out, report)
        for result in pool.map(fetch, new):
            _new_entry(result, include, out, report)
    return report


# -- command line -----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check docs suites for /episteme:docs.")
    sub = parser.add_subparsers(dest="command", required=True)
    c7 = sub.add_parser("context7", help="lastUpdateDate of Context7 libraries")
    c7.add_argument("ids", nargs="+")
    d = sub.add_parser("diff", help="compare a suite with its sources")
    d.add_argument("--pages", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--upstream", nargs="*", default=[])
    d.add_argument("--include", nargs="*", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "context7":
        report: dict = {i: context7_date(i) for i in args.ids}
    else:
        report = diff(read_pages(args.pages), args.out, args.upstream, args.include)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
