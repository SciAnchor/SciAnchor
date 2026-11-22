from __future__ import annotations

import asyncio
from types import SimpleNamespace

from research_harness.pdf_download import PaperDownloadCandidate


class _FakeResponse:
    def __init__(
        self,
        url: str,
        *,
        status_code: int = 200,
        content: bytes = b"",
        content_type: str = "",
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type} if content_type else {}


class _FakeAsyncClient:
    responses: list[_FakeResponse | BaseException] = []

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    async def get(self, url: str):
        if not self.responses:
            raise AssertionError(f"unexpected fetch: {url}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_route_candidate_serialization_redacts_query_secrets() -> None:
    from research_harness.acquisition.routes import PDFRouteCandidate

    candidate = PDFRouteCandidate(
        route="metadata_open_access",
        url="https://example.org/paper.pdf?token=secret&download=1",
        source="openalex",
        priority=190,
        metadata={"query": "kept"},
    )

    assert candidate.to_dict() == {
        "route": "metadata_open_access",
        "url": "https://example.org/paper.pdf?token=REDACTED&download=1",
        "host": "example.org",
        "source": "openalex",
        "priority": 190,
        "requires_browser": False,
        "metadata": {"query": "kept"},
    }


def test_route_candidate_serialization_redacts_url_userinfo_and_signed_params() -> None:
    from research_harness.acquisition.routes import PDFRouteAttempt

    attempt = PDFRouteAttempt(
        route="metadata_open_access",
        url=(
            "https://user:pass@example.org/private.pdf?"
            "X-Amz-Signature=secret&x-amz-credential=credential&download=1"
        ),
    )

    assert attempt.to_dict()["url"] == (
        "https://REDACTED@example.org/private.pdf?"
        "X-Amz-Signature=REDACTED&x-amz-credential=REDACTED&download=1"
    )


def test_route_candidate_collapse_is_deterministic() -> None:
    from research_harness.acquisition.routes import build_route_candidates

    paper = PaperDownloadCandidate(
        paper_id=1,
        title="Route paper",
        url="https://openaccess.example.org/paper.pdf?token=abc",
        arxiv_id="2401.12345",
        doi="10.5555/test",
    )

    routes = build_route_candidates(
        paper,
        [
            "https://arxiv.org/pdf/2401.12345.pdf",
            "https://openaccess.example.org/paper.pdf?token=abc",
            "https://arxiv.org/pdf/2401.12345.pdf",
            "https://doi.org/10.5555/test",
        ],
    )

    assert [(item.route, item.url) for item in routes] == [
        ("metadata_open_access", "https://openaccess.example.org/paper.pdf?token=abc"),
        ("arxiv", "https://arxiv.org/pdf/2401.12345.pdf"),
        ("doi_landing", "https://doi.org/10.5555/test"),
    ]


def test_download_result_keeps_compatible_fields_with_audit() -> None:
    from research_harness.acquisition.downloader import DownloadResult
    from research_harness.acquisition.routes import PDFRouteAudit

    result = DownloadResult(
        paper_id=1,
        status="failed",
        failure_reason="all candidate URLs failed",
        audit=PDFRouteAudit(paper_id=1, failure_taxonomy="all_routes_failed"),
    )

    assert result.paper_id == 1
    assert result.status == "failed"
    assert result.path is None
    assert result.provider is None
    assert result.failure_reason == "all candidate URLs failed"
    assert result.audit is not None
    assert result.audit.to_dict()["failure_taxonomy"] == "all_routes_failed"


def test_managed_download_preserves_upstream_failures(monkeypatch, tmp_path):
    from research_harness.acquisition import downloader, spc_bridge
    from research_harness.acquisition.seed_pack_import import map_spc_failure_class

    for code in (
        "http_404",
        "not_pdf",
        "too_small",
        "subscription_required",
        "publisher_challenge",
        "credentials_missing",
        "identity_mismatch",
        "pdf_link_not_found",
    ):

        def fail(*args, **kwargs):
            raise spc_bridge.SPCAcquisitionError("download", {"error": {"code": code}})

        monkeypatch.setattr(spc_bridge, "spc_download", fail)
        result = asyncio.run(
            downloader.download_single(
                PaperDownloadCandidate(paper_id=1, title="Paper", doi="10.1234/test"),
                tmp_path / code,
                asyncio.Semaphore(1),
            )
        )
        assert result.status != "success"
        assert result.path is None
        assert result.audit.attempts[0].route == "spc"
        assert result.audit.attempts[0].error_class == code
        assert result.audit.failure_taxonomy == map_spc_failure_class(code)


def test_managed_download_rejects_invalid_bytes(monkeypatch, tmp_path):
    from research_harness.acquisition import downloader, spc_bridge

    for i, content in enumerate((b"<html>not PDF</html>" * 1000, b"%PDF-small")):

        def source(candidate, directory):
            path = directory / "input.pdf"
            path.write_bytes(content)
            return path

        monkeypatch.setattr(spc_bridge, "spc_download", source)
        result = asyncio.run(
            downloader.download_single(
                PaperDownloadCandidate(paper_id=2, title="Paper", doi="10.1234/test"),
                tmp_path / str(i),
                asyncio.Semaphore(1),
            )
        )
        assert result.status == "failed"
        assert result.path is None
        assert result.audit.failure_taxonomy == "not_pdf"


def test_managed_download_rejects_identity_mismatch(monkeypatch, tmp_path):
    from research_harness.acquisition import downloader, spc_bridge

    def source(candidate, directory):
        path = directory / "input.pdf"
        path.write_bytes(b"%PDF-1.7\n" + b"x" * 12000)
        return path

    monkeypatch.setattr(spc_bridge, "spc_download", source)
    monkeypatch.setattr(
        downloader,
        "audit_pdf_identity",
        lambda **_: SimpleNamespace(status="suspect", reason="wrong identity"),
    )
    result = asyncio.run(
        downloader.download_single(
            PaperDownloadCandidate(paper_id=3, title="Expected", doi="10.1234/test"),
            tmp_path,
            asyncio.Semaphore(1),
        )
    )
    assert result.status != "success"
    assert result.path is None
    assert not list(tmp_path.glob("*.pdf"))
    assert result.audit.failure_taxonomy == "identity_mismatch"


def test_managed_download_preserves_candidates_and_success_audit(monkeypatch, tmp_path):
    from research_harness.acquisition import downloader, spc_bridge

    def source(candidate, directory):
        assert candidate.extra_urls == ("https://oa.example.org/paper.pdf",)
        path = directory / "input.pdf"
        path.write_bytes(b"%PDF-1.7\n" + b"x" * 12000)
        return path

    monkeypatch.setattr(spc_bridge, "spc_download", source)
    monkeypatch.setattr(
        downloader,
        "audit_pdf_identity",
        lambda **_: SimpleNamespace(status="verified", reason=""),
    )
    result = asyncio.run(
        downloader.download_single(
            PaperDownloadCandidate(
                paper_id=4,
                title="Paper",
                doi="10.1234/test",
                extra_urls=("https://oa.example.org/paper.pdf",),
            ),
            tmp_path,
            asyncio.Semaphore(1),
        )
    )
    assert result.status == "success"
    assert result.provider == result.audit.successful_route == "spc"
    assert result.audit.sha256


def test_download_single_classifies_missing_identifiers_before_fetching(
    monkeypatch, tmp_path
):
    from research_harness.acquisition import downloader, spc_bridge

    def forbidden(*args, **kwargs):
        raise AssertionError("missing identity must not fetch")

    monkeypatch.setattr(spc_bridge, "spc_download", forbidden)
    result = asyncio.run(
        downloader.download_single(
            PaperDownloadCandidate(paper_id=5, title="No identifiers"),
            tmp_path,
            asyncio.Semaphore(1),
        )
    )
    assert result.status == "failed"
    assert result.audit.failure_taxonomy == "no_candidate_identifier"
    assert "enrich metadata" in result.failure_reason


def test_download_single_is_spc_only_and_records_spc_failure(monkeypatch, tmp_path):
    """PDF acquisition is SPC-only: no direct fetch runs alongside SPC, and an
    SPC failure is recorded as a single ``spc`` attempt."""
    from research_harness.acquisition import downloader, pdf_cache, spc_bridge

    monkeypatch.setattr(
        pdf_cache.VerifiedPDFCache,
        "from_env",
        classmethod(lambda cls, **_: cls(None)),
    )
    monkeypatch.setattr(
        pdf_cache.FailureTTLCache,
        "from_env",
        classmethod(lambda cls: cls(tmp_path / "failures", 0)),
    )
    seen = []

    def unavailable(candidate, target):
        seen.append(candidate.doi)
        raise spc_bridge.SPCAcquisitionError(
            "download", {"error": {"code": "unavailable"}}
        )

    monkeypatch.setattr(spc_bridge, "spc_download", unavailable)

    result = asyncio.run(
        downloader.download_single(
            PaperDownloadCandidate(paper_id=1, title="Paper", doi="10.5555/test"),
            tmp_path,
            asyncio.Semaphore(1),
        )
    )

    assert seen == ["10.5555/test"]
    assert result.status == "failed"
    assert result.audit is not None
    assert [attempt.route for attempt in result.audit.attempts] == ["spc"]
    assert result.audit.attempts[0].error_class == "unavailable"
