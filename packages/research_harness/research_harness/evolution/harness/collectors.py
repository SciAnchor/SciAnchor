"""MVP collectors for project-level self-evolution.

These helpers only support the v1 loop: manually archive deterministic
evaluation evidence, select champions, and assemble PDF/final-bundle replay
signals. They do not mutate code, prompts, skills, or workflow graphs.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .archive import (
    build_candidate_archive_record_from_researchflowbench_score,
    build_champion_registry_entries,
    record_candidate_archive_pack,
    record_champion_registry_pack,
)
from .models import (
    CandidateArchiveRecord,
    FinalBundleReplayCandidate,
    FinalBundleReplayDiscoveryReport,
    ImprovementCandidate,
    PDFQualityReplayTrajectory,
    PDFQualitySignal,
    PDFQualityTrajectoryPoint,
)
from .pdf_quality import scan_pdf_quality_bundle


def collect_pdf_quality_signals_from_final_bundles(
    db: Any,
    *,
    topic_id: int | None = None,
    limit: int = 20,
) -> tuple[PDFQualitySignal, ...]:
    """Scan active final-bundle artifacts for deterministic PDF quality issues."""
    clauses = [
        "artifact_type = 'final_bundle'",
        "status = 'active'",
        "(stale = 0 OR stale IS NULL)",
    ]
    params: list[Any] = []
    if topic_id is not None:
        clauses.append("topic_id = ?")
        params.append(topic_id)
    params.append(limit)

    conn = db.connect()
    try:
        rows = conn.execute(
            f"""
            SELECT id, topic_id, payload_json
            FROM project_artifacts
            WHERE {" AND ".join(clauses)}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return ()
    finally:
        conn.close()

    signals: list[PDFQualitySignal] = []
    for row in rows:
        payload = _decode_payload(str(row["payload_json"] or "{}"))
        paths = _final_bundle_paths(payload)
        signals.append(
            scan_pdf_quality_bundle(
                tex_path=paths["tex_path"],
                pdf_path=paths["pdf_path"],
                log_path=paths["log_path"],
                topic_id=int(row["topic_id"]),
                target_profile=str(payload.get("target_profile") or ""),
                artifact_id=int(row["id"]),
            )
        )
    return tuple(signals)


def collect_final_bundle_replay_signals(
    db: Any,
    *,
    source_topic_id: int | None = None,
    source_artifact_ids: tuple[int, ...] = (),
    target_profile: str = "",
    compatible_target_profiles: tuple[str, ...] = (),
    limit: int = 20,
    lifecycle_pack_payload: dict[str, Any] | None = None,
    include_controlled_backfills: bool = False,
) -> tuple[PDFQualitySignal, ...]:
    """Scan held-out active final bundles for deterministic replay.

    ``lifecycle_pack_payload`` and ``include_controlled_backfills`` are accepted
    for one-release compatibility with older callers, but v1 no longer consumes
    skill lifecycle records or controlled synthetic replay packs.
    """
    del lifecycle_pack_payload, include_controlled_backfills
    source_ids = {int(item) for item in source_artifact_ids if int(item)}
    profiles = {target_profile} if target_profile else set()
    compatible_profiles = set(compatible_target_profiles)

    clauses = [
        "artifact_type = 'final_bundle'",
        "status = 'active'",
        "(stale = 0 OR stale IS NULL)",
    ]
    params: list[Any] = []
    if source_topic_id is not None:
        clauses.append("topic_id != ?")
        params.append(source_topic_id)
    if source_ids:
        placeholders = ", ".join("?" for _ in source_ids)
        clauses.append(f"id NOT IN ({placeholders})")
        params.extend(sorted(source_ids))
    params.append(limit)

    conn = db.connect()
    try:
        rows = conn.execute(
            f"""
            SELECT id, topic_id, payload_json
            FROM project_artifacts
            WHERE {" AND ".join(clauses)}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return ()
    finally:
        conn.close()

    signals: list[PDFQualitySignal] = []
    for row in rows:
        payload = _decode_payload(str(row["payload_json"] or "{}"))
        row_profile = str(payload.get("target_profile") or "")
        profile_match = _target_profile_match(
            row_profile,
            profiles=profiles,
            compatible_profiles=compatible_profiles,
        )
        if profile_match is None:
            continue

        paths = _final_bundle_paths(payload)
        signal = scan_pdf_quality_bundle(
            tex_path=paths["tex_path"],
            pdf_path=paths["pdf_path"],
            log_path=paths["log_path"],
            topic_id=int(row["topic_id"]),
            target_profile=row_profile,
            artifact_id=int(row["id"]),
        )
        signals.append(
            _with_replay_metadata(
                signal,
                payload=payload,
                source_artifact_ids=source_ids,
                source_topic_id=source_topic_id,
                target_profile_match=profile_match,
            )
        )
    return tuple(signals)


def collect_final_bundle_replay_discovery_report(
    db: Any,
    *,
    source_topic_id: int | None = None,
    source_artifact_ids: tuple[int, ...] = (),
    target_profile: str = "",
    compatible_target_profiles: tuple[str, ...] = (),
    limit: int = 50,
) -> FinalBundleReplayDiscoveryReport:
    """Report which active final bundles are eligible held-out replay targets."""
    source_ids = {int(item) for item in source_artifact_ids if int(item)}
    profiles = {target_profile} if target_profile else set()
    compatible_profiles = set(compatible_target_profiles)

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, topic_id, payload_json
            FROM project_artifacts
            WHERE artifact_type = 'final_bundle'
              AND status = 'active'
              AND (stale = 0 OR stale IS NULL)
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    candidates: list[FinalBundleReplayCandidate] = []
    for row in rows:
        artifact_id = int(row["id"])
        row_topic_id = int(row["topic_id"])
        payload = _decode_payload(str(row["payload_json"] or "{}"))
        row_profile = str(payload.get("target_profile") or "")
        profile_match = _target_profile_match(
            row_profile,
            profiles=profiles,
            compatible_profiles=compatible_profiles,
        )
        reasons = _held_out_exclusion_reasons(
            artifact_id=artifact_id,
            topic_id=row_topic_id,
            target_profile_match=profile_match,
            source_topic_id=source_topic_id,
            source_artifact_ids=source_ids,
        )
        candidates.append(
            FinalBundleReplayCandidate(
                artifact_id=artifact_id,
                topic_id=row_topic_id,
                target_profile=row_profile,
                accepted=not reasons,
                exclusion_reasons=tuple(reasons),
                metadata={
                    "target_profile_match": profile_match or "",
                    "source": "active_final_bundle",
                },
            )
        )

    accepted_ids = tuple(
        candidate.artifact_id for candidate in candidates if candidate.accepted
    )
    return FinalBundleReplayDiscoveryReport(
        source_topic_id=source_topic_id or 0,
        source_artifact_ids=tuple(sorted(source_ids)),
        target_profiles=tuple(sorted(profiles | compatible_profiles)),
        candidates=tuple(candidates),
        accepted_artifact_ids=accepted_ids,
        metadata={
            "candidate_count": len(candidates),
            "accepted_count": len(accepted_ids),
            "source": "active_final_bundle",
        },
    )


def record_final_bundle_replay_discovery_report(
    orchestrator_service: Any,
    *,
    topic_id: int,
    report: FinalBundleReplayDiscoveryReport,
    stage: str = "project_self_evolution",
) -> Any:
    """Persist a held-out replay discovery report."""
    return orchestrator_service.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="final_bundle_replay_discovery_report",
        title="Final bundle replay discovery report",
        payload={
            "schema_version": 1,
            "source_topic_id": report.source_topic_id,
            "source_artifact_ids": list(report.source_artifact_ids),
            "target_profiles": list(report.target_profiles),
            "accepted_artifact_ids": list(report.accepted_artifact_ids),
            "candidates": [
                {
                    "artifact_id": candidate.artifact_id,
                    "topic_id": candidate.topic_id,
                    "target_profile": candidate.target_profile,
                    "accepted": candidate.accepted,
                    "exclusion_reasons": list(candidate.exclusion_reasons),
                    "metadata": candidate.metadata,
                }
                for candidate in report.candidates
            ],
            "metadata": report.metadata,
        },
        metadata={
            "source": "project_self_evolution",
            "accepted_count": len(report.accepted_artifact_ids),
        },
        dependency_artifact_ids=list(report.source_artifact_ids),
        dependency_type="derived_from",
    )


def collect_candidate_archive_records_from_artifacts(
    db: Any,
    *,
    topic_id: int | None = None,
    limit: int = 100,
) -> tuple[CandidateArchiveRecord, ...]:
    """Build archive records from durable ResearchFlowBench artifacts."""
    rows = _archive_source_artifact_rows(db, topic_id=topic_id, limit=limit)
    records: list[CandidateArchiveRecord] = []
    for row in rows:
        artifact_type = str(row["artifact_type"] or "")
        artifact_id = int(row["id"])
        payload = _decode_payload(str(row["payload_json"] or "{}"))
        source_ref = f"project_artifacts:{artifact_id}:{artifact_type}"
        records.extend(
            _archive_records_from_researchflowbench_payload(
                payload,
                artifact_id=artifact_id,
                source_ref=source_ref,
            )
        )
    return tuple(records)


def record_self_evolution_archive_from_artifacts(
    orchestrator_service: Any,
    db: Any,
    *,
    topic_id: int,
    stage: str = "project_self_evolution",
    limit: int = 100,
) -> dict[str, Any]:
    """Persist archive and champion packs from already-recorded eval evidence."""
    records = collect_candidate_archive_records_from_artifacts(
        db,
        topic_id=topic_id,
        limit=limit,
    )
    dependency_artifact_ids = _existing_artifact_ids(
        db,
        _dependency_artifact_ids(records),
    )
    archive_artifact = record_candidate_archive_pack(
        orchestrator_service,
        topic_id=topic_id,
        records=records,
        stage=stage,
        dependency_artifact_ids=dependency_artifact_ids,
    )
    champion_entries = build_champion_registry_entries(records)
    champion_artifact = record_champion_registry_pack(
        orchestrator_service,
        topic_id=topic_id,
        entries=champion_entries,
        stage=stage,
        dependency_artifact_ids=dependency_artifact_ids,
    )
    return {
        "schema_version": 1,
        "record_count": len(records),
        "champion_entry_count": len(champion_entries),
        "archive_artifact_id": getattr(archive_artifact, "id", None),
        "champion_artifact_id": getattr(champion_artifact, "id", None),
        "dependency_artifact_ids": dependency_artifact_ids,
        "mutation_performed": False,
    }


def collect_pdf_quality_replay_trajectory(
    db: Any,
    *,
    topic_id: int,
    target_profile: str = "",
    limit: int = 100,
) -> PDFQualityReplayTrajectory:
    """Build a path-safe trajectory from durable PDF quality snapshots."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, topic_id, artifact_type, payload_json
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type IN (
                  'final_bundle',
                  'pdf_quality_snapshot_backfill',
                  'research_state_update',
                  'pdf_quality_replay_trajectory'
              )
            ORDER BY id ASC
            LIMIT ?
            """,
            (topic_id, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return PDFQualityReplayTrajectory(
            topic_id=topic_id,
            target_profile=target_profile,
            points=(),
            metadata={"path_scan_used": False, "source": "durable_payload"},
        )
    finally:
        conn.close()

    points: list[PDFQualityTrajectoryPoint] = []
    for row in rows:
        payload = _decode_payload(str(row["payload_json"] or "{}"))
        artifact_type = str(row["artifact_type"] or "")
        source = f"project_artifacts:{int(row['id'])}:{artifact_type}"
        points.extend(
            _trajectory_points_from_payload(
                payload,
                artifact_type=artifact_type,
                row_topic_id=int(row["topic_id"]),
                evidence_source=source,
            )
        )

    filtered = tuple(
        point
        for point in _dedupe_trajectory_points(points)
        if not target_profile or point.target_profile == target_profile
    )
    return PDFQualityReplayTrajectory(
        topic_id=topic_id,
        target_profile=target_profile,
        points=filtered,
        metadata={
            "path_scan_used": False,
            "source": "durable_payload",
            "point_count": len(filtered),
        },
    )


def _archive_source_artifact_rows(
    db: Any,
    *,
    topic_id: int | None,
    limit: int,
) -> list[Any]:
    clauses = [
        "artifact_type IN ('researchflowbench_eval_result', 'researchflowbench_score_report')",
        "status = 'active'",
        "(stale = 0 OR stale IS NULL)",
    ]
    params: list[Any] = []
    if topic_id is not None:
        clauses.append("topic_id = ?")
        params.append(topic_id)
    params.append(limit)

    conn = db.connect()
    try:
        return list(
            conn.execute(
                f"""
                SELECT id, artifact_type, payload_json
                FROM project_artifacts
                WHERE {" AND ".join(clauses)}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _archive_records_from_researchflowbench_payload(
    payload: dict[str, Any],
    *,
    artifact_id: int,
    source_ref: str,
) -> tuple[CandidateArchiveRecord, ...]:
    benchmark_id = _benchmark_id(payload)
    gate_action = str(payload.get("gate_action") or "evaluate")
    records: list[CandidateArchiveRecord] = []
    for index, score in enumerate(_score_payloads(payload), start=1):
        task_id = _task_id(score, fallback=f"{benchmark_id}.task{index}")
        split = _replay_split_role(score.get("split") or payload.get("split"))
        candidate = _researchflowbench_candidate(
            benchmark_id=benchmark_id,
            task_id=task_id,
            score=score,
            source_ref=source_ref,
        )
        records.append(
            build_candidate_archive_record_from_researchflowbench_score(
                candidate,
                benchmark_id=benchmark_id,
                task_id=task_id,
                score={
                    **score,
                    "source_refs": tuple(score.get("source_refs") or (source_ref,)),
                    "promotion_test_refs": tuple(
                        score.get("promotion_test_refs") or ()
                    ),
                    "held_out_refs": tuple(score.get("held_out_refs") or ()),
                },
                split=split,
                gate_action=gate_action,
                artifact_refs=(source_ref,),
            )
        )
    return tuple(records)


def _researchflowbench_candidate(
    *,
    benchmark_id: str,
    task_id: str,
    score: dict[str, Any],
    source_ref: str,
) -> ImprovementCandidate:
    candidate_id = str(
        score.get("candidate_id")
        or _stable_id("candidate", "researchflowbench", benchmark_id, task_id)
    )
    finding_id = str(
        score.get("finding_id")
        or _stable_id("finding", "researchflowbench", benchmark_id, task_id)
    )
    return ImprovementCandidate(
        candidate_id=candidate_id,
        finding_id=finding_id,
        title=f"ResearchFlowBench {benchmark_id} {task_id}",
        target_kind=str(score.get("target_kind") or f"benchmark:{benchmark_id}"),
        affected_surfaces=("eval", "retrieval", "workflow"),
        priority_score=_int_value(score.get("priority_score")) or 1,
        verification_plan=("Archive deterministic replay evidence.",),
        status=str(score.get("candidate_status") or "verified"),
        patch_allowed=False,
        metadata={"source_ref": source_ref, "benchmark_id": benchmark_id},
    )


def _dependency_artifact_ids(records: tuple[CandidateArchiveRecord, ...]) -> list[int]:
    artifact_ids: list[int] = []
    for record in records:
        for ref in record.artifact_refs:
            parts = ref.split(":")
            if len(parts) >= 2 and parts[0] == "project_artifacts":
                artifact_id = _int_value(parts[1])
                if artifact_id:
                    artifact_ids.append(artifact_id)
    return sorted(set(artifact_ids))


def _existing_artifact_ids(db: Any, artifact_ids: list[int]) -> list[int]:
    if not artifact_ids:
        return []
    placeholders = ", ".join("?" for _ in artifact_ids)
    conn = db.connect()
    try:
        rows = conn.execute(
            f"SELECT id FROM project_artifacts WHERE id IN ({placeholders})",
            artifact_ids,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return sorted(int(row["id"]) for row in rows)


def _trajectory_points_from_payload(
    payload: dict[str, Any],
    *,
    artifact_type: str,
    row_topic_id: int,
    evidence_source: str,
) -> tuple[PDFQualityTrajectoryPoint, ...]:
    if artifact_type == "pdf_quality_replay_trajectory":
        raw_points = payload.get("points")
        if isinstance(raw_points, list):
            return tuple(
                _trajectory_point_from_snapshot(
                    point,
                    artifact_id=_int_value(point.get("artifact_id")),
                    row_topic_id=row_topic_id,
                    evidence_source=evidence_source,
                )
                for point in raw_points
                if isinstance(point, dict)
            )

    snapshot = _dict_value(
        payload.get("pdf_quality_snapshot")
        or payload.get("pdf_quality")
        or payload.get("quality")
    )
    if not snapshot:
        return ()
    artifact_id = _int_value(snapshot.get("artifact_id")) or _artifact_id_from_source(
        evidence_source
    )
    return (
        _trajectory_point_from_snapshot(
            snapshot,
            artifact_id=artifact_id,
            row_topic_id=row_topic_id,
            evidence_source=evidence_source,
        ),
    )


def _trajectory_point_from_snapshot(
    snapshot: dict[str, Any],
    *,
    artifact_id: int,
    row_topic_id: int,
    evidence_source: str,
) -> PDFQualityTrajectoryPoint:
    metadata = _dict_value(snapshot.get("metadata"))
    return PDFQualityTrajectoryPoint(
        artifact_id=artifact_id,
        topic_id=_int_value(snapshot.get("topic_id")) or row_topic_id,
        target_profile=str(snapshot.get("target_profile") or ""),
        evidence_source=evidence_source,
        issue_count=_int_value(snapshot.get("issue_count")),
        blocking_issue_count=_int_value(snapshot.get("blocking_issue_count")),
        recompile_repairable_issue_count=_int_value(
            snapshot.get("recompile_repairable_issue_count")
        ),
        layout_issue_count=_int_value(snapshot.get("layout_issue_count")),
        encoding_issue_count=_int_value(snapshot.get("encoding_issue_count")),
        overfull_hbox_count=_int_value(snapshot.get("overfull_hbox_count")),
        underfull_hbox_count=_int_value(snapshot.get("underfull_hbox_count")),
        invalid_utf8_count=_int_value(snapshot.get("invalid_utf8_count")),
        malformed_latex_command_count=_int_value(
            snapshot.get("malformed_latex_command_count")
        ),
        path_scan_used=False,
        metadata=metadata,
    )


def _dedupe_trajectory_points(
    points: list[PDFQualityTrajectoryPoint],
) -> tuple[PDFQualityTrajectoryPoint, ...]:
    by_artifact: dict[int, PDFQualityTrajectoryPoint] = {}
    for point in points:
        if not point.artifact_id:
            continue
        current = by_artifact.get(point.artifact_id)
        if current is None or _point_rank(point) >= _point_rank(current):
            by_artifact[point.artifact_id] = point
    return tuple(by_artifact[key] for key in sorted(by_artifact))


def _point_rank(point: PDFQualityTrajectoryPoint) -> int:
    rank = 0
    if point.blocking_issue_count:
        rank += 4
    if point.issue_count:
        rank += 2
    if point.target_profile:
        rank += 1
    return rank


def _with_replay_metadata(
    signal: PDFQualitySignal,
    *,
    payload: dict[str, Any],
    source_artifact_ids: set[int],
    source_topic_id: int | None,
    target_profile_match: str,
) -> PDFQualitySignal:
    replay_metadata = {
        "held_out_replay": True,
        "replay_source": "final_bundle_quality",
        "source_artifact_ids": tuple(sorted(source_artifact_ids)),
        "source_topic_id": source_topic_id,
        "target_profile_match": target_profile_match,
        "promotion_eligible": True,
        "page_count_gate_passed": _page_count_gate_passed(payload),
        "citation_gate_passed": _evidence_passed(
            payload,
            "citation_integrity_evidence",
        ),
        "anonymity_gate_passed": _evidence_passed(
            payload,
            "anonymization_evidence",
        ),
        "bibliography_gate_passed": _evidence_passed(
            payload,
            "bibliography_style_evidence",
        ),
    }
    replay_metadata["topic_replay_passed"] = (
        signal.metadata.get("recompile_repairable_issue_count") == 0
        and signal.metadata.get("blocking_issue_count") == 0
        and replay_metadata["page_count_gate_passed"]
        and replay_metadata["citation_gate_passed"]
        and replay_metadata["anonymity_gate_passed"]
        and replay_metadata["bibliography_gate_passed"]
    )
    return replace(signal, metadata={**signal.metadata, **replay_metadata})


def _target_profile_match(
    target_profile: str,
    *,
    profiles: set[str],
    compatible_profiles: set[str],
) -> str | None:
    if profiles and target_profile in profiles:
        return "exact"
    if target_profile in compatible_profiles:
        return "compatible"
    if not profiles and not compatible_profiles:
        return "unfiltered"
    return None


def _held_out_exclusion_reasons(
    *,
    artifact_id: int,
    topic_id: int,
    target_profile_match: str | None,
    source_topic_id: int | None,
    source_artifact_ids: set[int],
) -> list[str]:
    reasons: list[str] = []
    if source_topic_id is not None and topic_id == source_topic_id:
        reasons.append("same source topic")
    if artifact_id in source_artifact_ids:
        reasons.append("source artifact")
    if target_profile_match is None:
        reasons.append("target profile mismatch")
    return reasons


def _final_bundle_paths(payload: dict[str, Any]) -> dict[str, str]:
    paper_finalize = _dict_value(payload.get("paper_finalize"))
    tex_path = str(payload.get("tex_path") or paper_finalize.get("tex_path") or "")
    pdf_path = str(
        payload.get("compiled_pdf_path")
        or payload.get("pdf_path")
        or paper_finalize.get("pdf_path")
        or ""
    )
    log_path = str(payload.get("log_path") or paper_finalize.get("log_path") or "")
    output_dir = str(payload.get("output_dir") or "")
    if not log_path:
        if output_dir:
            log_path = str(Path(output_dir) / "paper.log")
        elif tex_path:
            log_path = str(Path(tex_path).with_suffix(".log"))
    return {"tex_path": tex_path, "pdf_path": pdf_path, "log_path": log_path}


def _page_count_gate_passed(payload: dict[str, Any]) -> bool:
    evidence = payload.get("page_limit_evidence")
    if isinstance(evidence, dict):
        if "passed" in evidence:
            return bool(evidence.get("passed"))
        return bool(evidence.get("full_pages") or evidence.get("content_pages"))
    return bool(payload.get("full_pages") or payload.get("content_pages"))


def _evidence_passed(payload: dict[str, Any], key: str) -> bool:
    evidence = payload.get(key)
    return isinstance(evidence, dict) and bool(evidence.get("passed"))


def _benchmark_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("benchmark_id")
        or payload.get("benchmark")
        or payload.get("suite")
        or "researchflowbench"
    )


def _score_payloads(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    scores = payload.get("scores")
    if isinstance(scores, list):
        return tuple(score for score in scores if isinstance(score, dict))
    if isinstance(payload.get("score"), dict):
        return (dict(payload["score"]),)
    metric_keys = {"recall_at_k", "mrr", "score", "precision", "f1"}
    if metric_keys & set(payload):
        return (payload,)
    return ()


def _task_id(score: dict[str, Any], *, fallback: str) -> str:
    return str(score.get("task_id") or score.get("id") or fallback)


def _replay_split_role(value: Any, *, fallback: str = "mutate_dev") -> str:
    role = str(value or fallback)
    if role in {"source", "mutate_dev", "promotion_test", "held_out"}:
        return role
    return fallback


def _artifact_id_from_source(source: str) -> int:
    parts = source.split(":")
    if len(parts) >= 2 and parts[0] == "project_artifacts":
        return _int_value(parts[1])
    return 0


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "::".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}.{digest}"


def _decode_payload(payload_json: str) -> dict[str, Any]:
    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
