"""Architecture-figure reference anchoring (option 2): unit_type=figure curation,
the style-anchor plan, architecture_style_reference orchestration, and the
figure_generate wiring that records reference_style_selection as executed."""

from __future__ import annotations

import json

import pytest

import research_harness.execution.llm_primitives as LP
import research_harness.primitives.exemplar_impls as EAG
from research_harness.primitives.exemplar_impls import (
    architecture_style_reference,
    exemplar_curate,
    exemplar_plan,
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
        return _FakeCur([{"content": "note"}])

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


_ARCH_FORM = (
    '{"form":{"layout_archetype":"layered stack","palette_strategy":"cool technical",'
    '"geometry_language":"rounded modules","depth_model":"flat","composition":"three '
    'zones left-to-right","label_density":"medium"},"quality":9,'
    '"summary":"clean layered schematic"}'
)
_ARCH_PLAN = (
    '{"plan":{"style_anchor":{"layout_archetype":"layered horizontal stack",'
    '"palette_strategy":"restrained monochrome + one accent","geometry_language":'
    '"rounded modules with thin connectors","depth_model":"flat","composition":'
    '"encoder | fusion core | decoder, left to right","typography_mood":"clean '
    'conference"},"rationale":"suits an encoder-fusion-decoder method","avoid":['
    '"generic AI decoration","glowing brains"]}}'
)


# --------------------------------------------------------------------------- #
# unit_type=figure is now real curation (no longer a pb_refs stub)             #
# --------------------------------------------------------------------------- #


def test_curate_figure_uses_architecture_evidence(monkeypatch):
    seen = []

    def responder(client, prompt):
        seen.append(prompt)
        return _ARCH_FORM

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(
        EAG,
        "_architecture_evidence",
        lambda db, pid: (
            "ARCHITECTURE/METHOD FIGURE CAPTIONS:\n- Figure 2: The overall "
            "framework of our model." + " pad" * 30
        ),
    )
    db = _FakeDB(
        [
            {
                "id": 3,
                "title": "ArchPaper",
                "abstract": "a" * 200,
                "venue": "CVPR",
                "year": 2025,
            }
        ]
    )
    out = exemplar_curate(db=db, topic_id=1, unit_type="figure", min_quality=7)
    assert out.kept == 1
    unit = out.units[0]
    assert unit.unit_type == "figure"
    assert unit.form["layout_archetype"] == "layered stack"
    assert "VISUAL STYLE" in seen[0]
    assert "ARCHITECTURE/METHOD FIGURE CAPTIONS" in seen[0]


def test_curate_figure_falls_back_without_pdf(monkeypatch):
    seen = []

    def responder(client, prompt):
        seen.append(prompt)
        return _ARCH_FORM

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(EAG, "_architecture_evidence", lambda db, pid: "")
    db = _FakeDB(
        [
            {
                "id": 4,
                "title": "NoPdf",
                "abstract": "b" * 200,
                "venue": "arXiv",
                "year": 2024,
            }
        ]
    )
    out = exemplar_curate(
        db=db, topic_id=1, unit_type="figure", min_quality=7, min_tier_score=0
    )
    assert out.kept == 1
    assert "b" * 50 in seen[0]  # abstract fallback


def test_plan_figure_produces_style_anchor(monkeypatch):
    seen = []

    def responder(client, prompt):
        seen.append(prompt)
        return _ARCH_PLAN

    _mock_llm(monkeypatch, responder)
    pool = [
        ExemplarUnit(
            unit_type="figure",
            source_paper_id=9,
            form={"layout_archetype": "layered stack"},
        )
    ]
    pl = exemplar_plan(
        unit_type="figure",
        target_content="encoder-fusion-decoder method",
        retrieved_units=pool,
    )
    assert pl.form_only is True and pl.exemplar_ids == [9]
    assert pl.plan["style_anchor"]["layout_archetype"] == "layered horizontal stack"
    assert "VISUAL STYLE ANCHOR" in seen[0]
    assert "NEVER the" in seen[0]  # form-not-content instruction


# --------------------------------------------------------------------------- #
# architecture_style_reference orchestration                                  #
# --------------------------------------------------------------------------- #


def test_style_reference_end_to_end(monkeypatch):
    def responder(client, prompt):
        if "STYLE ANCHOR" in prompt or "style_anchor" in prompt:
            return _ARCH_PLAN
        return _ARCH_FORM  # curate

    _mock_llm(monkeypatch, responder)
    monkeypatch.setattr(
        EAG, "_architecture_evidence", lambda db, pid: "arch caps " * 40
    )
    db = _FakeDB(
        [{"id": 5, "title": "P", "abstract": "a" * 200, "venue": "ICCV", "year": 2025}]
    )
    ref = architecture_style_reference(
        db=db, topic_id=1, target_content="a talking-face model"
    )
    assert ref["executed"] is True
    assert ref["reference_ids"] == [5]
    assert ref["style_anchor"]["palette_strategy"].startswith("restrained")
    assert "encoder" in ref["style_anchor"]["composition"]


def test_style_reference_no_exemplars(monkeypatch):
    _mock_llm(monkeypatch, lambda c, p: '{"form":{},"quality":2,"summary":"x"}')
    monkeypatch.setattr(EAG, "_architecture_evidence", lambda db, pid: "")
    db = _FakeDB(
        [{"id": 6, "title": "P", "abstract": "a" * 200, "venue": "arXiv", "year": 2024}]
    )
    ref = architecture_style_reference(db=db, topic_id=1, target_content="x")
    assert ref["executed"] is False and ref["reason"] == "no_architecture_exemplars"


def test_style_reference_no_topic():
    ref = architecture_style_reference(db=None, topic_id=None, target_content="x")
    assert ref["executed"] is False and ref["reason"] == "no_topic"


# --------------------------------------------------------------------------- #
# figure_generate wiring: prompt injection + provenance                        #
# --------------------------------------------------------------------------- #


def test_figure_generate_injects_and_records_style_reference(monkeypatch, tmp_path):
    from research_harness.execution.llm_primitives import figure_generate

    captured = {}

    def _fake_generate_image(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        captured["contract"] = kwargs.get("figure_contract")

        class _R:
            success = True
            local_path = str(tmp_path / "f.png")
            error = ""
            model_id = "illustration"
            width = 100
            height = 100
            provenance = {"route": "gpt_image"}

        return _R()

    monkeypatch.setattr(
        "research_harness.execution.fal_image_client.generate_image",
        _fake_generate_image,
    )
    monkeypatch.setattr(
        EAG,
        "architecture_style_reference",
        lambda **k: {
            "executed": True,
            "style_anchor": {
                "layout_archetype": "radial hub",
                "palette_strategy": "cool technical",
            },
            "reference_ids": [11, 12],
            "candidates_seen": 4,
            "rationale": "fits",
            "model_used": "mock",
        },
    )

    out = figure_generate(
        db=object(),
        topic_id=1,
        items=[
            {
                "figure_id": "fig:arch",
                "title": "Arch",
                "purpose": "show pipeline",
                "kind": "figure",
            }
        ],
        output_dir=str(tmp_path),
    )
    item = out.items[0]
    # style anchor rendered into the prompt
    assert "radial hub" in captured["prompt"]
    assert "form only" in captured["prompt"]
    # injected into the contract passed to the provider
    assert captured["contract"]["style_reference"]["layout_archetype"] == "radial hub"
    # provenance records reference_style_selection as EXECUTED with real ids
    rss = item.provenance["reference_style_selection"]
    assert rss["executed"] is True
    assert rss["reference_paper_ids"] == [11, 12]
    assert rss["source"] == "rh_exemplar_architecture"
    json.dumps(rss)  # serializable


def test_figure_generate_style_reference_disabled(monkeypatch, tmp_path):
    from research_harness.execution.llm_primitives import figure_generate

    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_STYLE_REF", "0")
    called = {"n": 0}

    def _should_not_call(**k):
        called["n"] += 1
        return {"executed": True}

    monkeypatch.setattr(EAG, "architecture_style_reference", _should_not_call)

    def _fake_generate_image(**kwargs):
        class _R:
            success = True
            local_path = str(tmp_path / "f.png")
            error = ""
            model_id = "m"
            width = 10
            height = 10
            provenance = {}

        return _R()

    monkeypatch.setattr(
        "research_harness.execution.fal_image_client.generate_image",
        _fake_generate_image,
    )
    out = figure_generate(
        db=object(),
        topic_id=1,
        items=[{"figure_id": "f", "title": "t", "purpose": "p", "kind": "figure"}],
        output_dir=str(tmp_path),
    )
    assert called["n"] == 0
    assert out.items[0].provenance["reference_style_selection"]["executed"] is False


def test_figure_generate_fake_route_skips_style_reference(monkeypatch, tmp_path):
    from research_harness.execution.llm_primitives import figure_generate

    called = {"n": 0}
    monkeypatch.setattr(
        EAG,
        "architecture_style_reference",
        lambda **k: called.__setitem__("n", called["n"] + 1) or {"executed": True},
    )
    figure_generate(
        db=object(),
        topic_id=1,
        items=[{"figure_id": "f", "title": "t", "purpose": "p", "kind": "figure"}],
        output_dir=str(tmp_path),
        illustration_fake=True,
    )
    assert called["n"] == 0  # fake route does not resolve references


# --------------------------------------------------------------------------- #
# multimodal image-conditioning: opt-in reference image feeding                #
# --------------------------------------------------------------------------- #


def _wire_generate(monkeypatch, tmp_path, ref_images_fn):
    from research_harness.execution.llm_primitives import figure_generate

    captured = {}

    def _fake_generate_image(**kwargs):
        captured["reference_images"] = kwargs.get("reference_images")

        class _R:
            success = True
            local_path = str(tmp_path / "f.png")
            error = ""
            model_id = "illustration"
            width = 10
            height = 10
            provenance = {}

        return _R()

    monkeypatch.setattr(
        "research_harness.execution.fal_image_client.generate_image",
        _fake_generate_image,
    )
    monkeypatch.setattr(
        EAG,
        "architecture_style_reference",
        lambda **k: {
            "executed": True,
            "style_anchor": {"layout_archetype": "hub"},
            "reference_ids": [11, 12],
            "candidates_seen": 3,
            "model_used": "m",
        },
    )
    monkeypatch.setattr(
        "research_harness.visualization.result_figure_refs.architecture_reference_images",
        ref_images_fn,
    )
    out = figure_generate(
        db=object(),
        topic_id=1,
        items=[
            {"figure_id": "fig:arch", "title": "A", "purpose": "p", "kind": "figure"}
        ],
        output_dir=str(tmp_path),
    )
    return out, captured


def test_reference_images_fed_when_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_REF_IMAGES", "1")
    out, captured = _wire_generate(
        monkeypatch, tmp_path, lambda db, ids, **k: [b"png1", b"png2"]
    )
    # actual reference PNG bytes were passed to generation
    assert captured["reference_images"] == (b"png1", b"png2")
    rss = out.items[0].provenance["reference_style_selection"]
    assert rss["reference_image_count"] == 2
    assert rss["conditioning"] == "image"


def test_reference_images_not_fed_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_REF_IMAGES", raising=False)
    called = {"n": 0}

    def _should_not_extract(db, ids, **k):
        called["n"] += 1
        return [b"x"]

    out, captured = _wire_generate(monkeypatch, tmp_path, _should_not_extract)
    assert called["n"] == 0  # not resolved unless opted in
    assert captured["reference_images"] == ()
    rss = out.items[0].provenance["reference_style_selection"]
    assert rss["reference_image_count"] == 0
    assert rss["conditioning"] == "text_anchor"


def test_reference_images_degrade_when_none_extracted(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_REF_IMAGES", "1")
    out, captured = _wire_generate(monkeypatch, tmp_path, lambda db, ids, **k: [])
    # no vision / no PDFs → falls back to text-only anchor, still generates
    assert captured["reference_images"] == ()
    assert (
        out.items[0].provenance["reference_style_selection"]["conditioning"]
        == "text_anchor"
    )


def test_llm_handle_accepts_writing_tier():
    # The writing tier must survive the clamp: silently degrading manuscript
    # prose to "medium" is exactly what the tier exists to prevent.
    assert EAG._llm(None, "writing", "exemplar_generate").tier == "writing"
    assert EAG._llm(None, "bogus", "x").tier == "medium"
