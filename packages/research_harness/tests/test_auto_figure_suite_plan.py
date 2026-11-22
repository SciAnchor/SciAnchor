"""Boundary 1: write-stage auto-trigger for figure_suite_plan."""

from __future__ import annotations

import research_harness.auto_runner.tool_dispatch as TD


class _FakeArtifact:
    def __init__(self, id=1, version=1):
        self.id = id
        self.version = version


class _FakeSvc:
    def __init__(self, existing=None):
        self._existing = existing
        self.recorded = []

    def get_latest_artifact(self, topic_id, stage, artifact_type):
        return self._existing

    def record_artifact(self, **kwargs):
        self.recorded.append(kwargs)
        return _FakeArtifact()


class _FakePlanOut:
    version_phase = "v1_design"
    paper_type = "empirical"
    style_profile = "stem_conference"
    inventory_mode = "planned"
    matrix_coverage = {"verdict": "gaps_found"}

    def __init__(self, figures):
        self.spec = {"figures": figures}


def test_auto_plan_records_when_spec_nonempty(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_AUTOPLAN", raising=False)
    svc = _FakeSvc(existing=None)
    monkeypatch.setattr(
        "research_harness.primitives.result_figure_impls.figure_suite_plan",
        lambda **k: _FakePlanOut([{"figure_id": "fig:main", "role": "results"}]),
    )
    TD._maybe_auto_figure_suite_plan(db=object(), svc=svc, topic_id=1)
    assert len(svc.recorded) == 1
    rec = svc.recorded[0]
    assert rec["artifact_type"] == "figure_suite_plan"
    assert rec["metadata"]["auto"] is True


def test_auto_plan_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_AUTOPLAN", "0")
    svc = _FakeSvc(existing=None)
    called = {"n": 0}

    def _boom(**k):
        called["n"] += 1
        raise AssertionError("should not be called when disabled")

    monkeypatch.setattr(
        "research_harness.primitives.result_figure_impls.figure_suite_plan", _boom
    )
    TD._maybe_auto_figure_suite_plan(db=object(), svc=svc, topic_id=1)
    assert called["n"] == 0 and svc.recorded == []


def test_auto_plan_skips_when_plan_exists(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_AUTOPLAN", raising=False)
    svc = _FakeSvc(existing=_FakeArtifact())  # already planned
    monkeypatch.setattr(
        "research_harness.primitives.result_figure_impls.figure_suite_plan",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not plan")),
    )
    TD._maybe_auto_figure_suite_plan(db=object(), svc=svc, topic_id=1)
    assert svc.recorded == []


def test_auto_plan_skips_empty_spec(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_AUTOPLAN", raising=False)
    svc = _FakeSvc(existing=None)
    monkeypatch.setattr(
        "research_harness.primitives.result_figure_impls.figure_suite_plan",
        lambda **k: _FakePlanOut([]),  # no figures (no LLM/exemplars)
    )
    TD._maybe_auto_figure_suite_plan(db=object(), svc=svc, topic_id=1)
    assert svc.recorded == []


def test_auto_plan_silent_on_no_inventory(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_AUTOPLAN", raising=False)
    svc = _FakeSvc(existing=None)

    def _refuse(**k):
        raise ValueError("no experiment inventory available")

    monkeypatch.setattr(
        "research_harness.primitives.result_figure_impls.figure_suite_plan", _refuse
    )
    TD._maybe_auto_figure_suite_plan(db=object(), svc=svc, topic_id=1)  # no raise
    assert svc.recorded == []


def test_auto_plan_never_raises_on_error(monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_AUTOPLAN", raising=False)
    svc = _FakeSvc(existing=None)

    def _boom(**k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(
        "research_harness.primitives.result_figure_impls.figure_suite_plan", _boom
    )
    TD._maybe_auto_figure_suite_plan(db=object(), svc=svc, topic_id=1)  # swallowed
    assert svc.recorded == []
