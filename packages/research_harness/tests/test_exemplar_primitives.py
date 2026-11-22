"""Deterministic tests for the Exemplar-Anchored Generation (EAG) primitives.

LLM calls are mocked (fake client + canned responses); the anti-plagiarism gate
and DB access use no LLM. Covers: quality gate, structure>topic ranking, form-only
plan, the generate↔critique revision loop, and abstract/style units.
"""

from __future__ import annotations

import io

import pytest

import research_harness.execution.llm_primitives as LP
import research_harness.primitives.exemplar_impls as EAG
from research_harness.primitives import registry as R
from research_harness.primitives.exemplar_impls import (
    exemplar_critique,
    exemplar_curate,
    exemplar_generate,
    exemplar_plan,
    exemplar_retrieve,
)
from research_harness.primitives.types import ExemplarUnit


class _FakeCur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, papers):
        self._papers = papers

    def execute(self, sql, params=None):
        if "FROM papers" in sql:
            return _FakeCur(self._papers)
        return _FakeCur([{"content": "methodology: ..."}])

    def close(self):
        pass


class _FakeDB:
    def __init__(self, papers):
        self._papers = papers

    def connect(self):
        return _FakeConn(self._papers)


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


def test_direct_chat_honours_http_timeout_floor(monkeypatch):
    """`--llm direct` used to hard-code urlopen(timeout=180); a 900s line bound
    was ignored, and a leftover 180 in private.env must not pull it back down."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        return io.BytesIO(b'{"choices":[{"message":{"content":"ok"}}]}')

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("LLM_HTTP_TIMEOUT_SECONDS", "180")
    monkeypatch.setattr(EAG.urllib.request, "urlopen", fake_urlopen)
    assert EAG._direct_chat("m", "p") == "ok"
    assert captured["timeout"] == 900


def test_all_five_registered():
    for n in (
        "exemplar_curate",
        "exemplar_retrieve",
        "exemplar_plan",
        "exemplar_generate",
        "exemplar_critique",
    ):
        assert n in R.PRIMITIVE_REGISTRY
        assert R.get_primitive_impl(n) is not None


def test_critique_overlap_gate():
    ex = [
        "the quick brown fox jumps over the lazy dog near the river bank every morning today"
    ]
    bad = exemplar_critique(draft_text=ex[0], exemplar_texts=ex, max_overlap=0.18)
    ok = exemplar_critique(
        draft_text="a wholly original sentence about hepatic tumours and embolization",
        exemplar_texts=ex,
        max_overlap=0.18,
    )
    assert bad.passed is False and bad.overlap_score == 1.0
    assert ok.passed is True and ok.overlap_score == 0.0


def test_curate_quality_gate(monkeypatch):
    def responder(client, prompt):
        if "WeakPaper" in prompt:
            return '{"form":{},"quality":3,"summary":"sparse"}'
        return '{"form":{"moves":[{"move":"gap","gist":"x"}]},"quality":9,"summary":"clean arc"}'

    _mock_llm(monkeypatch, responder)
    db = _FakeDB(
        [
            {
                "id": 1,
                "title": "StrongA",
                "abstract": "a" * 200,
                "venue": "Nature Machine Intelligence",
                "year": 2025,
            },
            {
                "id": 2,
                "title": "WeakPaper",
                "abstract": "b" * 200,
                "venue": "arXiv",
                "year": 2024,
            },
        ]
    )
    out = exemplar_curate(
        db=db, topic_id=1, unit_type="intro_arc", min_quality=7, min_tier_score=0
    )
    assert out.candidates_seen == 2 and out.kept == 1 and out.rejected == 1
    assert out.units[0].venue_tier == "A" and out.units[0].quality == 9.0


def test_curate_chat_exception_is_not_a_quality_reject(monkeypatch):
    """csmopen12 WRITE 017: HTTP 503 from _chat was swallowed as rejected+=1,
    so the calling runtime parked on 'kept no abstract exemplar' instead of route_down."""

    def boom(*_a, **_k):
        raise RuntimeError("HTTP Error 503")

    monkeypatch.setattr(EAG, "_chat", boom)
    db = _FakeDB(
        [
            {
                "id": 1,
                "title": "AnyPaper",
                "abstract": "a" * 200,
                "venue": "Nature",
                "year": 2025,
            }
        ]
    )
    with pytest.raises(RuntimeError, match="503"):
        exemplar_curate(
            db=db, topic_id=1, unit_type="abstract", min_quality=5, min_tier_score=0
        )


def test_curate_tier_filter_default_filters_low_tier(monkeypatch):
    """Default min_tier_score=85 drops non CCF-A/CAS-Q1 sources (goal 4)."""
    _mock_llm(
        monkeypatch,
        lambda c, p: (
            '{"form":{"moves":[{"move":"gap","gist":"x"}]},"quality":9,'
            '"prose_quality":9,"summary":"clean"}'
        ),
    )
    db = _FakeDB(
        [
            {
                "id": 1,
                "title": "TopPaper",
                "abstract": "a" * 200,
                "venue": "Nature",
                "year": 2025,
            },
            {
                "id": 2,
                "title": "LowPaper",
                "abstract": "b" * 200,
                "venue": "arXiv",
                "year": 2024,
            },
        ]
    )
    out = exemplar_curate(db=db, topic_id=1, unit_type="intro_arc", min_quality=7)
    assert out.candidates_seen == 1 and out.kept == 1
    assert out.units[0].source_paper_id == 1


class _TieredConn:
    """Returns topic-scoped rows vs global rows depending on the query shape."""

    def __init__(self, topic_rows, global_rows):
        self._topic = topic_rows
        self._global = global_rows

    def execute(self, sql, params=None):
        if "JOIN paper_topics" in sql:
            return _FakeCur(self._topic)
        if "ORDER BY citation_count DESC" in sql:
            return _FakeCur(self._global)
        if "FROM papers" in sql:
            return _FakeCur(self._global)
        return _FakeCur([{"content": "methodology: ..."}])

    def close(self):
        pass


class _TieredDB:
    def __init__(self, topic_rows, global_rows):
        self._topic = topic_rows
        self._global = global_rows

    def connect(self):
        return _TieredConn(self._topic, self._global)


def test_fetch_sources_global_high_tier_fill():
    """Topic poor in high-tier papers is filled from the global corpus (goal 4)."""
    db = _TieredDB(
        topic_rows=[
            {
                "id": 1,
                "title": "Low",
                "abstract": "b",
                "venue": "arXiv",
                "year": 2024,
                "affiliations": None,
                "citation_count": 100,
            }
        ],
        global_rows=[
            {
                "id": 2,
                "title": "Top",
                "abstract": "a",
                "venue": "Nature",
                "year": 2025,
                "affiliations": '["Stanford University"]',
                "citation_count": 500,
            }
        ],
    )
    out = EAG._fetch_sources(db, topic_id=1, paper_ids=None, limit=3, min_tier_score=85)
    assert [s["id"] for s in out] == [2]
    assert out[0]["top_institutions"]


def test_a_relaxed_grade_does_not_lower_the_bar_on_a_borrowed_exemplar():
    """Relaxing the grade says what the topic's own papers must clear, not how good a
    borrowed exemplar has to be. Tying the fill to the relaxed grade left the relaxed
    retry weaker than the strict pass it retried: A0093's fourteen own papers, a
    retraction notice among them, were judged, all rejected, and the stage parked."""
    db = _TieredDB(
        topic_rows=[
            {
                "id": 1,
                "title": "Low",
                "abstract": "b",
                "venue": "arXiv",
                "year": 2024,
                "affiliations": None,
                "citation_count": 100,
            }
        ],
        global_rows=[
            {
                "id": 2,
                "title": "Top",
                "abstract": "a",
                "venue": "Nature",
                "year": 2025,
                "affiliations": '["Stanford University"]',
                "citation_count": 500,
            }
        ],
    )
    out = EAG._fetch_sources(db, topic_id=1, paper_ids=None, limit=3, min_tier_score=0)
    # The topic's own paper is kept -- that is what the relaxation bought -- and the
    # pool is still filled with a paper that clears the standing bar.
    assert sorted(s["id"] for s in out) == [1, 2]


def test_fetch_sources_respects_explicit_paper_ids():
    """paper_ids is an operator override: keep named sources even below the tier bar."""
    db = _TieredDB(
        topic_rows=[],
        global_rows=[
            {
                "id": 2,
                "title": "Low",
                "abstract": "a",
                "venue": "arXiv",
                "year": 2025,
                "affiliations": None,
                "citation_count": 0,
            }
        ],
    )
    out = EAG._fetch_sources(
        db, topic_id=None, paper_ids=[2], limit=5, min_tier_score=85
    )
    assert [s["id"] for s in out] == [2]
    assert out[0]["tier_score"] < 85


def test_retrieve_structure_over_topic(monkeypatch):
    # pool > top_k -> the LLM ranking path runs; mock returns [2,0,...] (structure>topic)
    _mock_llm(
        monkeypatch,
        lambda c, p: '{"ranking":[2,0,1,3],"rationale":"same-form beats same-topic"}',
    )
    pool = [
        ExemplarUnit(
            unit_type="intro_arc", source_paper_id=i, quality=5.0, form={"moves": []}
        )
        for i in range(4)
    ]
    ret = exemplar_retrieve(
        unit_type="intro_arc", target_content="x", units=pool, top_k=2
    )
    assert [u.source_paper_id for u in ret.ranked] == [2, 0]


def test_retrieve_short_circuit_by_quality(monkeypatch):
    _mock_llm(monkeypatch, lambda c, p: "{}")
    pool = [
        ExemplarUnit(source_paper_id=1, quality=6.0),
        ExemplarUnit(source_paper_id=2, quality=9.0),
    ]
    ret = exemplar_retrieve(
        unit_type="intro_arc", target_content="x", units=pool, top_k=3
    )
    assert [u.source_paper_id for u in ret.ranked] == [2, 1]


def test_plan_form_only(monkeypatch):
    _mock_llm(
        monkeypatch,
        lambda c, p: (
            '{"plan":{"moves":[{"move":"gap","instruction":"state THIS gap"}]}}'
        ),
    )
    pool = [ExemplarUnit(source_paper_id=7, form={"moves": []})]
    pl = exemplar_plan(
        unit_type="intro_arc", target_content="HCC TACE", retrieved_units=pool
    )
    assert pl.form_only is True and pl.exemplar_ids == [7]
    assert pl.plan["moves"][0]["move"] == "gap"


def test_generate_loop_revises_on_overlap(monkeypatch):
    ex = "the quick brown fox jumps over the lazy dog by the river every single morning today indeed"

    def responder(client, prompt):
        if "Write the" in prompt:
            if "IMPORTANT: your previous draft" in prompt:
                return "An original introduction about HCC and TACE, written in our own words."
            return ex  # verbatim copy -> fails the gate on round 1
        return "{}"

    _mock_llm(monkeypatch, responder)
    gen = exemplar_generate(
        unit_type="intro_arc",
        target_content="HCC",
        plan={"moves": [{"move": "gap"}]},
        exemplar_texts=[ex],
        max_rounds=2,
        max_overlap=0.18,
    )
    assert gen.rounds == 2 and gen.passed is True and gen.backend == "self"
    assert gen.critique["overlap_score"] == 0.0


def test_quality_critique_word_band_and_deferral():
    qt = [
        {
            "dimension": "abstract",
            "metric_type": "deterministic",
            "target": {"band": [180, 260]},
            "remediation": "expand the abstract",
        },
        {
            "dimension": "logical_flow",
            "metric_type": "llm_judge",
            "target": {"op": ">=", "value": 4.0},
            "remediation": "strengthen transitions",
        },
        {
            "dimension": "figure_density",
            "metric_type": "deterministic",
            "target": {"op": ">=", "value": 1.0},
            "remediation": "add figures",
        },
    ]
    short = EAG._quality_critique("only a few words", qt, section="abstract")
    assert short["passed"] is False
    assert [f["dimension"] for f in short["failures"]] == ["abstract"]
    assert "logical_flow" in short["deferred"]
    assert "figure_density" in short["deferred"]  # full-document, not per-section

    in_band = EAG._quality_critique(
        " ".join(f"w{i}" for i in range(200)), qt, section="abstract"
    )
    assert in_band["passed"] is True and in_band["failures"] == []


def test_quality_critique_paragraph_development():
    qt = [
        {
            "dimension": "paragraph_length",
            "metric_type": "deterministic",
            "target": {"op": ">=", "value": 1.0},
            "remediation": "develop thin paragraphs",
        }
    ]
    thin = (
        "This is a single sentence paragraph that contains more than fifteen "
        "words so it is underdeveloped."
    )
    developed = (
        "First sentence introduces the idea with enough detail. "
        "Second sentence develops the evidence and reasoning further. "
        "Third sentence draws the implication and transitions onward."
    )
    draft = "\n\n".join([thin, developed, developed])
    res = EAG._quality_critique(draft, qt, section="introduction")
    assert res["passed"] is False
    assert res["failures"][0]["dimension"] == "paragraph_length"

    res2 = EAG._quality_critique(
        "\n\n".join([developed, developed, developed]), qt, section="introduction"
    )
    assert res2["passed"] is True


def test_coerce_quality_targets_accepts_serialized_prescription():
    from research_harness.primitives.venue_prescription import (
        resolve_venue_prescription,
    )

    doc = resolve_venue_prescription(target_venue="NeurIPS").to_dict()
    targets = EAG._coerce_quality_targets(doc)
    assert len(targets) == 14
    assert EAG._coerce_quality_targets(None) == []
    assert EAG._coerce_quality_targets([{"dimension": "x"}]) == [{"dimension": "x"}]


def test_generate_loop_revises_on_quality_miss(monkeypatch):
    too_short = "A short abstract about hepatic tumours."
    in_band = " ".join(f"token{i}" for i in range(200))  # 200 words, in [180, 260]

    def responder(client, prompt):
        if "Write the" in prompt:
            if "IMPORTANT: your draft fails the venue" in prompt:
                return in_band
            return too_short
        return "{}"

    _mock_llm(monkeypatch, responder)
    qt = [
        {
            "dimension": "abstract",
            "metric_type": "deterministic",
            "target": {"band": [180, 260]},
            "remediation": "expand the abstract",
        }
    ]
    gen = exemplar_generate(
        unit_type="abstract",
        target_content="HCC",
        plan={"moves": [{"move": "gap"}]},
        max_rounds=2,
        quality_targets=qt,
    )
    assert gen.rounds == 2 and gen.passed is True and gen.backend == "self"
    assert gen.critique["quality"]["passed"] is True
    assert gen.critique["quality"]["failures"] == []


def test_curate_abstract_and_style_units(monkeypatch):
    _mock_llm(
        monkeypatch,
        lambda c, p: (
            '{"form":{"elements":["problem","method"]},"quality":8,'
            '"prose_quality":8,"summary":"s"}'
        ),
    )
    db = _FakeDB(
        [
            {
                "id": 1,
                "title": "T",
                "abstract": "a" * 200,
                "venue": "Nature",
                "year": 2025,
            }
        ]
    )
    for ut in ("abstract", "style"):
        out = exemplar_curate(db=db, topic_id=1, unit_type=ut, min_quality=7)
        assert out.kept == 1 and out.units[0].unit_type == ut


# --------------------------------------------------------------------------- #
# figure_suite: whole-paper figure-contract FORM curation + suite-spec planning #
# --------------------------------------------------------------------------- #

_SUITE_FORM = (
    '{"form":{"paper_type":"empirical","figures":['
    '{"role":"method","charts":["image"],"n_panels":1,"composition":"1x1"},'
    '{"role":"results","charts":["grouped_bar","heatmap"],"n_panels":2,"composition":"1x2"}],'
    '"narrative_order":["method","results"],'
    '"style_traits":{"palette":"muted","annotation_density":"low","panel_labels":"a",'
    '"error_bars":true},"n_figures":2},"quality":9,"summary":"clean composed suite"}'
)


def test_curate_figure_suite_prefers_caption_evidence(monkeypatch):
    seen_prompts: list[str] = []

    def responder(client, prompt):
        seen_prompts.append(prompt)
        return _SUITE_FORM

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(
        EAG,
        "_figure_evidence",
        lambda db, pid: (
            "FIGURE/TABLE CAPTIONS:\n- Figure 3: Accuracy across datasets. "
            "(a) benchmark comparison; (b) ablation heatmap." + " pad" * 30
        ),
    )
    db = _FakeDB(
        [
            {
                "id": 5,
                "title": "SuitePaper",
                "abstract": "a" * 200,
                "venue": "NeurIPS",
                "year": 2025,
            }
        ]
    )
    out = exemplar_curate(db=db, topic_id=1, unit_type="figure_suite", min_quality=7)
    assert out.kept == 1
    unit = out.units[0]
    assert unit.unit_type == "figure_suite" and unit.venue_tier == "A"
    assert unit.form["paper_type"] == "empirical"
    assert unit.form["figures"][1]["charts"] == ["grouped_bar", "heatmap"]
    assert "FIGURE/TABLE CAPTIONS" in seen_prompts[0]
    assert "WHOLE-PAPER FIGURE" in seen_prompts[0]
    # role vocabulary must be present in the curate prompt
    assert "spatial_map" in seen_prompts[0] and "survey_meta" in seen_prompts[0]


def test_curate_result_figure_suite_alias_still_accepted(monkeypatch):
    """The pilot name result_figure_suite must canonicalize to figure_suite."""
    _mock_llm(monkeypatch, lambda c, p: _SUITE_FORM)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "caps " * 40)
    db = _FakeDB(
        [{"id": 7, "title": "P", "abstract": "a" * 200, "venue": "ICML", "year": 2025}]
    )
    out = exemplar_curate(
        db=db, topic_id=1, unit_type="result_figure_suite", min_quality=7
    )
    assert out.unit_type == "figure_suite"  # canonicalized
    assert out.kept == 1 and out.units[0].unit_type == "figure_suite"


def test_curate_figure_suite_falls_back_without_pdf(monkeypatch):
    seen_prompts: list[str] = []

    def responder(client, prompt):
        seen_prompts.append(prompt)
        return _SUITE_FORM

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(EAG, "_figure_evidence", lambda db, pid: "")
    db = _FakeDB(
        [
            {
                "id": 6,
                "title": "NoPdfPaper",
                "abstract": "b" * 200,
                "venue": "arXiv",
                "year": 2024,
            }
        ]
    )
    out = exemplar_curate(
        db=db, topic_id=1, unit_type="figure_suite", min_quality=7, min_tier_score=0
    )
    assert out.kept == 1
    assert "b" * 50 in seen_prompts[0]  # abstract/notes fallback reached the prompt


def test_plan_figure_suite_produces_renderable_spec(monkeypatch):
    seen_prompts: list[str] = []
    plan_json = (
        '{"plan":{"paper_type":"empirical","style_profile":"biomed_omics","figures":['
        '{"figure_id":"fig:arch","role":"method","pipeline":"generative","title":"Arch",'
        '"purpose":"show the pipeline"},'
        '{"figure_id":"fig:main","role":"results","pipeline":"deterministic",'
        '"placement":"main","composition":"1x2","caption_skeleton":"(a) ...; (b) ...",'
        '"panels":[{"panel_id":"a","chart":"grouped_bar","message":"m",'
        '"record_filter":{"figure_type":"benchmark"}},{"panel_id":"b","chart":"km_survival",'
        '"message":"m2","record_filter":{"figure_type":"survival"}}]}],'
        '"narrative_order":["fig:arch","fig:main"],"notes":""}}'
    )

    def responder(client, prompt):
        seen_prompts.append(prompt)
        return plan_json

    _mock_llm(monkeypatch, responder)
    pool = [
        ExemplarUnit(
            unit_type="figure_suite",
            source_paper_id=9,
            form={"figures": [{"charts": ["grouped_bar"]}]},
        )
    ]
    pl = exemplar_plan(
        unit_type="figure_suite",
        target_content="contributions + record inventory: ...",
        retrieved_units=pool,
    )
    assert pl.form_only is True and pl.exemplar_ids == [9]
    assert pl.plan["paper_type"] == "empirical"
    assert pl.plan["style_profile"] == "biomed_omics"
    assert pl.plan["figures"][0]["pipeline"] == "generative"
    assert pl.plan["figures"][1]["panels"][1]["chart"] == "km_survival"
    # the plan prompt must pin the renderer's chart + style + role vocabularies
    assert "grouped_bar|heatmap|radar" in seen_prompts[0]
    assert "km_survival|volcano" in seen_prompts[0]
    assert (
        "stem_conference|nature_family|social_humanities|biomed_omics"
        in seen_prompts[0]
    )
    assert "framing|method|study_design" in seen_prompts[0]
    assert "empirical|survey" in seen_prompts[0]
    assert "never invent" in seen_prompts[0].lower()


def test_chart_and_style_vocabularies_match_renderer():
    from research_harness.visualization.experiment_figures import (
        PANEL_CHARTS,
        STYLE_PROFILES,
    )

    assert set(EAG.RESULT_FIGURE_CHART_VOCABULARY) == set(PANEL_CHARTS)
    assert set(EAG.RESULT_FIGURE_STYLE_PROFILES) == set(STYLE_PROFILES)


def test_role_pipeline_map_covers_all_roles():
    assert set(EAG.ROLE_PIPELINE) == set(EAG.FIGURE_SUITE_ROLES)
    assert set(EAG.ROLE_PIPELINE.values()) == {
        "deterministic",
        "generative",
        "latex",
        "external_asset",
    }


def test_figure_suite_in_registry_enum_and_render_registered():
    assert "figure_suite_render" in R.PRIMITIVE_REGISTRY
    assert R.get_primitive_impl("figure_suite_render") is not None
    for spec_name in ("exemplar_curate", "exemplar_retrieve", "exemplar_plan"):
        enum = R.PRIMITIVE_REGISTRY[spec_name].input_schema["properties"]["unit_type"][
            "enum"
        ]
        assert "figure_suite" in enum
        assert "result_figure_suite" in enum  # deprecated alias still advertised


def test_curate_pure_cs_topic_anchors_ccfa_prose_under_any_venue(monkeypatch):
    """User mandate: pure-CS papers imitate CCF-A FORM end to end, even when
    the target venue is a Nature-family journal."""
    _mock_llm(
        monkeypatch,
        lambda c, p: (
            '{"form":{"moves":[{"move":"gap","gist":"x"}]},"quality":9,'
            '"prose_quality":9,"summary":"s"}'
        ),
    )
    import research_harness.primitives.exemplar_impls as EAG_

    monkeypatch.setattr(EAG_, "_topic_domain_key", lambda db, tid: "stem")
    db = _FakeDB(
        [
            {
                "id": 1,
                "title": "NaturePaper",
                "abstract": "a" * 200,
                "venue": "Nature",
                "year": 2025,
            },
            {
                "id": 2,
                "title": "CCFAPaper",
                "abstract": "b" * 200,
                "venue": "AAAI Conference on Artificial Intelligence",
                "year": 2025,
            },
        ]
    )
    out = exemplar_curate(db=db, topic_id=1, unit_type="intro_arc", min_quality=7)
    kept_venues = {u.venue for u in out.units}
    assert kept_venues == {"AAAI Conference on Artificial Intelligence"}


# These synthetic controls prove contracts/routing only, not writing quality.
_PROFILE = {
    "venue": "npj Digital Medicine",
    "exemplar_family": "nature_medical",
    "prose_register": "medical_imrad",
}
_MOVE_FORM = {
    "moves": [
        {
            "move": "clinical-context",
            "sentence_action": "state the decision gap",
            "word_range": [15, 30],
        }
    ],
    "length_band_words": [100, 150],
    "opening_forbidden_moves": ["proposal-first"],
}


def _prose_unit(unit_type="abstract_moves", venue="npj Digital Medicine"):
    return ExemplarUnit(
        unit_type=unit_type,
        source_paper_id=17,
        venue=venue,
        quality=9,
        form=dict(_MOVE_FORM),
    )


@pytest.mark.parametrize(
    "target,family,wrong",
    [
        ("npj Digital Medicine", "nature_medical", "Nature Human Behaviour"),
        (
            "Humanities and Social Sciences Communications",
            "nature_hssc",
            "Nature Medicine",
        ),
        ("Scientific Reports", "nature_stem", "npj Digital Medicine"),
    ],
)
def test_discipline_families_do_not_cross(target, family, wrong):
    assert EAG._exemplar_family_for_target(target) == family
    assert EAG._venue_matches_family(target, family)
    assert not EAG._venue_matches_family(wrong, family)
    assert EAG._venue_matches_family("The Lancet Digital Health", "nature_medical")


@pytest.mark.parametrize("unit_type", ["skeleton", "intro_arc", "figure_suite"])
def test_profile_family_filters_global_fill_and_overrides_cs_topic(
    monkeypatch, unit_type
):
    import json

    monkeypatch.setattr(EAG, "_topic_domain_key", lambda *a: "stem")
    db = _TieredDB(
        [],
        [
            {"id": i, "title": v, "venue": v, "abstract": "Text. " * 40, "year": 2025}
            for i, v in enumerate(
                ["Nature Medicine", "Scientific Reports", "NeurIPS"], 1
            )
        ],
    )
    monkeypatch.setattr(
        EAG,
        "_chat",
        lambda *a: json.dumps(
            {"form": {"moves": ["context"]}, "quality": 9, "prose_quality": 9}
        ),
    )
    out = exemplar_curate(
        db=db, topic_id=1, unit_type=unit_type, venue_profile=_PROFILE
    )
    assert [u.venue for u in out.units] == ["Nature Medicine"]


@pytest.mark.parametrize("call", ["curate", "retrieve", "plan", "generate"])
def test_wrong_lane_and_empty_prose_pools_block_before_any_model(monkeypatch, call):
    monkeypatch.setattr(EAG, "_chat", lambda *a: pytest.fail("must block before model"))
    for pool in ([], [_prose_unit(venue="Scientific Reports")]):
        with pytest.raises(ValueError, match="E-WRITE-EAG-POOL-EMPTY"):
            if call == "curate":
                db = _FakeDB(
                    [
                        {
                            "id": 17,
                            "title": "Wrong lane",
                            "venue": "Scientific Reports",
                            "abstract": "Text. " * 40,
                            "year": 2025,
                        }
                    ]
                    if pool
                    else []
                )
                exemplar_curate(
                    db=db,
                    topic_id=1,
                    unit_type="abstract_moves",
                    paper_ids=[17],
                    min_tier_score=0,
                    venue_profile=_PROFILE,
                )
            else:
                kwargs = {
                    "unit_type": "abstract_moves",
                    "target_content": "Fixed claim.",
                    "venue_profile": _PROFILE,
                }
                if call == "retrieve":
                    exemplar_retrieve(units=pool, **kwargs)
                elif call == "plan":
                    exemplar_plan(retrieved_units=pool, **kwargs)
                else:
                    exemplar_generate(retrieved_units=pool, plan=_MOVE_FORM, **kwargs)


@pytest.mark.parametrize(
    "unit_type", ["abstract_moves", "intro_moves", "discussion_moves"]
)
def test_moves_curate_plan_generate_use_section_evidence_and_contract(
    monkeypatch, unit_type
):
    import json

    prompts = []
    source = "Actual section evidence. " * 20
    monkeypatch.setattr(EAG, "_section_prose", lambda *a, **k: source)
    db = _FakeDB(
        [
            {
                "id": 17,
                "title": "Fixture",
                "venue": "npj Digital Medicine",
                "abstract": source,
                "year": 2025,
            }
        ]
    )

    def fake_chat(client, prompt):
        prompts.append(prompt)
        if client.task == "exemplar_curate":
            return json.dumps({"form": _MOVE_FORM, "quality": 9, "prose_quality": 9})
        if client.task == "exemplar_plan":
            return json.dumps({"plan": _MOVE_FORM})
        return (
            "The supplied evidence addresses this decision with a bounded comparison."
        )

    monkeypatch.setattr(EAG, "_chat", fake_chat)
    cur = exemplar_curate(
        db=db, topic_id=1, unit_type=unit_type, venue_profile=_PROFILE
    )
    assert cur.kept == 1 and source.strip() in prompts[0]
    ret = exemplar_retrieve(
        unit_type=unit_type,
        target_content="Fixed claim",
        units=cur.units,
        venue_profile=_PROFILE,
    )
    plan = exemplar_plan(
        unit_type=unit_type,
        target_content="Fixed claim",
        retrieved_units=ret.ranked,
        venue_profile=_PROFILE,
    )
    assert plan.exemplar_ids == [17]
    assert plan.plan["exemplar_family"] == "nature_medical"
    assert plan.plan["prose_register"] == "medical_imrad"
    outline = EAG.render_arc_plan(plan.plan)
    assert (
        "state the decision gap" in outline
        and "100" in outline
        and "proposal-first" in outline
    )
    generated = exemplar_generate(
        unit_type=unit_type,
        target_content="Fixed claim",
        retrieved_units=ret.ranked,
        plan=plan.plan,
        venue_profile=_PROFILE,
    )
    assert generated.passed and generated.draft and generated.rounds == 1
    assert all("medical_imrad" in p for p in prompts)


def test_moves_require_real_section_prose_not_abstract_substitution(monkeypatch):
    monkeypatch.setattr(EAG, "_chat", lambda *a: pytest.fail("no section evidence"))
    monkeypatch.setattr(EAG, "_section_prose", lambda *a, **k: "")
    db = _FakeDB(
        [
            {
                "id": 17,
                "title": "Fixture",
                "venue": "npj Digital Medicine",
                "abstract": "Abstract only. " * 40,
                "year": 2025,
            }
        ]
    )
    with pytest.raises(ValueError, match="E-WRITE-EAG-POOL-EMPTY"):
        exemplar_curate(
            db=db, topic_id=1, unit_type="intro_moves", venue_profile=_PROFILE
        )


def test_empty_or_invalid_move_plan_cannot_fall_through_to_a_draft(monkeypatch):
    calls = []

    def fake_chat(client, prompt):
        calls.append(client.task)
        return "{}"

    monkeypatch.setattr(EAG, "_chat", fake_chat)
    with pytest.raises(ValueError, match="E-WRITE-EAG-PLAN-INVALID"):
        exemplar_generate(
            unit_type="abstract_moves",
            target_content="Fixed claim",
            retrieved_units=[_prose_unit()],
            venue_profile=_PROFILE,
        )
    assert calls == ["exemplar_plan"]


def test_planner_preserves_complete_target_and_json_forms(monkeypatch):
    """Constructed counterexample to csmopen12's ledger R23-R30 tail loss."""
    import json

    target = json.dumps({"paper": "claim " * 1500, "inventory": ["required-tail.csv"]})
    unit = ExemplarUnit(
        unit_type="figure_suite",
        source_paper_id=17,
        venue="Nature",
        quality=9,
        form={"panels": ["panel " * 900], "last": "required-axis"},
    )
    seen = []
    monkeypatch.setattr(
        EAG,
        "_chat",
        lambda client, prompt: seen.append(prompt) or '{"plan":{"figures":[]}}',
    )
    exemplar_plan(
        unit_type="figure_suite", target_content=target, retrieved_units=[unit]
    )
    assert target in seen[0]
    assert (
        json.dumps([{"venue": unit.venue, "form": unit.form}], separators=(",", ":"))
        in seen[0]
    )


@pytest.mark.parametrize(
    "section,unit",
    [
        ("abstract", "abstract_moves"),
        ("introduction", "intro_moves"),
        ("discussion", "discussion_moves"),
    ],
)
def test_actual_arc_consumer_prefers_move_contract(db, monkeypatch, section, unit):
    from research_harness.orchestrator import OrchestratorService

    with db.connect() as conn:
        topic = conn.execute(
            "INSERT INTO topics(name) VALUES (?)", ("move consumer control",)
        ).lastrowid
    service = OrchestratorService(db)
    plan = {
        **_MOVE_FORM,
        "exemplar_family": "nature_medical",
        "prose_register": "medical_imrad",
    }
    service.record_artifact(
        topic, "write", f"exemplar_plan_{unit}", payload={"plan": plan}
    )
    rendered = LP._arc_contract_block(db, topic, section)
    assert "state the decision gap" in rendered
    assert "nature_medical" in rendered and "proposal-first" in rendered

    # Exercise the real section_draft prompt dispatch, stopping at the paid boundary.
    class CapturedPrompt(Exception):
        pass

    seen = []

    def capture(client, prompt, **kwargs):
        seen.append(prompt)
        raise CapturedPrompt

    monkeypatch.setattr(LP, "ensure_section_draft_logic_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        LP,
        "_build_numbered_evidence",
        lambda *args, **kwargs: ("[1] Fixed evidence", [1]),
    )
    monkeypatch.setattr(LP, "_get_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(LP, "_client_chat", capture)
    with pytest.raises(CapturedPrompt):
        LP.section_draft(
            db=db,
            topic_id=topic,
            section=section,
            outline="Caller outline must not suppress the move contract",
            paper_plan={"title": "Control"},
        )
    assert "state the decision gap" in seen[0] and "medical_imrad" in seen[0]


def test_planner_budget_drops_whole_optional_examples_and_blocks_oversize(monkeypatch):
    import json

    units = [
        ExemplarUnit(
            unit_type="figure_suite",
            source_paper_id=i,
            venue="Nature",
            quality=9,
            form={"panels": "p" * 9000},
        )
        for i in range(3)
    ]
    seen = []
    monkeypatch.setattr(
        EAG,
        "_chat",
        lambda client, prompt: seen.append(prompt) or '{"plan":{"figures":[]}}',
    )
    output = exemplar_plan(
        unit_type="figure_suite", target_content="target" * 900, retrieved_units=units
    )
    assert output.exemplar_ids == [0, 1]
    assert (
        json.dumps(
            [{"venue": u.venue, "form": u.form} for u in units[:2]],
            separators=(",", ":"),
        )
        in seen[0]
    )
    with pytest.raises(ValueError, match="E-WRITE-EAG-PAYLOAD-LIMIT"):
        exemplar_plan(
            unit_type="figure_suite", target_content="x" * 24001, retrieved_units=units
        )
    assert len(seen) == 1


def test_invalid_new_moves_do_not_silently_fall_back_to_legacy(db):
    from research_harness.orchestrator import OrchestratorService

    with db.connect() as conn:
        topic = conn.execute(
            "INSERT INTO topics(name) VALUES (?)", ("invalid move control",)
        ).lastrowid
    service = OrchestratorService(db)
    service.record_artifact(
        topic,
        "write",
        "exemplar_plan_intro_arc",
        payload={
            "plan": {"moves": [{"move": "legacy", "instruction": "legacy-sentinel"}]}
        },
    )
    assert "legacy-sentinel" in LP._arc_contract_block(db, topic, "introduction")
    service.record_artifact(
        topic, "write", "exemplar_plan_intro_moves", payload={"plan": None}
    )
    with pytest.raises(ValueError, match="E-WRITE-EAG-PLAN-INVALID"):
        LP._arc_contract_block(db, topic, "introduction")


@pytest.mark.parametrize(
    "venue", ["npj Quantum Information", "npj Computational Materials"]
)
def test_npj_brand_does_not_imply_medical_discipline(venue):
    assert EAG._exemplar_family_for_target(venue) == "nature_stem"
    assert not EAG._venue_matches_family(venue, "nature_medical")


def test_frozen_legacy_contract_never_reads_latest_topic_moves(monkeypatch):
    monkeypatch.setattr(
        LP, "_section_arc_artifact", lambda *a: pytest.fail("must not read latest")
    )
    frozen = {
        "intro_arc": {"moves": [{"move": "legacy", "instruction": "frozen-sentinel"}]}
    }
    assert "frozen-sentinel" in LP._arc_contract_block(
        object(), 1, "introduction", frozen
    )
    assert LP._arc_contract_block(object(), 1, "discussion", frozen) == ""


@pytest.mark.parametrize(
    "change",
    [
        {"moves": [{"move": True, "sentence_action": "write", "word_range": [1, 2]}]},
        {"moves": [{"move": "context", "sentence_action": 17, "word_range": [1, 2]}]},
        {"length_band_words": [1, float("inf")]},
        {"length_band_words": [1, float("nan")]},
        {"length_band_words": [True, 2]},
        {"length_band_words": [3, 2]},
        {"moves": [{"move": " ", "sentence_action": "write", "word_range": [1, 2]}]},
        {"opening_forbidden_moves": [{}]},
        {"opening_forbidden_moves": [""]},
    ],
)
def test_move_shape_rejects_nonsemantic_or_nonfinite_fields(change):
    assert not EAG._valid_moves({**_MOVE_FORM, **change})


@pytest.mark.parametrize("forged", [{}, [], "fake", {"intro_moves": _MOVE_FORM}])
def test_public_plan_cannot_inject_unbound_eag_payload(db, forged):
    with pytest.raises(ValueError, match="EAG"):
        LP.section_draft(
            db=db, topic_id=1, section="introduction", paper_plan={"_eag_plans": forged}
        )


# --------------------------------------------------------------------------- #
# Track A — domain register (dual-track EAG)                                   #
# --------------------------------------------------------------------------- #


def _reg_unit(pid, **form):
    return ExemplarUnit(
        unit_type="domain_register",
        source_paper_id=pid,
        source_title=f"P{pid}",
        venue="ACL",
        quality=8.0,
        form=form,
    )


def test_register_lexicon_keeps_terms_shared_by_papers_and_votes_synonyms():
    units = [
        _reg_unit(
            1,
            task_names=["automated paper review"],
            terms=["strengths and weaknesses", "meta-review"],
            synonyms={"verdict": "accept/reject decision"},
        ),
        _reg_unit(
            2,
            task_names=["Automated paper review"],
            terms=["strengths and weaknesses"],
            synonyms={"verdict": "accept/reject decision", "meta-review": "summary"},
        ),
        _reg_unit(3, terms=["rebuttal"]),
    ]
    lex = EAG.build_register_lexicon(units, min_support=2)
    terms = [d["term"].lower() for d in lex["fields"]["terms"]]
    assert terms == ["strengths and weaknesses"]  # single-paper terms dropped
    assert lex["fields"]["task_names"][0]["support"] == 2
    assert lex["synonyms"]["verdict"] == "accept/reject decision"
    # a term the field itself uses canonically is never flagged as a synonym
    assert "meta-review" not in lex["synonyms"] or "meta-review" not in lex["whitelist"]


def test_register_lexicon_support_is_capped_by_pack_size():
    lex = EAG.build_register_lexicon(
        [_reg_unit(7, terms=["review generation"])], min_support=3
    )
    assert lex["min_support"] == 1
    assert lex["fields"]["terms"][0]["term"] == "review generation"


def test_critique_exempts_canonical_terms_from_overlap_gate():
    shared = "we identify the strengths and weaknesses of each paper submission for area chairs"
    exemplar = "Prior systems " + shared + " in a single pass."
    draft = "Our agent will " + shared + " with explicit evidence."
    plain = exemplar_critique(
        draft_text=draft, exemplar_texts=[exemplar], max_overlap=0.05
    )
    assert not plain.passed  # without a register the standard phrase counts as reuse
    lex = {
        "fields": {
            "terms": [{"term": "strengths and weaknesses", "support": 6}],
            "input_names": [{"term": "paper submission", "support": 6}],
            "output_names": [],
            "task_names": [],
            "metric_names": [],
        },
        "synonyms": {},
    }
    reg = exemplar_critique(
        draft_text=draft,
        exemplar_texts=[exemplar],
        max_overlap=0.05,
        register_lexicon=lex,
    )
    assert reg.overlap_score < plain.overlap_score
    assert (
        "strengths and weaknesses"
        in reg.conformance["register"]["canonical_terms_used"]
    )


def test_critique_flags_non_canonical_synonyms_and_strict_mode():
    lex = {
        "fields": {"output_names": [{"term": "accept/reject decision", "support": 3}]},
        "synonyms": {"verdict": "accept/reject decision"},
    }
    draft = "The agent issues a verdict and explains the verdict."
    strict = exemplar_critique(
        draft_text=draft, exemplar_texts=[], register_lexicon=lex
    )
    assert not strict.passed
    v = strict.conformance["register"]["violations"][0]
    assert v == {"found": "verdict", "use": "accept/reject decision", "count": 2}
    lenient = exemplar_critique(
        draft_text=draft, exemplar_texts=[], register_lexicon=lex, strict_register=False
    )
    assert lenient.passed and lenient.conformance["register"]["violations"]


def test_register_sources_are_never_borrowed_from_another_domain():
    db = _TieredDB(
        topic_rows=[
            {
                "id": 1,
                "title": "Own",
                "abstract": "b",
                "venue": "Annual Meeting of the "
                "Association for Computational Linguistics",
                "year": 2025,
                "affiliations": None,
                "citation_count": 10,
            }
        ],
        global_rows=[
            {
                "id": 2,
                "title": "Foreign",
                "abstract": "a",
                "venue": "Nature",
                "year": 2025,
                "affiliations": None,
                "citation_count": 900,
            }
        ],
    )
    filled = EAG._fetch_sources(
        db, topic_id=1, paper_ids=None, limit=3, min_tier_score=0
    )
    same = EAG._fetch_sources(
        db, topic_id=1, paper_ids=None, limit=3, min_tier_score=0, same_domain=True
    )
    assert 2 in [s["id"] for s in filled]
    assert [s["id"] for s in same] == [1]


def test_lexicon_clause_binds_canonical_terms_into_prompts():
    lex = {
        "fields": {
            "task_names": [{"term": "automated paper review", "support": 2}],
            "terms": [{"term": "strengths and weaknesses", "support": 6}],
        },
        "synonyms": {"verdict": "accept/reject decision"},
    }
    clause = EAG._lexicon_clause(lex)
    assert (
        "automated paper review" in clause
        and "'verdict' -> 'accept/reject decision'" in clause
    )
    assert EAG._lexicon_clause(None) == ""


def test_domain_register_in_registry_enum():
    assert "domain_register" in R._EXEMPLAR_UNIT_TYPES
