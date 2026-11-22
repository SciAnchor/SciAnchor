"""Deterministic golden workflow contract helpers for RH self-development."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from research_harness.service.types import ServiceResult
from research_harness.storage.db import Database


@dataclass(frozen=True)
class GoldenWorkflowContract:
    workflow_name: str
    topic_id: int
    topic_name: str
    paper_ids: tuple[int, ...]
    primitive_commands: tuple[str, ...]
    provenance_primitives: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    next_actions: tuple[str, ...]
    gate_decisions: tuple[str, ...]
    missing: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_golden_workflow_contract(
    *,
    db: Database,
    workflow_name: str,
    topic_id: int,
    service_results: Iterable[ServiceResult | Mapping[str, Any]],
    require_gate: bool = False,
) -> GoldenWorkflowContract:
    """Build a closed-loop evidence summary from deterministic service results."""

    result_payloads = tuple(
        _service_result_to_dict(result) for result in service_results
    )
    topic_name = _topic_name(db, topic_id)
    paper_ids = _paper_ids_for_topic(db, topic_id)
    artifact_refs = _unique(
        [
            *(
                str(artifact)
                for payload in result_payloads
                for artifact in payload.get("artifacts", [])
            ),
            *_project_artifact_refs(db, topic_id),
        ]
    )
    primitive_commands = _unique(
        _primitive_name(payload)
        for payload in result_payloads
        if _primitive_name(payload)
    )
    provenance_primitives = _provenance_primitives(db, topic_id)
    next_actions = _unique(
        str(action)
        for payload in result_payloads
        for action in payload.get("next_actions", [])
    )
    gate_decisions = _unique(
        decision for payload in result_payloads if (decision := _gate_decision(payload))
    )

    missing = _missing_contract_parts(
        topic_name=topic_name,
        paper_ids=paper_ids,
        primitive_commands=primitive_commands,
        provenance_primitives=provenance_primitives,
        artifact_refs=artifact_refs,
        next_actions=next_actions,
        gate_decisions=gate_decisions,
        require_gate=require_gate,
        result_payloads=result_payloads,
    )
    return GoldenWorkflowContract(
        workflow_name=workflow_name,
        topic_id=topic_id,
        topic_name=topic_name,
        paper_ids=paper_ids,
        primitive_commands=primitive_commands,
        provenance_primitives=provenance_primitives,
        artifact_refs=artifact_refs,
        next_actions=next_actions,
        gate_decisions=gate_decisions,
        missing=missing,
        status="success" if not missing else "error",
    )


def _service_result_to_dict(
    result: ServiceResult | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(result, ServiceResult):
        return result.to_dict()
    return dict(result)


def _topic_name(db: Database, topic_id: int) -> str:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT name FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
        return str(row["name"]) if row is not None else ""
    finally:
        conn.close()


def _paper_ids_for_topic(db: Database, topic_id: int) -> tuple[int, ...]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()
        return tuple(int(row["id"]) for row in rows)
    finally:
        conn.close()


def _project_artifact_refs(db: Database, topic_id: int) -> tuple[str, ...]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, artifact_type
            FROM project_artifacts
            WHERE topic_id = ? AND status = 'active'
            ORDER BY id
            """,
            (topic_id,),
        ).fetchall()
        return tuple(
            f"project_artifact:{int(row['id'])}:{row['artifact_type']}" for row in rows
        )
    finally:
        conn.close()


def _provenance_primitives(db: Database, topic_id: int) -> tuple[str, ...]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT primitive
            FROM provenance_records
            WHERE topic_id = ?
            ORDER BY id
            """,
            (topic_id,),
        ).fetchall()
        return tuple(str(row["primitive"]) for row in rows)
    finally:
        conn.close()


def _primitive_name(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("primitive"):
        return str(metadata["primitive"])
    return ""


def _gate_decision(payload: Mapping[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, Mapping):
        if output.get("gate_decision"):
            return str(output["gate_decision"])
        gate = output.get("gate")
        if isinstance(gate, Mapping) and gate.get("decision"):
            return str(gate["decision"])
    return ""


def _missing_contract_parts(
    *,
    topic_name: str,
    paper_ids: tuple[int, ...],
    primitive_commands: tuple[str, ...],
    provenance_primitives: tuple[str, ...],
    artifact_refs: tuple[str, ...],
    next_actions: tuple[str, ...],
    gate_decisions: tuple[str, ...],
    require_gate: bool,
    result_payloads: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    missing: list[str] = []
    if not topic_name:
        missing.append("topic")
    if not paper_ids:
        missing.append("paper")
    if not primitive_commands:
        missing.append("primitive_result")
    if not provenance_primitives:
        missing.append("provenance")
    if not artifact_refs:
        missing.append("artifact")
    if not next_actions:
        missing.append("next_actions")
    if require_gate and not gate_decisions:
        missing.append("gate_decision")
    for payload in result_payloads:
        if payload.get("status") != "success":
            missing.append(f"service_result:{payload.get('command', 'unknown')}")
    return tuple(missing)


def _unique(values: Iterable[Any]) -> tuple[Any, ...]:
    seen: set[Any] = set()
    unique_values: list[Any] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return tuple(unique_values)
