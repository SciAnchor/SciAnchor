"""Unified single-call topic introspection (``rh.topic_state.v1``).

Composes the existing preflight, pending-decision, and state-tree probes into
one read-only payload so agents can answer "where is this topic and what do I
do next" without stitching commands together. Transport-neutral: backs the
``rh topic state`` CLI command and the ``topic_state`` MCP tool.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from research_harness.config import (
    RuntimeConfig,
    detect_state_trees,
    load_runtime_config,
    state_dir_for_db_path,
)
from research_harness.storage.db import Database

from . import checkpoint as ckpt
from .hitl_commands import paper_production_pending_decisions, resolve_state_dir
from .paper_production_entry import _find_topic, preflight_paper_production_topic

TOPIC_STATE_SCHEMA_VERSION = "rh.topic_state.v1"


def _delivery_preflight(
    db: Database, topic: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Verify recorded ownership, never infer the external execution's live state."""
    if topic is None:
        return None
    reason = ""
    rows = []
    conn = db.connect()
    try:
        # Include inactive rows: filtering them out can turn damaged ownership
        # into a recommendation to start a different workflow.
        rows = conn.execute(
            "SELECT id, topic_id, stage, status, stale, payload_json, metadata_json "
            "FROM project_artifacts WHERE topic_id=? AND artifact_type=?",
            (topic["id"], "research_delivery_binding"),
        ).fetchall()
    except sqlite3.Error:
        reason = "delivery_binding_unreadable"
    finally:
        conn.close()
    if (
        not rows
        and not reason
        and not str(topic["name"]).startswith("ticket-execution-")
    ):
        return None

    execution: dict[str, Any] = {"binding_status": "unknown", "live_state": "unknown"}
    if not reason:
        if not rows:
            reason = "delivery_binding_missing"
        elif len(rows) != 1:
            reason = "delivery_binding_conflict"
        else:
            row = rows[0]
            try:
                payload = json.loads(row["payload_json"])
                metadata = json.loads(row["metadata_json"])
                valid = isinstance(payload, dict) and isinstance(metadata, dict)
                if valid:
                    digest = hashlib.sha256(
                        json.dumps(
                            payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode()
                    ).hexdigest()
                    fields = (
                        "execution_id",
                        "ticket_namespace",
                        "public_id",
                        "title",
                        "topic_text",
                        "target_journal",
                        "rh_db_path",
                    )
                    valid = (
                        row["status"] == "active"
                        and row["stale"] == 0
                        and row["stage"] == "propose"
                        and metadata.get("sha256") == digest
                        and payload.get("contract_version") == "research_execution.v1"
                        and payload.get("execution_mode") == "external_simulated"
                        and type(payload.get("topic_id")) is int
                        and payload["topic_id"] == row["topic_id"] == topic["id"]
                        and all(
                            isinstance(payload.get(key), str) and payload[key].strip()
                            for key in fields
                        )
                        and re.fullmatch(r"[0-9a-f]{32}", payload["execution_id"])
                        is not None
                        and topic["name"]
                        == f"ticket-execution-{payload['execution_id']}"
                        and Path(payload["rh_db_path"]).is_absolute()
                        and Path(payload["rh_db_path"]).resolve()
                        == Path(db.db_path).resolve()
                    )
                if valid:
                    execution.update(
                        binding_status="verified",
                        binding_artifact_id=row["id"],
                        execution_id=payload["execution_id"],
                        execution_mode=payload["execution_mode"],
                    )
                else:
                    reason = "delivery_binding_invalid"
            except (ValueError, TypeError, OSError):
                reason = "delivery_binding_invalid"
    return {
        "topic": topic,
        "execution": execution,
        "classification": "delivery_state_unknown" if reason else "research_delivery",
        "blockers": [reason] if reason else [],
        "warnings": [],
    }


def topic_state(
    db: Database,
    *,
    topic: str | int,
    base_dir: Path | None = None,
    runtime_config: RuntimeConfig | None = None,
) -> dict[str, Any]:
    """Return the full state picture for one topic, with a computed next action."""
    config = runtime_config or load_runtime_config()
    state_dir = resolve_state_dir(base_dir, db_path=db.db_path)

    delivery = _delivery_preflight(db, _find_topic(db, topic))
    preflight = (
        delivery
        if delivery is not None
        else preflight_paper_production_topic(
            db=db,
            topic=topic,
            base_dir=state_dir,
        )
    )
    topic_payload = preflight.get("topic")
    trees = detect_state_trees(config)
    nonempty_trees = [tree for tree in trees if int(tree.get("pool_db_bytes") or 0) > 0]

    checkpoint_payload = dict(preflight.get("checkpoint") or {})
    pending: dict[str, Any] = {"has_pending": False}
    checkpoint_data: dict[str, Any] | None = None
    feedback_payload: dict[str, Any] = {"open_count": 0, "open_items": []}
    if isinstance(topic_payload, dict) and delivery is None:
        topic_id = int(topic_payload["id"])
        pending = paper_production_pending_decisions(topic_id, base_dir=state_dir)
        checkpoint_data = ckpt.load_checkpoint(
            ckpt.checkpoint_path(state_dir, topic_id)
        )
        from .feedback_loop import feedback_list

        feedback_result = feedback_list(db, topic=topic_id, status="open")
        if feedback_result.get("status") == "success":
            feedback_payload = {
                "open_count": int(feedback_result.get("count") or 0),
                "open_items": list(feedback_result.get("items") or []),
            }
    if checkpoint_data is not None:
        last_error = checkpoint_data.get("last_error") or {}
        human_decision = checkpoint_data.get("human_decision") or {}
        stage_context = checkpoint_data.get("stage_context")
        checkpoint_payload.update(
            {
                "updated_at": checkpoint_data.get("updated_at", ""),
                "last_error": {
                    "kind": str(last_error.get("kind") or ""),
                    "message": str(last_error.get("message") or ""),
                    "retry_count": int(last_error.get("retry_count") or 0),
                },
                "decision_selected": str(human_decision.get("selected") or ""),
                "decision_status": str(human_decision.get("decision_status") or ""),
                "has_feedback_context": isinstance(stage_context, dict)
                and isinstance(stage_context.get("human_feedback_context"), dict),
            }
        )

    db_tree = state_dir_for_db_path(db.db_path)
    resolution = {
        "db_path": str(db.db_path),
        "db_source": config.source
        if Path(str(db.db_path)).expanduser().resolve()
        == config.db_path.expanduser().resolve()
        else "explicit",
        "config_path": str(config.config_path) if config.config_path else "",
        "config_pinned": bool(config.config_path and config.config_path.exists()),
        "state_dir": str(state_dir),
        "checkpoint_path": str(checkpoint_payload.get("path") or ""),
        "paths_consistent": db_tree is None
        or state_dir.expanduser().resolve() == db_tree.expanduser().resolve(),
    }

    next_action = _compute_next_action(
        topic_payload=topic_payload,
        preflight=preflight,
        pending=pending,
        checkpoint_payload=checkpoint_payload,
        nonempty_tree_count=len(nonempty_trees),
        feedback_payload=feedback_payload,
    )

    state_consistency = _compute_state_consistency(
        preflight=preflight,
        checkpoint_payload=checkpoint_payload,
        nonempty_tree_count=len(nonempty_trees),
    )

    warnings = list(preflight.get("warnings") or [])
    if isinstance(topic_payload, dict) and delivery is None:
        # BUG-012: surface cross-species / cross-model validation evidence so a
        # topic that declares an expected organism doesn't silently treat
        # off-species papers as direct validation.
        from research_harness.experiment.coverage_gate import (
            experiment_coverage_findings,
        )
        from research_harness.experiment.organism_gate import (
            cross_species_evidence_findings,
        )

        _tid = int(topic_payload["id"])
        try:
            for finding in cross_species_evidence_findings(db, _tid):
                warnings.append(str(finding.get("message") or ""))
            # BUG-016: flag experiment categories the manuscript never discusses.
            for finding in experiment_coverage_findings(db, _tid):
                warnings.append(str(finding.get("message") or ""))
        except Exception:  # pragma: no cover - defensive; never break status
            pass

    return {
        "schema_version": TOPIC_STATE_SCHEMA_VERSION,
        "topic": topic_payload,
        "resolution": resolution,
        "state_trees": trees,
        "orchestrator": preflight.get("orchestrator") or {},
        "checkpoint": checkpoint_payload,
        "pending_decision": pending.get("decision")
        if pending.get("has_pending")
        else None,
        "feedback": feedback_payload,
        "classification": preflight.get("classification"),
        "state_consistency": state_consistency,
        "blockers": list(preflight.get("blockers") or []),
        "warnings": warnings,
        "next_action": next_action,
        **({"execution": delivery["execution"]} if delivery is not None else {}),
    }


def _compute_state_consistency(
    *,
    preflight: dict[str, Any],
    checkpoint_payload: dict[str, Any],
    nonempty_tree_count: int,
) -> dict[str, Any]:
    """Reconcile the sources users otherwise read separately (BUG-013).

    The orchestrator run stage, the checkpoint stage, and the state-tree count
    used to give three different answers for one topic. This surfaces one
    authoritative comparison and names every disagreement so callers stop
    guessing which entry point to trust.
    """
    orchestrator = preflight.get("orchestrator") or {}
    run = orchestrator.get("run") if isinstance(orchestrator, dict) else {}
    run = run if isinstance(run, dict) else {}
    run_stage = str(run.get("current_stage") or "")
    checkpoint_stage = str(checkpoint_payload.get("current_stage") or "")
    blockers = set(preflight.get("blockers") or [])

    discrepancies: list[str] = []
    if preflight.get("classification") == "delivery_state_unknown":
        discrepancies.append("delivery execution ownership could not be verified")
    if run_stage and checkpoint_stage and run_stage != checkpoint_stage:
        discrepancies.append(
            f"orchestrator run is at '{run_stage}' but the checkpoint is at "
            f"'{checkpoint_stage}'"
        )
    elif "db_checkpoint_mismatch" in blockers:
        discrepancies.append("checkpoint and orchestrator run disagree on stage/mode")
    if nonempty_tree_count > 1:
        discrepancies.append(
            f"{nonempty_tree_count} non-empty pool.db state trees are visible"
        )

    return {
        "run_stage": run_stage,
        "checkpoint_stage": checkpoint_stage,
        "sources_agree": not discrepancies,
        "discrepancies": discrepancies,
        "authoritative_source": "next_action",
    }


def _action(code: str, summary: str, commands: list[str]) -> dict[str, Any]:
    return {"code": code, "summary": summary, "commands": commands}


def _compute_next_action(
    *,
    topic_payload: dict[str, Any] | None,
    preflight: dict[str, Any],
    pending: dict[str, Any],
    checkpoint_payload: dict[str, Any],
    nonempty_tree_count: int,
    feedback_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single next-action recommendation, highest-priority condition wins."""
    if not isinstance(topic_payload, dict):
        return _action(
            "missing_topic",
            "Topic not found in this database — check the id/name and the resolved DB path.",
            ["rh topic list", "topic_list()"],
        )

    topic_id = int(topic_payload["id"])

    execution = preflight.get("execution")
    if isinstance(execution, dict):
        if execution.get("binding_status") != "verified":
            return _action(
                "delivery_state_unknown",
                "Delivery execution binding is missing, invalid or ambiguous; ownership must be reconciled.",
                [],
            )
        return _action(
            "research_delivery_owned",
            f"Topic belongs to delivery execution {execution['execution_id']} "
            f"({execution['execution_mode']}); live execution state is unknown.",
            [],
        )

    if str(topic_payload.get("status") or "").strip().lower() == "archived":
        return _action(
            "archived",
            "Topic is archived — reactivate it before resuming paper production.",
            [
                f"rh topic update {topic_payload.get('name') or '<name>'} --status active",
                f"rh paper-production resume --topic {topic_id}",
            ],
        )

    blockers = set(preflight.get("blockers") or [])
    orchestrator = preflight.get("orchestrator") or {}
    run_payload = orchestrator.get("run") if isinstance(orchestrator, dict) else {}
    run_payload = run_payload if isinstance(run_payload, dict) else {}

    if "missing_orchestrator_run" in blockers and not checkpoint_payload.get("exists"):
        return _action(
            "not_started",
            "Topic exists but paper production has not started (S1).",
            [
                (
                    f"rh paper-production start --topic {topic_id} "
                    "--target-venue <venue> --interaction-mode checkpoint"
                ),
                f"paper_production_start(topic_id={topic_id}, target_venue=..., interaction_mode='checkpoint')",
            ],
        )

    if pending.get("has_pending"):
        decision = pending.get("decision") or {}
        reason = str(decision.get("reason_code") or "pending decision")
        recommended = str(decision.get("recommended_action") or "")
        return _action(
            "answer_pending_decision",
            f"A human decision is pending ({reason}); answer it before resuming.",
            [
                (
                    f"rh paper-production decide --topic {topic_id} "
                    f"--action {recommended or '<action>'} --reasoning '...'"
                ),
                f"paper_production_decide(topic_id={topic_id}, choice='{recommended or '<action>'}', reasoning='...')",
            ],
        )

    if (
        checkpoint_payload.get("decision_selected") == "stop"
        and checkpoint_payload.get("decision_status") == "stopped"
    ):
        return _action(
            "stopped_by_human",
            "Run was stopped by a human decision; record a new decision to continue.",
            [
                f"rh paper-production decide --topic {topic_id} --action broaden_search --reasoning '...'",
                f"paper_production_decide(topic_id={topic_id}, choice='broaden_search', reasoning='...')",
            ],
        )

    if nonempty_tree_count > 1:
        return _action(
            "state_split_brain",
            "More than one non-empty pool.db is visible — resolve before mutating state.",
            ["rh doctor", "see docs/state-cleanup.md"],
        )

    if "db_checkpoint_mismatch" in blockers:
        return _action(
            "db_checkpoint_mismatch",
            "Checkpoint and orchestrator run disagree on stage/mode; resume re-syncs them.",
            [
                f"rh paper-production preflight --topic {topic_id}",
                f"rh paper-production resume --topic {topic_id}",
            ],
        )

    if checkpoint_payload.get("stage_state") == "error":
        message = ""
        last_error = checkpoint_payload.get("last_error")
        if isinstance(last_error, dict):
            message = str(last_error.get("message") or "")
        return _action(
            "fix_last_error",
            f"Last stage attempt errored{': ' + message[:160] if message else ''}; fix the cause then resume.",
            [
                f"rh paper-production status --topic {topic_id}",
                f"rh paper-production resume --topic {topic_id}",
            ],
        )

    if "gate_blocked" in blockers and "missing_required_artifacts" not in blockers:
        gate = orchestrator.get("gate") if isinstance(orchestrator, dict) else {}
        reasons = gate.get("reasons") if isinstance(gate, dict) else []
        reason_text = "; ".join(
            str(reason.get("code") or reason)
            for reason in (reasons or [])[:3]
            if reason
        )
        return _action(
            "gate_blocked",
            f"Current stage gate is blocked{': ' + reason_text if reason_text else ''}.",
            [
                f"rh orchestrator status --topic {topic_id}",
                f"orchestrator_gate_check(topic_id={topic_id})",
            ],
        )

    open_feedback = int((feedback_payload or {}).get("open_count") or 0)
    if open_feedback and not checkpoint_payload.get("has_feedback_context"):
        return _action(
            "apply_open_feedback",
            f"{open_feedback} open feedback item(s) — build/apply a revision plan (S3).",
            [
                f"rh feedback plan --topic {topic_id}",
                f"rh feedback apply --topic {topic_id} --dry-run",
            ],
        )

    stage = str(
        run_payload.get("current_stage")
        or checkpoint_payload.get("current_stage")
        or ""
    )
    stage_status = str(run_payload.get("stage_status") or "")
    if stage == "write" and (
        stage_status == "completed"
        or checkpoint_payload.get("stage_state") == "complete"
    ):
        return _action(
            "finished_ready_for_feedback",
            "Write stage is complete — apply targeted reinforcement from user feedback (S3).",
            [
                (
                    f"rh feedback add --topic {topic_id} --target-kind section "
                    "--target <section> --note '...'"
                ),
                f"rh feedback plan --topic {topic_id}",
            ],
        )

    return _action(
        "resume",
        f"Resume from the current stage ({stage or 'unknown'}) (S2).",
        [
            f"rh paper-production resume --topic {topic_id}",
            f"paper_production_resume(topic_id={topic_id})",
        ],
    )
