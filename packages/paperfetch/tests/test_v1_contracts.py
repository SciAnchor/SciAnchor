"""SPC 1.0 公共边界的契约测试。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from paperfetch.core.contracts_v1 import (
    ArtifactRef,
    BusinessStatus,
    CommandItem,
    CommandResult,
    CommandSummary,
    EntityRef,
    ErrorInfo,
    Event,
    EventOutcome,
    JobLifecycle,
    JobRecord,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _error() -> ErrorInfo:
    return ErrorInfo(
        code="publisher_challenge",
        error_class="access_blocked",
        stage="transfer",
        retryable=True,
        message="出版社返回挑战页",
        remediation="稍后重试合法路由",
        audit_ref="audit/run-1",
    )


def test_completed_command_result_has_one_compact_schema():
    result = CommandResult(
        command="seed-pack.enrich",
        run_id="run-1",
        job_id="job-1",
        status=BusinessStatus.COMPLETED,
        summary=CommandSummary(selected=1, succeeded=1, elapsed_ms=25),
        items=[
            CommandItem(
                entity=EntityRef(type="paper", id="10.1000/example"),
                status=BusinessStatus.COMPLETED,
                artifacts=[
                    ArtifactRef(
                        kind="paper_pdf",
                        path="artifacts/paper/pdf/article.pdf",
                        sha256="a" * 64,
                        size_bytes=1024,
                    )
                ],
                data={"identity_verified": True, "parse_status": "parsed"},
            )
        ],
    )

    payload = result.model_dump(mode="json")
    assert payload["schema_version"] == "spc.command-result.v1"
    assert payload["error"] is None
    assert "primary_failure_class" not in str(payload)
    assert "last_failure_class" not in str(payload)
    assert "failure_taxonomy" not in str(payload)


def test_failed_command_requires_one_stable_error():
    with pytest.raises(ValidationError, match="must contain error"):
        CommandResult(
            command="paper.lookup",
            run_id="run-1",
            status=BusinessStatus.FAILED,
        )

    failed = CommandResult(
        command="paper.lookup",
        run_id="run-1",
        status=BusinessStatus.FAILED,
        summary=CommandSummary(selected=1, failed=1),
        error=_error(),
    )
    assert failed.error.error_class == "access_blocked"


def test_event_terminal_and_error_contract_is_unambiguous():
    with pytest.raises(ValidationError, match="non-terminal outcome"):
        Event(
            event_id="event-1",
            run_id="run-1",
            sequence=1,
            domain="paper",
            stage="transfer",
            action="download",
            outcome=EventOutcome.STARTED,
            terminal=True,
        )

    event = Event(
        event_id="event-2",
        run_id="run-1",
        sequence=2,
        domain="paper",
        entity=EntityRef(type="paper", id="10.1000/example"),
        stage="transfer",
        action="download",
        outcome=EventOutcome.FAILED,
        terminal=True,
        error=_error(),
        details_ref="audit/run-1/transfer.json",
    )
    assert event.error.code == "publisher_challenge"


def test_job_lifecycle_does_not_duplicate_business_status():
    now = datetime.now(timezone.utc)
    job = JobRecord(
        job_id="job-1",
        command="seed-pack.enrich",
        lifecycle=JobLifecycle.FINISHED,
        run_id="run-1",
        created_at=now,
        started_at=now,
        finished_at=now,
        command_ref="command.json",
        result_ref="result.json",
        event_ref="events.jsonl",
        stderr_ref="stderr.log",
    )
    payload = job.model_dump(mode="json")
    assert payload["lifecycle"] == "finished"
    assert "business_summary" not in payload
    assert "status" not in payload


def test_unknown_public_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CommandSummary(selected=1, succeeded=1, downloaded=1)


def test_summary_counts_partial_without_inventing_download_specific_totals():
    summary = CommandSummary(selected=2, succeeded=1, partial=1)
    assert summary.model_dump()["partial"] == 1
    with pytest.raises(ValidationError, match="outcome counts exceed"):
        CommandSummary(selected=1, succeeded=1, partial=1)


def test_partial_requires_one_actionable_error():
    with pytest.raises(ValidationError, match="partial, failed, or rejected"):
        CommandItem(
            entity=EntityRef(type="paper", id="paper-1"),
            status=BusinessStatus.PARTIAL,
        )
