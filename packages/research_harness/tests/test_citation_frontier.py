"""Self-check for citation_frontier: offline, uses a fixture KB + canned cache."""

import sqlite3
from pathlib import Path

from research_harness.primitives.citation_frontier import (
    RequestCache,
    load_kb,
    sweep,
    _tier_weight,
    _recency,
)


def _fixture_kb(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE entities (id INTEGER PRIMARY KEY, kind TEXT, name TEXT,
          canonical_key TEXT, attrs_json TEXT DEFAULT '{}');
        CREATE TABLE edges (id INTEGER PRIMARY KEY, src INT, rel TEXT, dst INT);
        CREATE TABLE territory_cells (anchor_entity INT, problem_cluster TEXT);
        """
    )
    db.execute(
        "INSERT INTO entities VALUES (1,'paper','Seed A','arxiv:1111.0001',"
        ' \'{"venue_tier":"CCF-A","year":2026,"research_area":"alpha"}\')'
    )
    db.execute(
        "INSERT INTO entities VALUES (2,'paper','Seed B','arxiv:1111.0002',"
        ' \'{"venue_tier":"CCF-A","year":2026,"research_area":"beta"}\')'
    )
    db.execute("INSERT INTO entities VALUES (3,'dataset','DS-1',NULL,'{}')")
    db.execute(
        "INSERT INTO entities VALUES (4,'claim','Nobody followed this up',NULL,'{}')"
    )
    db.commit()
    db.close()


def _canned_cache(path: Path, now_year: int) -> None:
    """Both seeds are cited by the same fresh paper -> bridge candidate."""
    cache = RequestCache(path)
    citing = {
        "title": "Bridge Paper X",
        "year": now_year,
        "venue": "NeurIPS",
        "citationCount": 7,
        "externalIds": {"ArXiv": "2299.9999"},
        "abstract": "",
    }
    for arx in ("1111.0001", "1111.0002"):
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/"
            f"arXiv%3A{arx}/citations"
            "?fields=title,year,venue,citationCount,externalIds,abstract&limit=60"
        )
        cache.put(url, {"data": [{"citingPaper": citing}]})


def test_citation_frontier_end_to_end() -> None:
    tmp = Path("/tmp/cf-selftest")
    tmp.mkdir(exist_ok=True)
    kb, cache = tmp / "kb.db", tmp / "cache.db"
    kb.unlink(missing_ok=True)
    cache.unlink(missing_ok=True)
    _fixture_kb(kb)
    NOW = 2026
    _canned_cache(cache, NOW)

    loaded = load_kb(kb)
    assert len(loaded["papers"]) == 2
    assert len(loaded["dead_end_claims"]) == 1

    cands = sweep(kb, cache, seed_limit=10, per_seed_citations=60, now_year=NOW)
    kinds = {c.kind for c in cands}
    assert "bridge" in kinds, f"expected a bridge candidate, got {kinds}"
    bridge = next(c for c in cands if c.kind == "bridge")
    assert bridge.title == "Bridge Paper X"
    assert set(bridge.clusters_bridged) == {"alpha", "beta"}
    assert bridge.score > 1.0, bridge.score  # CCF-A venue, 2 clusters, fresh
    assert any(c.kind == "dead_end" for c in cands)

    assert _tier_weight("NeurIPS 2026") == 1.0
    assert _tier_weight("Some Workshop") == 0.4
    assert _recency(NOW, NOW) == 1.0
    assert _recency(NOW - 3, NOW) < 0.2 + 1e-9 or _recency(NOW - 3, NOW) >= 0.2

    print(f"SELF-CHECK OK: {len(cands)} candidates, bridge score={bridge.score}")


if __name__ == "__main__":
    test_citation_frontier_end_to_end()
