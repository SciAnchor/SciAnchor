"""HTTP routes for the RH paper-production workbench.

Reads dominate this surface, but topic creation is the one deliberate write:
it lets a non-technical researcher start a brand-new study from the web
workbench instead of dropping to the CLI. Creation reuses the same
``prepare_paper_production_entry`` path as ``rh`` so a topic, its orchestrator
run, and the initial checkpoint all appear together.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from research_harness.auto_runner.paper_production_read_models import (
    HypothesisExperimentJob,
    HypothesisStopPolicy,
    PaperProductionRunSnapshot,
    ResearchHypothesisTree,
    VENUE_COMPLIANCE_REPORT_SCHEMA_VERSION,
    VenueComplianceReport,
)


logger = logging.getLogger(__name__)

PASSING_STATES = frozenset({"active", "current", "present", "ready", "passed"})
VENUE_PASSING_STATES = frozenset({"pass", "passed", "success", "ready"})
WORKBENCH_TOPIC_MODES = frozenset({"explore", "standard", "strict", "demo"})


class WorkbenchCreateTopicRequest(BaseModel):
    name: str
    description: str = ""
    target_venue: str = ""
    deadline: str = ""
    mode: str = "standard"


def register_workbench_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
    create_topic_entry: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Register paper-production workbench endpoints.

    ``create_topic_entry`` is optional so existing read-only wirings keep
    working; when it is not supplied the create endpoint returns 503.
    """

    @app.get("/api/workbench/topics")
    def list_workbench_topics():
        with get_db_context() as conn:
            rows = conn.execute(
                """
                SELECT id, name, description, status, target_venue, deadline,
                       created_at
                FROM topics
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return {"topics": [row_to_dict(row) for row in rows]}

    @app.get("/api/workbench/paper-production-runs")
    def list_paper_production_runs():
        with get_db_context() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.topic_id, t.name AS topic_name, r.mode,
                       r.current_stage, r.stage_status, r.gate_status,
                       r.blocking_issue_count, r.unresolved_issue_count,
                       r.stop_before, r.created_at, r.updated_at
                FROM orchestrator_runs r
                JOIN topics t ON t.id = r.topic_id
                ORDER BY r.updated_at DESC, r.id DESC
                """
            ).fetchall()
        return {"runs": [row_to_dict(row) for row in rows]}

    @app.post("/api/workbench/topics", status_code=201)
    def create_workbench_topic(body: WorkbenchCreateTopicRequest):
        if create_topic_entry is None:
            raise HTTPException(
                status_code=503,
                detail="topic creation is not enabled on this server",
            )
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be empty")
        mode = (body.mode or "standard").strip() or "standard"
        if mode not in WORKBENCH_TOPIC_MODES:
            raise HTTPException(
                status_code=422,
                detail=(
                    "unsupported mode: "
                    f"{mode} (expected one of {sorted(WORKBENCH_TOPIC_MODES)})"
                ),
            )
        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM topics WHERE name = ?", (name,)
            ).fetchone()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"a topic named '{name}' already exists",
            )
        try:
            result = create_topic_entry(
                name=name,
                description=body.description.strip(),
                target_venue=body.target_venue.strip(),
                deadline=body.deadline.strip(),
                mode=mode,
            )
        except Exception as exc:  # noqa: BLE001 - surface creation failure to client
            logger.exception("workbench topic creation failed")
            raise HTTPException(
                status_code=500, detail=f"topic creation failed: {exc}"
            ) from exc
        return result

    @app.get("/api/workbench/topics/{topic_id}/run-snapshot")
    def get_run_snapshot(topic_id: int):
        with get_db_context() as conn:
            topic = _topic_or_404(conn, topic_id, row_to_dict)
            run = _latest_run(conn, topic_id, row_to_dict)
            tree_payload = _hypothesis_tree_payload(conn, topic_id, parse_json_field)
            final_bundle = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("final_bundle",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
            publication_pack = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("publication_pack",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
            venue_report = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("venue_compliance_report",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )

        summary = _tree_status_summary(tree_payload)
        snapshot = PaperProductionRunSnapshot(
            topic_id=topic_id,
            current_stage=str(
                (run or {}).get("current_stage") or "paper_production_not_started"
            ),
            current_milestone=str((run or {}).get("stage_status") or "not_started"),
            active_direction_or_idea=str(topic.get("description") or topic["name"]),
            active_hypothesis_id=_active_hypothesis_id(tree_payload),
            supported=summary["supported"],
            refuted=summary["refuted"],
            inconclusive=summary["inconclusive"],
            blocked=summary["blocked"],
            blockers=tuple(
                _snapshot_blockers(
                    run=run,
                    final_bundle=final_bundle,
                    publication_pack=publication_pack,
                    venue_report=venue_report,
                )
            ),
            next_action=_snapshot_next_action(
                final_bundle=final_bundle,
                publication_pack=publication_pack,
                venue_report=venue_report,
            ),
            final_bundle_ready=_artifact_ready(final_bundle),
            publication_pack_ready=_artifact_ready(publication_pack),
            venue_compliance_ready=_venue_report_ready(venue_report),
        )
        return snapshot.to_dict()

    @app.get("/api/workbench/topics/{topic_id}/hypothesis-tree")
    def get_hypothesis_tree(topic_id: int):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
            payload = _hypothesis_tree_payload(conn, topic_id, parse_json_field)
        return payload

    @app.get("/api/workbench/topics/{topic_id}/hypotheses/{hypothesis_id}")
    def get_hypothesis_detail(topic_id: int, hypothesis_id: str):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
            tree_payload = _hypothesis_tree_payload(conn, topic_id, parse_json_field)
        for node in tree_payload.get("nodes", []):
            if isinstance(node, dict) and node.get("id") == hypothesis_id:
                return {"topic_id": topic_id, "hypothesis": dict(node)}
        raise HTTPException(
            status_code=404,
            detail=f"Hypothesis {hypothesis_id} not found for topic {topic_id}",
        )

    @app.get("/api/workbench/topics/{topic_id}/experiment-jobs")
    def list_experiment_jobs(topic_id: int):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
            jobs = _artifact_experiment_jobs(
                conn,
                topic_id=topic_id,
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
            jobs.extend(
                _async_experiment_jobs(
                    conn,
                    topic_id=topic_id,
                    row_to_dict=row_to_dict,
                    parse_json_field=parse_json_field,
                )
            )
        return {"topic_id": topic_id, "jobs": jobs}

    @app.get("/api/workbench/topics/{topic_id}/pack-status")
    def get_pack_status(topic_id: int):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
            final_bundle = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("final_bundle",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
            publication_pack = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("publication_pack",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
            venue_report = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("venue_compliance_report",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
        return {
            "topic_id": topic_id,
            "final_bundle": _artifact_status(final_bundle),
            "publication_pack": _artifact_status(publication_pack),
            "venue_compliance": _artifact_status(
                venue_report,
                ready=_venue_report_ready(venue_report),
            ),
        }

    @app.get("/api/workbench/topics/{topic_id}/venue-compliance")
    def get_venue_compliance(topic_id: int):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
            report = _latest_artifact(
                conn,
                topic_id=topic_id,
                artifact_types=("venue_compliance_report",),
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
        return _venue_report_payload(topic_id=topic_id, report=report)

    @app.get("/api/workbench/doctor")
    def get_workbench_doctor():
        with get_db_context() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "schema_version": "rh.workbench_doctor_status.v1",
            "status": "ok",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "paper_production_read_api", "status": "ok"},
            ],
        }


def _topic_or_404(
    conn: Any,
    topic_id: int,
    row_to_dict: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, name, description, status, target_venue, deadline, created_at
        FROM topics
        WHERE id = ?
        """,
        (topic_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    return row_to_dict(row)


def _latest_run(
    conn: Any,
    topic_id: int,
    row_to_dict: Callable[[Any], dict[str, Any]],
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, topic_id, mode, current_stage, stage_status, gate_status,
               blocking_issue_count, unresolved_issue_count, stop_before,
               created_at, updated_at
        FROM orchestrator_runs
        WHERE topic_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (topic_id,),
    ).fetchone()
    return row_to_dict(row) if row is not None else None


def _latest_artifact(
    conn: Any,
    *,
    topic_id: int,
    artifact_types: tuple[str, ...],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in artifact_types)
    row = conn.execute(
        f"""
        SELECT id, topic_id, stage, artifact_type, status, version, title, path,
               payload_json, metadata_json, created_at, updated_at
        FROM project_artifacts
        WHERE topic_id = ? AND artifact_type IN ({placeholders})
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (topic_id, *artifact_types),
    ).fetchone()
    if row is None:
        return None
    artifact = row_to_dict(row)
    artifact["payload"] = parse_json_field(artifact.pop("payload_json", None), {})
    artifact["metadata"] = parse_json_field(artifact.pop("metadata_json", None), {})
    return artifact


def _artifacts_by_type(
    conn: Any,
    *,
    topic_id: int,
    artifact_type: str,
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, topic_id, stage, artifact_type, status, version, title, path,
               payload_json, metadata_json, created_at, updated_at
        FROM project_artifacts
        WHERE topic_id = ? AND artifact_type = ?
        ORDER BY created_at DESC, id DESC
        """,
        (topic_id, artifact_type),
    ).fetchall()
    artifacts: list[dict[str, Any]] = []
    for row in rows:
        artifact = row_to_dict(row)
        artifact["payload"] = parse_json_field(artifact.pop("payload_json", None), {})
        artifact["metadata"] = parse_json_field(artifact.pop("metadata_json", None), {})
        artifacts.append(artifact)
    return artifacts


def _hypothesis_tree_payload(
    conn: Any,
    topic_id: int,
    parse_json_field: Callable[[str | None, Any], Any],
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT payload_json
        FROM project_artifacts
        WHERE topic_id = ? AND artifact_type = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (topic_id, "research_hypothesis_tree"),
    ).fetchone()
    if row is None:
        return ResearchHypothesisTree(
            topic_id=topic_id,
            paper_plan_artifact_id=None,
            nodes=(),
            stop_policy=HypothesisStopPolicy(
                target_supported=0,
                max_tested=0,
                max_depth=0,
            ),
        ).to_dict()
    payload = parse_json_field(row["payload_json"], {})
    return dict(payload) if isinstance(payload, dict) else {}


def _tree_status_summary(tree_payload: dict[str, Any]) -> dict[str, int]:
    summary = tree_payload.get("status_summary")
    defaults = {
        "supported": 0,
        "refuted": 0,
        "inconclusive": 0,
        "blocked": 0,
        "untested": 0,
    }
    if isinstance(summary, dict):
        return {key: int(summary.get(key) or 0) for key in defaults}
    for node in _node_dicts(tree_payload.get("nodes", [])):
        status = str(node.get("status") or "untested")
        if status in defaults:
            defaults[status] += 1
    return defaults


def _active_hypothesis_id(tree_payload: dict[str, Any]) -> str | None:
    for node in _node_dicts(tree_payload.get("nodes", [])):
        if node.get("status") in {"untested", "inconclusive", "blocked"}:
            return str(node.get("id"))
    nodes = list(_node_dicts(tree_payload.get("nodes", [])))
    if not nodes:
        return None
    return str(nodes[0].get("id"))


def _node_dicts(nodes: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(nodes, list):
        return ()
    return tuple(node for node in nodes if isinstance(node, dict))


def _snapshot_blockers(
    *,
    run: dict[str, Any] | None,
    final_bundle: dict[str, Any] | None,
    publication_pack: dict[str, Any] | None,
    venue_report: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    if run is not None and int(run.get("blocking_issue_count") or 0) > 0:
        blockers.append("orchestrator:blocking_issues")
    if not _artifact_ready(final_bundle):
        blockers.append("final_bundle:missing")
    if not _artifact_ready(publication_pack):
        blockers.append("publication_pack:missing")
    if not _venue_report_ready(venue_report):
        blockers.append("venue_compliance:not_ready")
    return blockers


def _snapshot_next_action(
    *,
    final_bundle: dict[str, Any] | None,
    publication_pack: dict[str, Any] | None,
    venue_report: dict[str, Any] | None,
) -> str:
    if not _artifact_ready(final_bundle):
        return "assemble final bundle"
    if not _artifact_ready(publication_pack):
        return "assemble publication pack"
    if not _venue_report_ready(venue_report):
        return "run venue compliance check"
    return "continue citation, provenance, final bundle, and publication gates"


def _artifact_ready(artifact: dict[str, Any] | None) -> bool:
    if artifact is None:
        return False
    return str(artifact.get("status") or "").lower() in PASSING_STATES


def _venue_report_ready(artifact: dict[str, Any] | None) -> bool:
    if artifact is None:
        return False
    payload = artifact.get("payload")
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").lower()
        if status:
            return status in VENUE_PASSING_STATES
        passed = payload.get("passed")
        if isinstance(passed, bool):
            return passed
        blockers = payload.get("blockers")
        if isinstance(blockers, list) and blockers:
            return False
    return _artifact_ready(artifact)


def _venue_report_payload(
    *,
    topic_id: int,
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    if report is None:
        return VenueComplianceReport(
            topic_id=topic_id,
            status="missing",
            latex_compile_success=False,
            disallowed_packages=(),
            disallowed_commands=(),
            missing_files=(),
            undefined_citations=(),
            undefined_references=(),
            overfull_box_warnings=(),
            main_text_page_count=None,
            page_limit=None,
            references_appendix_excluded=False,
            blockers=("venue_compliance_report:missing",),
        ).to_dict()
    payload = report.get("payload")
    if not isinstance(payload, dict):
        return VenueComplianceReport(
            topic_id=topic_id,
            status="missing",
            latex_compile_success=False,
            disallowed_packages=(),
            disallowed_commands=(),
            missing_files=(),
            undefined_citations=(),
            undefined_references=(),
            overfull_box_warnings=(),
            main_text_page_count=None,
            page_limit=None,
            references_appendix_excluded=False,
            blockers=("venue_compliance_report:empty_payload",),
        ).to_dict()
    if payload.get("schema_version") == VENUE_COMPLIANCE_REPORT_SCHEMA_VERSION:
        return dict(payload)
    return _legacy_venue_report_payload(topic_id=topic_id, payload=payload)


def _legacy_venue_report_payload(
    *,
    topic_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    blockers = _legacy_venue_blockers(payload)
    return VenueComplianceReport(
        topic_id=topic_id,
        status=str(
            payload.get("status") or ("pass" if payload.get("passed") else "fail")
        ),
        latex_compile_success=_legacy_venue_check_passed(
            payload,
            "venue_pdf_compile",
        ),
        disallowed_packages=tuple(_string_list(payload.get("disallowed_packages"))),
        disallowed_commands=tuple(_string_list(payload.get("disallowed_commands"))),
        missing_files=tuple(_string_list(payload.get("missing_files"))),
        undefined_citations=tuple(_string_list(payload.get("undefined_citations"))),
        undefined_references=tuple(_string_list(payload.get("undefined_references"))),
        overfull_box_warnings=tuple(_string_list(payload.get("overfull_box_warnings"))),
        main_text_page_count=_optional_int(payload.get("main_text_page_count")),
        page_limit=_optional_int(payload.get("page_limit")),
        references_appendix_excluded=bool(payload.get("references_appendix_excluded")),
        blockers=tuple(blockers),
    ).to_dict()


def _legacy_venue_check_passed(payload: dict[str, Any], check_name: str) -> bool:
    explicit = payload.get("latex_compile_success")
    if isinstance(explicit, bool) and check_name == "venue_pdf_compile":
        return explicit
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return False
    for check in checks:
        if isinstance(check, dict) and check.get("check") == check_name:
            return check.get("passed") is True
    return False


def _legacy_venue_blockers(payload: dict[str, Any]) -> list[str]:
    blockers = _string_list(payload.get("blockers"))
    if blockers:
        return blockers
    blocking_findings = payload.get("blocking_findings")
    candidates = blocking_findings if isinstance(blocking_findings, list) else []
    if not candidates:
        checks = payload.get("checks")
        if isinstance(checks, list):
            candidates = [
                check
                for check in checks
                if isinstance(check, dict) and check.get("passed") is False
            ]
    return _unique_strings(
        [
            f"{check.get('check')}:failed"
            for check in candidates
            if isinstance(check, dict) and str(check.get("check") or "").strip()
        ]
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_strings([str(item).strip() for item in value if str(item).strip()])


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _artifact_status(
    artifact: dict[str, Any] | None,
    *,
    ready: bool | None = None,
) -> dict[str, Any]:
    if artifact is None:
        return {
            "ready": False if ready is None else ready,
            "artifact_id": None,
            "status": "missing",
            "payload": {},
        }
    return {
        "ready": _artifact_ready(artifact) if ready is None else ready,
        "artifact_id": artifact.get("id"),
        "status": artifact.get("status"),
        "artifact_type": artifact.get("artifact_type"),
        "title": artifact.get("title"),
        "path": artifact.get("path"),
        "payload": artifact.get("payload")
        if isinstance(artifact.get("payload"), dict)
        else {},
    }


def _artifact_experiment_jobs(
    conn: Any,
    *,
    topic_id: int,
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for artifact in _artifacts_by_type(
        conn,
        topic_id=topic_id,
        artifact_type="hypothesis_experiment_job",
        row_to_dict=row_to_dict,
        parse_json_field=parse_json_field,
    ):
        payload = artifact.get("payload")
        if isinstance(payload, dict):
            jobs.append(dict(payload))
    return jobs


def _async_experiment_jobs(
    conn: Any,
    *,
    topic_id: int,
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, job_type, status, topic_id, input_params, result, error,
               created_at, updated_at
        FROM async_jobs
        WHERE topic_id = ? AND job_type IN (?, ?)
        ORDER BY updated_at DESC, id DESC
        """,
        (topic_id, "hypothesis_experiment", "hypothesis_experiment_job"),
    ).fetchall()
    jobs: list[dict[str, Any]] = []
    for row in rows:
        raw = row_to_dict(row)
        input_params = parse_json_field(raw.get("input_params"), {})
        result = parse_json_field(raw.get("result"), {})
        if not isinstance(input_params, dict):
            input_params = {}
        if not isinstance(result, dict):
            result = {}
        hypothesis_id = str(input_params.get("hypothesis_id") or "unknown")
        job_id = str(raw["id"])
        job = HypothesisExperimentJob(
            topic_id=topic_id,
            hypothesis_id=hypothesis_id,
            run_id=f"async_jobs:{job_id}",
            status=_job_status(str(raw.get("status") or "")),
            effective_config=input_params,
            attempts=tuple(
                _runtime_event_attempts(
                    conn,
                    topic_id=topic_id,
                    job_id=job_id,
                    row_to_dict=row_to_dict,
                    parse_json_field=parse_json_field,
                )
            ),
            events_ref={"ledger": "runtime_events", "job_id": job_id},
            result_artifact_id=result.get("result_artifact_id"),
            report_artifact_id=result.get("report_artifact_id"),
        )
        jobs.append(job.to_dict())
    return jobs


def _runtime_event_attempts(
    conn: Any,
    *,
    topic_id: int,
    job_id: str,
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, event_type, created_at, payload_json
        FROM runtime_events
        WHERE topic_id = ? AND job_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (topic_id, job_id),
    ).fetchall()
    attempts: list[dict[str, Any]] = []
    for row in rows:
        event = row_to_dict(row)
        event["payload"] = parse_json_field(event.pop("payload_json", None), {})
        attempts.append(event)
    return attempts


def _job_status(status: str) -> str:
    normalized = status.lower()
    if normalized == "pending":
        return "queued"
    if normalized in {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    }:
        return normalized
    return "failed" if normalized == "error" else "queued"
