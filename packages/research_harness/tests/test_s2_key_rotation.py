"""Semantic Scholar key pool (owner report 2026-09-26: frequent 429s with several keys configured).

S2 allows 1 request/s per API key. Each key was paced at 0.15 s, and a 429 on one key failed the
request while the other keys sat idle."""

import io
import urllib.error
import urllib.parse

import pytest

import research_harness.paper_source_clients as psc
from research_harness.key_pool import KeyPool
from research_harness.paper_source_clients import SearchQuery, SemanticScholarProvider


def _provider(monkeypatch, limited, keys=("k1", "k2", "k3")):
    paced, seen = [], []
    monkeypatch.setattr(
        psc, "pace", lambda name, interval: paced.append((name, interval))
    )

    def fetch(url, headers):
        key = headers.get("x-api-key", "")
        seen.append(key)
        if key in limited:
            raise urllib.error.HTTPError(
                url, 429, "Too Many Requests", {}, io.BytesIO(b"")
            )
        return {"data": []}

    provider = SemanticScholarProvider(
        key_pool=KeyPool(name="s2-test", keys=keys), fetcher=fetch
    )
    return provider, paced, seen


def test_a_429_on_one_key_is_retried_on_the_next_live_key(monkeypatch):
    provider, paced, seen = _provider(monkeypatch, limited={"k1"})
    assert provider.search(SearchQuery(query="q", limit=5)) == []
    assert seen == ["k1", "k2"]
    assert provider._pool.available_count() == 2  # k1 cools down
    assert len({name for name, _ in paced}) == 2 and all(
        interval == 1.05 for _, interval in paced
    )


def test_the_request_fails_only_when_every_key_is_limited(monkeypatch):
    provider, _, seen = _provider(monkeypatch, limited={"k1", "k2", "k3"})
    with pytest.raises(urllib.error.HTTPError):
        provider.search(SearchQuery(query="q", limit=5))
    assert sorted(seen) == ["k1", "k2", "k3"]


def test_a_single_key_is_not_retried_on_itself(monkeypatch):
    provider, _, seen = _provider(monkeypatch, limited={"k1"}, keys=("k1",))
    with pytest.raises(urllib.error.HTTPError):
        provider.search(SearchQuery(query="q", limit=5))
    assert seen == ["k1"]


def test_each_key_is_paced_at_the_documented_one_request_per_second(monkeypatch):
    provider, _, _ = _provider(monkeypatch, limited=set())
    assert provider._min_interval >= 1.0


def test_openalex_retries_a_limited_key_on_the_next_one(monkeypatch):
    from research_harness.paper_source_clients import OpenAlexProvider

    seen = []

    def fetch(url, headers):
        key = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(
            "api_key", [""]
        )[0]
        seen.append(key)
        if key == "a1":
            raise urllib.error.HTTPError(
                url, 429, "Too Many Requests", {}, io.BytesIO(b"")
            )
        return {"results": []}

    provider = OpenAlexProvider(
        key_pool=KeyPool(name="oa-test", keys=("a1", "a2")), fetcher=fetch
    )
    monkeypatch.setattr(
        provider, "_fetch_json", lambda url, headers: fetch(url, headers)
    )
    assert provider.search(SearchQuery(query="q", limit=5)) == []
    assert seen == ["a1", "a2"]
    both = OpenAlexProvider(
        key_pool=KeyPool(name="oa-test2", keys=("a1",)), fetcher=fetch
    )
    monkeypatch.setattr(both, "_fetch_json", lambda url, headers: fetch(url, headers))
    with pytest.raises(urllib.error.HTTPError):
        both.search(SearchQuery(query="q", limit=5))


def test_openreview_search_sends_term():
    """spine-lumbar (ISSUE 2026-09-26): api2 answers `query=` with 400 on every request."""
    from research_harness.paper_source_clients import OpenReviewProvider

    seen = []

    def fetch(url, headers):
        seen.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
        return {
            "notes": [
                {
                    "id": "x",
                    "forum": "x",
                    "content": {"title": {"value": "A lumbar paper"}},
                }
            ]
        }

    provider = OpenReviewProvider(fetcher=fetch)
    provider._fetch_json = lambda url, headers: fetch(url, headers)
    records = provider.search(SearchQuery(query="lumbar spine segmentation", limit=3))
    assert seen[0]["term"] == ["lumbar spine segmentation"] and "query" not in seen[0]
    assert records and records[0].title == "A lumbar paper"
