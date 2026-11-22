"""RH fallback must never reopen direct scholarly API routes."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from research_harness.paper_source_clients import build_provider_suite
from research_harness.acquisition import spc_bridge


@pytest.mark.parametrize(
    "body",
    [
        {"data": {"title": "Paper"}},
        {"results": [{"data": {"title": "Paper"}}]},
        {"items": [{"data": {"title": "Paper"}}]},
    ],
)
def test_spc_public_and_internal_search_shapes(monkeypatch, body):
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    outputs = iter([{"data": {"version": "2.0.0"}}, {"status": "completed", **body}])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(next(outputs))),
    )
    assert spc_bridge.spc_search("test") == [{"title": "Paper"}]


def test_spc_graph_uses_managed_cli(monkeypatch):
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")

    def run(argv, **kwargs):
        assert argv[:3] == ["/trusted/spc", "paper", "graph"]
        assert argv[argv.index("--doi") + 1] == "10.1234/test"
        assert argv[argv.index("--direction") + 1] == "citations"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "completed",
                    "results": [{"data": {"title": "Citing paper"}}],
                }
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert spc_bridge.spc_graph("10.1234/test", direction="citations") == [
        {"title": "Citing paper"}
    ]


def test_spc_graph_failure_is_not_empty_success(monkeypatch):
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout='{"status":"failed"}'),
    )
    with pytest.raises(spc_bridge.SPCAcquisitionError):
        spc_bridge.spc_graph("10.1234/test", direction="references")


def test_download_uses_spc_and_preserves_identity_check(monkeypatch, tmp_path):
    import asyncio
    from research_harness.acquisition import downloader
    from research_harness.pdf_download import PaperDownloadCandidate

    candidate = PaperDownloadCandidate(paper_id=1, title="Paper", doi="10.1234/test")

    def download(candidate, root):
        path = root / "paper.pdf"
        path.write_bytes(b"%PDF" + b" " * 12000)
        return path

    monkeypatch.setattr(spc_bridge, "spc_download", download)
    monkeypatch.setattr(downloader, "_pdf_identity_failure", lambda *a: "wrong DOI")
    result = asyncio.run(
        downloader.download_single(candidate, tmp_path, asyncio.Semaphore(1))
    )
    assert result.status == "failed"
    assert "identity mismatch" in result.failure_reason
    monkeypatch.setattr(downloader, "_pdf_identity_failure", lambda *a: None)
    result = asyncio.run(
        downloader.download_single(candidate, tmp_path, asyncio.Semaphore(1))
    )
    assert result.status == "success"
    assert result.provider == "spc"
    assert result.path.is_file()


def test_managed_citation_verification_preserves_metadata_conflicts(monkeypatch):
    from research_harness import paper_source_clients
    from research_harness.paper_sources import PaperRecord
    from research_harness.experiment.citation_verifier import (
        CitationInput,
        verify_citation,
    )

    class Provider:
        name = "openalex"

        def search(self, query):
            return [
                PaperRecord(
                    title="Exact title",
                    doi="10.1234/test",
                    authors=["Wrong Author"],
                    year=2024,
                    provider=self.name,
                )
            ]

    monkeypatch.setattr(
        paper_source_clients, "build_provider_suite", lambda **kw: [Provider()]
    )
    result = verify_citation(
        CitationInput(
            title="Exact title",
            doi="10.1234/test",
            authors=["Correct Person"],
            year=2020,
        )
    )
    assert result.status == "partial_match"
    assert {c["field"] for c in result.conflicts} == {"authors", "year"}


def test_enrichment_rejects_wrong_identity(conn, monkeypatch):
    from research_harness.core.paper_pool import PaperPool
    from research_harness import paper_source_clients
    from research_harness.paper_sources import PaperRecord

    conn.execute("INSERT INTO papers (title, doi) VALUES ('Paper', '10.1234/target')")
    paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    class Provider:
        name = "spc"

        def search(self, query):
            return [
                PaperRecord(title="Wrong", doi="10.1234/other", abstract="wrong"),
                PaperRecord(title="Paper", doi="10.1234/target", abstract="verified"),
            ]

    monkeypatch.setattr(
        paper_source_clients, "build_provider_suite", lambda: [Provider()]
    )
    updates = PaperPool(conn).enrich_metadata(paper_id)
    assert updates["abstract"] == "verified"
    assert (
        conn.execute("SELECT doi FROM papers WHERE id=?", (paper_id,)).fetchone()[0]
        == "10.1234/target"
    )


def test_provider_status_matches_the_suite(monkeypatch):
    from research_harness.paper_source_clients import (
        KEYLESS_SOURCES,
        provider_status_report,
    )

    names = {row["name"] for row in provider_status_report()}
    assert names == {"spc", "papervault", *(name for name, _ in KEYLESS_SOURCES)}


def test_lookup_maps_production_citation_fields(monkeypatch):
    from research_harness.paper_source_clients import SPCProvider

    monkeypatch.setattr(
        spc_bridge,
        "spc_lookup",
        lambda *a, **k: {
            "paper": {"doi": "10.1234/test", "pubmed_id": "123"},
            "citation": {
                "title": "Paper",
                "authors": [{"name": "A Person"}],
                "publication_date": "2024-01-01",
                "venue": {"name": "Journal"},
            },
        },
    )
    record = SPCProvider().fetch_by_doi("10.1234/test")
    assert (record.title, record.year, record.venue, record.pmid) == (
        "Paper",
        2024,
        "Journal",
        "123",
    )
    assert record.authors == ["A Person"]


@pytest.mark.parametrize(
    "url",
    [
        "https://doi.org/10.1234/test",
        "https://example.org/article/file?id=10.1234/test&type=printable",
    ],
)
def test_scholarly_url_never_falls_back_to_html(monkeypatch, url):
    from research_harness.acquisition import html_ingest

    calls = []

    def fail(candidate, directory):
        calls.append(candidate.doi)
        raise RuntimeError("managed source unavailable")

    monkeypatch.setattr(spc_bridge, "spc_download", fail)
    monkeypatch.setattr(
        html_ingest.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("direct scholarly HTTP"),
    )
    result = html_ingest.fetch_html_as_markdown(url)
    assert calls == ["10.1234/test"]
    assert not result.ok
    assert "managed acquisition" in result.error


@pytest.mark.parametrize(
    "code,retryable",
    [("metadata_not_resolved", False), ("metadata_transport_failed", True)],
)
def test_lookup_failure_preserves_upstream_class(monkeypatch, code, retryable):
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "status": "failed",
                    "error": {"code": code, "retryable": retryable},
                }
            ),
        ),
    )
    with pytest.raises(spc_bridge.SPCAcquisitionError) as error:
        spc_bridge.spc_lookup("10.1234/test", kind="doi")
    assert error.value.code == code
    assert error.value.retryable is retryable


def test_url_only_download_resolves_exact_title(monkeypatch, tmp_path):
    from research_harness import paper_source_clients
    from research_harness.paper_sources import PaperRecord
    from research_harness.pdf_download import PaperDownloadCandidate

    class Provider:
        name = "openalex"

        def search(self, query):
            return [
                PaperRecord(title="Another paper", doi="10.1234/wrong"),
                PaperRecord(
                    title="Expected paper",
                    doi="10.1234/right",
                    url="https://example.org/article.pdf",
                ),
            ]

    monkeypatch.setattr(
        paper_source_clients, "build_provider_suite", lambda: [Provider()]
    )
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def run(argv, **kwargs):
        assert argv[argv.index("--doi") + 1] == "10.1234/right"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"status": "completed", "files": [{"path": str(pdf), "type": "pdf"}]}
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    candidate = PaperDownloadCandidate(
        paper_id=1, title="Expected paper", url="https://example.org/article.pdf"
    )
    assert spc_bridge.spc_download(candidate, tmp_path) == pdf


def test_same_title_without_version_evidence_is_not_downloaded(monkeypatch, tmp_path):
    from research_harness import paper_source_clients
    from research_harness.paper_sources import PaperRecord
    from research_harness.pdf_download import PaperDownloadCandidate

    class Provider:
        name = "openalex"

        def search(self, query):
            return [
                PaperRecord(
                    title="Expected paper",
                    doi="10.1234/slides",
                    url="https://example.org/slides.pdf",
                )
            ]

    monkeypatch.setattr(
        paper_source_clients, "build_provider_suite", lambda: [Provider()]
    )
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("unbound download")
    )
    candidate = PaperDownloadCandidate(
        paper_id=1, title="Expected paper", url="https://example.org/article.pdf"
    )
    with pytest.raises(spc_bridge.SPCAcquisitionError) as error:
        spc_bridge.spc_download(candidate, tmp_path)
    assert error.value.code == "paper_identity_unresolved"


def test_spc_version_timeout_is_handled(monkeypatch):
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("spc version", 30)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(spc_bridge.SPCAcquisitionError, match="version_probe"):
        spc_bridge.spc_search("test")


def test_shared_search_uses_keyless_public_sources(monkeypatch):
    from research_harness.paper_source_clients import KEYLESS_SOURCES

    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: None)
    names = [provider.name for provider in build_provider_suite()]
    assert set(names) - {"papervault"} == {name for name, _ in KEYLESS_SOURCES}
    assert "spc" not in names  # optional: only when the spc CLI is installed


def test_spc_joins_the_suite_when_installed(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/trusted/spc")
    assert "spc" in [provider.name for provider in build_provider_suite()]


def test_aggregator_reports_an_spc_failure_when_others_answer(monkeypatch):
    from research_harness.paper_sources import (
        PaperRecord,
        SearchAggregator,
        SearchQuery,
    )
    from research_harness.paper_source_clients import SPCProvider

    class Answering:
        name = "openalex"

        def search(self, query):
            return [PaperRecord(title="Public paper", doi="10.1/p", provider=self.name)]

    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: None)
    outcome = SearchAggregator([SPCProvider(), Answering()]).search(
        SearchQuery(query="test")
    )
    assert [r.title for r in outcome.results] == ["Public paper"]
    assert [e.provider for e in outcome.provider_errors] == ["spc"]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "failed", "error": {"code": "rate_limited", "retryable": True}},
        {"status": "completed", "results": []},
    ],
)
def test_spc_failures_and_zero_results_are_not_empty_success(monkeypatch, payload):
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    outputs = iter([{"data": {"version": "2.0.0"}}, payload])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(next(outputs)), returncode=0),
    )
    with pytest.raises(spc_bridge.SPCAcquisitionError):
        spc_bridge.spc_search("test")


def test_shared_aggregator_cannot_hide_spc_failure(monkeypatch):
    from research_harness.paper_sources import SearchAggregator, SearchQuery
    from research_harness.paper_source_clients import SPCProvider

    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: None)
    with pytest.raises(spc_bridge.SPCAcquisitionError, match="unavailable"):
        SearchAggregator([SPCProvider()]).search(SearchQuery(query="test"))


def test_pdf_same_title_wrong_doi_and_arxiv_version_are_rejected(tmp_path):
    from research_harness.acquisition.pdf_audit import audit_pdf_identity

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    for identifiers, text in [
        ({"doi": "10.1234/journal"}, "Exact title DOI 10.1234/slides"),
        ({"doi": "10.1234/abc"}, "Exact title DOI 10.1234/abcdef"),
        ({"pmcid": "PMC123"}, "Exact title PMCID PMC124"),
        ({"arxiv_id": "2401.01234v2"}, "Exact title arXiv:2401.01234v1"),
    ]:
        result = audit_pdf_identity(
            paper_id=1,
            title="Exact title",
            pdf_path=str(pdf),
            text_extractor=lambda _: text,
            **identifiers,
        )
        assert result.status == "suspect"


def test_search_and_ingest_retain_requested_arxiv_version(conn):
    from research_harness.paper_sources import (
        SearchAggregator,
        SearchQuery,
        PaperRecord,
    )
    from research_harness.core.paper_pool import PaperPool
    from research_harness.storage.models import Paper

    class Provider:
        name = "spc"

        def search(self, query):
            return [PaperRecord(title="Versioned paper", arxiv_id="2401.01234v2")]

    record = (
        SearchAggregator([Provider()]).search(SearchQuery(query="version")).results[0]
    )
    assert record.arxiv_id == "2401.01234v2"
    pool = PaperPool(conn)
    paper_id = pool.ingest(Paper(title=record.title, arxiv_id=record.arxiv_id))
    assert (
        conn.execute("SELECT arxiv_id FROM papers WHERE id=?", (paper_id,)).fetchone()[
            0
        ]
        == "2401.01234v2"
    )
    with pytest.raises(ValueError, match="paper_version_conflict"):
        pool.ingest(Paper(title=record.title, arxiv_id="2401.01234v3"))


def test_pdf_reference_doi_is_not_paper_identity(tmp_path):
    from research_harness.acquisition.pdf_audit import audit_pdf_identity

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = audit_pdf_identity(
        paper_id=1,
        title="Exact title",
        doi="10.1234/target",
        pdf_path=str(pdf),
        text_extractor=lambda _: "Exact title\nReferences\n10.1234/target",
    )
    assert result.status == "suspect"


def test_fanout_answers_first_and_spc_is_not_searched(db, monkeypatch):
    from research_harness.primitives import impls
    from research_harness.paper_sources import PaperRecord

    called = []

    def spc(*a, **k):
        called.append(a)
        return []

    class Provider:
        name = "openalex"

        def search(self, query):
            return [
                PaperRecord(
                    title="Adaptive pruning",
                    doi="10.1234/ap",
                    year=2025,
                    provider=self.name,
                )
            ]

    monkeypatch.setattr(spc_bridge, "spc_search", spc)
    monkeypatch.setattr(impls, "build_provider_suite", lambda **kw: [Provider()])
    out = impls.paper_search(db=db, query="a long ticket sentence")
    assert [p.title for p in out.papers] == ["Adaptive pruning"] and not called
    assert "spc" not in out.providers_queried


@pytest.mark.parametrize("spc_failure", [None, "unavailable"])
def test_spc_backs_up_an_empty_fanout(db, monkeypatch, spc_failure):
    from research_harness.primitives import impls

    def spc(*a, errors=None, **k):
        if spc_failure:
            raise spc_bridge.SPCAcquisitionError(
                "search", {"error": {"code": spc_failure}}
            )
        return [{"title": "Fallback paper", "doi": "10.1234/fb", "year": 2024}]

    class Provider:
        name = "openalex"

        def search(self, query):
            return []

    monkeypatch.setattr(spc_bridge, "spc_search", spc)
    monkeypatch.setattr(impls, "build_provider_suite", lambda **kw: [Provider()])
    out = impls.paper_search(db=db, query="a long ticket sentence")
    if (
        spc_failure
    ):  # the fan-out answered (empty); one failed fallback lane is not an outage
        assert out.papers == [] and "spc: unavailable" in out.provider_errors
    else:
        assert [p.title for p in out.papers] == [
            "Fallback paper"
        ] and "spc" in out.providers_queried


@pytest.mark.parametrize("failure", ["unavailable", "no_results", "rate_limited"])
def test_production_search_metadata_citation_and_graph_keep_failure(
    db, monkeypatch, failure
):
    from research_harness.primitives.impls import paper_search, expand_citations
    from research_harness.experiment.citation_verifier import (
        CitationInput,
        verify_citation,
    )
    from research_harness.core.paper_pool import PaperPool
    from research_harness.storage.models import Paper

    def fail(*a, **k):
        raise spc_bridge.SPCAcquisitionError("search", {"error": {"code": failure}})

    # SPC is installed and failing, and no keyless source answers (they are
    # offline in tests): the SPC failure must surface, never an empty success.
    monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: "/trusted/spc")
    monkeypatch.setattr(spc_bridge, "spc_search", fail)
    monkeypatch.setattr(spc_bridge, "spc_graph", fail)
    monkeypatch.setattr(spc_bridge, "spc_lookup", fail)
    conn = db.connect()
    try:
        topic = conn.execute(
            "INSERT INTO topics(name) VALUES ('fault injection')"
        ).lastrowid
        conn.commit()
        pool = PaperPool(conn)
        paper_id = pool.ingest(
            Paper(title="Test paper", doi="10.1234/target"),
            topic_id=topic,
            relevance="high",
        )
        if failure == "no_results":
            # Zero hits is an empty answer, not an outage: search, enrichment and
            # verification report nothing found instead of raising.
            out = paper_search(db=db, query="Test paper")
            assert "spc" in out.providers_queried
            assert not any(e.startswith("spc") for e in out.provider_errors)
            assert pool.enrich_metadata(paper_id) == {}
            verdict = verify_citation(
                CitationInput(title="Test paper", doi="10.1234/target")
            )
            assert verdict.status == "not_found"  # never "hallucinated"
        calls = [
            *(
                []
                if failure == "no_results"
                else [
                    lambda: paper_search(db=db, query="Test paper"),
                    lambda: pool.enrich_metadata(paper_id),
                    lambda: verify_citation(
                        CitationInput(title="Test paper", doi="10.1234/target")
                    ),
                ]
            ),
            lambda: expand_citations(db=db, topic_id=topic, seed_paper_ids=[paper_id]),
        ]
        for call in calls:
            with pytest.raises(spc_bridge.SPCAcquisitionError, match=failure):
                call()
    finally:
        conn.close()


def test_public_acquire_stage_cannot_skip_failed_metadata(db, monkeypatch):
    from research_harness.primitives.impls import paper_acquire
    from research_harness.core.paper_pool import PaperPool
    from research_harness.storage.models import Paper

    def fail(*a, **k):
        raise spc_bridge.SPCAcquisitionError(
            "search", {"error": {"code": "unavailable"}}
        )

    monkeypatch.setattr(PaperPool, "enrich_metadata", fail)
    monkeypatch.setattr(
        "research_harness.acquisition.pipeline.acquire_papers",
        lambda *a, **k: SimpleNamespace(
            total_papers=1, downloaded=0, annotated=0, failed=0, needs_manual=0
        ),
    )
    conn = db.connect()
    try:
        topic = conn.execute(
            "INSERT INTO topics(name) VALUES ('acquire stage failure')"
        ).lastrowid
        conn.commit()
        PaperPool(conn).ingest(
            Paper(title="Paper", doi="10.1234/stage"), topic_id=topic
        )
    finally:
        conn.close()
    with pytest.raises(spc_bridge.SPCAcquisitionError, match="unavailable"):
        paper_acquire(db=db, topic_id=topic)


@pytest.mark.parametrize(
    "code,retryable,calls", [("no_results", False, 1), ("TimeoutExpired", True, 2)]
)
def test_paper_ingest_survives_spc_enrichment_miss(
    db, monkeypatch, code, retryable, calls
):
    from research_harness.primitives.impls import paper_ingest
    from research_harness._core.core.paper_pool import PaperPool

    seen = []

    def enrich(self, paper_id):
        seen.append(paper_id)
        if len(seen) > 1:
            return {}  # the transient failure clears on the retry
        raise spc_bridge.SPCAcquisitionError(
            "search", {"error": {"code": code, "retryable": retryable}}
        )

    monkeypatch.setattr(PaperPool, "enrich_metadata", enrich)
    monkeypatch.setattr("time.sleep", lambda _: None)
    out = paper_ingest(db=db, source="10.1234/empty-batch")
    assert out.paper_id > 0 and len(seen) == calls
