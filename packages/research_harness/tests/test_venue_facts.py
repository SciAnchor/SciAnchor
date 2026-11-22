"""Tests for the single venue-fact lookup service (journal_master-backed)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from research_harness.venue_facts import (
    JOURNAL_MASTER_DB_ENV,
    CASQuartile,
    CCFTier,
    _db_tier,
    build_venue_facts_check,
    get_venue_tier,
    meets_tier_threshold,
    venue_tier_score,
)


@pytest.fixture(autouse=True)
def _no_journal_master(monkeypatch):
    """Default: no DB configured; DB tests opt in via _fixture_db."""
    monkeypatch.delenv(JOURNAL_MASTER_DB_ENV, raising=False)
    _db_tier.cache_clear()


def _build_journal_master(path: Path, records: dict[str, dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE journal_records (normalized_name TEXT PRIMARY KEY,"
        " original_name TEXT, facts_json TEXT)"
    )
    for normalized_name, facts in records.items():
        conn.execute(
            "INSERT INTO journal_records VALUES (?, ?, ?)",
            (normalized_name, facts.get("journal_name", ""), json.dumps(facts)),
        )
    conn.commit()
    conn.close()


def _fixture_db(tmp_path: Path, monkeypatch) -> Path:
    db_path = tmp_path / "journal_master.db"
    _build_journal_master(
        db_path,
        {
            "naturemachineintelligence": {
                "journal_name": "Nature Machine Intelligence",
                "cas": {"zone": 1, "top_journal": True},
            },
            "journaloffabricatedcomputing": {
                "journal_name": "Journal of Fabricated Computing",
                "ccf": {"rank": "B", "type": "journal"},
                "cas": {"zone": 2},
            },
        },
    )
    monkeypatch.setenv(JOURNAL_MASTER_DB_ENV, str(db_path))
    return db_path


# --- offline (DB absent) --------------------------------------------------


def test_db_absent_uses_hardcoded_registry() -> None:
    tier = get_venue_tier("NeurIPS")
    assert tier.ccf == CCFTier.A_STAR
    assert tier.score == 100


def test_db_absent_unknown_journal_scores_zero() -> None:
    assert venue_tier_score("Journal of Fabricated Computing") == 0


# --- DB-backed lookup -----------------------------------------------------


def test_db_journal_ccf_and_cas(tmp_path, monkeypatch) -> None:
    _fixture_db(tmp_path, monkeypatch)
    tier = get_venue_tier("Journal of Fabricated Computing")
    assert tier.ccf == CCFTier.B
    assert tier.cas == CASQuartile.Q2
    assert tier.score == 70


def test_db_cas_only_journal(tmp_path, monkeypatch) -> None:
    _fixture_db(tmp_path, monkeypatch)
    tier = get_venue_tier("Nature Machine Intelligence")
    assert tier.ccf == CCFTier.NONE
    assert tier.cas == CASQuartile.Q1
    assert tier.score == 85


def test_registry_conference_wins_before_db(tmp_path, monkeypatch) -> None:
    _fixture_db(tmp_path, monkeypatch)
    assert get_venue_tier("ICML").ccf == CCFTier.A_STAR


def test_broken_db_degrades_to_offline(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "not-a-db.db"
    bad.write_text("hello")
    monkeypatch.setenv(JOURNAL_MASTER_DB_ENV, str(bad))
    assert get_venue_tier("NeurIPS").ccf == CCFTier.A_STAR
    assert venue_tier_score("Journal of Fabricated Computing") == 0


# --- substring-guard regressions -----------------------------------------


def test_oa_suffix_does_not_pollute_to_ccf_a() -> None:
    # Regression: "(OA)" suffix used to substring-match the short key "chi"
    # and come back as CCF-A.
    tier = get_venue_tier("Nature Machine Intelligence (OA)")
    assert tier.ccf == CCFTier.NONE
    assert tier.cas == CASQuartile.Q1


def test_science_china_does_not_hit_chi_or_science() -> None:
    tier = get_venue_tier("Science China Information Sciences")
    assert tier.ccf == CCFTier.NONE
    assert tier.score == 0


def test_generic_science_journal_not_matched() -> None:
    assert venue_tier_score("Journal of Medical Science") == 0


def test_word_boundary_fallback_still_matches_abbreviations() -> None:
    tier = get_venue_tier(
        "Proceedings of the AAAI Conference on Artificial Intelligence"
    )
    assert tier.ccf == CCFTier.A


# --- threshold normalization / fail-closed --------------------------------


def test_threshold_common_spellings_normalized() -> None:
    assert meets_tier_threshold("CVPR", "CCF-A") is True
    assert meets_tier_threshold("ECCV", "CCF-A") is False
    assert meets_tier_threshold("NeurIPS", "CCF-A*") is True
    assert meets_tier_threshold("TPAMI", "CAS Q1") is True


def test_threshold_unknown_fails_closed(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert meets_tier_threshold("NeurIPS", "nonsense-tier") is False
    assert any("nonsense-tier" in rec.getMessage() for rec in caplog.records)


def test_threshold_empty_always_passes() -> None:
    assert meets_tier_threshold("Unknown Workshop", "") is True


# --- doctor check ----------------------------------------------------------


def test_doctor_check_not_configured() -> None:
    check = build_venue_facts_check()
    assert check["check"] == "venue_facts"
    assert check["state"] == "not_configured"
    assert check["ok"] is True
    assert JOURNAL_MASTER_DB_ENV in check["remediation"][0]


def test_doctor_check_ready_reports_row_count(tmp_path, monkeypatch) -> None:
    _fixture_db(tmp_path, monkeypatch)
    check = build_venue_facts_check()
    assert check["state"] == "ready"
    assert check["ok"] is True
    assert check["journal_count"] == 2
    assert "remediation" not in check


def test_doctor_check_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(JOURNAL_MASTER_DB_ENV, str(tmp_path / "nope.db"))
    check = build_venue_facts_check()
    assert check["state"] == "missing"
    assert check["ok"] is True
