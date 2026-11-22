"""Tests for panorama importers (pool DB, PwC archives, innovation KB).

All fixtures are synthetic and live in tmp_path; no dependency on the real
pool.db or the real PwC archive.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from research_harness.panorama import PanoramaStore
from research_harness.panorama.importers import (
    import_innovation_kb,
    import_pool_papers,
    import_pwc_benchmarks,
    import_pwc_code_links,
)


@pytest.fixture
def store(tmp_path):
    s = PanoramaStore(tmp_path / "panorama")
    s.init()
    return s


@pytest.fixture
def direction_id(store):
    return store.get_or_create_direction("test-dir", "Test Direction")


# -- fixtures builders -----------------------------------------------------


def _make_pool_db(path: Path, *, claims_link_papers: bool = True) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            authors TEXT DEFAULT '[]',
            year INTEGER,
            venue TEXT DEFAULT '',
            doi TEXT,
            arxiv_id TEXT,
            s2_id TEXT,
            url TEXT DEFAULT '',
            abstract TEXT DEFAULT '',
            citation_count INTEGER
        );
        CREATE TABLE paper_domains (
            paper_id INTEGER NOT NULL,
            domain_id INTEGER NOT NULL,
            is_primary INTEGER DEFAULT 0,
            PRIMARY KEY (paper_id, domain_id)
        );
        """
    )
    if claims_link_papers:
        conn.execute(
            "CREATE TABLE claims (id INTEGER PRIMARY KEY, text TEXT NOT NULL, "
            "claim_type TEXT, paper_ids_json TEXT)"
        )
    else:
        # No paper-linking column at all: importer must skip gracefully.
        conn.execute(
            "CREATE TABLE claims (id INTEGER PRIMARY KEY, text TEXT NOT NULL, "
            "topic_id INTEGER)"
        )
    conn.executemany(
        "INSERT INTO papers (id, title, year, venue, doi, arxiv_id, s2_id, "
        "url, abstract, citation_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                1,
                "AutoML Survey",
                2023,
                "TMLR",
                "10.1/a",
                "2301.00001",
                "s2a",
                "http://x/1",
                "A" * 700,
                42,
            ),
            (
                2,
                "Research Agents",
                2024,
                "",
                None,
                "2402.00002",
                None,
                "",
                "Short.",
                None,
            ),
            (3, "Off-Domain Paper", 2020, "ICML", None, "2001.00003", None, "", "", 5),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_domains (paper_id, domain_id) VALUES (?, ?)",
        [(1, 7), (2, 7), (3, 8)],
    )
    if claims_link_papers:
        conn.executemany(
            "INSERT INTO claims (id, text, claim_type, paper_ids_json) "
            "VALUES (?,?,?,?)",
            [
                (
                    1,
                    "AutoML pipelines transfer across domains.",
                    "empirical",
                    json.dumps([1, 3]),
                ),
                (2, "Links only an off-domain paper.", None, json.dumps([3])),
                (3, "Claim without any paper links.", None, None),
            ],
        )
    else:
        conn.execute("INSERT INTO claims (id, text, topic_id) VALUES (1, 'orphan', 9)")
    conn.commit()
    conn.close()


def _write_gz_json(path: Path, data) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_kb_dir(root: Path) -> Path:
    kb = root / "kb"
    (kb / "directions").mkdir(parents=True)
    (kb / "evidence").mkdir()
    (kb / "directions" / "x1-demo.md").write_text(
        "# X1 — Demo Direction\n\n"
        "**Status**: active as of today.\nSecond line of the paragraph.\n\n"
        "## Details\n\nMore text.\n",
        encoding="utf-8",
    )
    (kb / "lessons.md").write_text(
        "# Lessons\n\npreamble noise outside any section\n\n"
        "## Methodology\n\nPre-registration makes negatives publishable.\n\n"
        "## Engineering\n\n```\n## not a heading\n```\n\n"
        "Pin CUDA devices explicitly.\n",
        encoding="utf-8",
    )
    (kb / "evidence" / "prior-art.md").write_text(
        "# Prior art\n\n## FLAWS (2511.21843)\n\n"
        "Injects claim-invalidating errors into LaTeX.\n",
        encoding="utf-8",
    )
    return kb


# -- pool DB ---------------------------------------------------------------


def test_import_pool_papers_basic(store, direction_id, tmp_path):
    pool_db = tmp_path / "pool.db"
    _make_pool_db(pool_db)

    counts = import_pool_papers(store, direction_id, pool_db, 7)

    assert counts["papers_imported"] == 2
    assert counts["papers_skipped"] == 0
    papers = store.entities(direction_id, kind="paper")
    assert {p["name"] for p in papers} == {"AutoML Survey", "Research Agents"}
    survey = next(p for p in papers if p["name"] == "AutoML Survey")
    assert survey["pool_paper_id"] == 1
    assert survey["source"] == "pooldb"
    assert len(survey["summary"]) <= 600  # abstract truncated
    assert survey["ext_ids"] == {"arxiv": "2301.00001", "doi": "10.1/a", "s2": "s2a"}
    assert survey["attrs"]["year"] == 2023
    assert survey["attrs"]["venue"] == "TMLR"
    assert survey["attrs"]["citation_count"] == 42
    assert survey["attrs"]["url"] == "http://x/1"
    agents = next(p for p in papers if p["name"] == "Research Agents")
    assert agents["ext_ids"] == {"arxiv": "2402.00002"}  # empty ids skipped


def test_import_pool_claims_linked_via_paper_ids_json(store, direction_id, tmp_path):
    pool_db = tmp_path / "pool.db"
    _make_pool_db(pool_db)

    counts = import_pool_papers(store, direction_id, pool_db, 7)

    # Claim 1 links imported paper 1; claims 2/3 have no imported papers.
    assert counts["claims_imported"] == 1
    assert counts["claim_edges"] == 1
    claims = store.entities(direction_id, kind="claim")
    assert len(claims) == 1
    claim = claims[0]
    assert claim["name"] == "AutoML pipelines transfer across domains."
    assert claim["summary"] == "AutoML pipelines transfer across domains."
    assert claim["attrs"]["claim_type"] == "empirical"
    paper = next(
        p for p in store.entities(direction_id, kind="paper") if p["pool_paper_id"] == 1
    )
    edges = store.edges_for(claim["id"])
    assert [(e["src_id"], e["dst_id"], e["rel"]) for e in edges] == [
        (paper["id"], claim["id"], "claims")
    ]
    anchors = store.anchors_for("entity", claim["id"])
    assert len(anchors) == 1
    assert anchors[0]["quote"] == claim["summary"]
    assert anchors[0]["source_ref"] == "pool:paper:1"


def test_import_pool_papers_idempotent(store, direction_id, tmp_path):
    pool_db = tmp_path / "pool.db"
    _make_pool_db(pool_db)

    import_pool_papers(store, direction_id, pool_db, 7)
    first = store.stats(direction_id)
    import_pool_papers(store, direction_id, pool_db, 7)
    second = store.stats(direction_id)

    assert second == first  # no duplicate entities/edges/anchors


def test_import_pool_claims_schema_without_paper_link(store, direction_id, tmp_path):
    pool_db = tmp_path / "pool.db"
    _make_pool_db(pool_db, claims_link_papers=False)

    counts = import_pool_papers(store, direction_id, pool_db, 7)

    assert counts["papers_imported"] == 2
    assert counts["claims_imported"] == 0
    assert store.entities(direction_id, kind="claim") == []


# -- PwC code links --------------------------------------------------------


def test_import_pwc_code_links_joins_only_store_papers(store, direction_id, tmp_path):
    pool_db = tmp_path / "pool.db"
    _make_pool_db(pool_db)
    import_pool_papers(store, direction_id, pool_db, 7)

    archive = tmp_path / "archive"
    archive.mkdir()
    _write_gz_json(
        archive / "links-between-papers-and-code.json.gz",
        [
            {
                "paper_arxiv_id": "2301.00001v2",  # version suffix must normalize
                "repo_url": "https://github.com/acme/automl.git",
                "is_official": True,
                "framework": "pytorch",
                "mentioned_in_paper": True,
            },
            {  # arxiv id not in store: must not be imported
                "paper_arxiv_id": "1999.11111",
                "repo_url": "https://github.com/other/repo",
            },
            {"repo_url": "https://github.com/no/arxiv"},  # missing arxiv id
            {"paper_arxiv_id": "2402.00002"},  # missing repo_url
        ],
    )

    counts = import_pwc_code_links(store, direction_id, archive)

    assert counts == {"papers_matched": 1, "repos_imported": 1, "edges": 1}
    repos = store.entities(direction_id, kind="code_repo")
    assert len(repos) == 1
    repo = repos[0]
    assert repo["name"] == "acme/automl"
    assert repo["ext_ids"] == {"github": "acme/automl"}
    assert repo["attrs"]["url"] == "https://github.com/acme/automl.git"
    assert repo["attrs"]["is_official"] is True
    assert repo["attrs"]["framework"] == "pytorch"
    paper = next(
        p for p in store.entities(direction_id, kind="paper") if p["pool_paper_id"] == 1
    )
    edges = store.edges_for(repo["id"])
    assert [(e["src_id"], e["dst_id"], e["rel"]) for e in edges] == [
        (repo["id"], paper["id"], "implements")
    ]

    before = store.stats(direction_id)
    import_pwc_code_links(store, direction_id, archive)
    assert store.stats(direction_id) == before  # idempotent


# -- PwC benchmarks --------------------------------------------------------


def test_import_pwc_benchmarks_keyword_filter(store, direction_id, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    _write_gz_json(
        archive / "evaluation-tables.json.gz",
        [
            {
                "task": "Image Classification",
                "description": "Assign labels to images.",
                "subtasks": [
                    {
                        "task": "Neural Architecture Search",
                        "description": "Search over network architectures.",
                        "subtasks": [],
                        "datasets": [
                            {"dataset": "NAS-Bench-101", "description": "NAS bench."},
                            {"dataset": "", "description": "nameless, skipped"},
                        ],
                    }
                ],
                "datasets": [{"dataset": "ImageNet", "description": "Images."}],
            },
            {
                "task": "AutoML",
                "description": "",
                "subtasks": [],
                "datasets": [{"dataset": "OpenML-CC18"}],
            },
        ],
    )
    keywords = ["automl", "neural architecture search"]

    counts = import_pwc_benchmarks(store, direction_id, archive, keywords)

    assert counts["tasks_matched"] == 2
    assert counts["benchmarks_imported"] == 2
    assert counts["datasets_imported"] == 2
    assert counts["edges"] == 2
    benchmarks = {b["name"]: b for b in store.entities(direction_id, kind="benchmark")}
    assert set(benchmarks) == {"Neural Architecture Search", "AutoML"}
    datasets = {d["name"]: d for d in store.entities(direction_id, kind="dataset")}
    assert set(datasets) == {"NAS-Bench-101", "OpenML-CC18"}  # no ImageNet
    edges = store.edges_for(datasets["NAS-Bench-101"]["id"])
    assert [(e["src_id"], e["dst_id"], e["rel"]) for e in edges] == [
        (
            datasets["NAS-Bench-101"]["id"],
            benchmarks["Neural Architecture Search"]["id"],
            "derived_from",
        )
    ]

    before = store.stats(direction_id)
    import_pwc_benchmarks(store, direction_id, archive, keywords)
    assert store.stats(direction_id) == before  # idempotent


# -- innovation KB ---------------------------------------------------------


def test_import_innovation_kb(store, direction_id, tmp_path):
    kb = _make_kb_dir(tmp_path)

    counts = import_innovation_kb(store, direction_id, kb)

    assert counts["direction_claims"] == 1
    assert counts["cells"] == 1
    assert counts["lessons"] == 2
    assert counts["prior_art_papers"] == 1

    claims = store.entities(direction_id, kind="claim")
    assert len(claims) == 1
    claim = claims[0]
    assert claim["name"] == "x1-demo"
    assert claim["source"] == "kb"
    assert (
        claim["summary"]
        == "**Status**: active as of today. Second line of the paragraph."
    )
    anchors = store.anchors_for("entity", claim["id"])
    assert len(anchors) == 1
    assert anchors[0]["source_ref"] == "directions/x1-demo.md"
    assert anchors[0]["quote"] == claim["summary"]

    cells = store.cells(direction_id)
    assert len(cells) == 1
    cell = cells[0]
    assert (cell["problem"], cell["mechanism"], cell["evidence_facet"]) == (
        "x1-demo",
        "rh-direction",
        "kb",
    )
    assert cell["status"] == "occupied"
    assert [e["id"] for e in store.cell_occupants(cell["id"])] == [claim["id"]]

    lessons = {e["name"]: e for e in store.entities(direction_id, kind="limitation")}
    assert set(lessons) == {"Methodology", "Engineering"}
    assert (
        lessons["Methodology"]["summary"]
        == "Pre-registration makes negatives publishable."
    )
    # Fenced "## not a heading" must not become a section; fence block skipped.
    assert lessons["Engineering"]["summary"] == "Pin CUDA devices explicitly."

    papers = store.entities(direction_id, kind="paper")
    assert [p["name"] for p in papers] == ["FLAWS (2511.21843)"]
    assert papers[0]["summary"] == "Injects claim-invalidating errors into LaTeX."


def test_import_innovation_kb_idempotent(store, direction_id, tmp_path):
    kb = _make_kb_dir(tmp_path)

    import_innovation_kb(store, direction_id, kb)
    first = store.stats(direction_id)
    counts = import_innovation_kb(store, direction_id, kb)
    second = store.stats(direction_id)

    assert second == first  # entities, cells, anchors all unchanged
    assert counts["anchors"] == 0  # nothing re-anchored on second run


def test_import_innovation_kb_missing_pieces(store, direction_id, tmp_path):
    kb = tmp_path / "empty-kb"
    kb.mkdir()

    counts = import_innovation_kb(store, direction_id, kb)

    assert counts == {
        "direction_claims": 0,
        "cells": 0,
        "lessons": 0,
        "prior_art_papers": 0,
        "anchors": 0,
    }
