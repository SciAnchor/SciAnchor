"""Orchestrator command group for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    invoke_service_or_exit: Callable[
        [click.Context, str, dict[str, object] | None], object
    ],
    orchestrator_status_payload_for_cli: Callable[[object], dict[str, object]],
    orchestrator_gate_check_payload_for_cli: Callable[
        [object, str | None], dict[str, object]
    ],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register orchestrator commands on the root CLI group."""

    @main.group()
    def orchestrator() -> None:
        """Research pipeline orchestrator: stage-gated workflow control."""

    @orchestrator.command("init")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--mode",
        type=click.Choice(["explore", "standard", "strict", "demo"]),
        default="standard",
    )
    @click.pass_context
    def orchestrator_init(ctx: click.Context, topic_name: str, mode: str) -> None:
        """Initialize an orchestrator run for a topic."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        run = svc.init_run(topic_id=topic_id, mode=mode)
        payload = {
            "run_id": run.id,
            "topic_id": run.topic_id,
            "mode": run.mode,
            "current_stage": run.current_stage,
            "stage_status": run.stage_status,
        }
        echo(
            ctx,
            payload,
            f"Orchestrator initialized: {topic_name} -> {run.current_stage}",
        )

    @orchestrator.command("status")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.pass_context
    def orchestrator_status(ctx: click.Context, topic_name: str) -> None:
        """Show orchestrator status for a topic (authoritative state surface)."""
        from .runtime.state_surface import (
            append_state_surface_text,
            orchestrator_run_surface_labels,
        )

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        service_output = invoke_service_or_exit(
            ctx, "orchestrator_status", {"topic_id": topic_id}
        )
        status = orchestrator_status_payload_for_cli(service_output)
        run = status.get("run")
        run_id = run.get("id") if isinstance(run, dict) else None
        # This command reads the orchestrator run, which is the authoritative
        # state surface; label it so a reader never has to guess which surface
        # produced the stage below.
        status.update(orchestrator_run_surface_labels(orchestrator_run_id=run_id))
        summary = f"Status: {status.get('run', {}).get('current_stage', 'unknown')}"
        echo(ctx, status, append_state_surface_text(summary, status))

    @orchestrator.command("artifacts")
    @click.option("--topic", "topic_name", required=True, help="Topic name or id")
    @click.option("--stage", default=None, help="Filter by stage")
    @click.option(
        "--type", "artifact_type", default=None, help="Filter by artifact type"
    )
    @click.option(
        "--active",
        "active_only",
        is_flag=True,
        default=False,
        help="Only show active artifacts (hide superseded/stale)",
    )
    @click.option(
        "--lineage",
        "lineage_id",
        type=int,
        default=None,
        help="Show upstream/downstream dependencies for one artifact id",
    )
    @click.pass_context
    def orchestrator_artifacts(
        ctx: click.Context,
        topic_name: str,
        stage: str | None,
        artifact_type: str | None,
        active_only: bool,
        lineage_id: int | None,
    ) -> None:
        """List artifacts for a topic, with per-artifact detail and lineage."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            lineage: dict[str, list[dict[str, object]]] | None = None
            if lineage_id is not None:
                lineage = {"upstream": [], "downstream": []}
                rows = conn.execute(
                    """
                    SELECT d.from_artifact_id, d.to_artifact_id, d.dependency_type,
                           pa.artifact_type, pa.version, pa.status
                    FROM artifact_dependencies d
                    JOIN project_artifacts pa ON pa.id = d.from_artifact_id
                    WHERE d.to_artifact_id = ?
                    """,
                    (lineage_id,),
                ).fetchall()
                for r in rows:
                    lineage["upstream"].append(
                        {
                            "id": r["from_artifact_id"],
                            "type": r["artifact_type"],
                            "version": r["version"],
                            "status": r["status"],
                            "dependency_type": r["dependency_type"],
                        }
                    )
                rows = conn.execute(
                    """
                    SELECT d.from_artifact_id, d.to_artifact_id, d.dependency_type,
                           pa.artifact_type, pa.version, pa.status
                    FROM artifact_dependencies d
                    JOIN project_artifacts pa ON pa.id = d.to_artifact_id
                    WHERE d.from_artifact_id = ?
                    """,
                    (lineage_id,),
                ).fetchall()
                for r in rows:
                    lineage["downstream"].append(
                        {
                            "id": r["to_artifact_id"],
                            "type": r["artifact_type"],
                            "version": r["version"],
                            "status": r["status"],
                            "dependency_type": r["dependency_type"],
                        }
                    )
        finally:
            conn.close()

        svc = OrchestratorService(db)
        artifacts = svc.list_artifacts(
            topic_id, stage=stage, artifact_type=artifact_type
        )
        if active_only:
            artifacts = [a for a in artifacts if a.status == "active"]
        items = [
            {
                "id": a.id,
                "stage": a.stage,
                "type": a.artifact_type,
                "version": a.version,
                "status": a.status,
                "title": a.title,
                "created_at": a.created_at,
            }
            for a in artifacts
        ]
        payload: object = items
        lines = [
            f"[{i['id']}] {i['type']} v{i['version']} ({i['status']}) "
            f"stage={i['stage']} {i['title'] or ''}".rstrip()
            for i in items
        ]
        message = "\n".join(lines) if lines else "0 artifacts"
        if lineage is not None:
            payload = {"artifacts": items, "lineage": lineage}
            lineage_lines = [f"lineage for artifact {lineage_id}:"]
            for direction in ("upstream", "downstream"):
                for dep in lineage[direction]:
                    lineage_lines.append(
                        f"  {direction}: [{dep['id']}] {dep['type']} "
                        f"v{dep['version']} ({dep['status']}) via {dep['dependency_type']}"
                    )
            if len(lineage_lines) == 1:
                lineage_lines.append("  (no recorded dependencies)")
            message = message + "\n" + "\n".join(lineage_lines)
        echo(ctx, payload, message)

    @orchestrator.command("advance")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option("--actor", default="user", help="Actor name")
    @click.pass_context
    def orchestrator_advance(ctx: click.Context, topic_name: str, actor: str) -> None:
        """Advance the topic to the next stage."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        result = invoke_service_or_exit(
            ctx, "orchestrator_advance", {"topic_id": topic_id, "actor": actor}
        )
        if not isinstance(result, dict):
            raise click.ClickException("orchestrator_advance returned invalid payload")
        echo(
            ctx,
            result,
            result.get("error")
            or f"Advanced: {result.get('from_stage')} -> {result.get('to_stage')}",
        )

    @orchestrator.command("gate-check")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option("--stage", default=None, help="Stage to check (defaults to current)")
    @click.pass_context
    def orchestrator_gate_check(
        ctx: click.Context, topic_name: str, stage: str | None
    ) -> None:
        """Check the gate for a stage."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        service_args: dict[str, object] = {"topic_id": topic_id}
        if stage:
            service_args["stage"] = stage
        service_output = invoke_service_or_exit(
            ctx, "orchestrator_gate_check", service_args
        )
        payload = orchestrator_gate_check_payload_for_cli(service_output, stage)
        echo(ctx, payload, f"Gate decision: {payload['gate_decision']}")

    @orchestrator.command("adversarial-run")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--artifact-id", type=int, required=True, help="Target artifact ID to review"
    )
    @click.option(
        "--proposal",
        "proposal_json",
        required=True,
        help="Proposal snapshot as JSON string",
    )
    @click.option(
        "--objections",
        "objections_json",
        required=True,
        help="Objections as JSON array",
    )
    @click.option(
        "--responses",
        "responses_json",
        default=None,
        help="Proposer responses as JSON array",
    )
    @click.option("--resolver-notes", default="", help="Resolver notes")
    @click.option("--actor", default="user", help="Actor name")
    @click.pass_context
    def orchestrator_adversarial_run(
        ctx: click.Context,
        topic_name: str,
        artifact_id: int,
        proposal_json: str,
        objections_json: str,
        responses_json: str | None,
        resolver_notes: str,
        actor: str,
    ) -> None:
        """Run an adversarial round against a proposal."""
        import json

        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        try:
            proposal = json.loads(proposal_json)
            objections = json.loads(objections_json)
            responses = json.loads(responses_json) if responses_json else None
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON input: {e}", err=True)
            return

        svc = OrchestratorService(db)
        result = svc.run_adversarial_round(
            topic_id=topic_id,
            target_artifact_id=artifact_id,
            proposal_snapshot=proposal,
            objections=objections,
            proposer_responses=responses,
            resolver_notes=resolver_notes,
            actor=actor,
        )
        echo(
            ctx,
            result,
            result.get("error")
            or f"Adversarial round {result.get('round_number')} recorded",
        )

    @orchestrator.command("adversarial-resolve")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--round-artifact-id",
        type=int,
        required=True,
        help="Round artifact ID to resolve",
    )
    @click.option(
        "--scores",
        "scores_json",
        default="{}",
        help="Scores dict as JSON (e.g. '{\"novelty\": 4.5}')",
    )
    @click.option("--notes", default="", help="Resolution notes")
    @click.option("--actor", default="user", help="Actor name")
    @click.pass_context
    def orchestrator_adversarial_resolve(
        ctx: click.Context,
        topic_name: str,
        round_artifact_id: int,
        scores_json: str,
        notes: str,
        actor: str,
    ) -> None:
        """Resolve an adversarial round and determine outcome."""
        import json

        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        try:
            scores = json.loads(scores_json) if scores_json else {}
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON scores: {e}", err=True)
            return

        svc = OrchestratorService(db)
        result = svc.resolve_adversarial_round(
            topic_id=topic_id,
            round_artifact_id=round_artifact_id,
            scores=scores,
            notes=notes,
            actor=actor,
        )
        echo(
            ctx,
            result,
            result.get("error")
            or f"Resolution: {result.get('outcome')} (score: {result.get('mean_score')})",
        )

    @orchestrator.command("adversarial-status")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.pass_context
    def orchestrator_adversarial_status(ctx: click.Context, topic_name: str) -> None:
        """Check adversarial status for the topic."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        status = svc.check_adversarial_status(topic_id)
        echo(
            ctx,
            status,
            f"Adversarial status: {status.get('status', status.get('outcome', 'unknown'))}",
        )

    @orchestrator.command("review-bundle")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--integrity-artifact-id",
        type=int,
        default=None,
        help="Integrity report artifact ID",
    )
    @click.option(
        "--scholarly-artifact-id",
        type=int,
        default=None,
        help="Scholarly report artifact ID",
    )
    @click.pass_context
    def orchestrator_review_bundle(
        ctx: click.Context,
        topic_name: str,
        integrity_artifact_id: int | None,
        scholarly_artifact_id: int | None,
    ) -> None:
        """Create a review bundle from report artifacts."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        try:
            result = svc.create_review_bundle(
                topic_id=topic_id,
                integrity_artifact_id=integrity_artifact_id,
                scholarly_artifact_id=scholarly_artifact_id,
            )
            echo(
                ctx,
                result,
                result.get("error")
                or f"Review bundle created (cycle {result.get('cycle_number')})",
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)

    @orchestrator.command("review-add-issue")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--review-type",
        required=True,
        type=click.Choice(["integrity", "scholarly"]),
        help="Review type",
    )
    @click.option(
        "--severity",
        required=True,
        type=click.Choice(["critical", "high", "medium", "low"]),
        help="Issue severity",
    )
    @click.option("--category", required=True, help="Issue category")
    @click.option("--summary", required=True, help="Issue summary")
    @click.option("--details", default="", help="Detailed description")
    @click.option(
        "--blocking/--no-blocking",
        default=False,
        help="Whether issue blocks advancement",
    )
    @click.option("--recommended-action", default="", help="Recommended fix")
    @click.option(
        "--review-artifact-id", type=int, default=None, help="Source review artifact ID"
    )
    @click.pass_context
    def orchestrator_review_add_issue(
        ctx: click.Context,
        topic_name: str,
        review_type: str,
        severity: str,
        category: str,
        summary: str,
        details: str,
        blocking: bool,
        recommended_action: str,
        review_artifact_id: int | None,
    ) -> None:
        """Add a review finding as an issue."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        result = svc.add_review_issue(
            topic_id=topic_id,
            review_type=review_type,
            severity=severity,
            category=category,
            summary=summary,
            details=details,
            blocking=blocking,
            recommended_action=recommended_action,
            review_artifact_id=review_artifact_id,
        )
        echo(
            ctx,
            result,
            result.get("error")
            or f"Issue #{result.get('issue_id')} added ({severity})",
        )

    @orchestrator.command("review-issues")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option("--stage", default=None, help="Filter by stage")
    @click.option(
        "--status",
        "issue_status",
        default=None,
        type=click.Choice(["open", "in_progress", "resolved", "wontfix"]),
        help="Filter by status",
    )
    @click.option(
        "--blocking-only", is_flag=True, default=False, help="Show only blocking issues"
    )
    @click.pass_context
    def orchestrator_review_issues(
        ctx: click.Context,
        topic_name: str,
        stage: str | None,
        issue_status: str | None,
        blocking_only: bool,
    ) -> None:
        """List review issues."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        issues = svc.list_review_issues(
            topic_id=topic_id,
            stage=stage,
            status=issue_status,
            blocking_only=blocking_only,
        )
        echo(ctx, issues, f"{len(issues)} issues")

    @orchestrator.command("review-respond")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option("--issue-id", type=int, required=True, help="Issue ID to respond to")
    @click.option(
        "--response-type",
        required=True,
        type=click.Choice(["change", "clarify", "dispute", "acknowledge"]),
        help="Response type",
    )
    @click.option("--text", required=True, help="Response text")
    @click.option("--artifact-id", type=int, default=None, help="Linked artifact ID")
    @click.option(
        "--evidence", "evidence_json", default=None, help="Evidence as JSON string"
    )
    @click.pass_context
    def orchestrator_review_respond(
        ctx: click.Context,
        topic_name: str,
        issue_id: int,
        response_type: str,
        text: str,
        artifact_id: int | None,
        evidence_json: str | None,
    ) -> None:
        """Respond to a review issue."""
        import json as json_mod

        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        evidence = None
        if evidence_json:
            try:
                evidence = json_mod.loads(evidence_json)
            except json_mod.JSONDecodeError as e:
                click.echo(f"Error: Invalid JSON evidence: {e}", err=True)
                return

        svc = OrchestratorService(db)
        result = svc.respond_to_issue(
            issue_id=issue_id,
            topic_id=topic_id,
            response_type=response_type,
            response_text=text,
            artifact_id=artifact_id,
            evidence=evidence,
        )
        echo(
            ctx,
            result,
            result.get("error") or f"Response recorded ({response_type})",
        )

    @orchestrator.command("review-resolve")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option("--issue-id", type=int, required=True, help="Issue ID to resolve")
    @click.option(
        "--status",
        "resolution_status",
        required=True,
        type=click.Choice(["resolved", "wontfix"]),
        help="Resolution status",
    )
    @click.pass_context
    def orchestrator_review_resolve(
        ctx: click.Context,
        topic_name: str,
        issue_id: int,
        resolution_status: str,
    ) -> None:
        """Resolve a review issue."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        result = svc.resolve_review_issue(issue_id, resolution_status)
        echo(
            ctx,
            result,
            result.get("error") or f"Issue #{issue_id} -> {resolution_status}",
        )

    @orchestrator.command("review-status")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.pass_context
    def orchestrator_review_status(ctx: click.Context, topic_name: str) -> None:
        """Show review status summary."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        status = svc.get_review_status(topic_id)
        decision = status.get("decision", "unknown")
        blocking = status.get("blocking_open", 0)
        echo(
            ctx,
            status,
            f"Decision: {decision} | Blocking: {blocking} | Cycle: {status.get('cycle_number', 0)}/{status.get('max_cycles', 2)}",
        )

    @orchestrator.command("integrity-check")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--findings",
        "findings_json",
        default=None,
        help="External findings as JSON array",
    )
    @click.pass_context
    def orchestrator_integrity_check(
        ctx: click.Context,
        topic_name: str,
        findings_json: str | None,
    ) -> None:
        """Run 5-phase integrity verification."""
        import json as json_mod

        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        findings = None
        if findings_json:
            try:
                findings = json_mod.loads(findings_json)
            except json_mod.JSONDecodeError as e:
                click.echo(f"Error: Invalid JSON findings: {e}", err=True)
                return

        svc = OrchestratorService(db)
        result = svc.run_integrity_check(topic_id=topic_id, findings=findings)
        passed = "PASSED" if result.get("passed") else "FAILED"
        echo(
            ctx,
            result,
            f"Integrity: {passed} | Critical: {result.get('critical_count', 0)} | Findings: {result.get('total_findings', 0)}",
        )

    @orchestrator.command("finalize")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.pass_context
    def orchestrator_finalize(ctx: click.Context, topic_name: str) -> None:
        """Produce final bundle and process summary."""
        from .orchestrator import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        svc = OrchestratorService(db)
        result = svc.finalize(topic_id=topic_id)
        echo(
            ctx,
            result,
            result.get("error")
            or f"Finalized: {result.get('artifact_count', 0)} artifacts, {result.get('stages_traversed', 0)} stage events",
        )
