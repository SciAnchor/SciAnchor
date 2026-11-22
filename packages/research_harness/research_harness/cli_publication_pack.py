"""Publication-pack command group for the RH CLI."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import click


def _publication_pack_summary_text(payload: dict[str, object]) -> str:
    ready = "ready" if payload.get("ready_for_review") else "not ready"
    submission = (
        "submission ready"
        if payload.get("submission_ready")
        else "submission checks pending"
    )
    target_profile = str(payload.get("target_profile") or "high-impact-general")
    lines = [f"Publication pack: {ready}; {submission} ({target_profile})"]

    artifact_id = int(payload.get("publication_pack_artifact_id") or 0)
    if artifact_id > 0:
        lines.append(f"artifact_id: {artifact_id}")

    components = payload.get("components")
    if isinstance(components, dict):
        present = [
            str(name)
            for name, component in components.items()
            if isinstance(component, dict) and component.get("status") == "present"
        ]
        if present:
            lines.append(f"present: {', '.join(present)}")

    missing_required = payload.get("missing_required")
    if isinstance(missing_required, list) and missing_required:
        lines.append(
            "missing required: " + ", ".join(str(item) for item in missing_required)
        )

    missing_optional = payload.get("missing_optional")
    if isinstance(missing_optional, list) and missing_optional:
        lines.append(
            "missing optional: " + ", ".join(str(item) for item in missing_optional)
        )

    qa_checks = payload.get("qa_checks")
    if isinstance(qa_checks, list):
        failed = [
            str(check.get("check"))
            for check in qa_checks
            if isinstance(check, dict) and not check.get("passed", False)
        ]
        if failed:
            lines.append(f"qa warnings: {', '.join(failed)}")

    next_actions = payload.get("next_actions")
    if isinstance(next_actions, list):
        components = [
            str(action.get("component"))
            for action in next_actions
            if isinstance(action, dict) and action.get("component")
        ]
        if components:
            lines.append(f"next actions: {', '.join(components)}")

    return "\n".join(lines)


def _publication_pack_backfill_summary_text(payload: dict[str, object]) -> str:
    created_count = int(payload.get("created_count") or 0)
    ready = "ready" if payload.get("ready_for_review") else "not ready"
    submission = (
        "submission ready"
        if payload.get("submission_ready")
        else "submission checks pending"
    )
    lines = [
        f"Publication pack backfill: created {created_count}; {ready}; {submission}"
    ]

    created_artifacts = payload.get("created_artifacts")
    if isinstance(created_artifacts, list) and created_artifacts:
        names = [
            str(item.get("artifact_type"))
            for item in created_artifacts
            if isinstance(item, dict) and item.get("artifact_type")
        ]
        if names:
            lines.append(f"created: {', '.join(names)}")

    remaining = payload.get("remaining_next_actions")
    if isinstance(remaining, list) and remaining:
        components = [
            str(item.get("component"))
            for item in remaining
            if isinstance(item, dict) and item.get("component")
        ]
        if components:
            lines.append(f"remaining next actions: {', '.join(components)}")

    skipped = payload.get("skipped_actions")
    if isinstance(skipped, list) and skipped:
        components = [
            str(item.get("component"))
            for item in skipped
            if isinstance(item, dict) and item.get("component")
        ]
        if components:
            lines.append(f"skipped: {', '.join(components)}")

    return "\n".join(lines)


def _publication_run_summary_text(payload: dict[str, object]) -> str:
    status = str(payload.get("status") or "unknown")
    ready = "ready" if payload.get("ready_for_review") else "not ready"
    submission = (
        "submission ready"
        if payload.get("submission_ready")
        else "submission checks pending"
    )
    target_profile = str(payload.get("target_profile") or "high-impact-general")
    lines = [f"Publication run: {status}; {ready}; {submission} ({target_profile})"]

    run_artifact_id = int(payload.get("publication_run_artifact_id") or 0)
    if run_artifact_id > 0:
        lines.append(f"publication_run_artifact_id: {run_artifact_id}")

    pack_artifact_id = int(payload.get("publication_pack_artifact_id") or 0)
    if pack_artifact_id > 0:
        lines.append(f"publication_pack_artifact_id: {pack_artifact_id}")

    created = payload.get("created_artifacts")
    if isinstance(created, list) and created:
        artifact_types = [
            str(item.get("artifact_type"))
            for item in created
            if isinstance(item, dict) and item.get("artifact_type")
        ]
        if artifact_types:
            lines.append(f"created: {', '.join(artifact_types)}")

    blocking = payload.get("blocking_checks")
    if isinstance(blocking, list) and blocking:
        checks = [
            str(check.get("check"))
            for check in blocking
            if isinstance(check, dict) and check.get("check")
        ]
        if checks:
            lines.append(f"blocking checks: {', '.join(checks)}")

    next_actions = payload.get("next_actions")
    if isinstance(next_actions, list) and next_actions:
        components = [
            str(action.get("component"))
            for action in next_actions
            if isinstance(action, dict) and action.get("component")
        ]
        if components:
            lines.append(f"next actions: {', '.join(components)}")

    return "\n".join(lines)


def _venue_compliance_summary_text(payload: dict[str, object]) -> str:
    status = str(payload.get("status") or "unknown")
    target_profile = str(payload.get("target_profile") or "")
    artifact_id = int(payload.get("venue_compliance_report_artifact_id") or 0)
    blocking = payload.get("blocking_findings")
    blocking_count = len(blocking) if isinstance(blocking, list) else 0
    lines = [
        f"Venue compliance: {status} ({target_profile}); blocking findings: {blocking_count}"
    ]
    if artifact_id > 0:
        lines.append(f"artifact_id: {artifact_id}")
    if isinstance(blocking, list) and blocking:
        checks = [
            str(item.get("check"))
            for item in blocking
            if isinstance(item, dict) and item.get("check")
        ]
        if checks:
            lines.append(f"blocking checks: {', '.join(checks)}")
    next_actions = payload.get("next_actions")
    if isinstance(next_actions, list) and next_actions:
        lines.append(f"next actions: {len(next_actions)}")
    return "\n".join(lines)


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register publication-pack commands on the root CLI group."""

    @main.group("publication-pack")
    def publication_pack() -> None:
        """Generate evidence-bound publication package readiness reports."""

    @publication_pack.command("generate")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--target-profile",
        default="high-impact-general",
        help="Submission/style profile label for the pack contract.",
    )
    @click.option(
        "--record-artifact",
        is_flag=True,
        help="Persist the generated publication_pack artifact in the write stage.",
    )
    @click.pass_context
    def publication_pack_generate_cli(
        ctx: click.Context,
        topic_name: str,
        target_profile: str,
        record_artifact: bool,
    ) -> None:
        """Generate a deterministic publication-pack readiness report for a topic."""
        from .execution.local import LocalBackend
        from .execution.tracked import TrackedBackend
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        backend = TrackedBackend(
            LocalBackend(db),
            ProvenanceRecorder(db),
            default_topic_id=topic_id,
        )
        result = backend.execute(
            "publication_pack_generate",
            topic_id=topic_id,
            target_profile=target_profile,
            record_artifact=record_artifact,
            _stage="write",
            _actor="cli",
            _origin="publication-pack",
        )
        if not result.success:
            raise click.ClickException(
                result.error or "publication_pack_generate failed"
            )
        if not dataclasses.is_dataclass(result.output):
            raise click.ClickException(
                "publication_pack_generate returned an invalid output"
            )

        payload = dataclasses.asdict(result.output)
        echo(ctx, payload, _publication_pack_summary_text(payload))

    @publication_pack.command("venue-check")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--target-profile",
        default="AAAI-style",
        help="Venue/style profile label, e.g. AAAI-style-science-discovery.",
    )
    @click.option(
        "--compiled-pdf-path",
        default="",
        help="Optional venue-formatted PDF path to validate.",
    )
    @click.option(
        "--page-count", type=int, default=None, help="Compiled PDF page count."
    )
    @click.option("--page-limit", type=int, default=None, help="Venue page limit.")
    @click.option(
        "--anonymous/--not-anonymous",
        default=None,
        help="Whether anonymization/double-blind checks passed.",
    )
    @click.option("--bibliography-style", default="", help="Bibliography style label.")
    @click.option(
        "--figure-qa-passed/--figure-qa-not-passed",
        default=None,
        help="Whether final PDF figure placement/legibility passed.",
    )
    @click.option(
        "--human-review-approved/--human-review-not-approved",
        default=None,
        help="Whether final scholarly/human review approved the manuscript.",
    )
    @click.option(
        "--record-artifact/--no-record-artifact",
        default=True,
        help="Persist the venue_compliance_report artifact.",
    )
    @click.pass_context
    def publication_pack_venue_check_cli(
        ctx: click.Context,
        topic_name: str,
        target_profile: str,
        compiled_pdf_path: str,
        page_count: int | None,
        page_limit: int | None,
        anonymous: bool | None,
        bibliography_style: str,
        figure_qa_passed: bool | None,
        human_review_approved: bool | None,
        record_artifact: bool,
    ) -> None:
        """Run deterministic venue-specific submission compliance checks."""
        from .execution.local import LocalBackend
        from .execution.tracked import TrackedBackend
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        backend = TrackedBackend(
            LocalBackend(db),
            ProvenanceRecorder(db),
            default_topic_id=topic_id,
        )
        result = backend.execute(
            "venue_compliance_check",
            topic_id=topic_id,
            target_profile=target_profile,
            compiled_pdf_path=compiled_pdf_path,
            page_count=page_count,
            page_limit=page_limit,
            anonymous=anonymous,
            bibliography_style=bibliography_style,
            figure_qa_passed=figure_qa_passed,
            human_review_approved=human_review_approved,
            record_artifact=record_artifact,
            _stage="write",
            _actor="cli",
            _origin="publication-pack",
        )
        if not result.success:
            raise click.ClickException(result.error or "venue_compliance_check failed")
        if not dataclasses.is_dataclass(result.output):
            raise click.ClickException(
                "venue_compliance_check returned an invalid output"
            )

        payload = dataclasses.asdict(result.output)
        echo(ctx, payload, _venue_compliance_summary_text(payload))

    @publication_pack.command("backfill")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--target-profile",
        default="high-impact-general",
        help="Submission/style profile label for the refreshed pack contract.",
    )
    @click.option(
        "--component",
        "components",
        multiple=True,
        help="Specific publication-pack component/action to backfill. Repeatable.",
    )
    @click.option(
        "--record-artifact/--no-record-artifact",
        default=True,
        help="Persist the refreshed publication_pack artifact after backfill.",
    )
    @click.pass_context
    def publication_pack_backfill_cli(
        ctx: click.Context,
        topic_name: str,
        target_profile: str,
        components: tuple[str, ...],
        record_artifact: bool,
    ) -> None:
        """Backfill deterministic publication-pack QA artifacts."""
        from .execution.local import LocalBackend
        from .execution.tracked import TrackedBackend
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        backend = TrackedBackend(
            LocalBackend(db),
            ProvenanceRecorder(db),
            default_topic_id=topic_id,
        )
        args: dict[str, object] = {
            "topic_id": topic_id,
            "target_profile": target_profile,
            "record_artifact": record_artifact,
            "_stage": "write",
            "_actor": "cli",
            "_origin": "publication-pack",
        }
        if components:
            args["components"] = list(components)
        result = backend.execute("publication_pack_backfill", **args)
        if not result.success:
            raise click.ClickException(
                result.error or "publication_pack_backfill failed"
            )
        if not dataclasses.is_dataclass(result.output):
            raise click.ClickException(
                "publication_pack_backfill returned an invalid output"
            )

        payload = dataclasses.asdict(result.output)
        echo(ctx, payload, _publication_pack_backfill_summary_text(payload))

    @publication_pack.command("run")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--target-profile",
        default="high-impact-general",
        help="Submission/style profile label for the publication run.",
    )
    @click.option(
        "--component",
        "components",
        multiple=True,
        help="Specific safe publication closure component to backfill. Repeatable.",
    )
    @click.option(
        "--record-artifact/--no-record-artifact",
        default=True,
        help="Persist publication_pack and publication_run artifacts.",
    )
    @click.pass_context
    def publication_run_cli(
        ctx: click.Context,
        topic_name: str,
        target_profile: str,
        components: tuple[str, ...],
        record_artifact: bool,
    ) -> None:
        """Run one deterministic publication closure cycle for a topic."""
        from .execution.local import LocalBackend
        from .execution.tracked import TrackedBackend
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        backend = TrackedBackend(
            LocalBackend(db),
            ProvenanceRecorder(db),
            default_topic_id=topic_id,
        )
        args: dict[str, object] = {
            "topic_id": topic_id,
            "target_profile": target_profile,
            "record_artifact": record_artifact,
            "_stage": "finalize",
            "_actor": "cli",
            "_origin": "publication-pack",
        }
        if components:
            args["components"] = list(components)
        result = backend.execute("publication_run", **args)
        if not result.success:
            raise click.ClickException(result.error or "publication_run failed")
        if not dataclasses.is_dataclass(result.output):
            raise click.ClickException("publication_run returned an invalid output")

        payload = dataclasses.asdict(result.output)
        echo(ctx, payload, _publication_run_summary_text(payload))
