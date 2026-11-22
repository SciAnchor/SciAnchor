"""Tests for the blind-submission disclosure checker.

Rule being enforced (user decision, 2026-08-08):

    The blind_submission package must mimic what a real submission in this
    scenario would release — and nothing more. Open data: description only, no
    payload. Internal data: partial, desensitized, with a scenario-appropriate
    justification. Give only what the paper cites as important and a reviewer
    would ask to see; never more.

The key insight that makes this coherent: **over-disclosure is itself a
detectable trace**. A real education study cannot release full individual
student records, so a package that contains them is anomalous on its face. The
checker therefore treats an undeclared asset as a failure, not a bonus.

Scope: only the mechanisable half. Whether the amount is *right* stays a human
and simulator judgement — this checks that everything present was declared,
justified, and of a permitted kind.

This checker is standalone. It is wired into no execution path, gates nothing
automatically, and must be run deliberately before blind review.
"""

from __future__ import annotations

import json

import pytest

from research_harness.reports.disclosure_check import (
    DISCLOSURE_CHECK_SCHEMA,
    check_disclosure_package,
)


def _manifest(**overrides) -> dict:
    manifest = {
        "schema": "rh.disclosure_manifest.v1",
        "episode_id": "demo-episode",
        "assets": [
            {
                "path": "manuscript/main.pdf",
                "role": "manuscript",
                "evidence_class": "observed",
                "justification": "the paper itself",
                "why_a_reviewer_would_ask": "primary object of review",
            },
            {
                "path": "data/sample_records.csv",
                "role": "internal_data_sample",
                "evidence_class": "derived_sample",
                "justification": "student records are privacy-restricted; a "
                "de-identified 200-row sample supports the descriptive table",
                "why_a_reviewer_would_ask": "verify Table 1 descriptives",
            },
        ],
    }
    manifest.update(overrides)
    return manifest


def _write(tmp_path, manifest, files):
    (tmp_path / "disclosure_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    pkg = tmp_path / "blind_submission"
    for rel in files:
        target = pkg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    return tmp_path / "disclosure_manifest.json", pkg


def test_schema_id_is_stable() -> None:
    assert DISCLOSURE_CHECK_SCHEMA == "rh.schema.report.disclosure_check.v1"


def test_declared_and_present_package_passes(tmp_path) -> None:
    mpath, pkg = _write(
        tmp_path, _manifest(), ["manuscript/main.pdf", "data/sample_records.csv"]
    )
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is True
    assert report["findings"] == []


def test_undeclared_asset_fails(tmp_path) -> None:
    """The mechanisable form of 'never give more than asked'."""
    mpath, pkg = _write(
        tmp_path,
        _manifest(),
        ["manuscript/main.pdf", "data/sample_records.csv", "data/full_records.csv"],
    )
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is False
    codes = {f["code"] for f in report["findings"]}
    assert "undeclared_asset" in codes
    assert any("full_records.csv" in f["path"] for f in report["findings"])


def test_declared_but_missing_asset_fails(tmp_path) -> None:
    mpath, pkg = _write(tmp_path, _manifest(), ["manuscript/main.pdf"])
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is False
    assert "declared_asset_missing" in {f["code"] for f in report["findings"]}


def test_internal_data_without_justification_fails(tmp_path) -> None:
    manifest = _manifest()
    manifest["assets"][1]["justification"] = ""
    mpath, pkg = _write(
        tmp_path, manifest, ["manuscript/main.pdf", "data/sample_records.csv"]
    )
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is False
    assert "internal_data_missing_justification" in {
        f["code"] for f in report["findings"]
    }


def test_open_data_payload_fails(tmp_path) -> None:
    """Open data gets a description, not a payload."""
    manifest = _manifest()
    manifest["assets"].append(
        {
            "path": "data/sba_7a_full.csv",
            "role": "open_data",
            "evidence_class": "observed",
            "justification": "public SBA data",
            "why_a_reviewer_would_ask": "check the sample",
        }
    )
    mpath, pkg = _write(
        tmp_path,
        manifest,
        ["manuscript/main.pdf", "data/sample_records.csv", "data/sba_7a_full.csv"],
    )
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is False
    assert "open_data_payload_included" in {f["code"] for f in report["findings"]}


def test_unknown_role_fails(tmp_path) -> None:
    manifest = _manifest()
    manifest["assets"][1]["role"] = "mystery"
    mpath, pkg = _write(
        tmp_path, manifest, ["manuscript/main.pdf", "data/sample_records.csv"]
    )
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is False
    assert "unknown_role" in {f["code"] for f in report["findings"]}


def test_missing_reviewer_rationale_fails(tmp_path) -> None:
    """Every asset must answer 'why would a reviewer ask for this?' — that is
    the question the rule is stated in terms of."""
    manifest = _manifest()
    manifest["assets"][0]["why_a_reviewer_would_ask"] = ""
    mpath, pkg = _write(
        tmp_path, manifest, ["manuscript/main.pdf", "data/sample_records.csv"]
    )
    report = check_disclosure_package(mpath, pkg)
    assert report["passed"] is False
    assert "missing_reviewer_rationale" in {f["code"] for f in report["findings"]}


def test_report_states_that_amount_is_not_checked(tmp_path) -> None:
    """The checker must not be mistaken for a judgement that the disclosure
    volume is correct — that half is deliberately left to a human."""
    mpath, pkg = _write(
        tmp_path, _manifest(), ["manuscript/main.pdf", "data/sample_records.csv"]
    )
    report = check_disclosure_package(mpath, pkg)
    assert "not_checked" in report
    assert any("amount" in item.lower() for item in report["not_checked"])


def test_missing_manifest_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        check_disclosure_package(tmp_path / "absent.json", tmp_path)
