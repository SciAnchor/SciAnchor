"""Tests for panorama code+industry collectors (GitHub patrol, blog snapshots).

Zero network / zero subprocess: the ``gh`` runner and the feed fetcher are
injected fakes, and ``now`` is pinned so L0 date directories are deterministic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from research_harness.panorama import PanoramaStore
from research_harness.panorama.collectors import (
    DEFAULT_BLOG_WHITELIST,
    DEFAULT_GITHUB_QUERIES,
    patrol_github,
    snapshot_blogs,
)

FIXED_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
DATE_DIR = "2026-08-01"


@pytest.fixture
def store(tmp_path):
    s = PanoramaStore(tmp_path / "panorama")
    s.init()
    return s


@pytest.fixture
def direction_id(store):
    return store.get_or_create_direction("test-dir", "Test Direction")


# -- fixtures builders -----------------------------------------------------


def _repo(full_name: str, stars: int, **extra) -> dict:
    item = {
        "full_name": full_name,
        "stargazers_count": stars,
        "description": f"Description of {full_name}",
        "html_url": f"https://github.com/{full_name}",
        "pushed_at": "2026-07-30T00:00:00Z",
        "language": "Python",
        "topics": ["ai", "agents"],
    }
    item.update(extra)
    return item


def _gh_response(repos: list[dict]) -> str:
    return json.dumps({"total_count": len(repos), "items": repos})


RSS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Acme Blog</title>
    <item>
      <title>Introducing our research agent</title>
      <link>https://acme.test/research-agent</link>
      <pubDate>Fri, 31 Jul 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Company picnic recap</title>
      <link>https://acme.test/picnic</link>
      <pubDate>Thu, 30 Jul 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Beta Feed</title>
  <entry>
    <title>New benchmark for automated science</title>
    <link rel="alternate" href="https://beta.test/benchmark"/>
    <updated>2026-07-29T00:00:00Z</updated>
  </entry>
  <entry>
    <title>Office relocation notice</title>
    <link href="https://beta.test/office"/>
    <updated>2026-07-28T00:00:00Z</updated>
  </entry>
</feed>
"""


# -- defaults --------------------------------------------------------------


def test_default_constants_shape():
    assert "ai-scientist" in DEFAULT_GITHUB_QUERIES
    assert len(DEFAULT_GITHUB_QUERIES) == 6
    assert len(DEFAULT_BLOG_WHITELIST) == 6
    for entry in DEFAULT_BLOG_WHITELIST:
        assert entry["org"]
        assert entry["feed_url"].startswith("https://")
        assert entry["kind"] in ("rss", "atom")


# -- github patrol ---------------------------------------------------------


def test_patrol_github_upserts_filters_and_snapshots(store, direction_id):
    calls: list[list[str]] = []

    def runner(args: list[str]) -> str:
        calls.append(args)
        return _gh_response(
            [_repo("acme/ai-scientist", 120), _repo("someone/tiny-fork", 2)]
        )

    result = patrol_github(
        store,
        direction_id,
        queries=["ai-scientist"],
        per_query_limit=15,
        runner=runner,
        min_stars=5,
        now=FIXED_NOW,
    )
    assert result["errors"] == []
    assert result["queries_ok"] == 1
    assert result["repos_upserted"] == 1

    # gh invocation shape
    assert calls == [
        [
            "gh",
            "api",
            "search/repositories?q=ai-scientist&sort=stars&order=desc&per_page=15",
        ]
    ]

    # min_stars filter: only the starred repo becomes an entity
    repos = store.entities(direction_id, kind="code_repo")
    assert [e["name"] for e in repos] == ["acme/ai-scientist"]
    entity = repos[0]
    assert entity["summary"] == "Description of acme/ai-scientist"
    assert entity["ext_ids"] == {"github": "acme/ai-scientist"}
    assert entity["attrs"]["url"] == "https://github.com/acme/ai-scientist"
    assert entity["attrs"]["stars"] == 120
    assert entity["attrs"]["language"] == "Python"
    assert entity["attrs"]["topics"] == ["ai", "agents"]
    assert entity["source"] == "collector:github"

    # harvest run recorded with matched entity
    runs = store.harvest_runs(direction_id)
    assert len(runs) == 1
    assert runs[0]["source"] == "github"
    assert runs[0]["query"] == "ai-scientist"
    assert runs[0]["result_count"] == 1
    assert runs[0]["new_count"] == 1
    matrix = store.capture_matrix(direction_id)
    assert matrix == {"github:acme/ai-scientist": {"github"}}

    # L0 snapshot + meta contract
    snap = store.l0_dir / "github" / DATE_DIR / "ai-scientist.json"
    assert snap.exists()
    payload = snap.read_bytes()
    assert json.loads(payload)["total_count"] == 2
    meta = json.loads((snap.parent / "ai-scientist.meta.json").read_text())
    assert meta["sha256"] == hashlib.sha256(payload).hexdigest()
    assert meta["source_url"] == (
        "search/repositories?q=ai-scientist&sort=stars&order=desc&per_page=15"
    )
    assert meta["fetched_at"] == FIXED_NOW.isoformat()


def test_patrol_github_topics_truncated_to_eight(store, direction_id):
    def runner(args: list[str]) -> str:
        return _gh_response([_repo("a/b", 50, topics=[f"t{i}" for i in range(12)])])

    patrol_github(store, direction_id, queries=["q"], runner=runner, now=FIXED_NOW)
    (entity,) = store.entities(direction_id, kind="code_repo")
    assert entity["attrs"]["topics"] == [f"t{i}" for i in range(8)]


def test_patrol_github_query_failure_contained(store, direction_id):
    def runner(args: list[str]) -> str:
        if "bad+query" in args[-1]:
            raise RuntimeError("gh exploded")
        return _gh_response([_repo("good/repo", 30)])

    result = patrol_github(
        store,
        direction_id,
        queries=["bad query", "good query"],
        runner=runner,
        now=FIXED_NOW,
    )
    assert result["queries"] == 2
    assert result["queries_ok"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("bad query:")
    assert [e["name"] for e in store.entities(direction_id, kind="code_repo")] == [
        "good/repo"
    ]
    # only the successful query produced a harvest run
    assert [r["query"] for r in store.harvest_runs(direction_id)] == ["good query"]


def test_patrol_github_idempotent_second_run(store, direction_id):
    def runner(args: list[str]) -> str:
        return _gh_response([_repo("acme/ai-scientist", 120)])

    first = patrol_github(
        store, direction_id, queries=["ai-scientist"], runner=runner, now=FIXED_NOW
    )
    second = patrol_github(
        store, direction_id, queries=["ai-scientist"], runner=runner, now=FIXED_NOW
    )
    assert first["errors"] == second["errors"] == []
    assert len(store.entities(direction_id, kind="code_repo")) == 1
    runs = store.harvest_runs(direction_id)
    assert len(runs) == 2
    assert runs[0]["new_count"] == 1
    assert runs[1]["new_count"] == 0  # nothing marginal on the recapture


# -- blog snapshots --------------------------------------------------------


def test_snapshot_blogs_rss_and_atom(store, direction_id):
    whitelist = [
        {"org": "Acme", "feed_url": "https://acme.test/rss.xml", "kind": "rss"},
        {"org": "Beta Labs", "feed_url": "https://beta.test/atom.xml", "kind": "atom"},
    ]
    feeds = {
        "https://acme.test/rss.xml": RSS_FEED,
        "https://beta.test/atom.xml": ATOM_FEED,
    }

    result = snapshot_blogs(
        store,
        direction_id,
        whitelist=whitelist,
        fetcher=lambda url: feeds[url],
        now=FIXED_NOW,
    )
    assert result["errors"] == []
    assert result["feeds_ok"] == 2
    assert result["docs_upserted"] == 2  # keyword filter drops picnic + office

    docs = store.entities(direction_id, kind="industry_doc")
    names = {e["name"] for e in docs}
    assert names == {
        "Acme: Introducing our research agent",
        "Beta Labs: New benchmark for automated science",
    }
    by_name = {e["name"]: e for e in docs}
    rss_doc = by_name["Acme: Introducing our research agent"]
    assert rss_doc["ext_ids"] == {"url": "https://acme.test/research-agent"}
    assert rss_doc["attrs"]["org"] == "Acme"
    assert rss_doc["attrs"]["published"] == "Fri, 31 Jul 2026 10:00:00 GMT"
    assert rss_doc["source"] == "collector:blog"
    atom_doc = by_name["Beta Labs: New benchmark for automated science"]
    assert atom_doc["attrs"]["url"] == "https://beta.test/benchmark"
    assert atom_doc["attrs"]["published"] == "2026-07-29T00:00:00Z"

    # anchors carry title + link + fetched_at
    (anchor,) = store.anchors_for("entity", rss_doc["id"])
    assert anchor["summary"] == "Introducing our research agent"
    assert anchor["source_ref"] == "https://acme.test/research-agent"
    assert anchor["fetched_at"] == FIXED_NOW.isoformat()

    # L0 snapshots + meta contract
    for org_slug, url, payload in [
        ("acme", "https://acme.test/rss.xml", RSS_FEED),
        ("beta-labs", "https://beta.test/atom.xml", ATOM_FEED),
    ]:
        snap = store.l0_dir / "blogs" / DATE_DIR / f"{org_slug}.xml"
        assert snap.read_bytes() == payload
        meta = json.loads((snap.parent / f"{org_slug}.meta.json").read_text())
        assert meta["sha256"] == hashlib.sha256(payload).hexdigest()
        assert meta["source_url"] == url
        assert meta["fetched_at"] == FIXED_NOW.isoformat()


def test_snapshot_blogs_keyword_filter(store, direction_id):
    whitelist = [
        {"org": "Acme", "feed_url": "https://acme.test/rss.xml", "kind": "rss"}
    ]
    result = snapshot_blogs(
        store,
        direction_id,
        whitelist=whitelist,
        fetcher=lambda url: RSS_FEED,
        keywords=["picnic"],
        now=FIXED_NOW,
    )
    assert result["docs_upserted"] == 1
    (doc,) = store.entities(direction_id, kind="industry_doc")
    assert doc["name"] == "Acme: Company picnic recap"


def test_snapshot_blogs_feed_failure_contained(store, direction_id):
    whitelist = [
        {"org": "Dead", "feed_url": "https://dead.test/rss.xml", "kind": "rss"},
        {"org": "Acme", "feed_url": "https://acme.test/rss.xml", "kind": "rss"},
    ]

    def fetcher(url: str) -> bytes:
        if "dead" in url:
            raise OSError("connection refused")
        return RSS_FEED

    result = snapshot_blogs(
        store, direction_id, whitelist=whitelist, fetcher=fetcher, now=FIXED_NOW
    )
    assert result["feeds"] == 2
    assert result["feeds_ok"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("Dead:")
    # the healthy feed still produced its entity and snapshot
    assert len(store.entities(direction_id, kind="industry_doc")) == 1
    assert (store.l0_dir / "blogs" / DATE_DIR / "acme.xml").exists()
    assert not (store.l0_dir / "blogs" / DATE_DIR / "dead.xml").exists()


def test_snapshot_blogs_idempotent_second_run(store, direction_id):
    whitelist = [
        {"org": "Acme", "feed_url": "https://acme.test/rss.xml", "kind": "rss"}
    ]
    kwargs = dict(whitelist=whitelist, fetcher=lambda url: RSS_FEED, now=FIXED_NOW)
    first = snapshot_blogs(store, direction_id, **kwargs)
    second = snapshot_blogs(store, direction_id, **kwargs)
    assert first["errors"] == second["errors"] == []
    docs = store.entities(direction_id, kind="industry_doc")
    assert len(docs) == 1  # no duplicate entities
    assert second["anchors_added"] == 0  # no duplicate anchors either
    assert len(store.anchors_for("entity", docs[0]["id"])) == 1


def test_snapshot_blogs_malformed_xml_contained(store, direction_id):
    whitelist = [
        {"org": "Bad XML", "feed_url": "https://bad.test/rss.xml", "kind": "rss"}
    ]
    result = snapshot_blogs(
        store,
        direction_id,
        whitelist=whitelist,
        fetcher=lambda url: b"<rss><channel><item>",
        now=FIXED_NOW,
    )
    assert result["feeds_ok"] == 0
    assert len(result["errors"]) == 1
    assert store.entities(direction_id, kind="industry_doc") == []
