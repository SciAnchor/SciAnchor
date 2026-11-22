"""Tests for human feedback context carry-forward and post-planner injection."""

from __future__ import annotations

from research_harness.auto_runner import checkpoint as ckpt
from research_harness.auto_runner.stage_executor import (
    _apply_human_feedback_context,
    _carried_forward_stage_context,
)

_CONTEXT = {
    "schema_version": "rh.human_feedback_context.v1",
    "feedback_items": [
        {"target_kind": "section", "target": "related_work", "note": "weak evidence"}
    ],
    "sections_scope": ["related_work"],
    "instructions": "Address the following human feedback explicitly: related_work",
}


def test_feedback_context_survives_stage_context_reset():
    carried = _carried_forward_stage_context(
        {
            "human_feedback_context": dict(_CONTEXT),
            "summary_md": "dropped between stages",
        }
    )

    assert carried["human_feedback_context"] == _CONTEXT
    assert "summary_md" not in carried


def test_injection_overrides_planner_output_on_write():
    checkpoint_data = ckpt.new_checkpoint(1, mode="standard")
    checkpoint_data["stage_context"].update(
        {
            "human_feedback_context": dict(_CONTEXT),
            # planner clobbered these after carry-forward:
            "sections_to_draft": ["introduction", "methods"],
            "extra_instructions": "planner guidance",
        }
    )

    _apply_human_feedback_context(checkpoint_data, "write")

    context = checkpoint_data["stage_context"]
    assert context["sections_to_draft"] == ["related_work"]
    assert "planner guidance" in context["extra_instructions"]
    assert _CONTEXT["instructions"] in context["extra_instructions"]

    # idempotent: applying again must not duplicate the instructions
    _apply_human_feedback_context(checkpoint_data, "write")
    assert context["extra_instructions"].count(_CONTEXT["instructions"]) == 1


def test_injection_keeps_sections_on_non_write_stages():
    checkpoint_data = ckpt.new_checkpoint(2, mode="standard")
    checkpoint_data["stage_context"].update(
        {
            "human_feedback_context": dict(_CONTEXT),
            "sections_to_draft": ["introduction"],
        }
    )

    _apply_human_feedback_context(checkpoint_data, "analyze")

    context = checkpoint_data["stage_context"]
    assert context["sections_to_draft"] == ["introduction"]
    assert _CONTEXT["instructions"] in context["extra_instructions"]


def test_injection_noop_without_feedback_context():
    checkpoint_data = ckpt.new_checkpoint(3, mode="standard")
    before = dict(checkpoint_data["stage_context"])

    _apply_human_feedback_context(checkpoint_data, "write")

    assert checkpoint_data["stage_context"] == before
