"""S4: the figure_suite_plan primitive — v1 design (dual grounding, matrix
coverage, generative export, logging requirements) and v2 reconcile."""

from __future__ import annotations

import json

import pytest

import research_harness.execution.llm_primitives as LP
import research_harness.primitives.exemplar_impls as EAG
from research_harness.primitives import registry as R
from research_harness.primitives.result_figure_impls import figure_suite_plan
from research_harness.primitives.types import _to_jsonable


@pytest.fixture(autouse=True)
def _reset_router():
    EAG._ROUTER_OK = None
    yield
    EAG._ROUTER_OK = None


def _mock_llm(monkeypatch, responder):
    class _FC:
        model = "mock-llm"

    monkeypatch.setattr(LP, "_get_client", lambda *a, **k: _FC())
    monkeypatch.setattr(LP, "_client_chat", responder)


# A design plan the mocked planner returns: one generative method figure + one
# deterministic 2-panel results figure (benchmark bar + survival curve).
_PLAN_JSON = json.dumps(
    {
        "plan": {
            "paper_type": "empirical",
            "style_profile": "biomed_omics",
            "figures": [
                {
                    "figure_id": "fig:arch",
                    "role": "method",
                    "pipeline": "generative",
                    "title": "Architecture",
                    "purpose": "show the pipeline",
                    "composition": "1x1",
                },
                {
                    "figure_id": "fig:main",
                    "role": "results",
                    "pipeline": "deterministic",
                    "placement": "main",
                    "composition": "1x2",
                    "caption_skeleton": "(a) benchmark; (b) survival",
                    "panels": [
                        {
                            "panel_id": "a",
                            "chart": "grouped_bar",
                            "record_filter": {"figure_type": "benchmark"},
                        },
                        {
                            "panel_id": "b",
                            "chart": "km_survival",
                            "record_filter": {"figure_type": "survival"},
                        },
                    ],
                },
            ],
            "narrative_order": ["fig:arch", "fig:main"],
            "notes": "",
        }
    }
)


def _responder(client, prompt):
    if "WHOLE-PAPER FIGURE SUITE" in prompt or "Design THIS paper" in prompt:
        return _PLAN_JSON
    # curate: return a high-quality figure_suite exemplar form
    return json.dumps(
        {
            "form": {
                "paper_type": "empirical",
                "figures": [
                    {
                        "role": "results",
                        "charts": ["grouped_bar", "km_survival"],
                        "n_panels": 2,
                    }
                ],
                "n_figures": 1,
            },
            "quality": 9,
            "summary": "clean",
        }
    )


# --------------------------------------------------------------------------- #
# Fake DB (papers for curate + goal_pool for planned inventory)               #
# --------------------------------------------------------------------------- #


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Row(dict):
    def __getitem__(self, k):
        return dict.get(self, k)


class _Conn:
    def __init__(self, papers, goals, topic):
        self._papers = papers
        self._goals = goals
        self._topic = topic

    def execute(self, sql, params=None):
        if "FROM papers" in sql:
            return _Cur(self._papers)
        if "FROM goal_pool" in sql:
            return _Cur(self._goals)
        if "FROM topics t" in sql:
            return _Cur([self._topic] if self._topic else [])
        if "FROM project_artifacts" in sql:
            return _Cur([])
        return _Cur([{"content": "note"}])

    def close(self):
        pass


class _DB:
    def __init__(self, papers, goals, topic=None):
        self._papers = [_Row(p) for p in papers]
        self._goals = [_Row(g) for g in goals]
        self._topic = _Row(topic) if topic else None

    def connect(self):
        return _Conn(self._papers, self._goals, self._topic)


# --------------------------------------------------------------------------- #
# v1 design                                                                   #
# --------------------------------------------------------------------------- #


def test_v1_design_from_goal_pool_planned(monkeypatch):
    _mock_llm(monkeypatch, _responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "captions " * 40)
    db = _DB(
        papers=[
            {"id": 1, "title": "P", "abstract": "a" * 200, "venue": "npj", "year": 2025}
        ],
        goals=[
            {
                "dataset": "LIHC",
                "metric_name": "C-index",
                "baseline_metric": 0.7,
                "target_metric_delta": 0.05,
                "target_venue": "npj",
            }
        ],
    )
    out = figure_suite_plan(
        db=db, topic_id=1, target_content="A survival model", source="matrix"
    )
    assert out.version_phase == "v1_design"
    assert (
        out.inventory_source == "goal_pool_baselines"
        and out.inventory_mode == "planned"
    )
    assert out.paper_type == "empirical"
    assert out.style_profile == "biomed_omics"
    # generative export: the method figure only
    assert [f.figure_id for f in out.generative_figures] == ["fig:arch"]
    assert out.generative_figures[0].purpose == "show the pipeline"
    # logging requirements cover the two deterministic panels
    charts = {r["chart"] for r in out.logging_requirements}
    assert "grouped_bar" in charts and "km_survival" in charts
    # matrix coverage: benchmark bar feedable from goal_pool; survival is not →
    # unfeedable panel reported (planned matrix has no survival records)
    assert out.matrix_coverage["verdict"] == "gaps_found"
    unfeed = [u["panel"] for u in out.matrix_coverage["unfeedable_panels"]]
    assert "fig:main/b" in unfeed  # km_survival has no planned records
    json.dumps(_to_jsonable(out))  # artifact-serializable
    assert out.spec["figure_modules"]["method"] == "illustration"
    assert out.spec["figure_modules"]["results"] == "figure_suite_render"
    assert isinstance(out.spec.get("venue_figure_grammar"), dict)
    assert isinstance(out.spec.get("figure_knowledge"), dict)
    assert out.spec["figures"][0].get("form_id")


def test_the_record_inventory_survives_the_planner_s_truncation(monkeypatch):
    """The planner cuts what it is handed at 3500 characters and the inventory was
    last, so "the only data available to plot" had never been shown to it.
    csmopen12's figure target renders 7,953 characters: the planner saw 36% of the
    paper, none of the inventory, and planned four result figures filtering on
    fields no record carries."""
    prompts: list[str] = []

    def _capture(client, prompt):
        prompts.append(prompt)
        return _responder(client, prompt)

    _mock_llm(monkeypatch, _capture)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _DB(
        papers=[
            {"id": 1, "title": "P", "abstract": "a" * 200, "venue": "npj", "year": 2025}
        ],
        goals=[],
    )
    figure_suite_plan(
        db=db,
        topic_id=1,
        target_content="A cord field queried at assigned levels. " * 250,  # ~10k chars
        source="matrix",
        matrix_json={"datasets": ["DS-A"], "methods": ["Base", "Ours"], "metric": "F1"},
    )
    planning = [p for p in prompts if "RECORD INVENTORY" in p]
    assert planning, "the planner was never shown the inventory"
    # what the planner is handed is cut at 3500; the inventory has to be inside it
    for prompt in planning:
        head = prompt[: prompt.index("RECORD INVENTORY") + 3500]
        assert "DETERMINISTIC RESULT-PLOT POLICY" in head
        assert '"columns"' in head or '"record_count"' in head


def test_v1_design_from_explicit_matrix(monkeypatch):
    _mock_llm(monkeypatch, _responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _DB(
        papers=[
            {
                "id": 1,
                "title": "P",
                "abstract": "a" * 200,
                "venue": "AAAI",
                "year": 2025,
            }
        ],
        goals=[],
        topic={
            "target_venue": "Nature Medicine",
            "domain_name": "clinical medicine",
        },
    )
    out = figure_suite_plan(
        db=db,
        topic_id=1,
        target_content="method",
        source="matrix",
        matrix_json={
            "datasets": ["BEAT", "VOCASET"],
            "methods": ["Base", "Ours"],
            "metric": "LVE",
        },
        style_profile="stem_conference",
    )
    assert out.inventory_source == "explicit_matrix" and out.inventory_mode == "planned"
    assert out.spec["target_venue"] == "Nature Medicine"
    assert out.spec["figure_modules"]["method"] == "illustration"
    assert out.spec["figure_modules"]["results"] == "figure_suite_render"
    assert isinstance(out.spec.get("venue_figure_grammar"), dict)
    # explicit style override wins
    assert out.style_profile == "stem_conference"
    assert out.spec["result_plot_policy"]["selection_basis"] == "explicit_style_profile"


def test_v1_design_routes_topic_venue_over_planner_style(monkeypatch):
    planning_prompts: list[str] = []

    def responder(client, prompt):
        if "WHOLE-PAPER FIGURE SUITE" in prompt or "Design THIS paper" in prompt:
            planning_prompts.append(prompt)
            return _PLAN_JSON.replace('"biomed_omics"', '"stem_conference"')
        return _responder(client, prompt)

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _DB(
        papers=[
            {
                "id": 1,
                "title": "P",
                "abstract": "a" * 200,
                "venue": "Nature Medicine",
                "year": 2025,
            }
        ],
        goals=[],
        topic={
            "target_venue": "Nature Medicine",
            "domain_name": "clinical medicine",
        },
    )

    out = figure_suite_plan(
        db=db,
        topic_id=1,
        target_content="A clinical survival model",
        source="matrix",
        matrix_json={
            "datasets": ["Cohort A"],
            "methods": ["Baseline", "Ours"],
            "metric": "C-index",
        },
    )

    assert out.style_profile == "biomed_omics"
    assert out.spec["style_profile"] == "biomed_omics"
    assert out.spec["target_venue"] == "Nature Medicine"
    assert out.spec["discipline"] == "clinical medicine"
    assert out.spec["result_plot_policy"]["policy_id"] == "biomed_clinical_v1"
    assert out.spec["result_plot_policy"]["selection_basis"] == "venue_discipline"
    assert len(planning_prompts) == 1
    assert "DETERMINISTIC RESULT-PLOT POLICY" in planning_prompts[0]
    assert '"policy_id": "biomed_clinical_v1"' in planning_prompts[0]
    assert '"recommended_charts"' in planning_prompts[0]
    assert '"discouraged_charts"' in planning_prompts[0]


def test_v1_refuses_to_publish_a_plan_without_figures(monkeypatch):
    def responder(client, prompt):
        if "WHOLE-PAPER FIGURE SUITE" in prompt or "Design THIS paper" in prompt:
            return '{"plan":{"paper_type":"empirical"}}'
        return _responder(client, prompt)

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _DB(
        papers=[
            {
                "id": 1,
                "title": "P",
                "abstract": "a" * 200,
                "venue": "AAAI",
                "year": 2025,
            }
        ],
        goals=[],
    )
    with pytest.raises(ValueError, match="planner returned no figures"):
        figure_suite_plan(
            db=db,
            topic_id=1,
            target_content="method",
            source="matrix",
            matrix_json={"datasets": ["D"], "methods": ["M"], "metric": "F1"},
        )


def test_v1_refuses_without_any_inventory(monkeypatch):
    _mock_llm(monkeypatch, _responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _DB(
        papers=[
            {
                "id": 1,
                "title": "P",
                "abstract": "a" * 200,
                "venue": "AAAI",
                "year": 2025,
            }
        ],
        goals=[],
    )
    with pytest.raises(ValueError, match="no experiment inventory"):
        figure_suite_plan(db=db, topic_id=1, target_content="m", source="matrix")


def test_v1_observed_records_grounding(monkeypatch):
    _mock_llm(monkeypatch, _responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _DB(
        papers=[
            {
                "id": 1,
                "title": "P",
                "abstract": "a" * 200,
                "venue": "AAAI",
                "year": 2025,
            }
        ],
        goals=[],
    )
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "BEAT",
            "method": m,
            "metric": "LVE",
            "value": v,
        }
        for m, v in {"Base": 6.8, "Ours": 5.4}.items()
    ]
    out = figure_suite_plan(
        db=db, topic_id=1, target_content="m", source="matrix", records=records
    )
    assert out.inventory_mode == "observed"
    # benchmark bar is now feedable; only survival panel unfeedable
    unfeed = [u["panel"] for u in out.matrix_coverage["unfeedable_panels"]]
    assert "fig:main/a" not in unfeed and "fig:main/b" in unfeed


# --------------------------------------------------------------------------- #
# v2 reconcile                                                                #
# --------------------------------------------------------------------------- #


def test_v2_reconcile_prunes_unfeedable_figure():
    prior = json.loads(_PLAN_JSON)  # {"plan": {...}}
    prior.update(
        {
            "target_venue": "Nature Medicine",
            "discipline": "clinical medicine",
            "result_plot_policy": {
                "policy_id": "biomed_clinical_v1",
                "selection_basis": "venue_discipline",
            },
        }
    )
    # actual records only feed the benchmark bar; the survival panel + any
    # figure with no feedable panels should be handled
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "BEAT",
            "method": m,
            "metric": "LVE",
            "value": v,
        }
        for m, v in {"Base": 6.8, "Ours": 5.4}.items()
    ]
    out = figure_suite_plan(
        target_content="m", source="records", prior_plan=prior, records=records
    )
    assert out.version_phase == "v2_reconciled"
    # fig:main keeps its feedable benchmark panel (not pruned); fig:arch is
    # generative (not record-fed) so it survives too
    kept = [f["figure_id"] for f in out.spec["figures"]]
    assert "fig:main" in kept and "fig:arch" in kept
    # survival panel reported unsatisfied, and the reason separates a value no row
    # holds from a field the records never carried — the second is a plan written
    # against a vocabulary the evidence never used, and it is a different repair.
    unsat = {u["panel"]: u["reason"] for u in out.reconciliation["unsatisfied"]}
    assert "fig:main/b" in unsat
    assert all(
        reason == "no_matching_records"
        or ":records_carry_no_field:" in reason
        or ":no_row_matches:" in reason
        for reason in unsat.values()
    ), unsat
    assert out.spec["target_venue"] == "Nature Medicine"
    assert out.spec["discipline"] == "clinical medicine"
    assert out.spec["result_plot_policy"]["policy_id"] == "biomed_clinical_v1"


def test_v2_reconcile_drops_fully_unfeedable_figure():
    prior = {
        "plan": {
            "figures": [
                {
                    "figure_id": "fig:km",
                    "role": "results",
                    "pipeline": "deterministic",
                    "panels": [
                        {
                            "panel_id": "a",
                            "chart": "km_survival",
                            "record_filter": {"figure_type": "survival"},
                        }
                    ],
                },
                {
                    "figure_id": "fig:bar",
                    "role": "results",
                    "pipeline": "deterministic",
                    "panels": [
                        {
                            "panel_id": "a",
                            "chart": "grouped_bar",
                            "record_filter": {"figure_type": "benchmark"},
                        }
                    ],
                },
            ],
            "narrative_order": ["fig:km", "fig:bar"],
        }
    }
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "D",
            "method": "Ours",
            "metric": "F1",
            "value": 0.8,
        }
    ]
    out = figure_suite_plan(
        target_content="m", source="records", prior_plan=prior, records=records
    )
    kept = [f["figure_id"] for f in out.spec["figures"]]
    assert kept == ["fig:bar"]  # fig:km pruned (no survival records)
    assert "fig:km" in out.reconciliation["pruned"]
    assert out.spec["narrative_order"] == ["fig:bar"]


def test_v2_requires_prior_plan():
    with pytest.raises(ValueError, match="requires a prior_plan"):
        figure_suite_plan(target_content="m", source="records", records=[])


def test_plan_primitive_registered():
    assert "figure_suite_plan" in R.PRIMITIVE_REGISTRY
    assert R.get_primitive_impl("figure_suite_plan") is not None
    spec = R.PRIMITIVE_REGISTRY["figure_suite_plan"]
    assert spec.requires_llm is False
    assert set(spec.input_schema["properties"]["source"]["enum"]) == {
        "matrix",
        "records",
    }
