"""Tests for the acquisition diagnosis read model."""

from __future__ import annotations

import json

from research_harness.acquisition.diagnose import build_acquisition_diagnosis


def _seed(db) -> int:
    """Two papers: one covered natively, one failing native + external."""
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name) VALUES ('rag')")
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO papers (title, doi, venue, pdf_path, status) VALUES"
            " ('Covered Paper', '10.1000/covered', 'NeurIPS', '/x/1.pdf',"
            " 'downloaded')"
        )
        conn.execute(
            "INSERT INTO papers (title, doi, venue, status) VALUES"
            " ('Blocked Paper', '10.1126/blocked', 'Science', 'meta_only')"
        )
        for paper_id in (1, 2):
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance,"
                " screening_status, manuscript_eligible)"
                " VALUES (?, ?, 'high', 'screened_in', 1)",
                (paper_id, topic_id),
            )
        conn.execute(
            "INSERT INTO paper_artifacts (paper_id, artifact_type, path,"
            " metadata) VALUES (1, 'pdf_route_audit', '', ?)",
            (
                json.dumps(
                    {
                        "successful_route": "arxiv",
                        "failure_taxonomy": None,
                        "attempts": [
                            {"route": "arxiv", "duration_ms": 900},
                        ],
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO paper_artifacts (paper_id, artifact_type, path,"
            " metadata) VALUES (2, 'pdf_route_audit', '', ?)",
            (
                json.dumps(
                    {
                        "successful_route": None,
                        "failure_taxonomy": "paywall",
                        "attempts": [
                            {
                                "route": "doi_landing",
                                "error_class": "paywall",
                                "duration_ms": 12_500,
                            }
                        ],
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO paper_artifacts (paper_id, artifact_type, path,"
            " metadata) VALUES (2, 'external_route_audit', '', ?)",
            (
                json.dumps(
                    {
                        "successful_route": None,
                        "failure_taxonomy": "subscription_required",
                        "download_attempts": [
                            {
                                "route": "spc:publisher_portal",
                                "error_class": "browser_challenge",
                                "duration_ms": 31_000,
                            }
                        ],
                    }
                ),
            ),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def test_diagnosis_aggregates_both_audit_streams(db):
    topic_id = _seed(db)

    diagnosis = build_acquisition_diagnosis(db, topic_id)

    assert diagnosis["schema_version"] == "rh.acquisition_diagnosis.v1"
    assert diagnosis["totals"] == {
        "papers": 2,
        "with_pdf": 1,
        "without_pdf": 1,
        "coverage_rate": 0.5,
    }
    assert diagnosis["failure_taxonomy"] == {
        "paywall": 1,
        "subscription_required": 1,
    }
    assert diagnosis["failure_by_origin"]["native"] == {"paywall": 1}
    assert diagnosis["failure_by_origin"]["external"] == {"subscription_required": 1}
    assert diagnosis["route_success"] == {"arxiv": 1}


def test_publisher_and_doi_prefix_summaries(db):
    topic_id = _seed(db)

    diagnosis = build_acquisition_diagnosis(db, topic_id)

    assert diagnosis["publisher_failure_summary"]["science"] == {
        "paywall": 1,
        "subscription_required": 1,
    }
    assert diagnosis["doi_prefix_failure_summary"]["10.1126"] == {
        "paywall": 1,
        "subscription_required": 1,
    }


def test_slow_attempts_are_ranked_and_thresholded(db):
    topic_id = _seed(db)

    diagnosis = build_acquisition_diagnosis(db, topic_id)

    slow = diagnosis["slowest_attempts"]
    assert [item["duration_ms"] for item in slow] == [31_000, 12_500]
    assert slow[0]["origin"] == "external"


def test_uncovered_papers_carry_latest_taxonomy(db):
    topic_id = _seed(db)

    diagnosis = build_acquisition_diagnosis(db, topic_id)

    uncovered = diagnosis["uncovered_papers"]
    assert len(uncovered) == 1
    assert uncovered[0]["paper_id"] == 2
    assert uncovered[0]["attempted"] is True
    assert uncovered[0]["latest_failure_taxonomy"] == "subscription_required"


def test_empty_topic_is_well_formed(db):
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name) VALUES ('empty')")
        conn.commit()
        topic_id = int(cur.lastrowid)
    finally:
        conn.close()

    diagnosis = build_acquisition_diagnosis(db, topic_id)

    assert diagnosis["totals"]["papers"] == 0
    assert diagnosis["totals"]["coverage_rate"] == 0.0
    assert diagnosis["uncovered_papers"] == []
