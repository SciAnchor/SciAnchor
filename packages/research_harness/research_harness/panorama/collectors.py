"""Code + industry collectors for the Domain Panorama KB (plan §4).

Two thin collectors for the non-academic realms:

- ``patrol_github``: GitHub repo patrol over a fixed query set (via the ``gh``
  CLI by default; injectable runner for tests) → ``code_repo`` entities plus
  harvest-run bookkeeping for coverage estimation.
- ``snapshot_blogs``: whitelist polling of industry engineering blogs
  (RSS/Atom) → ``industry_doc`` entities with evidence anchors.

Both write raw payload snapshots to the store's L0 directory following the L0
contract: ``L0/<category>/<UTC date>/<name>`` plus a sibling ``.meta.json``
carrying ``{source_url, fetched_at, sha256}``.

Per-source failures are contained and reported in the returned ``errors`` list;
a bad query or unreachable feed never aborts the whole patrol.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import PanoramaStore

Runner = Callable[[list[str]], str]
Fetcher = Callable[[str], bytes]

USER_AGENT = "research-harness-panorama/0.1"
FETCH_TIMEOUT_SECONDS = 30

DEFAULT_GITHUB_QUERIES = [
    "ai-scientist",
    "research-agent llm",
    "automated-scientific-discovery",
    "autonomous research agent",
    "paper-generation llm",
    "ai co-scientist",
]

DEFAULT_BLOG_WHITELIST: list[dict] = [
    {"org": "OpenAI", "feed_url": "https://openai.com/news/rss.xml", "kind": "rss"},
    {
        "org": "Anthropic",
        "feed_url": "https://www.anthropic.com/rss.xml",
        "kind": "rss",
    },
    {
        "org": "DeepMind",
        "feed_url": "https://deepmind.google/blog/rss.xml",
        "kind": "rss",
    },
    {"org": "Sakana AI", "feed_url": "https://sakana.ai/rss.xml", "kind": "rss"},
    {"org": "Ai2", "feed_url": "https://allenai.org/blog/rss.xml", "kind": "rss"},
    {
        "org": "FutureHouse",
        "feed_url": "https://www.futurehouse.org/rss.xml",
        "kind": "rss",
    },
]

DEFAULT_BLOG_KEYWORDS = [
    "research",
    "agent",
    "scientist",
    "science",
    "discovery",
    "benchmark",
    "evaluation",
    "paper",
]


# -- shared helpers --------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return slug or "item"


def _write_snapshot(
    l0_dir: Path,
    category: str,
    name: str,
    payload: bytes,
    source_url: str,
    *,
    fetched_at: datetime | None = None,
) -> Path:
    """Write one L0 snapshot: ``L0/<category>/<UTC date>/<name>`` + meta.

    The sibling ``<stem>.meta.json`` records ``{source_url, fetched_at,
    sha256}`` so any later consumer can verify payload integrity and origin.
    """
    ts = fetched_at or _utcnow()
    path = l0_dir / category / ts.strftime("%Y-%m-%d") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    meta = {
        "source_url": source_url,
        "fetched_at": ts.isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _default_runner(args: list[str]) -> str:
    proc = subprocess.run(args, check=True, capture_output=True, text=True)
    return proc.stdout


def _default_fetcher(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        return resp.read()


# -- github patrol ---------------------------------------------------------


def patrol_github(
    store: PanoramaStore,
    direction_id: int,
    *,
    queries: Iterable[str] | None = None,
    per_query_limit: int = 15,
    runner: Runner | None = None,
    min_stars: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Patrol GitHub repo search for each query; upsert ``code_repo`` entities.

    For every query the raw API response is snapshotted to
    ``L0/github/<date>/<query-slug>.json`` and the accepted repos (stars >=
    ``min_stars``) are recorded as one harvest run (source ``"github"``) for
    capture-recapture coverage estimation. Per-query failures are contained.
    """
    query_list = list(queries) if queries is not None else list(DEFAULT_GITHUB_QUERIES)
    run = runner or _default_runner
    ts = now or _utcnow()
    repos_upserted = 0
    queries_ok = 0
    snapshots: list[str] = []
    errors: list[str] = []
    for query in query_list:
        api_path = (
            "search/repositories?q="
            f"{urllib.parse.quote_plus(query)}"
            f"&sort=stars&order=desc&per_page={per_query_limit}"
        )
        try:
            raw = run(["gh", "api", api_path])
            payload = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            snapshot = _write_snapshot(
                store.l0_dir,
                "github",
                f"{_slug(query)}.json",
                payload,
                api_path,
                fetched_at=ts,
            )
            snapshots.append(str(snapshot))
            data = json.loads(payload)
            items = data.get("items", []) if isinstance(data, dict) else []
            hits: list[dict[str, Any]] = []
            for item in items:
                full_name = str(item.get("full_name") or "").strip()
                stars = int(item.get("stargazers_count") or 0)
                if not full_name or stars < min_stars:
                    continue
                entity_id = store.upsert_entity(
                    direction_id,
                    "code_repo",
                    full_name,
                    summary=str(item.get("description") or ""),
                    ext_ids={"github": full_name},
                    attrs={
                        "url": str(item.get("html_url") or ""),
                        "stars": stars,
                        "pushed_at": str(item.get("pushed_at") or ""),
                        "language": str(item.get("language") or ""),
                        "topics": list(item.get("topics") or [])[:8],
                    },
                    source="collector:github",
                )
                repos_upserted += 1
                hits.append(
                    {
                        "identity": f"github:{full_name}",
                        "scheme": "github",
                        "title": full_name,
                        "matched_entity_id": entity_id,
                    }
                )
            store.record_harvest_run(direction_id, "github", query, hits)
            queries_ok += 1
        except Exception as exc:  # noqa: BLE001 - per-query containment
            errors.append(f"{query}: {exc}")
    return {
        "queries": len(query_list),
        "queries_ok": queries_ok,
        "repos_upserted": repos_upserted,
        "snapshots": snapshots,
        "errors": errors,
    }


# -- industry blog snapshots -----------------------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _feed_entries(root: ET.Element) -> list[ET.Element]:
    """RSS ``<item>`` and Atom ``<entry>`` elements, namespace-agnostic."""
    return [el for el in root.iter() if _localname(el.tag) in ("item", "entry")]


def _entry_fields(entry: ET.Element) -> tuple[str, str, str]:
    """Extract (title, link, published) from an RSS item / Atom entry."""
    title = ""
    published = ""
    links: list[tuple[str, str]] = []
    for child in entry:
        name = _localname(child.tag)
        if name == "title" and not title:
            title = "".join(child.itertext()).strip()
        elif name == "link":
            href = (child.text or "").strip() or (child.get("href") or "").strip()
            links.append((child.get("rel") or "alternate", href))
        elif name in ("pubDate", "published", "updated") and not published:
            published = (child.text or "").strip()
    link = next((h for rel, h in links if rel == "alternate" and h), "")
    if not link:
        link = next((h for _, h in links if h), "")
    return title, link, published


def _has_anchor(
    store: PanoramaStore, entity_id: int, summary: str, source_ref: str
) -> bool:
    return any(
        a.get("summary") == summary and a.get("source_ref") == source_ref
        for a in store.anchors_for("entity", entity_id)
    )


def snapshot_blogs(
    store: PanoramaStore,
    direction_id: int,
    *,
    whitelist: Iterable[dict] | None = None,
    fetcher: Fetcher | None = None,
    keywords: Iterable[str] | None = None,
    max_items_per_feed: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Poll whitelisted industry blogs; upsert ``industry_doc`` entities.

    Each feed's raw bytes are snapshotted to ``L0/blogs/<date>/<org>.xml``
    (plus ``.meta.json``). Entries whose title matches any keyword (casefold
    substring) become entities with an evidence anchor. Per-feed failures are
    contained so one dead feed never blocks the rest of the whitelist.
    """
    feeds = (
        [dict(f) for f in whitelist]
        if whitelist is not None
        else [dict(f) for f in DEFAULT_BLOG_WHITELIST]
    )
    fetch = fetcher or _default_fetcher
    keyword_list = [
        k.casefold()
        for k in (list(keywords) if keywords is not None else DEFAULT_BLOG_KEYWORDS)
    ]
    ts = now or _utcnow()
    fetched_at_iso = ts.isoformat()
    feeds_ok = 0
    docs_upserted = 0
    anchors_added = 0
    snapshots: list[str] = []
    errors: list[str] = []
    for feed in feeds:
        org = str(feed.get("org") or "").strip() or "unknown"
        feed_url = str(feed.get("feed_url") or "")
        try:
            payload = fetch(feed_url)
            snapshot = _write_snapshot(
                store.l0_dir,
                "blogs",
                f"{_slug(org)}.xml",
                payload,
                feed_url,
                fetched_at=ts,
            )
            snapshots.append(str(snapshot))
            root = ET.fromstring(payload)
            for entry in _feed_entries(root)[:max_items_per_feed]:
                title, link, published = _entry_fields(entry)
                folded = title.casefold()
                if not title or not any(k in folded for k in keyword_list):
                    continue
                entity_id = store.upsert_entity(
                    direction_id,
                    "industry_doc",
                    f"{org}: {title}"[:200],
                    summary="",
                    ext_ids={"url": link} if link else {},
                    attrs={"org": org, "url": link, "published": published},
                    source="collector:blog",
                )
                docs_upserted += 1
                if not _has_anchor(store, entity_id, title, link):
                    store.add_anchor(
                        "entity",
                        entity_id,
                        summary=title,
                        source_ref=link,
                        fetched_at=fetched_at_iso,
                    )
                    anchors_added += 1
            feeds_ok += 1
        except Exception as exc:  # noqa: BLE001 - per-feed containment
            errors.append(f"{org}: {exc}")
    return {
        "feeds": len(feeds),
        "feeds_ok": feeds_ok,
        "docs_upserted": docs_upserted,
        "anchors_added": anchors_added,
        "snapshots": snapshots,
        "errors": errors,
    }
