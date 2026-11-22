"""Candidate archive, replay split, and champion registry helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .models import (
    ArchiveGateAction,
    CandidateArchiveRecord,
    ChampionRegistryEntry,
    ImprovementCandidate,
    ReplaySplit,
    VerificationGateResult,
)


def build_replay_split(
    *,
    candidate_id: str,
    source_refs: tuple[str, ...] = (),
    mutate_dev_refs: tuple[str, ...] = (),
    promotion_test_refs: tuple[str, ...] = (),
    held_out_refs: tuple[str, ...] = (),
    min_promotion_examples: int = 1,
    metadata: dict[str, Any] | None = None,
) -> ReplaySplit:
    """Build a replay split and mark it incubating when promotion evidence is thin."""
    reasons: list[str] = []
    promotion_count = len(promotion_test_refs) + len(held_out_refs)
    if promotion_count < min_promotion_examples:
        reasons.append("not enough promotion replay examples")
    if not source_refs:
        reasons.append("missing source replay references")

    return ReplaySplit(
        candidate_id=candidate_id,
        source_refs=tuple(dict.fromkeys(source_refs)),
        mutate_dev_refs=tuple(dict.fromkeys(mutate_dev_refs)),
        promotion_test_refs=tuple(dict.fromkeys(promotion_test_refs)),
        held_out_refs=tuple(dict.fromkeys(held_out_refs)),
        incubating=bool(reasons),
        reasons=tuple(reasons),
        metadata=dict(metadata or {}),
    )


def build_candidate_archive_record(
    candidate: ImprovementCandidate,
    *,
    gate_result: VerificationGateResult | None = None,
    replay_split: ReplaySplit | None = None,
    metric_mappings: tuple[Any, ...] = (),
    gate_action: ArchiveGateAction | str | None = None,
    gate_reasons: tuple[str, ...] = (),
    parent_candidate_id: str = "",
    champion_candidate_id: str = "",
    artifact_refs: tuple[str, ...] = (),
    metrics: dict[str, Any] | None = None,
    cost_quality_telemetry: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> CandidateArchiveRecord:
    """Create an immutable archive record for one candidate."""
    resolved_gate_action = gate_action or (gate_result.action if gate_result else "")
    resolved_gate_reasons = gate_reasons or (gate_result.reasons if gate_result else ())
    benchmark_ids = _benchmark_ids(metric_mappings)
    rh_axis_ids = _rh_axis_ids(metric_mappings)
    merged_metadata = {
        **candidate.metadata,
        **dict(metadata or {}),
    }
    if benchmark_ids:
        merged_metadata["benchmark_ids"] = benchmark_ids

    return CandidateArchiveRecord(
        candidate_id=candidate.candidate_id,
        finding_id=candidate.finding_id,
        target_kind=candidate.target_kind,
        status=candidate.status,
        priority_score=candidate.priority_score,
        affected_surfaces=candidate.affected_surfaces,
        rh_axis_ids=rh_axis_ids,
        replay_split=replay_split,
        gate_action=resolved_gate_action,
        gate_reasons=tuple(resolved_gate_reasons),
        parent_candidate_id=parent_candidate_id,
        champion_candidate_id=champion_candidate_id,
        artifact_refs=tuple(dict.fromkeys(artifact_refs)),
        metrics=dict(metrics or {}),
        cost_quality_telemetry=dict(cost_quality_telemetry or {}),
        metadata=merged_metadata,
    )


def build_candidate_archive_record_from_researchflowbench_score(
    candidate: ImprovementCandidate,
    *,
    benchmark_id: str,
    task_id: str,
    score: Any,
    split: str = "mutate_dev",
    gate_action: ArchiveGateAction | str = "evaluate",
    artifact_refs: tuple[str, ...] = (),
) -> CandidateArchiveRecord:
    """Archive one ResearchFlowBench task score as candidate evidence."""
    from research_harness.eval.researchflowbench.metric_map import (
        metric_mappings_for_benchmark,
    )

    refs = (task_id,) if task_id else ()
    metrics = _score_payload(score)
    replay_split = build_replay_split(
        candidate_id=candidate.candidate_id,
        source_refs=_tuple_of_str(metrics.get("source_refs"))
        or (refs if split == "source" else ()),
        mutate_dev_refs=_tuple_of_str(metrics.get("mutate_dev_refs"))
        or (refs if split == "mutate_dev" else ()),
        promotion_test_refs=_tuple_of_str(metrics.get("promotion_test_refs"))
        or (refs if split == "promotion_test" else ()),
        held_out_refs=_tuple_of_str(metrics.get("held_out_refs"))
        or (refs if split == "held_out" else ()),
    )
    return build_candidate_archive_record(
        candidate,
        replay_split=replay_split,
        metric_mappings=metric_mappings_for_benchmark(benchmark_id),
        gate_action=gate_action,
        gate_reasons=("ResearchFlowBench score archived as evaluation evidence",),
        artifact_refs=artifact_refs,
        metrics=metrics,
        metadata={
            "benchmark_id": benchmark_id,
            "task_id": task_id,
            "replay_split_role": split,
        },
    )


def build_candidate_archive_records_from_researchflowbench_scores(
    candidate: ImprovementCandidate,
    *,
    benchmark_id: str,
    scores: tuple[Any, ...],
    split: str = "mutate_dev",
    gate_action: ArchiveGateAction | str = "evaluate",
    artifact_refs: tuple[str, ...] = (),
) -> tuple[CandidateArchiveRecord, ...]:
    """Archive a batch of ResearchFlowBench task scores."""
    return tuple(
        build_candidate_archive_record_from_researchflowbench_score(
            candidate,
            benchmark_id=benchmark_id,
            task_id=str(getattr(score, "task_id", "") or ""),
            score=score,
            split=split,
            gate_action=gate_action,
            artifact_refs=artifact_refs,
        )
        for score in scores
    )


def candidate_archive_record_to_payload(
    record: CandidateArchiveRecord,
) -> dict[str, Any]:
    """Serialize an archive record for artifact payload storage."""
    return {
        "schema_version": 1,
        **asdict(record),
    }


def candidate_archive_record_from_payload(payload: Any) -> CandidateArchiveRecord:
    """Deserialize an archive record from an artifact payload."""
    data = payload if isinstance(payload, dict) else {}
    replay_data = data.get("replay_split")
    replay_split = (
        _replay_split_from_payload(replay_data)
        if isinstance(replay_data, dict)
        else None
    )
    return CandidateArchiveRecord(
        candidate_id=str(data.get("candidate_id") or ""),
        finding_id=str(data.get("finding_id") or ""),
        target_kind=str(data.get("target_kind") or ""),
        status=_candidate_status(data.get("status")),
        priority_score=_int_value(data.get("priority_score")),
        affected_surfaces=_tuple_of_str(data.get("affected_surfaces")),
        rh_axis_ids=_tuple_of_str(data.get("rh_axis_ids")),
        replay_split=replay_split,
        gate_action=str(data.get("gate_action") or ""),
        gate_reasons=_tuple_of_str(data.get("gate_reasons")),
        parent_candidate_id=str(data.get("parent_candidate_id") or ""),
        champion_candidate_id=str(data.get("champion_candidate_id") or ""),
        artifact_refs=_tuple_of_str(data.get("artifact_refs")),
        metrics=_dict_value(data.get("metrics")),
        cost_quality_telemetry=_dict_value(data.get("cost_quality_telemetry")),
        metadata=_dict_value(data.get("metadata")),
    )


def build_champion_registry_entry(
    *,
    target_kind: str,
    archive_records: tuple[CandidateArchiveRecord, ...],
) -> ChampionRegistryEntry | None:
    """Select the best promotable archive record as the champion for a target."""
    promotable = [
        record
        for record in archive_records
        if record.target_kind == target_kind
        and record.gate_action == "promote"
        and not (record.replay_split and record.replay_split.incubating)
    ]
    if not promotable:
        return None

    champion = sorted(
        promotable,
        key=lambda record: (record.priority_score, len(record.rh_axis_ids)),
        reverse=True,
    )[0]
    replay_refs: tuple[str, ...] = ()
    if champion.replay_split is not None:
        replay_refs = (
            champion.replay_split.promotion_test_refs
            + champion.replay_split.held_out_refs
        )

    return ChampionRegistryEntry(
        target_kind=champion.target_kind,
        champion_candidate_id=champion.candidate_id,
        finding_id=champion.finding_id,
        rh_axis_ids=champion.rh_axis_ids,
        replay_refs=replay_refs,
        promotion_strength=_promotion_strength(champion),
        artifact_refs=champion.artifact_refs,
        metrics=champion.metrics,
        metadata={
            "gate_reasons": champion.gate_reasons,
            "source_candidate_status": champion.status,
            "benchmark_id": champion.metadata.get("benchmark_id", ""),
            "benchmark_ids": champion.metadata.get("benchmark_ids", ()),
            "task_id": champion.metadata.get("task_id", ""),
            "replay_split_role": champion.metadata.get("replay_split_role", ""),
        },
    )


def build_champion_registry_entries(
    archive_records: tuple[CandidateArchiveRecord, ...],
) -> tuple[ChampionRegistryEntry, ...]:
    """Build one champion entry per target kind from archive records."""
    entries = tuple(
        build_champion_registry_entry(
            target_kind=target_kind,
            archive_records=archive_records,
        )
        for target_kind in sorted({record.target_kind for record in archive_records})
    )
    return tuple(entry for entry in entries if entry is not None)


def champion_registry_entry_to_payload(entry: ChampionRegistryEntry) -> dict[str, Any]:
    """Serialize one champion registry entry."""
    return asdict(entry)


def build_candidate_archive_pack_payload(
    records: tuple[CandidateArchiveRecord, ...],
) -> dict[str, Any]:
    """Build an artifact payload for a batch of candidate archive records."""
    return {
        "schema_version": 1,
        "record_count": len(records),
        "candidate_ids": [record.candidate_id for record in records],
        "target_kinds": sorted({record.target_kind for record in records}),
        "records": [candidate_archive_record_to_payload(record) for record in records],
    }


def build_champion_registry_pack_payload(
    entries: tuple[ChampionRegistryEntry | None, ...],
) -> dict[str, Any]:
    """Build an artifact payload for current champion registry entries."""
    live_entries = tuple(entry for entry in entries if entry is not None)
    return {
        "schema_version": 1,
        "entry_count": len(live_entries),
        "target_kinds": sorted({entry.target_kind for entry in live_entries}),
        "entries": [
            champion_registry_entry_to_payload(entry) for entry in live_entries
        ],
    }


def record_candidate_archive_pack(
    orchestrator_service: Any,
    *,
    topic_id: int,
    records: tuple[CandidateArchiveRecord, ...],
    stage: str = "project_self_evolution",
    dependency_artifact_ids: list[int] | None = None,
) -> Any | None:
    """Persist candidate archive records through the orchestrator artifact API."""
    if not records:
        return None

    payload = build_candidate_archive_pack_payload(records)
    return orchestrator_service.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="candidate_archive_pack",
        title="Candidate archive pack: " + ", ".join(payload["target_kinds"]),
        payload=payload,
        metadata={
            "source": "project_self_evolution",
            "record_count": payload["record_count"],
            "target_kinds": payload["target_kinds"],
        },
        dependency_artifact_ids=dependency_artifact_ids or [],
        dependency_type="derived_from",
    )


def record_champion_registry_pack(
    orchestrator_service: Any,
    *,
    topic_id: int,
    entries: tuple[ChampionRegistryEntry | None, ...],
    stage: str = "project_self_evolution",
    dependency_artifact_ids: list[int] | None = None,
) -> Any | None:
    """Persist champion registry entries through the orchestrator artifact API."""
    payload = build_champion_registry_pack_payload(entries)
    if not payload["entries"]:
        return None

    return orchestrator_service.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="champion_registry_pack",
        title="Champion registry pack: " + ", ".join(payload["target_kinds"]),
        payload=payload,
        metadata={
            "source": "project_self_evolution",
            "entry_count": payload["entry_count"],
            "target_kinds": payload["target_kinds"],
        },
        dependency_artifact_ids=dependency_artifact_ids or [],
        dependency_type="derived_from",
    )


def _benchmark_ids(metric_mappings: tuple[Any, ...]) -> tuple[str, ...]:
    ids = [
        str(getattr(mapping, "benchmark_id"))
        for mapping in metric_mappings
        if getattr(mapping, "benchmark_id", "")
    ]
    return tuple(dict.fromkeys(ids))


def _rh_axis_ids(metric_mappings: tuple[Any, ...]) -> tuple[str, ...]:
    axis_ids: list[str] = []
    for mapping in metric_mappings:
        axis_ids.extend(str(axis_id) for axis_id in getattr(mapping, "rh_axis_ids", ()))
    return tuple(dict.fromkeys(axis_ids))


def _promotion_strength(record: CandidateArchiveRecord) -> str:
    if record.replay_split is None:
        return "no_replay_metadata"
    if record.replay_split.held_out_refs:
        return "held_out_replay"
    if record.replay_split.promotion_test_refs:
        return "promotion_test_replay"
    return "source_only"


def _score_payload(score: Any) -> dict[str, Any]:
    if hasattr(score, "to_dict"):
        payload = score.to_dict()
    elif is_dataclass(score):
        payload = asdict(score)
    elif isinstance(score, dict):
        payload = score
    else:
        payload = {"value": score}
    return dict(payload)


def _replay_split_from_payload(payload: dict[str, Any]) -> ReplaySplit:
    return ReplaySplit(
        candidate_id=str(payload.get("candidate_id") or ""),
        source_refs=_tuple_of_str(payload.get("source_refs")),
        mutate_dev_refs=_tuple_of_str(payload.get("mutate_dev_refs")),
        promotion_test_refs=_tuple_of_str(payload.get("promotion_test_refs")),
        held_out_refs=_tuple_of_str(payload.get("held_out_refs")),
        incubating=bool(payload.get("incubating")),
        reasons=_tuple_of_str(payload.get("reasons")),
        metadata=_dict_value(payload.get("metadata")),
    )


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _candidate_status(value: Any) -> str:
    status = str(value or "")
    if status in {
        "needs_verification",
        "verified",
        "rejected",
        "needs_human_approval",
        "implemented",
    }:
        return status
    return "needs_verification"
