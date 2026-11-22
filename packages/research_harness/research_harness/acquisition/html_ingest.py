"""Minimal HTML → markdown fetcher for URL-only paper_ingest.

Designed for the 'doctrine' / blog-post case where the source is a
plain-text article (e.g. an Anthropic engineering blog, a research lab
writeup) rather than a PDF. Stdlib-only: uses html.parser so there is
no runtime dependency on bs4 / html2text / readability.

Not a general-purpose scraper:
- No JS execution.
- Strips <script>, <style>, <nav>, <header>, <footer> blocks.
- Preserves structure at heading / paragraph / list / code / link level.
- Returns (title, markdown_body). Either may be empty on failure.

If the URL returns a non-text MIME type (e.g. application/pdf) we
return empty strings and let the caller decide to dispatch to the
PDF-acquisition pipeline instead.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


_SKIP_TAGS = frozenset(
    {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg"}
)
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "br", "hr"})
_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
_LIST_ITEM_TAGS = frozenset({"li"})


def invalid_source_reason(title: str, content: str = "") -> str:
    """Return known challenge/error-page evidence, not a scholarly-quality verdict.

    Empty means unknown or no matching signature. Short text, missing identifiers,
    and prose about browser verification are not evidence of a failed fetch.
    """
    normalized_title = " ".join((title or "").casefold().split()).rstrip(".!…")
    if re.fullmatch(
        r"(?:verifying your browser|checking your browser|verify you are human|"
        r"verifying you are human)(?:\s*\|\s*(?:openreview|cloudflare))?"
        r"|just a moment|attention required!?\s*\|\s*cloudflare",
        normalized_title,
    ):
        return "source_challenge_page"
    if re.fullmatch(
        r"access denied|(?:403\s*[-:]?\s*)?forbidden|(?:404\s*[-:]?\s*)?not found"
        r"|(?:502\s*[-:]?\s*)?bad gateway|(?:503\s*[-:]?\s*)?service unavailable",
        normalized_title,
    ):
        return "source_error_page"

    # Match the opening page structure, not quotations or generated summaries.
    lines = [
        " ".join(line.casefold().split()).lstrip("# ").rstrip(".!…")
        for line in (content or "").splitlines()
        if line.strip()
    ]
    if lines[:3] == [
        "verifying your browser",
        "complete the check below to continue to openreview",
        "please complete the verification above",
    ]:
        return "source_challenge_page"
    if (
        lines
        and lines[0] == "just a moment"
        and "enable javascript and cookies to continue" in lines[1:3]
    ):
        return "source_challenge_page"
    return ""


@dataclass
class FetchedPage:
    url: str
    title: str = ""
    markdown: str = ""
    content_type: str = ""
    http_status: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        if not self.error:
            self.error = invalid_source_reason(self.title, self.markdown)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.markdown.strip())


class _MarkdownExtractor(HTMLParser):
    """Convert a limited subset of HTML to markdown.

    Tracks a tag stack so we can detect <script> / <style> and drop
    their text entirely. Keeps link text + href. Emits paragraph breaks
    at block-level tags.
    """

    def __init__(self) -> None:
        super().__init__()
        self._stack: list[str] = []
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._in_title = False
        self._pending_href: str = ""
        self._in_link = False
        self._link_text: list[str] = []

    # ---- helpers ----

    def _in_skip(self) -> bool:
        return any(t in _SKIP_TAGS for t in self._stack)

    def _emit(self, s: str) -> None:
        if s:
            self._parts.append(s)

    # ---- events ----

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack.append(tag)
        if tag == "title":
            self._in_title = True
            return
        if self._in_skip():
            return
        if tag in _HEADING_TAGS:
            self._emit("\n\n" + "#" * _HEADING_TAGS[tag] + " ")
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "br":
            self._emit("  \n")
        elif tag in _BLOCK_TAGS:
            self._emit("\n\n")
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._emit("\n\n```\n")
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "a":
            self._in_link = True
            self._link_text = []
            href = ""
            for k, v in attrs:
                if k == "href" and v:
                    href = v
                    break
            self._pending_href = href

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if tag == "title":
            self._in_title = False
            return
        if self._in_skip():
            return
        if tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._emit("\n```\n")
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "a" and self._in_link:
            text = "".join(self._link_text).strip()
            href = self._pending_href
            if text and href:
                self._emit(f"[{text}]({href})")
            elif text:
                self._emit(text)
            self._in_link = False
            self._link_text = []
            self._pending_href = ""

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._in_skip():
            return
        if self._in_link:
            self._link_text.append(data)
            return
        self._parts.append(data)

    # ---- result ----

    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    def markdown(self) -> str:
        text = "".join(self._parts)
        # Collapse > 2 newlines in a row, trim trailing whitespace per line
        lines = [line.rstrip() for line in text.splitlines()]
        collapsed: list[str] = []
        blank_run = 0
        for line in lines:
            if not line.strip():
                blank_run += 1
                if blank_run > 1:
                    continue
            else:
                blank_run = 0
            collapsed.append(line)
        return "\n".join(collapsed).strip()


def fetch_html_as_markdown(
    url: str, *, timeout: float = 15.0, user_agent: str | None = None
) -> FetchedPage:
    """Fetch a URL and extract (title, markdown_body).

    Non-text-HTML responses (e.g. application/pdf) return an empty body
    so the caller can fall through to PDF acquisition.
    """
    # Scholarly identifiers use the managed fulltext route; ordinary web sources
    # (blogs, documentation, dataset pages) retain HTML ingestion.
    import re
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    path = unquote(parsed.path)
    doi_match = re.search(r"10\.\d{4,9}/[^\s?&#]+", unquote(url))
    arxiv_match = (
        re.search(r"/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", path)
        if parsed.hostname in {"arxiv.org", "www.arxiv.org"}
        else None
    )
    if doi_match or arxiv_match:
        import tempfile
        from pathlib import Path
        from .spc_bridge import spc_download
        from ..pdf_download import PaperDownloadCandidate

        try:
            import pymupdf

            candidate = PaperDownloadCandidate(
                paper_id=0,
                title="",
                doi=doi_match.group(0) if doi_match else "",
                arxiv_id=arxiv_match.group(1) if arxiv_match else "",
            )
            with tempfile.TemporaryDirectory(prefix="rh-spc-html-") as temporary:
                pdf = spc_download(candidate, Path(temporary))
                # Reuse the same identity check as regular acquisition.
                from .downloader import _pdf_identity_failure

                if _pdf_identity_failure(candidate, pdf):
                    return FetchedPage(url=url, error="managed PDF identity mismatch")
                with pymupdf.open(pdf) as doc:
                    text = "\n".join(page.get_text() for page in doc)
                    title = str(doc.metadata.get("title") or "")
            return FetchedPage(
                url=url,
                title=title,
                markdown=text,
                content_type="application/pdf",
                http_status=200,
            )
        except Exception as exc:
            return FetchedPage(
                url=url, error=f"managed acquisition unavailable: {type(exc).__name__}"
            )
    ua = user_agent or "research-harness/paper_ingest (HTML extractor)"
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Accept": "text/html,*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ct and "application/xhtml" not in ct:
                return FetchedPage(
                    url=url,
                    content_type=ct,
                    http_status=getattr(resp, "status", 200),
                    error=f"non-HTML content-type: {ct or 'unknown'}",
                )
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                body = raw.decode(charset, errors="replace")
            except LookupError:
                body = raw.decode("utf-8", errors="replace")
            http_status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        return FetchedPage(
            url=url, http_status=exc.code, error=f"HTTP {exc.code}: {exc.reason}"
        )
    except Exception as exc:  # noqa: BLE001 — network errors all logged the same
        logger.warning("fetch_html_as_markdown network error for %s: %s", url, exc)
        return FetchedPage(url=url, error=f"{type(exc).__name__}: {exc}")

    extractor = _MarkdownExtractor()
    try:
        extractor.feed(body)
        extractor.close()
    except Exception as exc:  # noqa: BLE001 — malformed HTML should not crash ingest
        logger.warning("fetch_html_as_markdown parse error for %s: %s", url, exc)
        return FetchedPage(url=url, http_status=http_status, error=f"parse: {exc}")

    return FetchedPage(
        url=url,
        title=extractor.title(),
        markdown=extractor.markdown(),
        content_type=ct,
        http_status=http_status,
    )


__all__ = ["FetchedPage", "fetch_html_as_markdown", "invalid_source_reason"]
