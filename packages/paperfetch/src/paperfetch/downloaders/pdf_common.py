# -*- coding: utf-8 -*-
"""PDF 下载共享辅助函数。"""

import hashlib
from paperfetch.observability import get_event_logger
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

logger = get_event_logger(__name__)


@dataclass
class PDFDownloadResult:
    path: str
    resolved_url: Optional[str]
    source: str
    content_type: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    diagnostics: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.diagnostics is None:
            self.diagnostics = {}


def redact_url(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
        query = "<redacted-query>" if parts.query else ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except Exception:
        return "<redacted-url>"


def mask_identifier(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 4:
        return "***"
    return f"***{text[-4:]}"


def build_pdf_result(
    path: str,
    resolved_url: Optional[str],
    source: str,
    content_type: Optional[str] = None,
) -> PDFDownloadResult:
    size = os.path.getsize(path) if os.path.exists(path) else None
    sha256 = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
    return PDFDownloadResult(
        path=path,
        resolved_url=resolved_url,
        source=source,
        content_type=content_type,
        size=size,
        sha256=sha256,
    )


NON_PDF_URL_PATTERNS = (
    "article/figure",
    "figure/image",
    "suppl/extlink",
    "supplementary_material",
)


def _is_likely_false_positive_pdf(href_lower: str, base_url: str) -> bool:
    for pattern in NON_PDF_URL_PATTERNS:
        if pattern in href_lower:
            return True

    # PLOS 特有的非打印版下载地址。
    if "journals.plos.org" in href_lower or "journals.plos.org" in base_url.lower():
        if "type=download" in href_lower and "type=printable" not in href_lower:
            return True

    return False


def find_pdf_link_from_html(html_content: str, base_url: str) -> Optional[str]:
    """从开放落地页中保守提取 PDF 链接。"""
    try:
        soup = BeautifulSoup(html_content, "lxml")

        for meta in soup.find_all("meta"):
            content = meta.get("content", "").strip()
            if not content:
                continue
            name = (meta.get("name") or meta.get("property") or "").lower()
            if name in {"citation_pdf_url", "dc.identifier", "og:pdf"} and (
                ".pdf" in content.lower() or "/pdf/" in content.lower()
            ):
                return urljoin(base_url, content)

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue
            href_lower = href.lower()

            if _is_likely_false_positive_pdf(href_lower, base_url):
                continue

            if (
                ".pdf" in href_lower
                or "/pdf/" in href_lower
                or "download" in href_lower
            ):
                return urljoin(base_url, href)

        for tag_name, attr in (
            ("iframe", "src"),
            ("embed", "src"),
            ("object", "data"),
            ("frame", "src"),
        ):
            for tag in soup.find_all(tag_name):
                value = tag.get(attr, "").strip()
                if not value:
                    continue
                value_lower = value.lower()
                if any(
                    k in value_lower
                    for k in (
                        ".pdf",
                        "/pdf/",
                        "getpdf",
                        "stamppdf",
                        "arnumber",
                        "pdfurl",
                    )
                ):
                    return urljoin(base_url, value)
    except Exception as exc:
        logger.warning("[PDF 解析] 开放落地页 PDF 地址提取失败，原因=%s", exc)
    return None


def verify_pdf_file(file_path: str) -> bool:
    if not os.path.exists(file_path):
        return False
    if os.path.getsize(file_path) < 100:
        return False
    try:
        with open(file_path, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception as exc:
        logger.warning("[PDF 校验] 文件头校验失败，原因=%s", exc)
        return False
