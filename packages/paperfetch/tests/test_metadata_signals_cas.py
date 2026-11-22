from __future__ import annotations

import json
import sqlite3
from argparse import Namespace
from unittest.mock import patch

from paperfetch.core.metadata_signals import (
    VenueCatalogLookup,
    journal_master_status,
)
from paperfetch.core.models import PaperRecord
from paperfetch.core.settings import reset_settings


def _write_master(path, records) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE journal_records (normalized_name TEXT PRIMARY KEY, original_name TEXT, facts_json TEXT)"
        )
        for record in records:
            conn.execute(
                "INSERT INTO journal_records VALUES (?, ?, ?)",
                (record["normalized_name"], record["journal_name"], json.dumps(record)),
            )


def test_cas_not_configured_degrades_quietly(monkeypatch) -> None:
    monkeypatch.delenv("SPC_JOURNAL_MASTER_DB", raising=False)
    reset_settings()
    with patch("paperfetch.core.metadata_signals.logger.warning") as warning:
        lookup = VenueCatalogLookup()
        assert lookup.find_cas("Nature") is None
        metadata = lookup.metadata_for(
            PaperRecord(paper_id="p1", title="x", journal="Nature")
        )

    warning.assert_not_called()
    assert metadata["cas_zone"] is None
    status = journal_master_status()
    assert status["configured"] is False
    assert status["error_class"] == "not_configured"


def test_cas_lookup_reads_user_supplied_master_from_env(tmp_path, monkeypatch) -> None:
    db = tmp_path / "journal_master.db"
    _write_master(
        db,
        [
            {
                "journal_name": "Nature",
                "normalized_name": "nature",
                "cas": {"zone": 1, "label": "1区", "top_journal": True},
            }
        ],
    )
    monkeypatch.setenv("SPC_JOURNAL_MASTER_DB", str(db))
    reset_settings()
    try:
        lookup = VenueCatalogLookup()
        match = lookup.find_cas("Nature")
        status = journal_master_status()
    finally:
        monkeypatch.delenv("SPC_JOURNAL_MASTER_DB")
        reset_settings()

    assert match == {
        "journal_name": "Nature",
        "zone": 1,
        "top_journal": True,
        "source": "journal_master_db",
    }
    assert status["ready"] is True
    assert status["journal_records"] == 1


def test_missing_cas_source_warns_only_when_queried_and_only_once(tmp_path) -> None:
    missing_db = tmp_path / "journal_master.db"

    with patch("paperfetch.core.metadata_signals.logger.warning") as warning:
        lookup = VenueCatalogLookup(cas_db_path=str(missing_db))
        warning.assert_not_called()
        assert lookup.find_cas("Nature") is None
        assert lookup.find_cas("Science") is None

    warning.assert_called_once()
    assert warning.call_args.args[-1] == "reference_data_missing"


def test_master_record_with_null_cas_is_not_a_zone(tmp_path) -> None:
    db = tmp_path / "journal_master.db"
    _write_master(
        db,
        [
            {
                "journal_name": "Computers in Biology and Medicine",
                "normalized_name": "computersinbiologyandmedicine",
                "cas": None,
                "jcr": None,
            }
        ],
    )
    lookup = VenueCatalogLookup(cas_db_path=str(db))
    assert lookup.find_cas("Computers in Biology and Medicine") is None


def test_doctor_reports_journal_master_not_configured(monkeypatch) -> None:
    from paperfetch.cli.doctor import _collect_doctor_checks

    monkeypatch.delenv("SPC_JOURNAL_MASTER_DB", raising=False)
    reset_settings()
    checks = {item["id"]: item for item in _collect_doctor_checks(Namespace())}
    item = checks["paper.metadata.journal_master"]
    assert item["verdict"] == "unknown"
    assert "SPC_JOURNAL_MASTER_DB" in item["message"]
    assert checks["paper.metadata.files"]["verdict"] == "ok"
