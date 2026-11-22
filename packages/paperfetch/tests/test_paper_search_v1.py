from argparse import Namespace
import asyncio

import pytest

from paperfetch.cli.paper_v1 import build_paper_search_result
from paperfetch.cli.root import _main
from paperfetch.core.contracts_v1 import BusinessStatus
from paperfetch.papers.search import PaperSearchEngine, SearchCandidate, SearchPage


class _FakeEngine:
    async def search(self, **kwargs):
        return SearchPage(
            candidates=[
                SearchCandidate(
                    title="Example paper",
                    doi="10.1000/example",
                    pubmed_id=None,
                    pmc_id=None,
                    arxiv_id=None,
                    year=2024,
                    venue="Example Venue",
                    publisher="Example",
                    citation_count=12,
                    sources=("openalex",),
                    ccf_rank="A",
                    cas_zone=1,
                )
            ],
            source_errors={},
        )


@pytest.mark.asyncio
async def test_paper_search_is_read_only_command_result(monkeypatch):
    monkeypatch.setattr(
        "paperfetch.papers.search.PaperSearchEngine", lambda: _FakeEngine()
    )
    result = await build_paper_search_result(
        Namespace(
            query="urban climate",
            limit=10,
            min_year=2020,
            ccf_rank=None,
            cas_zone=None,
            min_citations=0,
        )
    )
    assert result.command == "paper.search"
    assert result.schema_version == "spc.command-result.v1"
    assert result.metrics["result_count"] == 1
    assert "seed_pack_saved_count" not in result.metrics
    assert result.items[0].data["doi"] == "10.1000/example"


@pytest.mark.asyncio
async def test_paper_search_cas_zone_filter_requires_configured_journal_master(
    monkeypatch,
):
    from paperfetch.core.settings import reset_settings

    monkeypatch.delenv("SPC_JOURNAL_MASTER_DB", raising=False)
    reset_settings()

    def _must_not_search():
        raise AssertionError("search must not run when CAS data is not configured")

    monkeypatch.setattr("paperfetch.papers.search.PaperSearchEngine", _must_not_search)
    result = await build_paper_search_result(
        Namespace(
            query="urban climate",
            limit=10,
            min_year=None,
            ccf_rank=None,
            cas_zone="1,2",
            min_citations=0,
        )
    )
    assert result.status == BusinessStatus.REJECTED
    assert result.error.code == "cas_zone_not_configured"
    assert "SPC_JOURNAL_MASTER_DB" in result.error.remediation


def test_paper_search_help_does_not_offer_auto_add():
    try:
        _main(["paper", "search", "--help"])
    except SystemExit as exc:
        assert exc.code == 0


@pytest.mark.asyncio
async def test_paper_search_fails_when_all_sources_error(monkeypatch):
    class _FailingEngine:
        async def search(self, **kwargs):
            return SearchPage(
                candidates=[], source_errors={"openalex": "TimeoutError: x"}
            )

    monkeypatch.setattr(
        "paperfetch.papers.search.PaperSearchEngine", lambda: _FailingEngine()
    )
    result = await build_paper_search_result(
        Namespace(
            query="urban climate",
            limit=10,
            min_year=None,
            ccf_rank=None,
            cas_zone=None,
            min_citations=0,
        )
    )
    assert result.status == BusinessStatus.FAILED
    assert result.error.code == "metadata_sources_failed"
    assert "openalex" in result.error.message
    assert result.metrics["source_error_count"] == 1


@pytest.mark.asyncio
async def test_engine_search_runs_sources_concurrently(monkeypatch):
    seen: list[str] = []
    gate = asyncio.Event()

    class _Client:
        async def aclose(self):
            return None

    class _GateSource:
        source_name = "openalex"

        def __init__(self, *_args, **_kwargs):
            return None

        async def search(self, **_kwargs):
            seen.append(self.source_name)
            if len(seen) < 3:
                await gate.wait()
            else:
                gate.set()
            if False:
                yield None

    class _OpenAlex(_GateSource):
        source_name = "openalex"

    class _S2(_GateSource):
        source_name = "semantic_scholar"

    class _PubMed(_GateSource):
        source_name = "pubmed"

    monkeypatch.setattr(
        "paperfetch.papers.search.create_metadata_client", lambda: _Client()
    )
    monkeypatch.setattr("paperfetch.papers.search.OpenAlexSource", _OpenAlex)
    monkeypatch.setattr("paperfetch.papers.search.SemanticScholarSource", _S2)
    monkeypatch.setattr("paperfetch.papers.search.PubMedSource", _PubMed)

    page = await asyncio.wait_for(
        PaperSearchEngine().search(query="climate", limit=3),
        timeout=2,
    )
    assert page.candidates == []
    assert set(seen) == {"openalex", "semantic_scholar", "pubmed"}


@pytest.mark.asyncio
async def test_a_rate_limited_source_cannot_hold_the_search(monkeypatch):
    from paperfetch.core.models import PaperRecord

    class _Client:
        async def aclose(self):
            return None

    class _OpenAlex:
        source_name = "openalex"

        def __init__(self, *_args, **_kwargs):
            return None

        async def search(self, **_kwargs):
            yield PaperRecord(
                paper_id="openalex:answered",
                title="Answered paper",
                doi="10.1000/answered",
                year=2025,
            )

    class _S2(_OpenAlex):
        source_name = "semantic_scholar"

        async def search(self, **_kwargs):
            await asyncio.Event().wait()  # 429 cooldown that never ends
            yield None

    class _PubMed(_OpenAlex):
        source_name = "pubmed"

        async def search(self, **_kwargs):
            if False:
                yield None

    monkeypatch.setenv("SPC_SEARCH_SOURCE_DEADLINE_SECONDS", "1")
    monkeypatch.setattr(
        "paperfetch.papers.search.create_metadata_client", lambda: _Client()
    )
    monkeypatch.setattr("paperfetch.papers.search.OpenAlexSource", _OpenAlex)
    monkeypatch.setattr("paperfetch.papers.search.SemanticScholarSource", _S2)
    monkeypatch.setattr("paperfetch.papers.search.PubMedSource", _PubMed)

    page = await asyncio.wait_for(
        PaperSearchEngine().search(query="climate", limit=3), timeout=5
    )
    assert [candidate.title for candidate in page.candidates] == ["Answered paper"], (
        page.source_errors
    )
    assert set(page.source_errors) == {"semantic_scholar"}
    assert "TimeoutError" in page.source_errors["semantic_scholar"]


def test_retired_commands_are_gone():
    for command in (
        ["curate", "--help"],
        ["init-brief", "--help"],
        ["validate-brief", "--help"],
        ["add-seed-papers", "--help"],
        ["enrich-seed-pack", "--help"],
        ["import-agent-reviews", "--help"],
        ["paper", "search", "--add-to-seed-pack", "x"],
    ):
        try:
            code = _main(command)
        except SystemExit as exc:
            code = exc.code
        assert code != 0


def test_source_error_redacts_provider_key():
    from paperfetch.papers.search import _redact

    message = "HTTPStatusError: 400 for url 'https://api.openalex.org/works?filter=x&api_key=SECRET123&per_page=1'"
    assert "SECRET123" not in _redact(message) and "api_key=<redacted>" in _redact(
        message
    )


@pytest.mark.asyncio
async def test_openalex_filter_drops_commas_from_the_query():
    from paperfetch.sources.openalex import OpenAlexSource

    seen = {}

    class _Source(OpenAlexSource):
        def __init__(self):
            self.base_url = "https://api.openalex.org"

        def _get_headers_and_params(self, params):
            return {}, dict(params)

        async def _cached_json(self, *, params, **_kwargs):
            seen["filter"] = params["filter"]
            return 200, {"results": []}

    async for _ in _Source().search("a hard, time gate: no score", limit=5):
        pass
    assert "," not in seen["filter"].split("title_and_abstract.search:", 1)[1]
