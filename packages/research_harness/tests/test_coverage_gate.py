"""BUG-016: experiment-category coverage for the manuscript."""

from __future__ import annotations

import pytest

from research_harness.experiment.coverage_gate import (
    detect_experiment_categories,
    evaluate_ablation_evidence,
    evaluate_ablation_payload,
    experiment_coverage_findings,
)
from research_harness.knowledge.experiment_design import ExperimentDesignBrief
from research_harness.orchestrator.service import OrchestratorService
from research_harness.storage.db import Database


def test_detect_experiment_categories():
    text = "We compare against baselines and run an ablation study."
    cats = detect_experiment_categories(text)
    assert "baseline" in cats
    assert "ablation" in cats
    assert "sensitivity" not in cats


def _topic(db: Database) -> int:
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name, description) VALUES ('t', 'x')")
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_coverage_findings_flag_missing_categories(db):
    topic_id = _topic(db)
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="section_draft",
        title="Experiments",
        payload={
            "section": "experiments",
            "content": "We compare against strong baselines and ablate each module.",
        },
    )

    findings = experiment_coverage_findings(db, topic_id)
    categories = {f["category"] for f in findings}
    # baseline + ablation present -> not flagged; sensitivity + explainability missing.
    assert categories == {"sensitivity", "explainability"}


def test_coverage_is_quiet_before_experiment_sections_exist(db):
    topic_id = _topic(db)
    OrchestratorService(db).record_artifact(
        topic_id=topic_id,
        stage="build",
        artifact_type="section_draft",
        title="Related Work",
        payload={"section": "related_work", "content": "background only"},
    )
    # No experiments/results/method section yet -> no coverage warnings.
    assert experiment_coverage_findings(db, topic_id) == []


def _brief(
    *,
    canonical_components: tuple[str, ...] = ("retriever", "reranker"),
    repeats: int = 3,
    acceptance_criteria: tuple[str, ...] = ("primary metric improves",),
) -> ExperimentDesignBrief:
    return ExperimentDesignBrief(
        schema_version="experiment_design_brief.v1",
        topic_id=1,
        opportunity_id="opportunity-1",
        support_level="evidence_bound",
        abstract_challenge="retrieval_quality",
        hypothesis="Each component improves retrieval quality.",
        target_task="paper retrieval",
        target_data_slice="held-out queries",
        baselines=("BM25",),
        metrics=("recall@k",),
        ablations=("retriever", "reranker"),
        failure_slices=("tail queries",),
        stress_tests=("query shift",),
        expected_outputs=("ablation table",),
        acceptance_criteria=acceptance_criteria,
        warnings=(),
        evidence_anchors=(),
        canonical_components=canonical_components,
        repeats=repeats,
    )


def test_ablation_evidence_blocks_and_names_missing_components() -> None:
    result = evaluate_ablation_evidence(
        _brief(canonical_components=("retriever", "reranker", "fusion")),
        ablation_components=("retriever",),
    )

    assert result["verdict"] == "blocked"
    assert result["missing_components"] == ["reranker", "fusion"]
    assert result["blockers"] == ["ablation_component_mismatch"]


@pytest.mark.parametrize(
    "ablation_components",
    [
        ("reranker", "retriever"),
        ("retriever", "reranker", "fusion"),
    ],
)
def test_ablation_evidence_blocks_reordered_or_extra_components(
    ablation_components: tuple[str, ...],
) -> None:
    result = evaluate_ablation_evidence(
        _brief(),
        ablation_components=ablation_components,
    )

    assert result["verdict"] == "blocked"
    assert result["ablation_components"] == list(ablation_components)


def test_ablation_evidence_reports_duplicate_components() -> None:
    result = evaluate_ablation_evidence(
        _brief(),
        ablation_components=("retriever", "retriever", "reranker"),
    )

    assert result["verdict"] == "blocked"
    assert result["duplicate_components"] == ["retriever"]
    assert result["blockers"] == [
        "duplicate_ablation_components",
        "ablation_component_mismatch",
    ]


def test_ablation_evidence_passes_exact_ordered_final_coverage() -> None:
    result = evaluate_ablation_evidence(
        _brief(),
        ablation_components=("retriever", "reranker"),
    )

    assert result["verdict"] == "pass"
    assert result["order_matches"] is True
    assert result["missing_components"] == []
    assert result["extra_components"] == []


def test_effect_size_without_comparable_variance_is_unclear() -> None:
    result = evaluate_ablation_evidence(
        _brief(acceptance_criteria=("recall improves by at least 0.5%",)),
        ablation_components=("retriever", "reranker"),
        variance_estimates=(0.02,),
    )

    assert result["verdict"] == "unclear"
    assert result["effect_size_claims"] == ["recall improves by at least 0.5%"]
    assert result["has_comparable_variance"] is False


def test_effect_size_with_repeats_and_comparable_variance_passes() -> None:
    result = evaluate_ablation_evidence(
        _brief(acceptance_criteria=("recall improves by at least 0.5%",)),
        ablation_components=("retriever", "reranker"),
        variance_estimates=(0.02, 0.03),
    )

    assert result["verdict"] == "pass"
    assert result["has_comparable_variance"] is True


@pytest.mark.parametrize(
    "criterion",
    ["delta <= 0.002", "MAE under 0.12", "95% CI excludes zero"],
)
def test_quantitative_criteria_require_comparable_variance(criterion: str) -> None:
    result = evaluate_ablation_evidence(
        _brief(acceptance_criteria=(criterion,)),
        ablation_components=("retriever", "reranker"),
    )

    assert result["verdict"] == "unclear"
    assert result["effect_size_claims"] == [criterion]


@pytest.mark.parametrize(
    "evidence_kind", ["smoke", "debug", "subset", "mock", "synthetic"]
)
def test_non_final_evidence_cannot_satisfy_gate(evidence_kind: str) -> None:
    result = evaluate_ablation_evidence(
        _brief(),
        ablation_components=("retriever", "reranker"),
        evidence_kind=evidence_kind,
    )

    assert result["verdict"] == "blocked"
    assert result["blockers"] == ["non_final_evidence"]


def test_legacy_payload_does_not_opt_into_ablation_contract() -> None:
    assert evaluate_ablation_payload({"metrics": {"recall": 0.9}}) is None


def test_partial_or_malformed_ablation_contract_is_blocked() -> None:
    assert evaluate_ablation_payload({"canonical_components": ["retriever"]}) == {
        "verdict": "blocked",
        "blockers": ["invalid_contract"],
    }
    payload = {
        "canonical_components": ["retriever"],
        "ablation_components": ["retriever"],
        "repeats": 3,
        "variance_estimates": ["invalid"],
        "acceptance_criteria": ["primary metric improves"],
        "evidence_kind": "final",
    }
    assert evaluate_ablation_payload(payload) == {
        "verdict": "blocked",
        "blockers": ["invalid_contract"],
    }
    assert evaluate_ablation_payload({"metric_direction": "maximize"}) == {
        "verdict": "blocked",
        "blockers": ["invalid_contract"],
    }


def _memory_payload(
    *,
    component_provenance=None,
    ablation_outcomes=None,
) -> dict:
    default_provenance = [
        {
            "component_family": "retriever",
            "provenance_tag": "borrowed",
            "source_paper_id": 9,
        }
    ]
    provenance = (
        default_provenance if component_provenance is None else component_provenance
    )
    outcome_source = provenance[0] if provenance else default_provenance[0]
    outcomes = (
        ablation_outcomes
        if ablation_outcomes is not None
        else [
            {
                **outcome_source,
                "removal_effect": "hurt",
                "evidence": "observed accuracy: full=0.9, without_1=0.85",
            }
        ]
    )
    return {
        "canonical_components": ["retriever"],
        "ablation_components": ["retriever"],
        "repeats": 3,
        "variance_estimates": [0.0001],
        "acceptance_criteria": [],
        "evidence_kind": "final",
        "component_provenance": provenance,
        "metric_direction": "maximize",
        "ablation_outcomes": outcomes,
    }


def test_complete_ablation_memory_contract_passes() -> None:
    assert evaluate_ablation_payload(_memory_payload())["verdict"] == "pass"


@pytest.mark.parametrize(
    "payload",
    [
        _memory_payload(component_provenance=[]),
        _memory_payload(
            component_provenance=[
                {
                    "component_family": "reranker",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ]
        ),
        *[
            _memory_payload(
                component_provenance=[
                    {
                        "component_family": "retriever",
                        "provenance_tag": tag,
                        "source_paper_id": paper_id,
                    }
                ]
            )
            for tag, paper_id in (("borrowed", 0), ("modified", None))
        ],
        _memory_payload(
            component_provenance=[
                {
                    "component_family": "retriever",
                    "provenance_tag": "novel",
                    "source_paper_id": 9,
                }
            ]
        ),
        _memory_payload(ablation_outcomes=[]),
    ],
    ids=[
        "missing-provenance",
        "wrong-component",
        "borrowed-without-paper",
        "modified-without-paper",
        "novel-with-paper",
        "missing-observed-outcome",
    ],
)
def test_invalid_ablation_memory_contract_is_blocked(payload: dict) -> None:
    assert evaluate_ablation_payload(payload) == {
        "verdict": "blocked",
        "blockers": ["invalid_ablation_memory"],
    }
