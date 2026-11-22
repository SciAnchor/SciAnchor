"""Tests for the false-open-rate calibration harness (no LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_harness.panorama.calibration import (
    CalibrationCase,
    evaluate_case,
    load_cases,
    prior_success_index,
    run_calibration,
)

SYNTHETIC_CASES = {
    "description": "Synthetic calibration set for load_cases tests.",
    "cases": [
        {
            "case_id": "s1-negative-control",
            "gap": "A synthetic gap whose automated verdict was correct.",
            "truth": "occupied",
            "judged_at": "2026-01-15",
            "preemptors": [{"title": "Synthetic Prior Work A", "arxiv_id": ""}],
            "notes": "Negative control.",
        },
        {
            "case_id": "s2-dated-preemptors",
            "gap": "A synthetic gap with dated pre-emptors.",
            "truth": "occupied",
            "judged_at": "2026-01-15",
            "preemptors": [
                {
                    "title": "Synthetic Prior Work B",
                    "arxiv_id": "2601.00001",
                    "published_ym": "2026-01",
                },
                {"title": "Synthetic Prior Work C", "arxiv_id": ""},
            ],
        },
        {
            "case_id": "s3-open-gap",
            "gap": "A synthetic gap that is genuinely open.",
            "truth": "open",
            "judged_at": "2026-01-20",
        },
    ],
}


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "calibration_cases.json"
    path.write_text(json.dumps(SYNTHETIC_CASES), encoding="utf-8")
    return path


def _case(**over) -> CalibrationCase:
    base = dict(
        case_id="c",
        gap="a gap",
        truth="occupied",
        preemptors=[{"title": "Killer Paper", "arxiv_id": "2604.00001"}],
        judged_at="2026-08-02",
    )
    base.update(over)
    return CalibrationCase(**base)


def test_load_cases_reads_fixture_cases(tmp_path):
    cases = load_cases(_write_fixture(tmp_path))
    assert [c.case_id for c in cases] == [
        "s1-negative-control",
        "s2-dated-preemptors",
        "s3-open-gap",
    ]
    occupied = [c for c in cases if c.truth == "occupied"]
    assert len(occupied) == 2
    assert all(c.preemptors for c in occupied)
    assert cases[2].preemptors == []
    assert all(c.judged_at.startswith("2026-01") for c in cases)
    assert cases[0].notes == "Negative control."
    assert cases[1].notes == ""


def test_occupied_truth_requires_preemptors():
    with pytest.raises(ValueError):
        _case(preemptors=[])


def test_false_open_and_judge_failure_are_separated():
    case = _case()
    # Pre-emptor retrieved but the judge still called the gap open.
    record = evaluate_case(
        case,
        {
            "verdict": "open",
            "occupying": [],
            "candidates": [{"title": "Killer Paper", "arxiv_id": "2604.00001"}],
        },
    )
    assert record["false_open"] is True
    assert record["missed_occupation"] is True
    assert record["preemptor_retrieved"] is True
    assert record["failure_mode"] == "judge"


def test_recall_failure_when_preemptor_never_retrieved():
    record = evaluate_case(
        _case(),
        {"verdict": "partially_occupied", "occupying": [], "candidates": []},
    )
    assert record["false_open"] is True
    assert record["failure_mode"] == "recall"


def test_correct_occupied_verdict_via_arxiv_id_match():
    record = evaluate_case(
        _case(),
        {
            "verdict": "occupied",
            "occupying": [{"title": "Different Spelling!", "arxiv_id": "2604.00001"}],
            "candidates": [{"title": "Different Spelling!", "arxiv_id": "2604.00001"}],
        },
    )
    assert record["missed_occupation"] is False
    assert record["preemptor_cited"] is True
    assert record["failure_mode"] == "none"


def test_missing_candidates_leaves_recall_unknown():
    record = evaluate_case(_case(), {"verdict": "open", "occupying": []})
    assert record["preemptor_retrieved"] is None
    assert "failure_mode" not in record


def test_run_calibration_aggregates_per_budget_and_isolates_errors():
    cases = [_case(case_id="a"), _case(case_id="b")]

    def verify(case: CalibrationCase, budget: int) -> dict:
        if case.case_id == "b" and budget == 5:
            raise RuntimeError("provider down")
        if budget >= 25:
            return {
                "verdict": "occupied",
                "occupying": [{"title": "Killer Paper", "arxiv_id": "2604.00001"}],
                "candidates": [{"title": "Killer Paper", "arxiv_id": "2604.00001"}],
            }
        return {"verdict": "open", "occupying": [], "candidates": []}

    out = run_calibration(cases, verify, budgets=[5, 25])
    low, high = out["curve"]
    assert low["n_cases"] == 1  # the crashed case is excluded, not scored
    assert low["errors"][0]["case_id"] == "b"
    assert low["false_open_rate"] == 1.0
    assert low["preemptor_retrieval_recall"] == 0.0
    assert high["n_cases"] == 2
    assert high["false_open_rate"] == 0.0
    assert high["missed_occupation_rate"] == 0.0
    assert high["judge_miss_rate_given_retrieved"] == 0.0
    assert out["resumed_cells"] == 0


def test_load_cases_keeps_published_ym_only_on_dated_preemptors(tmp_path):
    cases = {c.case_id: c for c in load_cases(_write_fixture(tmp_path))}
    s2 = {p["title"]: p for p in cases["s2-dated-preemptors"].preemptors}
    assert s2["Synthetic Prior Work B"]["published_ym"] == "2026-01"
    assert "published_ym" not in s2["Synthetic Prior Work C"]
    s1 = cases["s1-negative-control"].preemptors[0]
    assert "published_ym" not in s1


def test_prior_success_index_and_resume_skips_verify():
    cases = [_case(case_id="a"), _case(case_id="b")]
    prior = {
        "curve": [
            {
                "budget": 5,
                "records": [
                    {
                        "case_id": "a",
                        "truth": "occupied",
                        "verdict": "open",
                        "false_open": True,
                        "missed_occupation": True,
                        "preemptor_retrieved": False,
                        "failure_mode": "recall",
                    }
                ],
                "errors": [{"case_id": "b", "error": "502"}],
            }
        ]
    }
    assert set(prior_success_index(prior)) == {(5, "a")}
    calls: list[tuple[str, int]] = []

    def verify(case: CalibrationCase, budget: int) -> dict:
        calls.append((case.case_id, budget))
        return {
            "verdict": "occupied",
            "occupying": [{"title": "Killer Paper", "arxiv_id": "2604.00001"}],
            "candidates": [{"title": "Killer Paper", "arxiv_id": "2604.00001"}],
        }

    out = run_calibration(cases, verify, budgets=[5], prior=prior)
    assert out["resumed_cells"] == 1
    assert calls == [("b", 5)]  # prior error retried; a reused
    assert out["curve"][0]["n_cases"] == 2
    reused = next(r for r in out["curve"][0]["records"] if r["case_id"] == "a")
    assert reused["verdict"] == "open"
