"""Tests for affiliation enrichment from PDF author blocks and emails."""

from __future__ import annotations

import json

from research_harness.primitives.deepread_impls import (
    _affiliations_from_emails,
    _extract_explicit_affiliations,
    enrich_affiliations,
    merge_affiliation_lists,
    persist_paper_affiliations,
)


def test_merge_affiliation_lists_deduplicates_case_insensitively():
    merged = merge_affiliation_lists(
        ["MIT", "Stanford University"],
        ["mit", "Google", "Stanford University"],
    )
    assert merged == ["MIT", "Stanford University", "Google"]


def test_affiliations_from_emails_maps_known_domains():
    text = "Contact: alice@google.com and bob@tsinghua.edu.cn"
    assert _affiliations_from_emails(text) == ["Google", "Tsinghua University"]


def test_extract_explicit_affiliations_reads_author_block_lines():
    text = """
Alice Smith, Bob Lee
1 Google Research, Mountain View
2 Department of Computer Science, Stanford University
{alice@google.com}
"""
    affiliations = _extract_explicit_affiliations(text)
    assert any("Google Research" in line for line in affiliations)
    assert any("Stanford University" in line for line in affiliations)


def test_enrich_affiliations_updates_papers_table(db):
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, authors, affiliations, year, venue, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Affiliation Test", "[]", "[]", 2024, "Test", "active"),
        )
        paper_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """
            INSERT INTO paper_artifacts (paper_id, artifact_type, path)
            VALUES (?, ?, ?)
            """,
            (paper_id, "paperindex_structure", "missing-structure.json"),
        )
        conn.commit()
    finally:
        conn.close()

    # Monkeypatch page text lookup for deterministic unit test.
    from research_harness.primitives import deepread_impls

    original = deepread_impls._get_pdf_pages_text

    def _fake_pages(_conn, _paper_id, _row, *, max_pages=2):
        return [
            "Alice Smith {alice@google.com}\n1 Google Research, Mountain View\n"
            "2 Department of Computer Science, Stanford University"
        ][:max_pages]

    deepread_impls._get_pdf_pages_text = _fake_pages
    try:
        result = enrich_affiliations(db=db, paper_id=paper_id)
    finally:
        deepread_impls._get_pdf_pages_text = original

    assert result.paper_id == paper_id
    assert "Google" in result.affiliations
    assert any("Stanford University" in name for name in result.affiliations)
    assert result.new_affiliations

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT affiliations FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        stored = json.loads(row["affiliations"])
    finally:
        conn.close()
    assert stored == result.affiliations


def test_persist_paper_affiliations_is_idempotent(db):
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, authors, affiliations, year, venue, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Persist Test", "[]", json.dumps(["MIT"]), 2024, "Test", "active"),
        )
        paper_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
    finally:
        conn.close()

    merged = persist_paper_affiliations(db, paper_id, ["mit", "Google"])
    assert merged == ["MIT", "Google"]
