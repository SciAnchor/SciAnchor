"""Tests for result-figure exemplar evidence + rendered-suite critique.

Vision calls are mocked; caption/image extraction runs against a tiny real PDF
built with PyMuPDF (an RH first-class dependency).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import research_harness.visualization.result_figure_refs as refs
from research_harness.visualization.result_figure_refs import (
    architecture_evidence_text,
    architecture_reference_images,
    critique_rendered_figures,
    describe_architecture_figures,
    describe_result_figures,
    extract_figure_captions,
    extract_result_figure_images,
    figure_evidence_text,
    keep_architecture_images,
    rank_figure_candidates,
)


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    text = (
        "4 Experiments\n"
        "We evaluate on three datasets.\n"
        "\n"
        "Figure 3: Accuracy across datasets. (a) grouped benchmark comparison\n"
        "against five baselines; (b) ablation heatmap over module variants.\n"
        "\n"
        "As shown, our method outperforms.\n"
        "Table 2: Dataset statistics and split sizes used in all experiments.\n"
    )
    page.insert_text((72, 72), text)
    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


class _FakeCur:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def execute(self, sql, params=None):
        return _FakeCur(self._row)

    def close(self):
        pass


class _FakeDB:
    def __init__(self, row):
        self._row = row

    def connect(self):
        return _FakeConn(self._row)


def test_extract_figure_captions(sample_pdf: Path) -> None:
    captions = extract_figure_captions(sample_pdf)
    assert len(captions) == 2
    assert captions[0].startswith("Figure 3:")
    assert "(b) ablation heatmap" in captions[0]  # wrapped lines joined
    assert captions[1].startswith("Table 2:")


def test_extract_figure_captions_defensive() -> None:
    assert extract_figure_captions("") == []
    assert extract_figure_captions("/nonexistent/path.pdf") == []


def test_extract_figure_captions_nature_family_format(tmp_path: Path) -> None:
    """Springer-Nature/HSSC captions have no punctuation after the number."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Fig. 1 The interaction between text variety and genre. The left\n"
        "shows MTLD values of different text varieties.\n"
        "\n"
        "Table 2 Main effect and interaction effect of independent variables.\n"
        "\n"
        "Tables 3 and 4 and Fig. 1. In addition, the differences in lexical\n"
        "Table 2, the effect size of genre is larger than that of text variety\n"
        "Figure 3 shows that our method outperforms all baselines there.\n",
    )
    path = tmp_path / "nature_family.pdf"
    doc.save(path)
    doc.close()

    captions = extract_figure_captions(path)
    assert len(captions) == 2
    assert captions[0].startswith("Fig. 1 The interaction")
    assert captions[1].startswith("Table 2 Main effect")


def test_extract_result_figure_images_renders_caption_pages(sample_pdf: Path) -> None:
    candidates = extract_result_figure_images(sample_pdf)
    assert len(candidates) >= 1  # caption page rendered as a vector-chart fallback
    stats = refs._png_bytes_stats(candidates[0])
    assert stats is not None and stats[0] > 100


def test_figure_evidence_text_with_and_without_pdf(sample_pdf: Path) -> None:
    db = _FakeDB({"pdf_path": str(sample_pdf)})
    evidence = figure_evidence_text(db, 1, use_vision=False)
    assert evidence.startswith("FIGURE/TABLE CAPTIONS:")
    assert "Figure 3:" in evidence

    assert figure_evidence_text(_FakeDB({"pdf_path": ""}), 1, use_vision=False) == ""
    assert figure_evidence_text(_FakeDB(None), 1, use_vision=False) == ""


@pytest.fixture()
def arch_pdf(tmp_path: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "3 Method\n"
        "Figure 2: The overall framework of our model. The encoder feeds a\n"
        "fusion module, then a decoder produces the output.\n"
        "\n"
        "Figure 3: Main results. Accuracy across five datasets versus baselines.\n"
        "\n"
        "Table 1: Dataset statistics.\n",
    )
    path = tmp_path / "arch.pdf"
    doc.save(path)
    doc.close()
    return path


def test_architecture_evidence_keeps_only_arch_captions(arch_pdf: Path) -> None:
    db = _FakeDB({"pdf_path": str(arch_pdf)})
    evidence = architecture_evidence_text(db, 1, use_vision=False)
    assert evidence.startswith("ARCHITECTURE/METHOD FIGURE CAPTIONS:")
    assert "overall framework" in evidence
    # a result caption ("Main results") must NOT be admitted as architecture style
    assert "Main results" not in evidence
    assert (
        architecture_evidence_text(_FakeDB({"pdf_path": ""}), 1, use_vision=False) == ""
    )


def test_describe_architecture_figures_inverse_gate(
    monkeypatch, arch_pdf: Path
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        refs, "extract_result_figure_images", lambda *a, **k: [b"p1", b"p2", b"p3"]
    )
    answers = iter(
        [
            '{"is_architecture_schematic": true, "quality": 8, "form": {"layout_archetype":'
            ' "layered stack", "palette_strategy": "cool technical"}, "summary": "clean"}',
            '{"is_architecture_schematic": false, "quality": 9, "form": {"charts": ["bar"]},'
            ' "summary": "a result bar chart"}',  # result plot → rejected
            '{"is_architecture_schematic": true, "quality": 3, "form": {"layout_archetype":'
            ' "hub"}, "summary": "low quality"}',  # below min_quality
        ]
    )
    monkeypatch.setattr(refs, "_vision_chat", lambda *a, **k: next(answers))
    described = describe_architecture_figures(arch_pdf, min_quality=6.0)
    assert len(described) == 1
    assert described[0]["form"]["layout_archetype"] == "layered stack"


def test_describe_architecture_figures_without_vision(
    monkeypatch, arch_pdf: Path
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert describe_architecture_figures(arch_pdf) == []


def test_keep_architecture_images_returns_bytes(monkeypatch, arch_pdf: Path) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        refs, "extract_result_figure_images", lambda *a, **k: [b"archA", b"resultB"]
    )
    answers = iter(
        [
            '{"is_architecture_schematic": true, "quality": 8, "form": {}}',
            '{"is_architecture_schematic": false, "quality": 9, "form": {}}',  # rejected
        ]
    )
    monkeypatch.setattr(refs, "_vision_chat", lambda *a, **k: next(answers))
    kept = keep_architecture_images(arch_pdf, min_quality=6.0)
    assert kept == [b"archA"]  # only the schematic's bytes kept


def test_architecture_reference_images_across_papers(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    db = _FakeDB({"pdf_path": "/some/paper.pdf"})
    monkeypatch.setattr(
        refs,
        "keep_architecture_images",
        lambda pdf, **k: [b"arch_of_" + pdf.encode()[:1]],
    )
    imgs = architecture_reference_images(db, [11, 12], max_images=3, per_paper=1)
    assert len(imgs) == 2  # one per paper


def test_architecture_reference_images_no_vision(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db = _FakeDB({"pdf_path": "/p.pdf"})
    assert architecture_reference_images(db, [1, 2]) == []
    assert architecture_reference_images(db, []) == []


def test_describe_result_figures_gates_on_vlm_judgement(
    monkeypatch, sample_pdf: Path
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        refs, "extract_result_figure_images", lambda *a, **k: [b"p1", b"p2", b"p3"]
    )
    answers = iter(
        [
            '{"is_quant_result_plot": true, "quality": 8, "form": {"charts": ["grouped_bar"],'
            ' "n_panels": 2, "composition": "1x2"}, "summary": "composed benchmark"}',
            '{"is_quant_result_plot": false, "quality": 9, "form": {"charts": ["line"]},'
            ' "summary": "an architecture schematic"}',
            '{"is_quant_result_plot": true, "quality": 3, "form": {"charts": ["bar"]},'
            ' "summary": "low quality"}',
        ]
    )
    monkeypatch.setattr(refs, "_vision_chat", lambda *a, **k: next(answers))

    described = describe_result_figures(sample_pdf, min_quality=6.0)
    assert len(described) == 1
    assert described[0]["form"]["charts"] == ["grouped_bar"]
    assert described[0]["quality"] == 8.0


def test_describe_result_figures_without_vision_backend(
    monkeypatch, sample_pdf: Path
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert describe_result_figures(sample_pdf) == []


def _small_png(tmp_path: Path, name: str, *, size=(640, 480), blank=False) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    if not blank:
        ax.plot([1, 2, 3], [1, 4, 2], marker="o")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
    else:
        ax.axis("off")
    path = tmp_path / name
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def test_critique_deterministic_only(tmp_path: Path) -> None:
    good = _small_png(tmp_path, "good.png")
    blank = _small_png(tmp_path, "blank.png", blank=True)
    missing = tmp_path / "missing.png"

    reports = critique_rendered_figures(
        [str(good), str(blank), str(missing)], use_vision=False
    )
    by_path = {r["path"]: r for r in reports}

    assert by_path[str(good)]["verdict"] == "pass_deterministic_only"
    assert by_path[str(good)]["findings"] == []
    assert by_path[str(good)]["checks"]["width"] == 640

    assert by_path[str(blank)]["verdict"] == "fail"
    assert "image_near_blank" in by_path[str(blank)]["findings"]

    assert by_path[str(missing)]["verdict"] == "fail"
    assert "file_missing" in by_path[str(missing)]["findings"]


def test_critique_with_mocked_vlm(monkeypatch, tmp_path: Path) -> None:
    good = _small_png(tmp_path, "good.png")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        refs,
        "_vision_chat",
        lambda *a, **k: (
            '```json\n{"scores": {"readability": 8, "composition": 7, '
            '"aesthetics": 7, "publication_readiness": 8}, "findings": ["legend slightly '
            'cramped"], "verdict": "pass"}\n```'
        ),
    )
    reports = critique_rendered_figures(
        [str(good)], style_profile="nature_family", use_vision=True
    )
    assert reports[0]["verdict"] == "pass"
    assert reports[0]["vision"]["scores"]["readability"] == 8
    assert reports[0]["vision"]["findings"] == ["legend slightly cramped"]


def test_critique_vlm_failure_degrades(monkeypatch, tmp_path: Path) -> None:
    good = _small_png(tmp_path, "good.png")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _boom(*a, **k):
        raise RuntimeError("backend down")

    monkeypatch.setattr(refs, "_vision_chat", _boom)
    reports = critique_rendered_figures([str(good)], use_vision=True)
    assert reports[0]["verdict"] == "pass_deterministic_only"
    assert reports[0]["vision"] is None


def test_rank_figure_candidates_prefers_nonblank(tmp_path: Path) -> None:
    good = _small_png(tmp_path, "good.png")
    blank = _small_png(tmp_path, "blank.png", blank=True)
    chosen = rank_figure_candidates(
        [str(blank), str(good)], style_profile="nature_family", use_vision=False
    )
    assert chosen["path"] == str(good)
    assert chosen["ranked"][0]["path"] == str(good)
    assert chosen["ranked"][-1]["path"] == str(blank)


def test_rank_prefers_nature_story_composite(tmp_path: Path) -> None:
    isolated = _small_png(tmp_path, "isolated.png")
    composite = _small_png(tmp_path, "composite.png")
    chosen = rank_figure_candidates(
        [str(isolated), str(composite)],
        style_profile="nature_family",
        candidate_specs=[
            {
                "role": "method",
                "archetype": "quantitative_grid",
                "panels": [{"chart": "line"}],
            },
            {
                "role": "study_design",
                "archetype": "schematic_led_composite",
                "hero_panel": "a",
                "claim": "Clinical decision pathway from intake to treatment change.",
                "panels": [
                    {"purpose": "mechanism", "chart": "image"},
                    {"purpose": "cohort flow", "chart": "box"},
                    {"purpose": "clinical vignette", "chart": "image"},
                ],
            },
        ],
        use_vision=False,
    )
    assert chosen["path"] == str(composite)
    assert chosen["dimensions"]["story_composite"] > 0


def test_rank_prefers_clinical_application_scene(tmp_path: Path) -> None:
    generic = _small_png(tmp_path, "generic.png")
    clinical = _small_png(tmp_path, "clinical.png")
    chosen = rank_figure_candidates(
        [str(generic), str(clinical)],
        style_profile="biomed_omics",
        candidate_specs=[
            {
                "role": "method",
                "title": "Architecture overview",
                "panels": [{"purpose": "encoder"}],
            },
            {
                "role": "case_exhibit",
                "title": "Patient-level clinical decision",
                "purpose": "bedside diagnosis workflow",
                "panels": [{"purpose": "vignette"}, {"purpose": "treatment"}],
            },
        ],
        use_vision=False,
    )
    assert chosen["path"] == str(clinical)
    assert chosen["dimensions"]["application_scene"] > 0


def test_rank_penalizes_discouraged_chart(tmp_path: Path) -> None:
    radar = _small_png(tmp_path, "radar.png")
    box = _small_png(tmp_path, "box.png")
    grammar = {"recommended_charts": ["box"], "discouraged_charts": ["radar"]}
    chosen = rank_figure_candidates(
        [str(radar), str(box)],
        style_profile="nature_family",
        venue_figure_grammar=grammar,
        candidate_specs=[
            {"panels": [{"chart": "radar"}]},
            {"panels": [{"chart": "box"}]},
        ],
        use_vision=False,
    )
    assert chosen["path"] == str(box)
    assert chosen["ranked"][-1]["dimensions"]["venue"] < 0


def test_rank_uses_form_prior(tmp_path: Path) -> None:
    rare = _small_png(tmp_path, "rare.png")
    common = _small_png(tmp_path, "common.png")
    grammar = {
        "figure_knowledge": {
            "venue_family": "npj",
            "form_priors": {"roc_pr_curve": 0.4, "causal_dag": 0.01},
        }
    }
    chosen = rank_figure_candidates(
        [str(rare), str(common)],
        style_profile="nature_family",
        venue_figure_grammar=grammar,
        candidate_specs=[
            {"form_id": "causal_dag", "panels": [{"chart": "line"}]},
            {"form_id": "roc_pr_curve", "panels": [{"chart": "line"}]},
        ],
        use_vision=False,
    )
    assert chosen["path"] == str(common)
    assert chosen["dimensions"]["form_prior"] > 0


def test_loose_json() -> None:
    assert refs._loose_json('{"a": 1}') == {"a": 1}
    assert refs._loose_json('prefix ```json\n{"a": 1}\n``` suffix') == {"a": 1}
    assert refs._loose_json("not json") == {}
    assert refs._loose_json("[1, 2]") == {}
