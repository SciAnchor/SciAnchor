"""Tests for the placeholder eval.jsonl guard in the experiment CLI."""

from __future__ import annotations

from research_harness.cli_experiment import (
    _AGENT_TEMPLATE_EVAL,
    _placeholder_fixture_error,
)


def test_unmodified_scaffold_eval_is_rejected():
    error = _placeholder_fixture_error({"eval.jsonl": _AGENT_TEMPLATE_EVAL})
    assert error is not None
    assert "placeholder" in error


def test_all_trivial_arithmetic_inputs_are_rejected():
    eval_text = (
        '{"input": "10+7", "answer": "17"}\n'
        '{"input": "6*9", "answer": "54"}\n'
        '{"input": "100-1", "answer": "99"}\n'
    )
    error = _placeholder_fixture_error({"eval.jsonl": eval_text})
    assert error is not None
    assert "arithmetic" in error


def test_topic_specific_eval_passes():
    eval_text = (
        '{"input": "Which zones show post-event hotspot uplift?", "answer": "z12,z14"}\n'
        '{"input": "2+2", "answer": "4"}\n'
    )
    assert _placeholder_fixture_error({"eval.jsonl": eval_text}) is None


def test_missing_eval_fixture_is_not_flagged():
    assert _placeholder_fixture_error({}) is None


def test_non_json_eval_is_left_to_scorer():
    assert _placeholder_fixture_error({"eval.jsonl": "not json"}) is None
