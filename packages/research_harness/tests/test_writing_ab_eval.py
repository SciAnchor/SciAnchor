"""Tests for the E1 A/B writing-quality harness (deterministic, fake generator)."""

from __future__ import annotations

import os

from research_harness._selfdev.writing_ab_eval import (
    CONDITIONS,
    build_report,
    condition_env,
    evaluate_section_text,
    paired_summary,
    run_condition,
)

CLEAN_TEXT = (
    "We study spatio-temporal demand forecasting for urban event scheduling. "
    "Our estimator combines a graph encoder with a calibrated head [1]. "
    "The design follows three constraints identified in prior work [2].\n\n"
    "The second paragraph reports the estimation protocol in concrete terms. "
    "We fit the model on 70/15/15 splits and report averaged results with "
    "standard deviations across five seeds [3]."
)

CLICHE_TEXT = (
    "In this rapidly evolving landscape, our groundbreaking approach paves the "
    "way for a paradigm shift. Leveraging the power of cutting-edge deep "
    "learning, we delve into the intricate interplay of factors.\n\n"
    "Moreover, it is important to note that our seamless integration "
    "underscores the transformative potential of this novel framework."
)


def test_condition_ladder_is_cumulative():
    assert CONDITIONS["C0"]["RESEARCH_HARNESS_EAG_SECTION_ARCS"] == "0"
    assert CONDITIONS["C1"]["RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN"] == "1"
    assert CONDITIONS["C1"]["RESEARCH_HARNESS_EAG_SECTION_ARCS"] == "0"
    assert CONDITIONS["C2"]["RESEARCH_HARNESS_EAG_SECTION_ARCS"] == "1"


def test_condition_env_applies_and_restores(monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", "1")
    with condition_env("C0"):
        assert os.environ["RESEARCH_HARNESS_EAG_SECTION_ARCS"] == "0"
    assert os.environ["RESEARCH_HARNESS_EAG_SECTION_ARCS"] == "1"

    monkeypatch.delenv("RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN", raising=False)
    with condition_env("C1"):
        assert os.environ["RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN"] == "1"
    assert "RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN" not in os.environ


def test_evaluate_section_text_scores_cliche_text_worse():
    clean = evaluate_section_text(CLEAN_TEXT, "method", planned_moves=2)
    dirty = evaluate_section_text(CLICHE_TEXT, "method")

    assert clean["words"] > 0 and clean["paragraphs"] == 2
    assert clean["structure_distance"] == 0
    assert dirty["violations"].get("ai_boilerplate")
    assert dirty["violation_density_per_1k"] > clean["violation_density_per_1k"]


def test_run_condition_and_paired_summary_prefer_cleaner_condition():
    # Fake generator: C0 produces cliche-ridden prose, C2 produces clean prose.
    def make_generator(text):
        return lambda topic_id, section: text

    records = run_condition(
        topics=[1, 2],
        sections=["method", "related_work"],
        condition="C0",
        generate=make_generator(CLICHE_TEXT),
    ) + run_condition(
        topics=[1, 2],
        sections=["method", "related_work"],
        condition="C2",
        generate=make_generator(CLEAN_TEXT),
    )

    summary = paired_summary(records)
    assert summary["conditions"]["C0"]["n"] == 4
    paired = summary["paired_vs_C0"]["C2"]
    assert paired["n_pairs"] == 4
    assert paired["wins"] == 4 and paired["losses"] == 0
    assert paired["mean_delta_violation_density"] < 0

    report = build_report(
        records=records, topics=[1, 2], sections=["method", "related_work"], seeds=1
    )
    assert report["schema"] == "rh.selfdev.writing_ab_eval.v1"
    assert len(report["records"]) == 8
    assert report["summary"]["paired_vs_C0"]["C2"]["wins"] == 4
