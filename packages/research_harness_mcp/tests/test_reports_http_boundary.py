from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.storage.db import Database


def test_report_listing_redacts_raw_share_token(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "reports-redaction.db"
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name, status) VALUES (1, 'T', 'active')")
        conn.execute(
            """
            INSERT INTO reports
                (id, topic_id, template, title, sections_json, metadata_json,
                 content_md, content_html, share_token, share_expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                10,
                1,
                "abstract_only",
                "Report",
                "[]",
                "{}",
                "md",
                "<p>html</p>",
                "raw-secret-token",
                "2026-06-30T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/topics/1/reports")
    finally:
        http_api.DB_PATH = original

    assert response.status_code == 200, response.text
    report = response.json()["reports"][0]
    assert report["has_share"] is True
    assert "share_token" not in report
