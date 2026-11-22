"""Threshold gates for PDF-quality replay trajectories."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import (
    PDFQualityReplayTrajectory,
    PDFQualityTrajectoryGateResult,
    PDFQualityTrajectoryPoint,
)


DEFAULT_PDF_QUALITY_TRAJECTORY_THRESHOLDS: dict[str, int] = {
    "min_points": 2,
    "max_final_blocking_issue_count": 0,
    "max_final_recompile_repairable_issue_count": 0,
    "max_final_encoding_issue_count": 0,
    "max_final_invalid_utf8_count": 0,
    "max_final_malformed_latex_command_count": 0,
    "max_final_overfull_hbox_count": 0,
}


def evaluate_pdf_quality_replay_trajectory(
    trajectory: PDFQualityReplayTrajectory,
    *,
    thresholds: dict[str, int] | None = None,
) -> PDFQualityTrajectoryGateResult:
    """Evaluate whether a PDF-quality trajectory is ready for held-out replay.

    This gate does not promote a project-level skill by itself. It only verifies
    that the source topic's historical quality curve has reached a clean enough
    final state to justify held-out replay.
    """
    active_thresholds = {
        **DEFAULT_PDF_QUALITY_TRAJECTORY_THRESHOLDS,
        **(thresholds or {}),
    }
    points = tuple(sorted(trajectory.points, key=lambda point: point.artifact_id))
    checked_artifact_ids = tuple(
        point.artifact_id for point in points if point.artifact_id
    )
    metrics = _trajectory_metrics(points)
    reasons: list[str] = []

    if len(points) < active_thresholds["min_points"]:
        reasons.append(
            "trajectory has fewer than "
            f"{active_thresholds['min_points']} structured points"
        )

    if bool(trajectory.metadata.get("path_scan_used")) or any(
        point.path_scan_used for point in points
    ):
        reasons.append("trajectory used a historical path scan")

    if points:
        final = points[-1]
        _append_final_threshold_reasons(
            reasons,
            final=final,
            thresholds=active_thresholds,
        )
        _append_regression_reasons(reasons, points=points)

    if reasons:
        return PDFQualityTrajectoryGateResult(
            action="refine",
            passed=False,
            reasons=tuple(reasons),
            checked_artifact_ids=checked_artifact_ids,
            thresholds=active_thresholds,
            metrics=metrics,
            metadata={
                "target_profile": trajectory.target_profile,
                "topic_id": trajectory.topic_id,
            },
        )

    return PDFQualityTrajectoryGateResult(
        action="ready_for_held_out_replay",
        passed=True,
        reasons=(
            "source trajectory meets final PDF quality thresholds; run held-out replay",
        ),
        checked_artifact_ids=checked_artifact_ids,
        thresholds=active_thresholds,
        metrics=metrics,
        metadata={
            "target_profile": trajectory.target_profile,
            "topic_id": trajectory.topic_id,
        },
    )


def record_pdf_quality_trajectory_gate_report(
    orchestrator_service: Any,
    *,
    topic_id: int,
    result: PDFQualityTrajectoryGateResult,
    stage: str = "project_self_evolution",
    dependency_artifact_ids: list[int] | None = None,
) -> Any:
    """Persist a trajectory threshold gate result through the orchestrator."""
    return orchestrator_service.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="pdf_quality_trajectory_gate_report",
        title="PDF quality trajectory gate report",
        payload={
            "schema_version": 1,
            "result": asdict(result),
        },
        metadata={
            "source": "project_self_evolution",
            "action": result.action,
            "passed": result.passed,
            "checked_artifact_ids": result.checked_artifact_ids,
        },
        dependency_artifact_ids=dependency_artifact_ids or [],
        dependency_type="derived_from",
    )


def _trajectory_metrics(
    points: tuple[PDFQualityTrajectoryPoint, ...],
) -> dict[str, Any]:
    if not points:
        return {"point_count": 0}
    first = points[0]
    final = points[-1]
    return {
        "point_count": len(points),
        "first_artifact_id": first.artifact_id,
        "final_artifact_id": final.artifact_id,
        "issue_count_delta": final.issue_count - first.issue_count,
        "blocking_issue_delta": (
            final.blocking_issue_count - first.blocking_issue_count
        ),
        "recompile_repairable_delta": (
            final.recompile_repairable_issue_count
            - first.recompile_repairable_issue_count
        ),
        "layout_issue_delta": final.layout_issue_count - first.layout_issue_count,
        "encoding_issue_delta": final.encoding_issue_count - first.encoding_issue_count,
        "overfull_hbox_delta": final.overfull_hbox_count - first.overfull_hbox_count,
        "underfull_hbox_delta": (
            final.underfull_hbox_count - first.underfull_hbox_count
        ),
        "invalid_utf8_delta": final.invalid_utf8_count - first.invalid_utf8_count,
        "malformed_latex_command_delta": (
            final.malformed_latex_command_count - first.malformed_latex_command_count
        ),
        "final_issue_count": final.issue_count,
        "final_blocking_issue_count": final.blocking_issue_count,
        "final_recompile_repairable_issue_count": (
            final.recompile_repairable_issue_count
        ),
        "final_layout_issue_count": final.layout_issue_count,
        "final_encoding_issue_count": final.encoding_issue_count,
        "final_overfull_hbox_count": final.overfull_hbox_count,
        "final_underfull_hbox_count": final.underfull_hbox_count,
        "final_invalid_utf8_count": final.invalid_utf8_count,
        "final_malformed_latex_command_count": (final.malformed_latex_command_count),
    }


def _append_final_threshold_reasons(
    reasons: list[str],
    *,
    final: PDFQualityTrajectoryPoint,
    thresholds: dict[str, int],
) -> None:
    checks = (
        (
            "blocking issue",
            final.blocking_issue_count,
            thresholds["max_final_blocking_issue_count"],
        ),
        (
            "recompile-repairable issue",
            final.recompile_repairable_issue_count,
            thresholds["max_final_recompile_repairable_issue_count"],
        ),
        (
            "encoding issue",
            final.encoding_issue_count,
            thresholds["max_final_encoding_issue_count"],
        ),
        (
            "Invalid UTF-8",
            final.invalid_utf8_count,
            thresholds["max_final_invalid_utf8_count"],
        ),
        (
            "malformed LaTeX command",
            final.malformed_latex_command_count,
            thresholds["max_final_malformed_latex_command_count"],
        ),
        (
            "overfull hbox",
            final.overfull_hbox_count,
            thresholds["max_final_overfull_hbox_count"],
        ),
    )
    for label, observed, allowed in checks:
        if observed > allowed:
            reasons.append(
                f"final {label} count {observed} exceeds threshold {allowed}"
            )


def _append_regression_reasons(
    reasons: list[str],
    *,
    points: tuple[PDFQualityTrajectoryPoint, ...],
) -> None:
    if len(points) < 2:
        return
    previous = points[-2]
    final = points[-1]
    checks = (
        ("blocking issue", final.blocking_issue_count, previous.blocking_issue_count),
        (
            "recompile-repairable issue",
            final.recompile_repairable_issue_count,
            previous.recompile_repairable_issue_count,
        ),
        ("encoding issue", final.encoding_issue_count, previous.encoding_issue_count),
        ("Invalid UTF-8", final.invalid_utf8_count, previous.invalid_utf8_count),
        (
            "malformed LaTeX command",
            final.malformed_latex_command_count,
            previous.malformed_latex_command_count,
        ),
        ("overfull hbox", final.overfull_hbox_count, previous.overfull_hbox_count),
    )
    for label, final_count, previous_count in checks:
        if final_count > previous_count:
            reasons.append(
                f"final {label} count regressed from {previous_count} to {final_count}"
            )
