"""Tests for the panorama academic harvest module.

All source clients are exercised through fake fetchers with canned payloads;
no test touches the network.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error

import pytest

from research_harness.panorama import PanoramaStore
from research_harness.panorama.harvest import (
    DEFAULT_QUERIES,
    DEFAULT_TRIAGE_KEYWORDS,
    canonical_identity,
    default_source_fetchers,
    harvest_academic,
    make_fetcher,
    record_external_source,
    search_arxiv,
    search_openalex,
    search_s2,
)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)


@pytest.fixture
def store(tmp_path):
    s = PanoramaStore(tmp_path / "panorama")
    s.init()
    return s


@pytest.fixture
def direction_id(store):
    return store.get_or_create_direction("automated-research", "Automated Research")


# -- canned payloads -------------------------------------------------------

_OPENALEX_PAYLOAD = json.dumps(
    {
        "results": [
            {
                "id": "https://openalex.org/W1111",
                "display_name": "The AI Scientist: Fully Automated Discovery",
                "publication_year": 2024,
                "doi": "https://doi.org/10.48550/ARXIV.2408.06292",
                "ids": {"openalex": "https://openalex.org/W1111"},
                "abstract_inverted_index": {
                    "agents": [2],
                    "Research": [0],
                    "automate": [1],
                    "discovery.": [3],
                },
                "primary_location": {
                    "landing_page_url": "https://arxiv.org/abs/2408.06292v2",
                    "source": {"display_name": "arXiv"},
                },
            },
            {
                "id": "https://openalex.org/W2222",
                "display_name": "Protein folding dynamics",
                "publication_year": 2020,
                "ids": {"openalex": "https://openalex.org/W2222"},
                "abstract_inverted_index": None,
                "primary_location": {
                    "landing_page_url": "https://example.org/x",
                    "source": {"display_name": "Nature"},
                },
                "locations": [{"pdf_url": None}],
            },
        ]
    }
).encode()

_S2_PAYLOAD = json.dumps(
    {
        "total": 2,
        "data": [
            {
                "paperId": "abc123",
                "title": "ResearchAgent: Iterative Research Idea Generation",
                "abstract": "A research agent for hypothesis generation.",
                "year": 2024,
                "venue": "NAACL",
                "externalIds": {"ArXiv": "2404.07738v1", "DOI": "10.1000/XYZ"},
            },
            {
                "paperId": "def456",
                "title": "Quantum error correction",
                "abstract": None,
                "year": 2023,
                "venue": "",
                "externalIds": {},
            },
        ],
    }
).encode()

_ARXIV_PAYLOAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2408.06292v2</id>
    <title>The AI Scientist: Towards Fully Automated
      Open-Ended Scientific Discovery</title>
    <summary>We present a framework for automated scientific discovery.</summary>
    <published>2024-08-12T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1701.00001v1</id>
    <title>Deep learning for cats</title>
    <summary>Cats and only cats.</summary>
    <published>2017-01-01T00:00:00Z</published>
  </entry>
</feed>
"""


def _fetcher_for(mapping):
    """URL-substring-dispatching fake fetcher; records the urls it saw."""
    calls: list[str] = []

    def fetch(url: str, *, timeout: float = 30.0) -> bytes:
        calls.append(url)
        for key, payload in mapping.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected url: {url}")

    fetch.calls = calls
    return fetch


_ALL_SOURCES_FETCHER = {
    "openalex.org": _OPENALEX_PAYLOAD,
    "semanticscholar.org": _S2_PAYLOAD,
    "export.arxiv.org": _ARXIV_PAYLOAD,
}


# -- defaults --------------------------------------------------------------


def test_default_queries_and_keywords():
    assert len(DEFAULT_QUERIES["automated-research"]) == 30
    assert "automated peer review" in DEFAULT_QUERIES["automated-research"]
    # merged in from the expanded panorama query set so the recurring --since sweep
    # covers the same surface as the initial build
    assert "literature-based discovery" in DEFAULT_QUERIES["automated-research"]
    assert len(DEFAULT_TRIAGE_KEYWORDS) == 14
    assert "agentic" in DEFAULT_TRIAGE_KEYWORDS


# -- per-source normalization ----------------------------------------------


def test_openalex_normalization():
    fetch = _fetcher_for({"api.openalex.org": _OPENALEX_PAYLOAD})
    records = search_openalex("ai scientist", 25, fetch)
    assert "per-page=25" in fetch.calls[0]
    assert len(records) == 2
    first = records[0]
    assert first["title"] == "The AI Scientist: Fully Automated Discovery"
    assert first["abstract"] == "Research automate agents discovery."
    assert first["year"] == 2024
    assert first["venue"] == "arXiv"
    assert first["ids"] == {
        "arxiv": "2408.06292",
        "doi": "10.48550/arxiv.2408.06292",
        "openalex": "W1111",
    }
    assert first["url"] == "https://arxiv.org/abs/2408.06292v2"
    second = records[1]
    assert second["abstract"] == ""
    assert second["ids"] == {"openalex": "W2222"}


def test_s2_normalization_with_429_then_success():
    state = {"attempts": 0}

    def fetch(url: str, *, timeout: float = 30.0) -> bytes:
        state["attempts"] += 1
        if state["attempts"] <= 2:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)
        return _S2_PAYLOAD

    records = search_s2("research agent", 25, fetch)
    assert state["attempts"] == 3
    assert len(records) == 2
    first = records[0]
    assert first["ids"] == {
        "arxiv": "2404.07738",
        "doi": "10.1000/xyz",
        "s2": "abc123",
    }
    assert first["year"] == 2024
    assert first["venue"] == "NAACL"
    assert first["url"] == "https://www.semanticscholar.org/paper/abc123"
    assert records[1]["ids"] == {"s2": "def456"}
    assert records[1]["abstract"] == ""


def test_s2_429_exhausts_retries():
    def fetch(url: str, *, timeout: float = 30.0) -> bytes:
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

    with pytest.raises(urllib.error.HTTPError):
        search_s2("research agent", 25, fetch)


def test_arxiv_normalization():
    fetch = _fetcher_for({"export.arxiv.org": _ARXIV_PAYLOAD})
    records = search_arxiv("ai scientist", 25, fetch)
    assert "max_results=25" in fetch.calls[0]
    assert len(records) == 2
    first = records[0]
    assert first["ids"] == {"arxiv": "2408.06292"}
    assert (
        first["title"]
        == "The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery"
    )
    assert first["year"] == 2024
    assert first["url"] == "http://arxiv.org/abs/2408.06292v2"
    assert records[1]["ids"] == {"arxiv": "1701.00001"}


# -- identity --------------------------------------------------------------


def test_canonical_identity_precedence():
    record = {
        "title": "Some Paper",
        "ids": {
            "arxiv": "2408.06292v3",
            "doi": "10.1/X",
            "openalex": "W1",
            "s2": "abc",
        },
    }
    assert canonical_identity(record) == ("arxiv:2408.06292", "arxiv")
    del record["ids"]["arxiv"]
    assert canonical_identity(record) == ("doi:10.1/x", "doi")
    del record["ids"]["doi"]
    assert canonical_identity(record) == ("openalex:W1", "openalex")
    del record["ids"]["openalex"]
    assert canonical_identity(record) == ("s2:abc", "s2")


def test_canonical_identity_title_fallback():
    expected = hashlib.sha1(b"theaiscientist").hexdigest()[:16]
    identity, scheme = canonical_identity({"title": "The  AI-Scientist!", "ids": {}})
    assert scheme == "title"
    assert identity == f"title:{expected}"
    same, _ = canonical_identity({"title": "THE AI SCIENTIST"})
    assert same == identity


def test_canonical_identity_doi_url_normalized():
    identity, scheme = canonical_identity(
        {"title": "t", "ids": {"doi": "https://doi.org/10.1000/XYZ"}}
    )
    assert (identity, scheme) == ("doi:10.1000/xyz", "doi")


# -- harvest_academic ------------------------------------------------------


def test_triage_filter_and_hits(store, direction_id):
    fetch = _fetcher_for({"api.openalex.org": _OPENALEX_PAYLOAD})
    result = harvest_academic(
        store,
        direction_id,
        sources=("openalex",),
        queries=["ai scientist"],
        fetcher=fetch,
    )
    # Only the AI-scientist record passes triage; protein folding does not.
    papers = store.entities(direction_id, kind="paper")
    assert len(papers) == 1
    paper = papers[0]
    assert paper["name"] == "The AI Scientist: Fully Automated Discovery"
    assert paper["source"] == "harvest:openalex"
    assert paper["ext_ids"]["arxiv"] == "2408.06292"
    assert paper["attrs"]["year"] == 2024
    assert paper["attrs"]["abstract"].startswith("Research automate")
    assert result["sources"]["openalex"] == {
        "queries": 1,
        "results": 2,
        "new_identities": 2,
        "imported": 1,
        "errors": [],
    }
    conn = store.connect()
    try:
        rows = conn.execute(
            "SELECT identity, scheme, matched_entity_id, relevance "
            "FROM harvest_hits ORDER BY identity"
        ).fetchall()
    finally:
        conn.close()
    by_identity = {r["identity"]: r for r in rows}
    assert set(by_identity) == {"arxiv:2408.06292", "openalex:W2222"}
    imported_hit = by_identity["arxiv:2408.06292"]
    assert imported_hit["relevance"] == 1.0
    assert imported_hit["matched_entity_id"] == paper["id"]
    rejected_hit = by_identity["openalex:W2222"]
    assert rejected_hit["relevance"] == 0.0
    assert rejected_hit["matched_entity_id"] is None


def test_import_budget_cap(store, direction_id):
    fetch = _fetcher_for(_ALL_SOURCES_FETCHER)
    result = harvest_academic(
        store,
        direction_id,
        sources=("openalex", "s2", "arxiv"),
        queries=["research agent"],
        fetcher=fetch,
        import_budget=1,
    )
    assert result["totals"]["imported"] == 1
    assert result["budget_exhausted"] is True
    assert len(store.entities(direction_id, kind="paper")) == 1
    # The denied-but-relevant s2 record is still logged as a hit, unmatched.
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT matched_entity_id, relevance FROM harvest_hits "
            "WHERE identity = 'arxiv:2404.07738'"
        ).fetchone()
    finally:
        conn.close()
    assert row["relevance"] == 1.0
    assert row["matched_entity_id"] is None


def test_two_rounds_overlap_counted_once(store, direction_id):
    fetch = _fetcher_for(_ALL_SOURCES_FETCHER)
    kwargs = dict(
        sources=("openalex", "arxiv"),
        queries=["ai scientist"],
        fetcher=fetch,
    )
    round1 = harvest_academic(store, direction_id, round_no=1, **kwargs)
    # openalex sees 2 identities (both new); arxiv re-sees the AI-scientist
    # paper (overlap, not new) plus one new cats paper.
    assert round1["sources"]["openalex"]["new_identities"] == 2
    assert round1["sources"]["arxiv"]["new_identities"] == 1
    assert round1["totals"]["new_identities"] == 3
    # AI scientist imported once (openalex); arxiv copy dedupes; cats fails triage.
    assert round1["totals"]["imported"] == 1
    matrix = store.capture_matrix(direction_id)
    assert matrix["arxiv:2408.06292"] == {"openalex", "arxiv"}
    assert matrix["openalex:W2222"] == {"openalex"}

    round2 = harvest_academic(store, direction_id, round_no=2, **kwargs)
    assert round2["totals"]["new_identities"] == 0
    assert round2["totals"]["imported"] == 0
    runs = store.harvest_runs(direction_id)
    assert [(r["round"], r["new_count"]) for r in runs] == [
        (1, 2),
        (1, 1),
        (2, 0),
        (2, 0),
    ]
    # Round-2 hits resolve to the entities imported in round 1.
    paper_ids = {p["id"] for p in store.entities(direction_id, kind="paper")}
    conn = store.connect()
    try:
        rows = conn.execute(
            "SELECT h.matched_entity_id FROM harvest_hits h "
            "JOIN harvest_runs r ON r.id = h.run_id "
            "WHERE r.round = 2 AND h.identity = 'arxiv:2408.06292'"
        ).fetchall()
    finally:
        conn.close()
    assert rows and all(r["matched_entity_id"] in paper_ids for r in rows)


def test_round1_imports_ai_scientist_once_across_sources(store, direction_id):
    fetch = _fetcher_for(_ALL_SOURCES_FETCHER)
    result = harvest_academic(
        store,
        direction_id,
        sources=("openalex", "arxiv"),
        queries=["ai scientist"],
        fetcher=fetch,
    )
    # arxiv's copy of the same paper must dedupe onto the openalex import.
    assert result["sources"]["openalex"]["imported"] == 1
    assert result["sources"]["arxiv"]["imported"] == 0
    names = [p["name"] for p in store.entities(direction_id, kind="paper")]
    assert names == ["The AI Scientist: Fully Automated Discovery"]


def test_error_containment(store, direction_id):
    fetch = _fetcher_for(
        {
            "api.openalex.org": b"this is not json",
            "semanticscholar.org": urllib.error.HTTPError(
                "https://api.semanticscholar.org", 500, "boom", None, None
            ),
            "export.arxiv.org": _ARXIV_PAYLOAD,
        }
    )
    result = harvest_academic(
        store,
        direction_id,
        sources=("openalex", "s2", "arxiv", "nosuch"),
        queries=["ai scientist"],
        fetcher=fetch,
    )
    assert len(result["sources"]["openalex"]["errors"]) == 1
    assert result["sources"]["openalex"]["queries"] == 0
    assert len(result["sources"]["s2"]["errors"]) == 1
    assert "500" in result["sources"]["s2"]["errors"][0]["error"]
    assert "unknown source" in result["sources"]["nosuch"]["errors"][0]["error"]
    # arxiv still ran and imported despite the two failing sources.
    assert result["sources"]["arxiv"]["results"] == 2
    assert result["sources"]["arxiv"]["imported"] == 1
    runs = store.harvest_runs(direction_id)
    # Failed sources must leave a harvest_run so coverage can see them (E1).
    by_source = {r["source"]: r for r in runs}
    assert (
        "openalex" in by_source and by_source["openalex"]["attrs"]["status"] == "failed"
    )
    assert "s2" in by_source and by_source["s2"]["attrs"]["status"] == "failed"
    assert "nosuch" in by_source and by_source["nosuch"]["attrs"]["status"] == "failed"
    assert "arxiv" in by_source
    assert len(runs) == 4


def test_default_queries_used_for_slug(store, direction_id):
    fetch = _fetcher_for({"export.arxiv.org": _ARXIV_PAYLOAD})
    result = harvest_academic(
        store,
        direction_id,
        direction_slug="automated-research",
        sources=("arxiv",),
        fetcher=fetch,
    )
    assert result["sources"]["arxiv"]["queries"] == 30
    assert len(store.harvest_runs(direction_id)) == 30


# -- record_external_source ------------------------------------------------


def test_record_external_source(store, direction_id):
    records = [
        {
            "title": "AgentBench for research agents",
            "abstract": "A benchmark for agentic research systems.",
            "year": 2025,
            "venue": "ICLR",
            "ids": {"arxiv": "2501.00001v1"},
            "url": "https://arxiv.org/abs/2501.00001",
        },
        {
            "title": "Bird migration atlas",
            "abstract": "Migration routes of birds.",
            "year": 2019,
            "venue": "",
            "ids": {"doi": "10.5/birds"},
            "url": "",
        },
    ]
    result = record_external_source(
        store, direction_id, "pwc-archive", records, round_no=1
    )
    assert result["source"] == "pwc-archive"
    assert result["query"] == "snapshot"
    assert result["results"] == 2
    assert result["new_identities"] == 2
    assert result["imported"] == 1
    assert result["budget_exhausted"] is False
    papers = store.entities(direction_id, kind="paper")
    assert [p["name"] for p in papers] == ["AgentBench for research agents"]
    assert papers[0]["source"] == "harvest:pwc-archive"
    runs = store.harvest_runs(direction_id)
    assert len(runs) == 1
    assert runs[0]["source"] == "pwc-archive"
    assert runs[0]["query"] == "snapshot"
    assert runs[0]["result_count"] == 2
    assert runs[0]["new_count"] == 2


def test_record_external_source_budget(store, direction_id):
    records = [
        {
            "title": f"Research agent paper {i}",
            "abstract": "agentic",
            "year": 2025,
            "venue": "",
            "ids": {"arxiv": f"2501.0000{i}"},
            "url": "",
        }
        for i in range(5)
    ]
    result = record_external_source(
        store, direction_id, "pwc-archive", records, import_budget=2
    )
    assert result["imported"] == 2
    assert result["budget_exhausted"] is True
    assert len(store.entities(direction_id, kind="paper")) == 2


def test_make_fetcher_injects_headers(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def _fake_urlopen(request, timeout=30.0):
        captured["headers"] = dict(request.headers)
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    fetch = make_fetcher({"x-api-key": "SECRET", "Empty": ""})
    fetch("https://example.org")
    # urllib capitalizes header keys; check case-insensitively.
    keys = {k.lower(): v for k, v in captured["headers"].items()}
    assert keys.get("X-api-key".lower()) == "SECRET"
    assert "empty" not in keys  # blank values dropped
    assert "user-agent" in keys


def test_default_source_fetchers_never_read_keys(monkeypatch):
    """Every harvest source is queried keyless; keys in the environment are ignored."""
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "s2-secret")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEYS", "key-a, key-b")
    monkeypatch.setenv("S2_API_KEY", "s2-secret")
    monkeypatch.setenv("OPENALEX_API_KEY", "oa-secret")
    assert default_source_fetchers() == {}
