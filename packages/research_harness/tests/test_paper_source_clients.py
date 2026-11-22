from __future__ import annotations

import http.client
import urllib.error
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from research_harness.paper_source_clients import (
    GoogleScholarProvider,
    OpenReviewProvider,
    PubMedProvider,
    SemanticScholarProvider,
    _fetch_with_retry,
    _parse_retry_after,
)
from research_harness.paper_sources import SearchQuery


def test_semantic_scholar_provider_uses_supported_fields_and_maps_external_ids() -> (
    None
):
    captured: dict[str, str] = {}

    def fetcher(url: str, headers: dict[str, str]):
        del headers
        captured["url"] = url
        return {
            "data": [
                {
                    "paperId": "paper-123",
                    "title": "Attention Is All You Need",
                    "authors": [{"name": "Ashish Vaswani"}],
                    "year": 2017,
                    "venue": "NeurIPS",
                    "abstract": "transformers",
                    "externalIds": {"DOI": "10.5555/test", "ArXiv": "1706.03762"},
                    "url": "https://www.semanticscholar.org/paper/paper-123",
                    "citationCount": 42,
                    "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
                }
            ]
        }

    provider = SemanticScholarProvider(api_key="test-key", fetcher=fetcher)
    results = provider.search(SearchQuery(query="attention", limit=1))

    fields = parse_qs(urlparse(captured["url"]).query)["fields"][0].split(",")
    assert "doi" not in fields
    assert "paperId" in fields

    assert len(results) == 1
    result = results[0]
    assert result.doi == "10.5555/test"
    assert result.arxiv_id == "1706.03762"
    assert result.s2_id == "paper-123"
    assert result.pdf_candidates[0].url == "https://arxiv.org/pdf/1706.03762.pdf"


def test_google_scholar_provider_maps_serpapi_style_payload() -> None:
    captured: dict[str, object] = {}

    def fetcher(url: str, headers: dict[str, str]):
        captured["url"] = url
        captured["headers"] = headers
        return {
            "organic_results": [
                {
                    "title": "Attention Is All You Need",
                    "publication_info": {
                        "authors": [
                            {"name": "Ashish Vaswani"},
                            {"name": "Noam Shazeer"},
                        ],
                        "summary": "A Vaswani, N Shazeer - Advances in neural information processing systems, 2017",
                    },
                    "inline_links": {"cited_by": {"total": "123456"}},
                    "resources": [
                        {
                            "title": "PDF",
                            "file_format": "PDF",
                            "link": "https://example.org/attention.pdf",
                        },
                        {"title": "HTML", "link": "https://example.org/html"},
                    ],
                    "link": "https://example.org/paper",
                    "snippet": "Transformer networks for sequence modeling.",
                }
            ]
        }

    provider = GoogleScholarProvider(
        api_url="https://scholar-gateway.example/search",
        api_key="scholar-key",
        fetcher=fetcher,
    )

    results = provider.search(
        SearchQuery(query="attention", limit=5, year_from=2017, year_to=2018)
    )

    assert len(results) == 1
    assert "q=attention" in str(captured["url"])
    assert "as_ylo=2017" in str(captured["url"])
    assert captured["headers"] == {
        "Accept": "application/json",
        "X-API-Key": "scholar-key",
    }
    result = results[0]
    assert result.title == "Attention Is All You Need"
    assert result.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert result.year == 2017
    assert result.venue == "Advances in neural information processing systems"
    assert result.citation_count == 123456
    assert result.pdf_candidates[0].url == "https://example.org/attention.pdf"
    assert result.pdf_candidates[0].source_type == "open_access_pdf"


def test_openreview_provider_maps_notes_and_filters_years() -> None:
    captured: dict[str, object] = {}

    def fetcher(url: str, headers: dict[str, str]):
        captured["url"] = url
        captured["headers"] = headers
        return {
            "notes": [
                {
                    "id": "paper-2025",
                    "forum": "forum-2025",
                    "pdate": 1735689600000,
                    "content": {
                        "title": {"value": "A Strong ICLR Paper"},
                        "abstract": {"value": "A useful abstract."},
                        "authors": {"value": ["Ada Lovelace", "Alan Turing"]},
                        "venue": {"value": "ICLR 2025 Conference"},
                        "pdf": {"value": "/pdf?id=forum-2025"},
                    },
                },
                {
                    "id": "paper-2023",
                    "pdate": 1672531200000,
                    "content": {
                        "title": {"value": "Too Old"},
                        "venue": {"value": "ICLR 2023"},
                    },
                },
            ]
        }

    provider = OpenReviewProvider(access_token="openreview-token", fetcher=fetcher)
    results = provider.search(
        SearchQuery(query="strong paper", limit=10, year_from=2025, year_to=2025)
    )

    assert len(results) == 1
    assert "content=title" in str(captured["url"])
    assert captured["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer openreview-token",
    }
    result = results[0]
    assert result.title == "A Strong ICLR Paper"
    assert result.year == 2025
    assert result.venue == "ICLR 2025 Conference"
    assert result.openreview_id == "forum-2025"
    assert result.url == "https://openreview.net/forum?id=forum-2025"
    assert result.pdf_candidates[0].url == "https://openreview.net/pdf?id=forum-2025"
    assert result.pdf_candidates[0].source_type == "openreview_pdf"


def test_pubmed_provider_searches_ids_then_fetches_article_metadata() -> None:
    captured_urls: list[str] = []

    def fetcher(url: str, headers: dict[str, str]) -> str:
        assert headers["Accept"] == "application/xml"
        captured_urls.append(url)
        if "esearch.fcgi" in url:
            return """
            <eSearchResult>
              <IdList>
                <Id>12345678</Id>
              </IdList>
            </eSearchResult>
            """
        if "efetch.fcgi" in url:
            return """
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>12345678</PMID>
                  <Article>
                    <Journal>
                      <Title>Environmental Health Perspectives</Title>
                      <JournalIssue>
                        <PubDate><Year>2025</Year></PubDate>
                      </JournalIssue>
                    </Journal>
                    <ArticleTitle>Climate change and pregnancy outcomes.</ArticleTitle>
                    <Abstract>
                      <AbstractText>Heat exposure increased preterm birth risk.</AbstractText>
                      <AbstractText Label="Background">Maternal heat adaptation remains understudied.</AbstractText>
                    </Abstract>
                    <AuthorList>
                      <Author>
                        <ForeName>Ada</ForeName>
                        <LastName>Lovelace</LastName>
                      </Author>
                      <Author>
                        <CollectiveName>Climate Birth Outcomes Study Group</CollectiveName>
                      </Author>
                    </AuthorList>
                    <PublicationTypeList>
                      <PublicationType>Journal Article</PublicationType>
                      <PublicationType>Systematic Review</PublicationType>
                    </PublicationTypeList>
                  </Article>
                  <MeshHeadingList>
                    <MeshHeading>
                      <DescriptorName MajorTopicYN="Y">Climate Change</DescriptorName>
                    </MeshHeading>
                    <MeshHeading>
                      <DescriptorName>Pregnancy Outcome</DescriptorName>
                    </MeshHeading>
                  </MeshHeadingList>
                </MedlineCitation>
                <PubmedData>
                  <ArticleIdList>
                    <ArticleId IdType="doi">10.1289/example</ArticleId>
                    <ArticleId IdType="pubmed">12345678</ArticleId>
                    <ArticleId IdType="pmc">PMC1234567</ArticleId>
                  </ArticleIdList>
                </PubmedData>
              </PubmedArticle>
            </PubmedArticleSet>
            """
        raise AssertionError(f"unexpected URL: {url}")

    provider = PubMedProvider(
        api_key="api-key",
        email="dev@example.org",
        tool="research_harness_test",
        fetcher=fetcher,
    )

    results = provider.search(
        SearchQuery(
            query="climate change maternal health",
            year_from=2024,
            year_to=2026,
            limit=1,
            per_provider_limit=1,
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.title == "Climate change and pregnancy outcomes."
    assert result.authors == [
        "Ada Lovelace",
        "Climate Birth Outcomes Study Group",
    ]
    assert result.year == 2025
    assert result.venue == "Environmental Health Perspectives"
    assert "preterm birth risk" in result.abstract
    assert "Background: Maternal heat adaptation" in result.abstract
    assert result.doi == "10.1289/example"
    assert result.pmid == "12345678"
    assert result.pmcid == "PMC1234567"
    assert result.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert result.provider == "pubmed"
    assert [candidate.url for candidate in result.pdf_candidates] == [
        "https://europepmc.org/api/getPdf?pmcid=PMC1234567",
        "https://europepmc.org/articles/PMC1234567?pdf=render",
        "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC1234567",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/",
    ]
    assert result.pdf_candidates[0].source_type == "open_access_pdf"
    assert result.pdf_candidates[-1].requires_browser is True
    assert {
        "source": "pubmed",
        "kind": "publication_type",
        "display_name": "Systematic Review",
    } in result.concepts
    assert {
        "source": "pubmed",
        "kind": "mesh",
        "display_name": "Climate Change",
        "major_topic": True,
    } in result.concepts

    search_url = captured_urls[0]
    search_params = parse_qs(urlparse(search_url).query)
    assert search_params["db"] == ["pubmed"]
    assert search_params["retmax"] == ["1"]
    assert search_params["tool"] == ["research_harness_test"]
    assert search_params["email"] == ["dev@example.org"]
    assert search_params["api_key"] == ["api-key"]
    assert "2024:2026[pdat]" in search_params["term"][0]

    fetch_url = captured_urls[1]
    fetch_params = parse_qs(urlparse(fetch_url).query)
    assert fetch_params["db"] == ["pubmed"]
    assert fetch_params["id"] == ["12345678"]
    assert fetch_params["retmode"] == ["xml"]


def test_pubmed_provider_skips_fetch_when_search_has_no_ids() -> None:
    captured_urls: list[str] = []

    def fetcher(url: str, headers: dict[str, str]) -> str:
        del headers
        captured_urls.append(url)
        return "<eSearchResult><IdList /></eSearchResult>"

    provider = PubMedProvider(fetcher=fetcher)

    assert provider.search(SearchQuery(query="no matches", limit=5)) == []
    assert len(captured_urls) == 1


class TestFetchWithRetry:
    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    def test_success_on_first_try(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"hello")
        result = _fetch_with_retry(
            "https://example.com",
            {},
            lambda data: data.decode("utf-8"),
            max_retries=0,
            base_backoff=0,
        )
        assert result == "hello"
        assert mock_urlopen.call_count == 1

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    @patch("research_harness.paper_source_clients.time.sleep")
    def test_retries_on_429(self, mock_sleep, mock_urlopen):
        # First call: 429, second call: success
        resp_ok = BytesIO(b'{"ok": true}')
        resp_ok.read = resp_ok.read
        mock_urlopen.side_effect = [
            urllib.error.HTTPError(
                "http://x", 429, "rate limited", http.client.HTTPMessage(), BytesIO(b"")
            ),
            _mock_response(b'{"ok": true}'),
        ]

        result = _fetch_with_retry(
            "http://x",
            {},
            lambda d: d.decode(),
            max_retries=2,
            base_backoff=0.01,
        )
        assert result == '{"ok": true}'
        assert mock_sleep.call_count == 1

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    def test_raises_on_non_retryable_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://x",
            404,
            "not found",
            http.client.HTTPMessage(),
            BytesIO(b""),
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch_with_retry(
                "http://x", {}, lambda d: d, max_retries=2, base_backoff=0.01
            )
        assert exc_info.value.code == 404

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    @patch("research_harness.paper_source_clients.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = [
            urllib.error.HTTPError(
                "http://x", 503, "unavailable", http.client.HTTPMessage(), BytesIO(b"")
            )
            for _ in range(4)
        ]
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _fetch_with_retry(
                "http://x", {}, lambda d: d, max_retries=3, base_backoff=0.01
            )
        assert exc_info.value.code == 503
        assert mock_sleep.call_count == 3

    @patch("research_harness.paper_source_clients.urllib.request.urlopen")
    @patch("research_harness.paper_source_clients.time.sleep")
    def test_post_request_with_data(self, mock_sleep, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b'{"result": "ok"}')
        result = _fetch_with_retry(
            "http://x",
            {"Content-Type": "application/json"},
            lambda d: d.decode(),
            data=b'{"q": "test"}',
            method="POST",
        )
        assert result == '{"result": "ok"}'
        req = mock_urlopen.call_args[0][0]
        assert req.data == b'{"q": "test"}'
        assert req.method == "POST"


class TestParseRetryAfter:
    def test_numeric_retry_after(self):
        exc = _make_http_error(429, retry_after="5")
        assert _parse_retry_after(exc, 1.0) == 5.0

    def test_missing_retry_after_returns_default(self):
        exc = _make_http_error(429)
        assert _parse_retry_after(exc, 2.5) == 2.5

    def test_invalid_retry_after_returns_default(self):
        exc = _make_http_error(429, retry_after="Wed, 21 Oct 2025 07:28:00 GMT")
        assert _parse_retry_after(exc, 3.0) == 3.0

    def test_zero_retry_after_clamps_to_minimum(self):
        exc = _make_http_error(429, retry_after="0")
        assert _parse_retry_after(exc, 1.0) == 0.5


def _mock_response(data: bytes):
    """Create a mock HTTP response context manager."""

    class _Resp:
        def read(self):
            return data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    return _Resp()


def _make_http_error(
    code: int, retry_after: str | None = None
) -> urllib.error.HTTPError:
    headers = http.client.HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "error", headers, BytesIO(b""))


# ---------------------------------------------------------------------------
# OpenAlex resolve_doi
# ---------------------------------------------------------------------------


class TestOpenAlexResolveDoi:
    def test_resolve_doi_returns_id(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()

        def fake_fetch(url, headers):
            return {"id": "https://openalex.org/W1234567"}

        with patch.object(oa, "_fetch_json", side_effect=fake_fetch):
            result = oa.resolve_doi("10.1234/test")
        assert result == "W1234567"

    def test_resolve_doi_strips_prefix(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()

        captured = {}

        def fake_fetch(url, headers):
            captured["url"] = url
            return {"id": "https://openalex.org/W999"}

        with patch.object(oa, "_fetch_json", side_effect=fake_fetch):
            result = oa.resolve_doi("https://doi.org/10.1234/test")
        assert result == "W999"
        assert "doi:10.1234/test" in captured["url"]

    def test_resolve_doi_returns_none_on_error(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()

        with patch.object(oa, "_fetch_json", side_effect=Exception("network")):
            assert oa.resolve_doi("10.1234/broken") is None

    def test_resolve_doi_returns_none_for_empty(self):
        from research_harness.paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()
        assert oa.resolve_doi("") is None
