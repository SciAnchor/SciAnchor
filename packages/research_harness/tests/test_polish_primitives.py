"""Deterministic tests for the final-draft polish primitives (LLM mocked)."""

from __future__ import annotations

import pytest

import research_harness.execution.llm_primitives as LP
import research_harness.primitives.exemplar_impls as EAG
from research_harness.primitives import registry as R
from research_harness.primitives.polish_impls import (
    _split_sections,
    manuscript_polish,
    manuscript_review,
)


@pytest.fixture(autouse=True)
def _reset_router():
    EAG._ROUTER_OK = None
    yield
    EAG._ROUTER_OK = None


def _mock(monkeypatch, responder):
    class _FC:
        model = "mock-llm"

    monkeypatch.setattr(LP, "_get_client", lambda *a, **k: _FC())
    monkeypatch.setattr(LP, "_client_chat", responder)


def test_registered():
    for n in ("manuscript_review", "manuscript_polish"):
        assert n in R.PRIMITIVE_REGISTRY and R.get_primitive_impl(n) is not None


def test_split_sections_deterministic():
    secs = _split_sections("intro\n## Abstract\naaa\n## Methods\nbbb\n")
    assert set(secs) == {"Abstract", "Methods"}
    assert secs["Abstract"] == "aaa"


def test_review_multi_angle_counts(monkeypatch):
    def responder(client, prompt):
        if "METHODS & STATISTICS" in prompt:
            return '{"findings":[{"severity":"high","location":"Results","issue":"no CI","fix":"add CI"}]}'
        if "DOMAIN" in prompt:
            return '{"findings":[{"severity":"medium","location":"Methods","issue":"scope","fix":"bound it"}]}'
        return '{"findings":[{"severity":"low","location":"Abstract","issue":"long","fix":"trim"}]}'

    _mock(monkeypatch, responder)
    out = manuscript_review(manuscript="## Results\nx\n## Methods\ny", venue="npj")
    assert out.n_high == 1 and out.n_medium == 1 and out.n_low == 1
    assert out.findings[0].severity == "high"  # sorted, high first
    assert set(out.angles) == {"methods_stats", "domain", "editorial"}


def test_polish_blocked_on_high(monkeypatch):
    _mock(
        monkeypatch,
        lambda c, p: (
            '{"findings":[{"severity":"high","location":"Results","issue":"x","fix":"y"}]}'
        ),
    )
    out = manuscript_polish(
        manuscript="## Results\nAUC 0.78 was observed here.",
        run_consistency=False,
        run_deterministic=False,
    )
    assert out.submission_readiness == "blocked" and out.n_high >= 1
    assert out.checks_run == ["manuscript_review"]


def test_polish_ready_when_only_low(monkeypatch):
    _mock(
        monkeypatch,
        lambda c, p: (
            '{"findings":[{"severity":"low","location":"Abstract","issue":"x","fix":"y"}]}'
        ),
    )
    out = manuscript_polish(
        manuscript="## Abstract\nSome text about livers and treatment.",
        run_consistency=False,
        run_deterministic=False,
    )
    assert out.submission_readiness == "ready" and out.n_high == 0 and out.n_medium == 0
