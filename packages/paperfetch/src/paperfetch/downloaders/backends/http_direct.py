# -*- coding: utf-8 -*-
"""Phase 1 统一流式 HTTP 传输后端。"""

from __future__ import annotations

import os
import uuid
from typing import Dict
from urllib.parse import urlsplit

import httpx

from paperfetch.downloaders.base import DownloadContext, DownloaderBackend
from paperfetch.downloaders.pdf_common import PDFDownloadResult, build_pdf_result
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.registry import BackendRegistry


MAX_PDF_BYTES = 200 * 1024 * 1024
CHALLENGE_MARKERS = (
    "cloudflare",
    "turnstile",
    "captcha",
    "verify you are human",
    "imperva",
    "incapsula",
    "x-amzn-waf-action",
    "device verification",
)


@BackendRegistry.register
class HTTPDirectBackend(DownloaderBackend):
    """传输一个已经规范化的公开 HTTP 资源。"""

    route_key = "public_http"
    display_name = "公开 HTTP 流式传输"
    supported_routes = frozenset({"public_http", "agent_browser"})

    @staticmethod
    def _headers(referer: str | None) -> Dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Sec-Ch-Ua": '"Not A(Brand";v="8", "Chromium";v="136", "Google Chrome";v="136"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
        }
        if referer:
            headers["Referer"] = referer
        return headers

    @staticmethod
    def _classify(
        status: int, content_type: str, preview: bytes, url: str, headers: httpx.Headers
    ) -> str:
        text = preview.decode("utf-8", errors="ignore").lower()
        header_text = "\n".join(
            f"{key}: {value}" for key, value in headers.items()
        ).lower()
        if any(marker in text or marker in header_text for marker in CHALLENGE_MARKERS):
            host = (urlsplit(url).hostname or "").lower()
            if host == "ncbi.nlm.nih.gov" or host.endswith(".ncbi.nlm.nih.gov"):
                return "pmc_download_challenge"
            return "publisher_challenge"
        if any(
            marker in text
            for marker in (
                "institution",
                "shibboleth",
                "openathens",
                "sign in via",
                "login via",
                "institutional access",
            )
        ):
            return "auth_required"
        if (
            "access denied" in text
            or "forbidden" in text
            or "access denied" in header_text
        ):
            return (
                "publisher_challenge"
                if any(
                    m in header_text or m in text
                    for m in ("akamai", "cloudflare", "imperva")
                )
                else "public_access_blocked"
            )
        if status == 401:
            return "auth_required"
        if status == 403:
            return "public_access_blocked"
        if status in {404, 410}:
            return "not_found"
        if status == 429:
            return "rate_limited"
        if "login" in text and any(
            marker in text
            for marker in (
                "sign in",
                "institution",
                "shibboleth",
                "device",
                "saml",
                "sso",
            )
        ):
            return "auth_required"
        if "html" in content_type or text.lstrip().startswith(
            ("<!doctype html", "<html")
        ):
            host = (urlsplit(url).hostname or "").lower()
            allowed = any(
                host == item or host.endswith("." + item)
                for item in ("frontiersin.org", "mdpi.com", "plos.org")
            )
            return "html_dynamic" if status == 200 and allowed else "html_landing"
        return "not_pdf"

    async def download(self, ctx: DownloadContext) -> PDFDownloadResult:
        candidate = ctx.candidate
        url = candidate.url
        if not url:
            raise DownloadError("missing_url", route=candidate.route)
        client = getattr(ctx, "client", None)
        local_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                follow_redirects=True, trust_env=False, timeout=12.0
            )
        timeout_seconds = float(
            candidate.metadata.get("attempt_timeout_seconds") or 12.0
        )
        part_path = f"{ctx.target_file}.{uuid.uuid4().hex}.part"
        handed_off = False
        os.makedirs(os.path.dirname(ctx.target_file), exist_ok=True)
        try:
            request_headers = self._headers(candidate.referer)
            preview = bytearray()
            total = 0
            async with client.stream(
                "GET", url, headers=request_headers, timeout=timeout_seconds
            ) as response:
                content_type = response.headers.get("content-type", "").lower()
                with open(part_path, "wb") as output:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        if len(preview) < 8192:
                            preview.extend(chunk[: 8192 - len(preview)])
                        total += len(chunk)
                        if total > MAX_PDF_BYTES:
                            raise DownloadError(
                                "pdf_too_large",
                                route=candidate.route,
                                url=str(response.url),
                                status_code=response.status_code,
                                content_type=content_type,
                            )
                        output.write(chunk)
                if response.status_code >= 400 or not bytes(preview).startswith(
                    b"%PDF"
                ):
                    error_class = self._classify(
                        response.status_code,
                        content_type,
                        bytes(preview),
                        str(response.url),
                        response.headers,
                    )
                    diagnostics = {}
                    retry_after = response.headers.get("retry-after")
                    if retry_after:
                        diagnostics["retry_after"] = retry_after
                    raise DownloadError(
                        error_class,
                        route=candidate.route,
                        url=str(response.url),
                        status_code=response.status_code,
                        content_type=content_type,
                        diagnostics=diagnostics,
                    )
                result = build_pdf_result(
                    part_path, str(response.url), candidate.route, content_type
                )
                result.size = total
                handed_off = True
                return result
        except httpx.TimeoutException as exc:
            raise DownloadError(
                "timeout",
                route=candidate.route,
                url=url,
                message=f"公开资源传输超过 {timeout_seconds:.1f} 秒",
            ) from exc
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError.from_exception(exc, route=candidate.route, url=url)
        finally:
            if local_client:
                await client.aclose()
            if os.path.exists(part_path) and not handed_off:
                os.remove(part_path)
