# -*- coding: utf-8 -*-
"""经过允许列表约束的公开动态页面浏览器后备。"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from urllib.parse import urlsplit

from paperfetch.downloaders.base import DownloadContext, DownloaderBackend
from paperfetch.downloaders.browser.auth_pool import BrowserPool
from paperfetch.downloaders.pdf_common import PDFDownloadResult, build_pdf_result
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.registry import BackendRegistry
from paperfetch.observability import get_event_logger


ALLOWED_OA_HOSTS = ("frontiersin.org", "mdpi.com", "plos.org", "rsna.org")
MAX_PDF_BYTES = 200 * 1024 * 1024
logger = get_event_logger("paperfetch.downloaders.open_access_browser")


def _decode_cdp_body(payload: dict[str, object]) -> bytes:
    body = payload.get("body") or ""
    if not isinstance(body, str):
        return b""
    if payload.get("base64Encoded"):
        return base64.b64decode(body)
    return body.encode("latin-1")


@BackendRegistry.register
class OpenAccessBrowserBackend(DownloaderBackend):
    """只处理公开 OA 主机的普通 200 动态页面，不处理挑战或登录。"""

    route_key = "public_browser"
    display_name = "公开动态页面浏览器后备"
    supported_routes = frozenset({"public_browser"})
    concurrency_group = "browser"

    async def download(self, ctx: DownloadContext) -> PDFDownloadResult:
        url = ctx.candidate.url or ""
        host = (urlsplit(url).hostname or "").lower()
        allowed_domain = next(
            (
                allowed
                for allowed in ALLOWED_OA_HOSTS
                if host == allowed or host.endswith("." + allowed)
            ),
            None,
        )
        if allowed_domain is None:
            raise DownloadError(
                "browser_host_not_allowed", route=self.route_key, url=url
            )
        if not (
            ctx.candidate.metadata.get("ordinary_html_confirmed")
            or ctx.candidate.metadata.get("known_public_pdf")
        ):
            raise DownloadError(
                "browser_precondition_failed", route=self.route_key, url=url
            )

        pool = await BrowserPool.get_instance()
        context = await pool.get_context()
        page = await context.new_page()
        part_path = f"{ctx.target_file}.{uuid.uuid4().hex}.part"
        captured: dict[str, object] = {"bytes": None, "url": url}
        tasks: list[asyncio.Task] = []
        cdp_session = None
        observation: dict[str, object] = {
            "cdp_paused_responses": 0,
            "pdf_responses": 0,
            "capture_errors": [],
        }

        async def collect(response: object) -> None:
            headers = getattr(response, "headers", {})
            content_type = str(headers.get("content-type") or "").lower()
            if "application/pdf" not in content_type or getattr(
                response, "status", 0
            ) not in {200, 206}:
                return
            observation["pdf_responses"] = int(observation["pdf_responses"]) + 1
            body = await response.body()
            if body.startswith(b"%PDF") and len(body) <= MAX_PDF_BYTES:
                captured["bytes"] = body
                captured["url"] = response.url

        def on_response(response: object) -> None:
            tasks.append(asyncio.create_task(collect(response)))

        page.on("response", on_response)
        try:
            # Chrome 的内置 PDF Viewer 有时会接管主文档，Playwright 的
            # response.body() 因 net::ERR_ABORTED 无法读取。导航前在允许列表
            # 主机上截获响应体，既不依赖 Viewer DOM，也不复用用户浏览器状态。
            try:
                cdp_session = await context.new_cdp_session(page)

                async def capture_paused_response(params: dict[str, object]) -> None:
                    observation["cdp_paused_responses"] = (
                        int(observation["cdp_paused_responses"]) + 1
                    )
                    request_id = params.get("requestId")
                    response_headers = params.get("responseHeaders") or []
                    headers = {
                        str(item.get("name") or "").lower(): str(
                            item.get("value") or ""
                        )
                        for item in response_headers
                        if isinstance(item, dict)
                    }
                    content_type = headers.get("content-type", "").lower()
                    status_code = int(params.get("responseStatusCode") or 0)
                    try:
                        if (
                            status_code in {200, 206}
                            and "application/pdf" in content_type
                        ):
                            payload = await asyncio.wait_for(
                                cdp_session.send(
                                    "Fetch.getResponseBody",
                                    {"requestId": request_id},
                                ),
                                timeout=10.0,
                            )
                            body = _decode_cdp_body(payload)
                            if body.startswith(b"%PDF") and len(body) <= MAX_PDF_BYTES:
                                captured["bytes"] = body
                                captured["url"] = str(
                                    (params.get("request") or {}).get("url") or url
                                )
                    except Exception as capture_error:
                        cast_errors = observation["capture_errors"]
                        if isinstance(cast_errors, list):
                            cast_errors.append(type(capture_error).__name__)
                        logger.debug(
                            "[OA 浏览器] PDF 响应体截获未完成，继续其他持久化策略，异常=%s",
                            type(capture_error).__name__,
                        )
                    finally:
                        try:
                            await cdp_session.send(
                                "Fetch.continueResponse",
                                {"requestId": request_id},
                            )
                        except Exception:
                            try:
                                await cdp_session.send(
                                    "Fetch.continueRequest",
                                    {"requestId": request_id},
                                )
                            except Exception:
                                pass

                def queue_paused_response(params: dict[str, object]) -> None:
                    tasks.append(asyncio.create_task(capture_paused_response(params)))

                await cdp_session.send(
                    "Fetch.enable",
                    {
                        "patterns": [
                            {
                                "urlPattern": f"*://*.{allowed_domain}/*",
                                "requestStage": "Response",
                            }
                        ]
                    },
                )
                cdp_session.on("Fetch.requestPaused", queue_paused_response)
            except Exception as cdp_error:
                logger.debug(
                    "[OA 浏览器] CDP 响应截获不可用，继续 Playwright 响应策略，异常=%s",
                    type(cdp_error).__name__,
                )
            if ctx.candidate.referer:
                await page.set_extra_http_headers({"Referer": ctx.candidate.referer})
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=10000
            )
            if response is None or response.status != 200:
                raise DownloadError(
                    "browser_navigation_failed",
                    route=self.route_key,
                    url=url,
                    status_code=response.status if response else None,
                )
            navigation_type = str(response.headers.get("content-type") or "").lower()
            page_parts = urlsplit(page.url)
            observation.update(
                {
                    "navigation_status": response.status,
                    "navigation_content_type": navigation_type.split(";", 1)[0],
                    "page_scheme": page_parts.scheme,
                    "page_host": page_parts.hostname or "",
                    "page_path": page_parts.path,
                    "page_title": (await page.title())[:160],
                }
            )
            if "application/pdf" in navigation_type:
                try:
                    body = await response.body()
                except Exception:
                    body = b""
                if body.startswith(b"%PDF") and len(body) <= MAX_PDF_BYTES:
                    captured["bytes"] = body
                    captured["url"] = response.url
                if not captured["bytes"]:
                    request_headers = (
                        {"Referer": ctx.candidate.referer}
                        if ctx.candidate.referer
                        else None
                    )
                    retry = await context.request.get(
                        url,
                        headers=request_headers,
                        timeout=10000,
                    )
                    retry_body = await retry.body()
                    if (
                        retry.status == 200
                        and retry_body.startswith(b"%PDF")
                        and len(retry_body) <= MAX_PDF_BYTES
                    ):
                        captured["bytes"] = retry_body
                        captured["url"] = retry.url
            else:
                page_text = (await page.content())[:12000].lower()
                if any(
                    marker in page_text
                    for marker in (
                        "cloudflare",
                        "turnstile",
                        "captcha",
                        "verify you are human",
                        "imperva",
                        "incapsula",
                        "sign in",
                        "device verification",
                    )
                ):
                    raise DownloadError(
                        "publisher_challenge", route=self.route_key, url=url
                    )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            pdf_bytes = captured["bytes"]
            if not isinstance(pdf_bytes, bytes):
                raise DownloadError(
                    "not_pdf",
                    route=self.route_key,
                    url=url,
                    message="公开动态页面未产生 PDF 响应",
                    diagnostics=observation,
                )
            os.makedirs(os.path.dirname(ctx.target_file), exist_ok=True)
            with open(part_path, "wb") as output:
                output.write(pdf_bytes)
            return build_pdf_result(
                part_path, str(captured["url"]), self.route_key, "application/pdf"
            )
        finally:
            if cdp_session is not None:
                try:
                    await cdp_session.detach()
                except Exception:
                    pass
            await context.close()
