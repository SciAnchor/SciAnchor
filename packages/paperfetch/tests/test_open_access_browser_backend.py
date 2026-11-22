import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.backends.open_access_browser import (
    OpenAccessBrowserBackend,
)
from paperfetch.downloaders.base import DownloadContext, PDFRouteCandidate
from paperfetch.downloaders.browser.auth_pool import BrowserPool
from paperfetch.downloaders.pipeline.errors import DownloadError


class FakeResponse:
    status = 200
    url = "https://pubs.rsna.org/doi/pdf/10.1148/ryai.230182"

    def __init__(self, content_type: str) -> None:
        self.headers = {"content-type": content_type}

    async def body(self) -> bytes:
        raise RuntimeError("viewer intercepted the response body")


class FakeCDPSession:
    def __init__(self, pdf_bytes: bytes) -> None:
        self.pdf_bytes = pdf_bytes
        self.listeners = {}
        self.patterns = []
        self.detached = False

    async def send(self, method, params=None):
        if method == "Fetch.enable":
            self.patterns = params["patterns"]
            return {}
        if method == "Fetch.getResponseBody":
            return {
                "body": base64.b64encode(self.pdf_bytes).decode("ascii"),
                "base64Encoded": True,
            }
        return {}

    def on(self, event, callback):
        self.listeners[event] = callback

    async def detach(self):
        self.detached = True


class FakePage:
    def __init__(self, cdp: FakeCDPSession, *, challenge: bool = False) -> None:
        self.cdp = cdp
        self.challenge = challenge
        self.url = "https://pubs.rsna.org/doi/pdf/10.1148/ryai.230182"
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    async def set_extra_http_headers(self, headers):
        self.extra_headers = headers

    async def goto(self, url, **kwargs):
        response = FakeResponse("text/html" if self.challenge else "application/pdf")
        if "response" in self.listeners:
            self.listeners["response"](response)
        if not self.challenge:
            self.cdp.listeners["Fetch.requestPaused"](
                {
                    "requestId": "request-1",
                    "request": {"url": response.url},
                    "responseStatusCode": 200,
                    "responseHeaders": [
                        {"name": "Content-Type", "value": "application/pdf"}
                    ],
                }
            )
        return response

    async def title(self):
        return "PDF Viewer"

    async def content(self):
        return (
            "<html>Verify you are human</html>" if self.challenge else "<html></html>"
        )


class FakeRequestClient:
    async def get(self, *args, **kwargs):
        return SimpleNamespace(
            status=200,
            url=args[0],
            body=self._body,
        )

    async def _body(self):
        return b"<html>not a PDF</html>"


class FakeContext:
    def __init__(self, pdf_bytes: bytes, *, challenge: bool = False) -> None:
        self.cdp = FakeCDPSession(pdf_bytes)
        self.page = FakePage(self.cdp, challenge=challenge)
        self.request = FakeRequestClient()
        self.closed = False

    async def new_page(self):
        return self.page

    async def new_cdp_session(self, page):
        return self.cdp

    async def close(self):
        self.closed = True


def make_context(tmp_path):
    return DownloadContext(
        paper=PaperRecord(
            paper_id="spc:rsna",
            doi="10.1148/ryai.230182",
            title="RSNA Paper",
        ),
        candidate=PDFRouteCandidate(
            "public_browser",
            url="https://pubs.rsna.org/doi/pdf/10.1148/ryai.230182",
            referer="https://pubs.rsna.org/doi/10.1148/ryai.230182",
            metadata={"known_public_pdf": True},
        ),
        target_file=str(tmp_path / "paper.pdf"),
        run_context=object(),
    )


@pytest.mark.asyncio
async def test_cdp_persists_pdf_when_chrome_viewer_hides_response_body(
    monkeypatch, tmp_path
):
    pdf_bytes = b"%PDF-1.7\n" + b"x" * 256
    context = FakeContext(pdf_bytes)

    async def get_instance():
        return SimpleNamespace(get_context=lambda: None)

    pool = await get_instance()

    async def get_context():
        return context

    pool.get_context = get_context

    async def fake_pool_instance():
        return pool

    monkeypatch.setattr(BrowserPool, "get_instance", fake_pool_instance)

    result = await OpenAccessBrowserBackend().download(make_context(tmp_path))

    assert result.source == "public_browser"
    assert Path(result.path).read_bytes() == pdf_bytes
    assert context.cdp.patterns[0]["urlPattern"] == "*://*.rsna.org/*"
    assert context.cdp.detached is True
    assert context.closed is True


@pytest.mark.asyncio
async def test_browser_backend_still_rejects_human_verification(monkeypatch, tmp_path):
    context = FakeContext(b"", challenge=True)
    pool = SimpleNamespace()

    async def get_context():
        return context

    pool.get_context = get_context

    async def fake_pool_instance():
        return pool

    monkeypatch.setattr(BrowserPool, "get_instance", fake_pool_instance)

    with pytest.raises(DownloadError) as caught:
        await OpenAccessBrowserBackend().download(make_context(tmp_path))

    assert caught.value.error_class == "publisher_challenge"
    assert context.closed is True
