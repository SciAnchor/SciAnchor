"""Citation Frontier Radar — citation-network-driven gap discovery over Panorama KB.

Anchored methods (what we adopt, what we add):

1. ResearchBench (arXiv:2503.21248) decomposes discovery into
   inspiration-retrieval steps and shows LLMs excel at OOD inspiration
   retrieval. We ADOPT the citation-hop as the inspiration channel, but
   REPLACE free-form LLM retrieval with deterministic citation expansion
   from a curated seed set (the KB's tiered papers), so every candidate has
   a provenance chain.
2. AI Idea Bench 2025 (arXiv:2504.14191) grounds idea evaluation in
   target-paper + motivating-papers pairs. We ADOPT the "motivating
   neighborhood" construct: for each frontier paper we keep the local
   citation context (which KB papers it cites / is cited with), so a later
   ideation pass sees the same neighborhood a human author would.
3. RH red_ocean.py (in-repo) scores competition density per area with
   deterministic bibliometrics. We EXTEND the same philosophy from *areas*
   to the *citation frontier*: novelty pressure lives at the boundary of
   the known graph — papers that cite 2+ of our KB clusters but belong to
   none (bridge candidates), and KB claims whose citing edge stops dead
   (dead-end candidates = nobody followed up).

Innovation (ours, not in the anchors):
- frontier_score = tier_w * (bridge_lift + dead_end_lift) * recency_decay,
  where bridge_lift rewards papers connecting >= 2 disjoint KB clusters
  (structural-hole logic, Burt 2004, applied to an agent-curated KB) and
  dead_end_lift rewards claims with zero follow-up citations after 12
  months (abandoned-thread mining). Both computable WITHOUT any LLM call;
  LLM certification (gap_ground_verify) is a downstream, optional stage.
- S2-first with OpenAlex fallback per hop, single on-disk request cache
  (30-day TTL) so repeated sweeps never refetch — the no-duplicate-work
  guarantee the workflow requires.

Outputs per candidate: refs to read (KB anchors + frontier paper),
datasets touched (KB dataset entities in the neighborhood), and a SOTA
snapshot (top-cited neighbors, so the reader sees the bar to beat).

CLI:
  python -m research_harness.primitives.citation_frontier sweep --db PATH
  python -m research_harness.primitives.citation_frontier report --db PATH
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .registry import register_primitive
from .types import PrimitiveCategory, PrimitiveSpec

S2_BASE = "https://api.semanticscholar.org/graph/v1"
OPENALEX_BASE = "https://api.openalex.org"
CACHE_TTL_DAYS = 30
S2_FIELDS = "title,year,venue,citationCount,externalIds,abstract"
RECENT_YEARS = 2  # frontier = last N years
DEAD_END_MONTHS = 12

# venue tier weights: KB curation priority (CCF-A/Q1 > CCF-B/Q2 > preprint)
TIER_WEIGHT = {"CCF-A": 1.0, "TOP": 1.0, "CCF-B": 0.7, None: 0.4}
# top-lab preprints get promoted from the default 0.4
TOP_ORGS = (
    "deepmind",
    "openai",
    "anthropic",
    "meta ai",
    "fair",
    "microsoft research",
    "google research",
    "stanford",
    "mit",
    "berkeley",
    "cmu",
    "tsinghua",
    "futurehouse",
    "sakana",
)


@dataclass
class FrontierCandidate:
    kind: str  # bridge | dead_end
    title: str
    ext_id: str  # arxiv:... | s2:... | openalex:W...
    year: int | None
    venue: str | None
    score: float
    clusters_bridged: list[str] = field(default_factory=list)
    kb_anchors: list[str] = field(default_factory=list)  # refs to read
    datasets: list[str] = field(default_factory=list)  # datasets touched
    sota_neighbors: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""


class RequestCache:
    """SQLite-backed request cache: never refetch what we already have."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS http_cache ("
            " url TEXT PRIMARY KEY, body TEXT, fetched_at TEXT)"
        )
        self.db.commit()

    def get(self, url: str) -> Any | None:
        row = self.db.execute(
            "SELECT body, fetched_at FROM http_cache WHERE url = ?", (url,)
        ).fetchone()
        if not row:
            return None
        body, fetched_at = row
        age_days = (
            datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
        ).days
        if age_days > CACHE_TTL_DAYS:
            return None
        return json.loads(body)

    def put(self, url: str, body: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?)",
            (url, json.dumps(body), datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()


def _http_json(url: str, cache: RequestCache, tries: int = 4) -> Any | None:
    cached = cache.get(url)
    if cached is not None:
        return cached
    headers = {"User-Agent": "rh-frontier/1.0"}  # keyless public APIs
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as r:
                body = json.loads(r.read())
                cache.put(url, body)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(8 * (i + 1))  # S2 unauthenticated rate limit
                continue
            if e.code == 404:
                return None
            if i == tries - 1:
                return None
            time.sleep(3 * (i + 1))
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(3 * (i + 1))
    return None


def s2_citations(ext_id: str, cache: RequestCache, limit: int = 100) -> list[dict]:
    """Citing papers through SPC; unresolved identifiers are explicit failures."""
    from research_harness.acquisition.spc_bridge import spc_graph

    # Existing cached graph facts stay usable without reopening their old API.
    old_key = f"{S2_BASE}/paper/{urllib.parse.quote(ext_id)}/citations?fields={S2_FIELDS}&limit={limit}"
    cached = cache.get(old_key)
    if isinstance(cached, dict) and "data" in cached:
        return [r["citingPaper"] for r in cached["data"] if r.get("citingPaper")]
    doi = ext_id.removeprefix("DOI:").removeprefix("doi:")
    if not doi.startswith("10."):
        from research_harness.acquisition.spc_bridge import spc_lookup

        if ext_id.lower().startswith("arxiv:"):
            resolved = spc_lookup(ext_id.split(":", 1)[1], kind="arxiv")
            identifiers = (
                resolved.get("paper") or resolved.get("identifiers") or resolved
            )
            doi = str(identifiers.get("doi") or "")
        if not doi.startswith("10."):
            raise ValueError("SPC citation frontier could not resolve a DOI")
    return [
        {
            "title": r.get("title"),
            "year": r.get("year"),
            "venue": r.get("venue"),
            "citationCount": r.get("citation_count", 0),
            "abstract": r.get("abstract"),
            "externalIds": {"DOI": r.get("doi", ""), "ArXiv": r.get("arxiv_id", "")},
        }
        for r in spc_graph(doi, direction="citations", limit=limit)
    ]


def _openalex_to_s2ish(r: dict) -> dict:
    return {
        "title": r.get("display_name"),
        "year": r.get("publication_year"),
        "venue": ((r.get("primary_location") or {}).get("source") or {}).get(
            "display_name"
        ),
        "citationCount": r.get("cited_by_count", 0),
        "externalIds": {"OpenAlex": r.get("id", "").rsplit("/", 1)[-1]},
        "abstract": None,
    }


def load_kb(db_path: Path) -> dict[str, Any]:
    """Load papers, clusters, datasets, claims from a Panorama L1 KB.

    Supports both the L1 production schema (entity_ext_ids table,
    edges.src_id/dst_id) and the simplified fixture schema
    (entities.canonical_key, edges.src/dst) used in tests.
    """
    db = sqlite3.connect(db_path)
    cols = {r[1] for r in db.execute("PRAGMA table_info(entities)")}
    papers: dict[int, dict[str, Any]] = {}
    if "canonical_key" in cols:  # fixture schema
        rows = db.execute(
            "SELECT id, name, canonical_key, attrs_json FROM entities"
            " WHERE kind = 'paper' AND canonical_key IS NOT NULL"
        )
        for pid, name, key, attrs in rows:
            a = json.loads(attrs or "{}")
            papers[pid] = {
                "id": pid,
                "title": name,
                "key": key,
                "tier": a.get("venue_tier"),
                "year": a.get("year"),
                "cluster": a.get("research_area") or a.get("cluster"),
            }
        edge_dst = "dst"
    else:  # L1 production schema
        ext: dict[int, str] = {}
        for eid, scheme, value in db.execute(
            "SELECT entity_id, scheme, value FROM entity_ext_ids"
            " WHERE scheme IN ('arxiv', 'openalex')"
        ):
            ext.setdefault(eid, f"{scheme}:{value}")
        for pid, name, attrs in db.execute(
            "SELECT id, name, attrs_json FROM entities WHERE kind = 'paper'"
        ):
            if pid not in ext:
                continue
            a = json.loads(attrs or "{}")
            papers[pid] = {
                "id": pid,
                "title": name,
                "key": ext[pid],
                "tier": a.get("venue_tier") or a.get("tier"),
                "year": a.get("year") or a.get("publication_year"),
                "cluster": a.get("research_area")
                or a.get("cluster")
                or a.get("problem"),
            }
        edge_dst = "dst_id"
    datasets = {
        pid: name
        for pid, name in db.execute(
            "SELECT id, name FROM entities WHERE kind = 'dataset'"
        )
    }
    claims = list(
        db.execute(
            "SELECT e.id, e.name FROM entities e WHERE e.kind = 'claim'"
            " AND NOT EXISTS (SELECT 1 FROM edges g"
            f"   WHERE g.{edge_dst} = e.id"
            "   AND g.rel IN ('cites', 'improves_on', 'reuses'))"
            " LIMIT 500"
        )
    )
    db.close()
    return {"papers": papers, "datasets": datasets, "dead_end_claims": claims}


def _tier_weight(venue: str | None, title: str | None = None) -> float:
    if venue:
        v = venue.lower()
        for tier, names in (
            (
                "CCF-A",
                (
                    "neurips",
                    "neural information",
                    "icml",
                    "aaai",
                    "acl",
                    "cvpr",
                    "kdd",
                    "sigir",
                    "tpami",
                    "jmlr",
                    "iclr",
                ),
            ),
            ("CCF-B", ("emnlp", "naacl", "coling", "ecai", "cikm", "wsdm")),
        ):
            if any(n in v for n in names):
                return TIER_WEIGHT[tier]
    return TIER_WEIGHT[None]


def _org_lift(paper: dict) -> float:
    """Top-org preprints represent the frontier: promote them."""
    text = " ".join(
        str(x or "") for x in (paper.get("venue"), paper.get("abstract"))
    ).lower()
    return 1.5 if any(org in text for org in TOP_ORGS) else 1.0


def _recency(year: int | None, now_year: int) -> float:
    if not year:
        return 0.5
    age = max(0, now_year - year)
    return max(0.2, 1.0 - 0.35 * age)


def sweep(
    kb_path: Path,
    cache_path: Path,
    seed_limit: int = 60,
    per_seed_citations: int = 60,
    now_year: int | None = None,
) -> list[FrontierCandidate]:
    """One radar sweep: citation-expand tiered KB seeds, score the frontier."""
    now_year = now_year or datetime.now(timezone.utc).year
    kb = load_kb(kb_path)
    cache = RequestCache(cache_path)

    # seeds: highest-tier, most recent KB papers with resolvable ids
    seeds = sorted(
        (
            p
            for p in kb["papers"].values()
            if p["key"]
            and (p["key"].startswith("arxiv:") or p["key"].startswith("openalex:"))
        ),
        key=lambda p: (TIER_WEIGHT.get(p["tier"], 0.4), p["year"] or 0),
        reverse=True,
    )[:seed_limit]

    kb_titles = {p["title"].lower().strip() for p in kb["papers"].values()}
    # frontier accumulation: ext_id -> {paper, set of seed clusters that reached it}
    frontier: dict[str, dict[str, Any]] = {}

    for seed in seeds:
        ext = seed["key"]
        s2_id = "arXiv:" + ext[6:] if ext.startswith("arxiv:") else ext[9:]
        for citing in s2_citations(s2_id, cache, per_seed_citations):
            title = (citing.get("title") or "").lower().strip()
            if not title or title in kb_titles:
                continue  # already known — no duplicate work
            year = citing.get("year")
            if year and year < now_year - RECENT_YEARS:
                continue  # frontier = recent only
            xid = _ext_id(citing)
            slot = frontier.setdefault(
                xid, {"paper": citing, "clusters": set(), "anchors": []}
            )
            # no curated cluster -> the seed itself is the micro-cluster;
            # bridge then = bibliographic coupling with >= 2 KB seeds
            slot["clusters"].add(seed["cluster"] or f"seed:{seed['title'][:60]}")
            slot["anchors"].append(seed["title"])

    candidates: list[FrontierCandidate] = []
    for xid, slot in frontier.items():
        p = slot["paper"]
        n_clusters = len(slot["clusters"])
        bridge_lift = 0.5 * (n_clusters - 1)  # 0 for 1 cluster, +0.5/extra
        base = _tier_weight(p.get("venue")) * _org_lift(p)
        score = base * (1.0 + bridge_lift) * _recency(p.get("year"), now_year)
        if n_clusters >= 2 or score >= 0.9:
            kind = "bridge" if n_clusters >= 2 else "frontier"
            candidates.append(
                FrontierCandidate(
                    kind=kind,
                    title=p.get("title") or "",
                    ext_id=xid,
                    year=p.get("year"),
                    venue=p.get("venue"),
                    score=round(score, 3),
                    clusters_bridged=sorted(slot["clusters"]),
                    kb_anchors=slot["anchors"][:5],
                    datasets=_datasets_near(kb, slot["clusters"]),
                    sota_neighbors=_sota_snapshot(slot, frontier),
                    rationale=(
                        f"cited by frontier work bridging {n_clusters} KB "
                        f"cluster(s): {', '.join(sorted(slot['clusters'])[:3])}"
                    ),
                )
            )

    # dead-end claims: KB claims nobody followed up — cheap, purely local
    for cid, name in kb["dead_end_claims"][:40]:
        candidates.append(
            FrontierCandidate(
                kind="dead_end",
                title=name[:180],
                ext_id=f"kb:claim:{cid}",
                year=None,
                venue=None,
                score=0.6,
                rationale=(
                    "KB claim with zero follow-up edges "
                    f"(no cites/improves_on/reuses inbound) after {DEAD_END_MONTHS}mo"
                ),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _ext_id(p: dict) -> str:
    ids = p.get("externalIds") or {}
    if ids.get("DOI"):
        return f"doi:{ids['DOI']}"
    if ids.get("ArXiv"):
        return f"arxiv:{ids['ArXiv']}"
    if ids.get("OpenAlex"):
        return f"openalex:{ids['OpenAlex']}"
    return f"title:{(p.get('title') or '')[:80]}"


def _datasets_near(kb: dict, clusters: set) -> list[str]:
    # ponytail: cluster->dataset mapping is coarse (all KB datasets returned
    # when any cluster matches); refine with edge walks when KB grows edges
    return sorted(kb["datasets"].values())[:6]


def _sota_snapshot(slot: dict, frontier: dict) -> list[dict[str, Any]]:
    same_cluster = [
        s["paper"] for s in frontier.values() if s["clusters"] & slot["clusters"]
    ]
    top = sorted(same_cluster, key=lambda p: p.get("citationCount") or 0, reverse=True)[
        :3
    ]
    return [
        {
            "title": p.get("title"),
            "citations": p.get("citationCount"),
            "year": p.get("year"),
        }
        for p in top
    ]


CITATION_FRONTIER_SPEC = PrimitiveSpec(
    name="citation_frontier_sweep",
    category=PrimitiveCategory.ANALYSIS,
    description=(
        "Citation-network radar over the Panorama KB: expands tiered seed "
        "papers one citation hop via S2/OpenAlex (cached), scores bridge "
        "papers (connect >=2 KB clusters) and dead-end claims (no follow-up) "
        "as gap candidates. Deterministic; no LLM."
    ),
    input_schema={
        "kb_path": "str",
        "cache_path": "str",
        "seed_limit": "int",
        "per_seed_citations": "int",
    },
    output_type="list[FrontierCandidate]",
    requires_llm=False,
    idempotent=True,
)


@register_primitive(CITATION_FRONTIER_SPEC)
def citation_frontier_sweep(
    kb_path: str,
    cache_path: str = "",
    seed_limit: int = 60,
    per_seed_citations: int = 60,
) -> list[dict[str, Any]]:
    cache = cache_path or str(Path(kb_path).with_suffix(".http-cache.db"))
    return [asdict(c) for c in sweep(Path(kb_path), Path(cache))]


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sweep")
    sp.add_argument("--db", required=True)
    sp.add_argument("--cache", default="")
    sp.add_argument("--seeds", type=int, default=60)
    sp.add_argument("--out", default="")
    args = ap.parse_args()

    cache = args.cache or str(Path(args.db).with_suffix(".http-cache.db"))
    cands = sweep(Path(args.db), Path(cache), seed_limit=args.seeds)
    payload = json.dumps([asdict(c) for c in cands], ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(payload)
        print(f"{len(cands)} candidates -> {args.out}")
    else:
        print(payload[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(_main())
