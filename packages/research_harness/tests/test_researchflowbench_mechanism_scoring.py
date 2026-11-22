from __future__ import annotations

from research_harness.eval.researchflowbench.mechanism_scoring import (
    score_artifact_mechanisms,
    score_artifact_trace,
    score_baseline_governance,
    score_rollback,
)


def _codes(score) -> set[str]:
    return {diagnostic.code for diagnostic in score.diagnostics}


def _mechanism_scores(report):
    return {score.mechanism: score for score in report.mechanism_scores}


def test_artifact_trace_accepts_dependency_edges_or_explicit_blockers():
    traced = score_artifact_trace(
        {
            "artifacts": [
                {"artifact_id": "draft.1", "artifact_type": "draft_pack"},
                {"artifact_id": "pack.1", "artifact_type": "publication_pack"},
            ],
            "dependencies": [
                {
                    "source_artifact_id": "draft.1",
                    "target_artifact_id": "pack.1",
                    "dependency_type": "derived_from",
                }
            ],
        }
    )

    assert traced.passed
    assert traced.score == 1.0
    assert "publication_pack_missing_upstream_trace" not in _codes(traced)

    blocked = score_artifact_trace(
        {
            "artifacts": [
                {"artifact_id": "pack.2", "artifact_type": "publication_pack"}
            ],
            "gate_decisions": [
                {
                    "gate_decision_artifact_id": "gate.2",
                    "target_artifact_ids": ["pack.2"],
                    "verdict": "block",
                    "reason_code": "missing_artifact_trace",
                }
            ],
            "review_issues": [
                {
                    "review_issue_id": "issue.trace",
                    "target_artifact_ids": ["pack.2"],
                    "status": "open",
                    "reason_code": "missing_artifact_trace",
                }
            ],
        }
    )

    assert blocked.passed
    assert blocked.score == 1.0
    assert "publication_pack_trace_blocked" in _codes(blocked)


def test_artifact_trace_rejects_unblocked_publication_pack_without_trace():
    score = score_artifact_trace(
        {
            "artifacts": [
                {"artifact_id": "pack.missing", "artifact_type": "publication_pack"}
            ]
        }
    )

    assert not score.passed
    assert score.score == 0.0
    assert "publication_pack_missing_upstream_trace" in _codes(score)


def test_artifact_trace_rejects_payload_ref_to_missing_artifact():
    score = score_artifact_trace(
        {
            "artifacts": [
                {
                    "artifact_id": "pack.bad",
                    "artifact_type": "publication_pack",
                    "payload": {"artifact_refs": ["draft.missing"]},
                }
            ]
        }
    )

    assert not score.passed
    assert "publication_pack_missing_upstream_trace" in _codes(score)


def test_artifact_trace_rejects_mixed_valid_and_invalid_payload_refs():
    score = score_artifact_trace(
        {
            "artifacts": [
                {"artifact_id": "draft.1", "artifact_type": "draft_pack"},
                {"artifact_id": "gap.1", "artifact_type": "gap_detect"},
                {
                    "artifact_id": "pack.bad",
                    "artifact_type": "publication_pack",
                    "payload": {"artifact_refs": ["draft.1", "gap.1"]},
                },
            ]
        }
    )

    assert not score.passed
    assert "publication_pack_missing_upstream_trace" in _codes(score)


def test_rollback_event_requires_traceable_review_gate_and_stale_source_coverage():
    complete = score_rollback(
        {
            "artifacts": [
                {"artifact_id": "source.1", "artifact_type": "paper", "state": "stale"}
            ],
            "rollback_events": [
                {
                    "rollback_event_id": "rollback.1",
                    "stale_source_artifact_id": "source.1",
                    "affected_artifact_ids": ["source.1", "draft.1"],
                    "rollback_cone": {
                        "affected_artifact_ids": ["source.1", "draft.1"],
                    },
                    "gate_decision_artifact_id": "gate.rollback",
                    "review_issue_ids": ["issue.stale"],
                }
            ],
        }
    )

    assert complete.passed
    assert complete.score == 1.0

    incomplete = score_rollback(
        {
            "artifacts": [
                {"artifact_id": "source.1", "artifact_type": "paper", "state": "stale"}
            ],
            "rollback_events": [
                {
                    "rollback_event_id": "rollback.bad",
                    "affected_artifact_ids": ["draft.1"],
                    "rollback_cone": {"affected_artifact_ids": ["draft.1"]},
                }
            ],
        }
    )

    assert not incomplete.passed
    assert {
        "rollback_event_missing_gate_decision_artifact_id",
        "rollback_event_missing_review_issue_ids",
        "rollback_event_missing_stale_source_coverage",
    }.issubset(_codes(incomplete))


def test_rollback_scoring_accepts_runtime_trigger_artifact_ids_payload():
    score = score_rollback(
        {
            "rollback_events": [
                {
                    "object_type": "rollback_event",
                    "trigger_artifact_ids": [10],
                    "affected_artifact_ids": [10, 11],
                    "rollback_cone": {
                        "trigger_artifact_ids": [10],
                        "affected_artifact_ids": [10, 11],
                    },
                    "gate_decision_artifact_id": 20,
                    "review_issue_ids": [30],
                }
            ],
        }
    )

    assert score.passed
    assert score.score == 1.0


def test_baseline_governance_covers_required_axes_and_flags_stale_baselines():
    score = score_baseline_governance(
        {
            "required_families": ["transformer", "retrieval_augmented"],
            "required_facets": ["method", "dataset"],
            "baseline_matrix": [
                {
                    "baseline_id": "baseline.current",
                    "family": "transformer",
                    "facets": {"method": "encoder", "dataset": "synthetic"},
                    "state": "current",
                },
                {
                    "baseline_id": "baseline.stale",
                    "family": "retrieval_augmented",
                    "facets": ["method", "dataset"],
                    "status": "stale",
                },
            ],
            "corrupted_case_ids": ["C05_false_novelty_missing_close_priors"],
            "gate_decisions": [
                {
                    "gate_decision_artifact_id": "gate.false_novelty",
                    "verdict": "block",
                    "reason_code": "false_novelty",
                    "reason": "Close prior baseline invalidates the novelty claim.",
                }
            ],
        }
    )

    assert score.passed
    assert score.score == 1.0
    assert "stale_baseline_detected" in _codes(score)


def test_baseline_governance_rejects_missing_matrix_coverage_and_false_novelty_reason():
    score = score_baseline_governance(
        {
            "required_families": ["transformer", "probabilistic"],
            "required_facets": ["method", "metric"],
            "baseline_matrix": [
                {
                    "baseline_id": "baseline.partial",
                    "family": "transformer",
                    "facets": ["method"],
                    "state": "current",
                }
            ],
            "corrupted_case_ids": ["C05_false_novelty_missing_close_priors"],
            "gate_decisions": [
                {
                    "gate_decision_artifact_id": "gate.novelty",
                    "verdict": "pass",
                    "reason": "Novelty claim accepted without close-prior analysis.",
                }
            ],
        }
    )

    assert not score.passed
    assert {
        "baseline_matrix_missing_required_family",
        "baseline_matrix_missing_required_facet",
        "false_novelty_gate_reason_missing",
    }.issubset(_codes(score))


def test_baseline_governance_does_not_count_required_facets_as_covered():
    score = score_baseline_governance(
        {
            "baseline_matrix": {
                "coverage": {
                    "required_facets": ["human_eval"],
                    "covered_facets": [],
                },
                "baselines": [
                    {
                        "baseline_id": "baseline.partial",
                        "family": "survey",
                        "facets": ["benchmark_coverage"],
                    }
                ],
            },
        },
        required_facets=["human_eval"],
    )

    assert not score.passed
    assert "baseline_matrix_missing_required_facet" in _codes(score)


def test_baseline_governance_reads_required_axes_from_runtime_coverage():
    score = score_baseline_governance(
        {
            "baseline_matrix": {
                "coverage": {
                    "required_families": ["transformer"],
                    "covered_families": ["retrieval"],
                    "required_facets": ["human_eval"],
                    "covered_facets": ["benchmark_coverage"],
                },
                "baselines": [
                    {
                        "baseline_id": "retrieval-only",
                        "method_family": "retrieval",
                        "facets": ["benchmark_coverage"],
                    }
                ],
            },
        },
    )

    assert not score.passed
    assert {
        "baseline_matrix_missing_required_family",
        "baseline_matrix_missing_required_facet",
    }.issubset(_codes(score))


def test_baseline_governance_does_not_count_false_mapping_values_as_covered():
    score = score_baseline_governance(
        {
            "baseline_matrix": {
                "families": {"transformer": False},
                "facets": {"human_eval": False},
            },
        },
        required_families=["transformer"],
        required_facets=["human_eval"],
    )

    assert not score.passed
    assert {
        "baseline_matrix_missing_required_family",
        "baseline_matrix_missing_required_facet",
    }.issubset(_codes(score))


def test_mechanism_scoring_report_aggregates_all_stage_a_mechanisms():
    report = score_artifact_mechanisms(
        {
            "artifacts": [
                {"artifact_id": "source.1", "artifact_type": "paper", "state": "stale"},
                {"artifact_id": "draft.1", "artifact_type": "draft_pack"},
                {
                    "artifact_id": "pack.1",
                    "artifact_type": "publication_pack",
                    "payload": {"artifact_refs": ["draft.1"]},
                },
            ],
            "rollback_events": [
                {
                    "rollback_event_id": "rollback.1",
                    "stale_source_artifact_id": "source.1",
                    "affected_artifact_ids": ["source.1", "draft.1"],
                    "rollback_cone": {"affected_artifact_ids": ["source.1", "draft.1"]},
                    "gate_decision_artifact_id": "gate.rollback",
                    "review_issue_ids": ["issue.stale"],
                }
            ],
            "required_families": ["transformer"],
            "required_facets": ["method"],
            "baseline_matrix": [
                {
                    "baseline_id": "baseline.current",
                    "family": "transformer",
                    "facets": {"method": "encoder"},
                }
            ],
        }
    )

    by_mechanism = _mechanism_scores(report)

    assert report.passed
    assert report.score == 1.0
    assert set(by_mechanism) == {
        "artifact_trace",
        "rollback",
        "baseline_governance",
    }
    assert report.to_dict()["mechanism_scores"][0]["diagnostics"] == []
