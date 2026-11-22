from __future__ import annotations

from research_harness.auto_runner import checkpoint as ckpt
from research_harness.runtime import RunTrace


def test_checkpoint_seeds_canonical_run_trace() -> None:
    checkpoint = ckpt.new_checkpoint(
        7,
        mode="autonomous",
        session_command=["rh", "auto-run"],
    )

    trace = RunTrace(**checkpoint["run_trace"])

    assert trace.run_id.startswith("auto_runner.topic.7.")
    assert trace.task_id == "topic:7"
    assert trace.status.value == "running"
    assert trace.inputs["topic_id"] == 7
    assert trace.inputs["mode"] == "autonomous"
    assert trace.inputs["session_command"] == ["rh", "auto-run"]


def test_record_event_mirrors_history_into_canonical_trace() -> None:
    checkpoint = ckpt.new_checkpoint(7)

    ckpt.record_event(
        checkpoint,
        stage="build",
        event="tool_call",
        detail="paper_search completed",
    )

    trace = RunTrace(**checkpoint["run_trace"])

    assert len(checkpoint["history"]) == 1
    assert len(trace.steps) == 1
    step = trace.steps[0]
    assert step.kind.value == "stage_event"
    assert step.status.value == "success"
    assert step.metadata["stage"] == "build"
    assert step.metadata["event"] == "tool_call"
    assert step.metadata["detail"] == "paper_search completed"
