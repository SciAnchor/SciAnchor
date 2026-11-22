"""SPC 1.0 精简事件与 detailed audit 分层。"""

from __future__ import annotations

import json

import pytest

from paperfetch.observability import (
    SPCLogEvent,
    configure_observability,
    emit_event,
    reset_event_state,
)
from paperfetch.core.contracts_v1 import Event


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_event_file_is_compact_v1_and_diagnostics_move_to_audit(tmp_path):
    event_file = tmp_path / "events.jsonl"
    reset_event_state("run-1")
    configure_observability(stderr=False, event_file=str(event_file))
    emit_event(
        SPCLogEvent(
            event_code="paper.transfer.failed",
            domain="paper",
            phase="transfer",
            action="download",
            outcome="failed",
            terminal=True,
            level="ERROR",
            task_id="paper-1",
            doi="10.1000/example",
            publisher_key="example",
            route="public_http",
            error_class="publisher_challenge",
            message="出版社返回挑战页",
            diagnostics={"status_code": 403, "cookie": "secret-cookie"},
        )
    )

    event = json.loads(event_file.read_text(encoding="utf-8"))
    Event.model_validate(event)
    assert event["schema_version"] == "spc.event.v1"
    assert event["sequence"] == 1
    assert event["entity"] == {"type": "paper", "id": "10.1000/example"}
    assert event["outcome"] == "failed"
    assert event["error"]["code"] == "publisher_challenge"
    assert event["details_ref"] == "audit/event-000001.json"
    assert "message" not in event
    assert "diagnostics" not in event
    assert "doi" not in event

    detail = json.loads((tmp_path / event["details_ref"]).read_text(encoding="utf-8"))
    assert detail["diagnostics"]["status_code"] == 403
    assert detail["diagnostics"]["cookie"] == "<redacted>"


def test_event_sequence_is_monotonic(tmp_path):
    event_file = tmp_path / "events.jsonl"
    reset_event_state("run-2")
    configure_observability(stderr=False, event_file=str(event_file))
    for index in range(3):
        emit_event(
            SPCLogEvent(
                event_code=f"paper.step.{index}",
                domain="paper",
                phase="transfer",
                action=f"step-{index}",
                outcome="started" if index == 0 else "success",
                terminal=False,
                level="INFO",
            )
        )
    events = [
        json.loads(line) for line in event_file.read_text(encoding="utf-8").splitlines()
    ]
    for event in events:
        Event.model_validate(event)
    assert [item["sequence"] for item in events] == [1, 2, 3]
    assert len({item["event_id"] for item in events}) == 3


def test_partial_is_a_terminal_event_with_one_error(tmp_path):
    event_file = tmp_path / "events.jsonl"
    reset_event_state("run-partial")
    configure_observability(stderr=False, event_file=str(event_file))
    emit_event(
        SPCLogEvent(
            event_code="paper.download.partial",
            domain="paper",
            phase="final",
            action="download",
            outcome="partial",
            terminal=True,
            level="WARNING",
            error_class="mineru_parse_failed",
            message="PDF 已验证，正文解析失败",
        )
    )
    Event.model_validate_json(event_file.read_text(encoding="utf-8"))
