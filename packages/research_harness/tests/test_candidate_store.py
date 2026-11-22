"""Tests for search-time PDF candidate persistence (acquisition.candidate_store)."""

from __future__ import annotations

from research_harness.acquisition.candidate_store import (
    ARTIFACT_TYPE,
    load_pdf_candidates,
    save_pdf_candidates,
)
from research_harness.paper_sources import PDFCandidate


def _seed_paper(conn) -> int:
    cur = conn.execute(
        "INSERT INTO papers (title, doi) VALUES ('Candidate store paper', '10.1/cs')"
    )
    conn.commit()
    return int(cur.lastrowid)


def test_save_and_load_roundtrip_preserves_rank_order(conn):
    paper_id = _seed_paper(conn)
    saved = save_pdf_candidates(
        conn,
        paper_id,
        [
            PDFCandidate(
                url="https://oa.example.org/paper.pdf",
                source_type="open_access_pdf",
                provider="openalex",
                confidence=0.95,
            ),
            {
                "url": "https://doi.org/10.1/cs",
                "source_type": "doi_landing",
                "provider": "crossref",
                "confidence": 0.6,
            },
        ],
    )

    assert saved == 2
    loaded = load_pdf_candidates(conn, paper_id)
    assert [item["url"] for item in loaded] == [
        "https://oa.example.org/paper.pdf",
        "https://doi.org/10.1/cs",
    ]
    assert loaded[0]["source_type"] == "open_access_pdf"
    assert loaded[0]["provider"] == "openalex"
    assert loaded[0]["requires_browser"] is False
    assert loaded[0]["confidence"] == 0.95


def test_save_replaces_previous_candidate_list(conn):
    paper_id = _seed_paper(conn)
    save_pdf_candidates(conn, paper_id, [{"url": "https://old.example.org/a.pdf"}])
    save_pdf_candidates(conn, paper_id, [{"url": "https://new.example.org/b.pdf"}])

    loaded = load_pdf_candidates(conn, paper_id)
    assert [item["url"] for item in loaded] == ["https://new.example.org/b.pdf"]
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM paper_artifacts WHERE paper_id = ? AND artifact_type = ?",
        (paper_id, ARTIFACT_TYPE),
    ).fetchone()
    assert rows["n"] == 1


def test_invalid_and_duplicate_candidates_are_dropped(conn):
    paper_id = _seed_paper(conn)
    saved = save_pdf_candidates(
        conn,
        paper_id,
        [
            {"url": "https://oa.example.org/paper.pdf"},
            {"url": "https://oa.example.org/paper.pdf"},  # duplicate
            {"url": "ftp://not-http.example.org/x.pdf"},  # non-http scheme
            {"url": ""},
            "not a candidate",
            None,
        ],
    )

    assert saved == 1
    loaded = load_pdf_candidates(conn, paper_id)
    assert [item["url"] for item in loaded] == ["https://oa.example.org/paper.pdf"]


def test_load_returns_empty_for_missing_or_corrupt_metadata(conn):
    paper_id = _seed_paper(conn)
    assert load_pdf_candidates(conn, paper_id) == []

    conn.execute(
        "INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)"
        " VALUES (?, ?, '', 'not json')",
        (paper_id, ARTIFACT_TYPE),
    )
    conn.commit()
    assert load_pdf_candidates(conn, paper_id) == []
