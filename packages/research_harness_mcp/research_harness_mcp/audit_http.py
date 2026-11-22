"""FastAPI route registration for topic audit drilldown endpoints."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException


_STAGE_KEYS = ("init", "build", "analyze", "propose", "experiment", "write")


def register_audit_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Path],
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    logger: logging.Logger | None = None,
) -> None:
    """Register read-only topic audit drilldown routes."""

    route_logger = logger or logging.getLogger(__name__)

    @app.get("/api/topics/{topic_id}/primitives")
    def list_topic_primitives(topic_id: int, stage: str | None = None):
        """Primitive executions for this topic, optionally scoped to a stage."""
        if stage is not None and stage not in _STAGE_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown stage {stage!r}")

        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            clauses = ["topic_id = ?"]
            params: list[Any] = [topic_id]
            if stage:
                clauses.append("stage = ?")
                params.append(stage)
            where = " AND ".join(clauses)

            try:
                rows = conn.execute(
                    f"""
                    SELECT id, primitive, category, started_at, finished_at,
                           backend, model_used, stage, cost_usd, success, error,
                           prompt_tokens, completion_tokens, loop_round,
                           actor, origin, retry_ordinal, cache_hit,
                           parallel_group, skipped, skip_reason,
                           artifact_id, quality_score, created_at
                    FROM provenance_records
                    WHERE {where}
                    ORDER BY started_at DESC
                    LIMIT 500
                    """,
                    params,
                ).fetchall()
            except sqlite3.OperationalError:
                # Legacy DB without the 055 audit columns: retry with base set.
                rows = conn.execute(
                    f"""
                    SELECT id, primitive, category, started_at, finished_at,
                           backend, model_used, stage, cost_usd, success, error,
                           prompt_tokens, completion_tokens, loop_round,
                           artifact_id, quality_score, created_at
                    FROM provenance_records
                    WHERE {where}
                    ORDER BY started_at DESC
                    LIMIT 500
                    """,
                    params,
                ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            item = row_to_dict(row)
            item.setdefault("actor", None)
            item.setdefault("origin", None)
            item.setdefault("retry_ordinal", 0)
            item.setdefault("cache_hit", 0)
            item.setdefault("parallel_group", None)
            item.setdefault("skipped", 0)
            item.setdefault("skip_reason", None)
            item["cache_hit"] = bool(item.get("cache_hit") or 0)
            item["skipped"] = bool(item.get("skipped") or 0)
            item["success"] = bool(item.get("success") or 0)
            out.append(item)

        return {"topic_id": topic_id, "stage": stage, "primitives": out}

    @app.get("/api/topics/{topic_id}/stage-policy/{stage}")
    def get_topic_stage_policy(topic_id: int, stage: str):
        """Serialize STAGE_POLICIES, invariants, and loopback state."""
        if stage not in _STAGE_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown stage {stage!r}")

        try:
            from research_harness.auto_runner.stage_policy import STAGE_POLICIES
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"stage policy unavailable: {exc}"
            )

        policy = STAGE_POLICIES.get(stage)
        if policy is None:
            raise HTTPException(status_code=404, detail=f"No policy for stage {stage}")

        policy_dict = {
            "name": policy.name,
            "tools": list(policy.tools),
            "codex": policy.codex,
            "codex_focus": policy.codex_focus,
            "human_checkpoint": policy.human_checkpoint,
            "retry": policy.retry,
            "max_codex_rounds": policy.max_codex_rounds,
            "description": policy.description,
            "autonomous_allowed": policy.autonomous_allowed,
            "risk_level": policy.risk_level,
            "approval_policy": policy.approval_policy,
            "expansion_paper_budget": policy.expansion_paper_budget,
        }

        invariant_violations: list[dict[str, Any]] = []
        try:
            from research_harness.orchestrator.invariants import InvariantChecker
            from research_harness.storage.db import Database as _Db

            db = _Db(db_path_provider())
            checker = InvariantChecker(db)
            violations = checker.check_all(topic_id, stage)
            for violation in violations:
                invariant_violations.append(
                    {
                        "check": getattr(violation, "check", ""),
                        "severity": getattr(violation, "severity", ""),
                        "message": getattr(violation, "message", ""),
                        "artifact_id": getattr(violation, "artifact_id", None),
                    }
                )
        except Exception as exc:
            route_logger.debug(
                "invariant check failed for %s/%s: %s", topic_id, stage, exc
            )

        loopback_state: dict[str, Any] = {
            "rounds_used": 0,
            "rounds_max": 0,
            "last_trigger": None,
        }
        try:
            from research_harness.orchestrator.service import OrchestratorService

            rounds_max = 0
            for (from_stage, _decision), (
                target,
                max_rounds,
                _reason,
                _checkpoint,
            ) in OrchestratorService.AUTO_LOOPBACK_RULES.items():
                if from_stage == stage or target == stage:
                    rounds_max = max(rounds_max, int(max_rounds))

            with get_db_context() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n,
                           MAX(created_at) AS last_at,
                           (SELECT trigger FROM rollback_log
                            WHERE topic_id = ? AND to_stage = ?
                            ORDER BY created_at DESC LIMIT 1) AS last_trigger
                    FROM rollback_log
                    WHERE topic_id = ? AND to_stage = ?
                    """,
                    (topic_id, stage, topic_id, stage),
                ).fetchone()
                if row is not None:
                    loopback_state = {
                        "rounds_used": int(row["n"] or 0),
                        "rounds_max": rounds_max,
                        "last_trigger": row["last_trigger"],
                    }
        except Exception as exc:
            route_logger.debug("loopback state lookup failed: %s", exc)

        return {
            "topic_id": topic_id,
            "stage": stage,
            "policy": policy_dict,
            "invariant_violations": invariant_violations,
            "loopback_state": loopback_state,
        }

    @app.get("/api/topics/{topic_id}/stage-summary/{stage}")
    def get_topic_stage_summary(topic_id: int, stage: str):
        """Counts and aggregate stats for a single stage."""
        if stage not in _STAGE_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown stage {stage!r}")

        try:
            from research_harness.auto_runner.stage_policy import STAGE_POLICIES
        except Exception:
            STAGE_POLICIES = {}  # type: ignore[assignment]

        policy = STAGE_POLICIES.get(stage)
        planned = len(policy.tools) if policy is not None else 0

        with get_db_context() as conn:
            try:
                agg = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS rows_total,
                        SUM(CASE WHEN COALESCE(skipped, 0) = 0 THEN 1 ELSE 0 END) AS ran,
                        SUM(CASE WHEN COALESCE(skipped, 0) = 1 THEN 1 ELSE 0 END) AS skipped_n,
                        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed,
                        SUM(COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)) AS tokens,
                        SUM(COALESCE(cost_usd, 0)) AS cost_usd,
                        MIN(started_at) AS first_at,
                        MAX(finished_at) AS last_at
                    FROM provenance_records
                    WHERE topic_id = ? AND stage = ?
                    """,
                    (topic_id, stage),
                ).fetchone()
            except sqlite3.OperationalError:
                agg = None

            rubric_row = None
            try:
                rubric_row = conn.execute(
                    """
                    SELECT weighted_total, verdict, shadow_verdict, scored_at
                    FROM rubric_scores
                    WHERE topic_id = ? AND stage = ?
                    ORDER BY scored_at DESC
                    LIMIT 1
                    """,
                    (topic_id, stage),
                ).fetchone()
            except sqlite3.OperationalError:
                pass

        inv_count = 0
        try:
            from research_harness.orchestrator.invariants import InvariantChecker
            from research_harness.storage.db import Database as _Db

            db = _Db(db_path_provider())
            inv_count = len(InvariantChecker(db).check_all(topic_id, stage))
        except Exception:
            pass

        def _i(key: str) -> int:
            if agg is None:
                return 0
            val = agg[key]
            return int(val or 0)

        def _f(key: str) -> float:
            if agg is None:
                return 0.0
            val = agg[key]
            return float(val or 0.0)

        duration_sec = 0.0
        if agg is not None and agg["first_at"] and agg["last_at"]:
            try:
                first = datetime.fromisoformat(
                    str(agg["first_at"]).replace("Z", "+00:00")
                )
                last = datetime.fromisoformat(
                    str(agg["last_at"]).replace("Z", "+00:00")
                )
                duration_sec = max(0.0, (last - first).total_seconds())
            except (ValueError, TypeError):
                duration_sec = 0.0

        rubric_dict: dict[str, Any] | None = None
        if rubric_row is not None:
            rubric_dict = {
                "weighted_total": float(rubric_row["weighted_total"] or 0.0),
                "verdict": rubric_row["verdict"],
                "shadow_verdict": rubric_row["shadow_verdict"],
                "scored_at": rubric_row["scored_at"],
            }

        evidence_breakdown: dict[str, int] = {}
        with get_db_context() as conn:
            try:
                artifact_n = conn.execute(
                    "SELECT COUNT(*) AS n FROM project_artifacts "
                    "WHERE topic_id = ? AND stage = ?",
                    (topic_id, stage),
                ).fetchone()
                evidence_breakdown["artifacts"] = (
                    int(artifact_n["n"] or 0) if artifact_n else 0
                )
            except sqlite3.OperationalError:
                evidence_breakdown["artifacts"] = 0

            if stage == "init":
                try:
                    ip_n = conn.execute(
                        "SELECT COUNT(*) AS n FROM topic_intake_profile WHERE topic_id = ?",
                        (topic_id,),
                    ).fetchone()
                    evidence_breakdown["intake_profile"] = (
                        int(ip_n["n"] or 0) if ip_n else 0
                    )
                except sqlite3.OperationalError:
                    evidence_breakdown["intake_profile"] = 0

            if stage == "build":
                try:
                    paper_n = conn.execute(
                        "SELECT COUNT(*) AS n FROM paper_topics WHERE topic_id = ?",
                        (topic_id,),
                    ).fetchone()
                    evidence_breakdown["papers"] = (
                        int(paper_n["n"] or 0) if paper_n else 0
                    )
                except sqlite3.OperationalError:
                    evidence_breakdown["papers"] = 0

            if stage in ("analyze", "propose"):
                try:
                    claim_n = conn.execute(
                        "SELECT COUNT(*) AS n FROM normalized_claims WHERE topic_id = ?",
                        (topic_id,),
                    ).fetchone()
                    evidence_breakdown["claims"] = (
                        int(claim_n["n"] or 0) if claim_n else 0
                    )
                except sqlite3.OperationalError:
                    evidence_breakdown["claims"] = 0

            if stage == "analyze":
                try:
                    gap_n = conn.execute(
                        "SELECT COUNT(*) AS n FROM gaps WHERE topic_id = ?",
                        (topic_id,),
                    ).fetchone()
                    evidence_breakdown["gaps"] = int(gap_n["n"] or 0) if gap_n else 0
                except sqlite3.OperationalError:
                    evidence_breakdown["gaps"] = 0

        evidence_count = sum(evidence_breakdown.values())

        return {
            "topic_id": topic_id,
            "stage": stage,
            "primitives_planned": planned,
            "primitives_ran": _i("ran"),
            "primitives_skipped": _i("skipped_n"),
            "primitives_failed": _i("failed"),
            "total_tokens": _i("tokens"),
            "total_cost_usd": _f("cost_usd"),
            "duration_sec": duration_sec,
            "invariant_violations_count": inv_count,
            "rubric": rubric_dict,
            "evidence_count": evidence_count,
            "evidence_breakdown": evidence_breakdown,
        }
