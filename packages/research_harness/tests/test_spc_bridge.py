"""Tests for the RH -> SPC bridge (wants-list export + provider probe)."""

from __future__ import annotations

import json

from research_harness.acquisition import spc_bridge
from research_harness.acquisition.spc_bridge import (
    build_spc_provider_check,
    build_spc_wants_list,
    export_spc_wants_list,
    spc_provider_status,
)


def _seed_topic_with_paper(db, *, with_audit_taxonomy: str | None = None) -> int:
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name) VALUES ('rag')")
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO papers (title, year, venue, doi, arxiv_id, status)"
            " VALUES ('Paper Needing Fulltext', 2026, 'NeurIPS',"
            " '10.5555/wants.1', '2601.00002', 'meta_only')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance,"
            " screening_status, manuscript_eligible)"
            " VALUES (1, ?, 'high', 'screened_in', 1)",
            (topic_id,),
        )
        if with_audit_taxonomy:
            conn.execute(
                "INSERT INTO paper_artifacts (paper_id, artifact_type, path,"
                " metadata) VALUES (1, 'pdf_route_audit', '', ?)",
                (json.dumps({"failure_taxonomy": with_audit_taxonomy}),),
            )
        conn.commit()
        return topic_id
    finally:
        conn.close()


class TestWantsList:
    def test_paper_without_pdf_becomes_manual_seed(self, db):
        topic_id = _seed_topic_with_paper(db)

        payload = build_spc_wants_list(db, topic_id)

        assert payload["schema_version"] == "rh.spc_wants_list.v1"
        assert payload["paper_count"] == 1
        seed = payload["manual_seeds"][0]
        assert seed["title"] == "Paper Needing Fulltext"
        assert seed["doi"] == "10.5555/wants.1"
        assert seed["arxiv_id"] == "2601.00002"
        assert seed["source"] == "user_supplied"
        assert seed["reason"].startswith("rh needs fulltext")

    def test_reason_carries_latest_failure_taxonomy(self, db):
        topic_id = _seed_topic_with_paper(
            db, with_audit_taxonomy="subscription_required"
        )

        payload = build_spc_wants_list(db, topic_id)

        assert "subscription_required" in payload["manual_seeds"][0]["reason"]

    def test_seed_entries_carry_only_contract_fields(self, db):
        topic_id = _seed_topic_with_paper(db)

        payload = build_spc_wants_list(db, topic_id)

        allowed = {"title", "doi", "arxiv_id", "reason", "source"}
        assert set(payload["manual_seeds"][0]) <= allowed

    def test_export_writes_file_and_topic_artifact(self, db, tmp_path):
        topic_id = _seed_topic_with_paper(db)
        target = tmp_path / "out" / "wants.json"

        payload = export_spc_wants_list(db, topic_id, target)

        assert payload["paper_count"] == 1
        on_disk = json.loads(target.read_text(encoding="utf-8"))
        assert on_disk["manual_seeds"][0]["title"] == "Paper Needing Fulltext"
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM project_artifacts"
                " WHERE artifact_type = 'spc_wants_list'"
            ).fetchone()
            assert row is not None
            assert json.loads(row["payload_json"])["paper_count"] == 1
        finally:
            conn.close()

    def test_paper_with_pdf_is_not_wanted(self, db):
        topic_id = _seed_topic_with_paper(db)
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE papers SET pdf_path = '/tmp/x.pdf', status = 'downloaded'"
                " WHERE id = 1"
            )
            conn.commit()
        finally:
            conn.close()

        payload = build_spc_wants_list(db, topic_id)

        assert payload["paper_count"] == 0


class TestProviderProbe:
    def test_absent_cli_and_unset_env_is_ok_but_not_ready(self, monkeypatch):
        monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: None)
        monkeypatch.delenv(spc_bridge.PAPERVAULT_DB_ENV, raising=False)

        status = spc_provider_status()

        assert status["cli_on_path"] is False
        assert status["papervault_state"] == "not_configured"

    def test_configured_papervault_db_reports_ready(self, monkeypatch, tmp_path):
        db_file = tmp_path / "papervault.db"
        db_file.write_bytes(b"SQLite format 3\x00")
        monkeypatch.setenv(spc_bridge.PAPERVAULT_DB_ENV, str(db_file))

        status = spc_provider_status()

        assert status["papervault_state"] == "ready"

    def test_configured_but_missing_db_reports_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv(spc_bridge.PAPERVAULT_DB_ENV, str(tmp_path / "gone.db"))

        status = spc_provider_status()

        assert status["papervault_state"] == "missing"

    def test_doctor_check_is_always_ok(self, monkeypatch):
        monkeypatch.setattr(spc_bridge.shutil, "which", lambda _: None)
        monkeypatch.delenv(spc_bridge.PAPERVAULT_DB_ENV, raising=False)

        check = build_spc_provider_check()

        assert check["check"] == "spc_provider"
        assert check["ok"] is True
        assert check["cli"] == "not installed"
