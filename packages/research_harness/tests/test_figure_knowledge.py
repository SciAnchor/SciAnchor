"""WF06 growing figure-knowledge tree. Caption-only; roles stay frozen."""

from __future__ import annotations

import json

import pytest

from research_harness.visualization.figure_knowledge import (
    SCHEMA_FIGURE_KNOWLEDGE,
    UNCLASSIFIED_FORM,
    V0_SNAPSHOT_PATH,
    attach_form,
    classify_caption,
    empty_knowledge,
    induce_from_captions,
    load_v0_snapshot,
    parent_role,
    stamp_suite_knowledge,
    validate_figure_knowledge,
)
from research_harness.visualization.figure_package_contracts import (
    FIGURE_ROLES,
    FigureContractError,
)


def test_stub_and_unclassified_are_not_forced_into_a_role() -> None:
    stub = classify_caption("Extracted document graphic/chart asset")
    assert stub["stub"] is True
    assert stub["unclassified"] is False
    assert parent_role("extractor_stub") is None

    miss = classify_caption("PCA projection of the learned latent space.")
    assert miss["stub"] is False
    assert miss["unclassified"] is True
    assert miss["forms"] == []


def test_known_captions_hang_under_frozen_roles() -> None:
    hit = classify_caption("ROC and PR curves for the external validation cohort.")
    assert hit["forms"] == ["roc_pr_curve"]
    assert parent_role("roc_pr_curve") == "quantitative_comparison"
    assert parent_role("roc_pr_curve") in FIGURE_ROLES

    hit = classify_caption("Overview of the proposed framework.")
    assert "pipeline_overview" in hit["forms"]
    assert parent_role("pipeline_overview") == "method_architecture"


def test_induce_keeps_unclassified_and_does_not_rewrite_roles() -> None:
    tree = induce_from_captions(
        [
            {"caption": "Extracted document figure/diagram", "venue_family": "npj"},
            {"caption": "Ablation of the fusion module.", "venue_family": "ipm"},
            {"caption": "Patient selection flowchart.", "venue_family": "npj"},
            {"caption": "Something unlabeled.", "venue_family": "ipm"},
        ],
        sources=[{"zip_name": "fixture.zip", "zip_sha256": "abc"}],
    )
    tree = validate_figure_knowledge(tree)
    obs = tree["observations"]
    assert tree["role_layer"] == list(FIGURE_ROLES)
    assert obs["n_captions"] == 4
    assert obs["n_stub"] == 1
    assert obs["n_real"] == 3
    assert obs["n_unclassified"] == 1
    assert obs["by_form"][UNCLASSIFIED_FORM]["n"] == 1
    assert obs["by_form"]["ablation"]["n"] == 1
    assert obs["by_form"]["cohort_flow"]["n"] == 1
    assert obs["by_role"]["ablation_or_sensitivity"] == 1
    blob = json.dumps(tree)
    assert '"caption":' not in blob
    assert "/Users/" not in blob


def test_attach_form_grows_children_not_roles() -> None:
    grown = attach_form(empty_knowledge(), "sankey_flow", "quantitative_comparison")
    assert any(item["form_id"] == "sankey_flow" for item in grown["form_layer"])
    assert grown["role_layer"] == list(FIGURE_ROLES)
    with pytest.raises(FigureContractError):
        attach_form(grown, "sankey_flow", "quantitative_comparison")
    with pytest.raises(FigureContractError):
        attach_form(empty_knowledge(), "new_form", "invented_role")
    bad = empty_knowledge()
    bad["role_layer"] = [*FIGURE_ROLES, "extra"]
    with pytest.raises(FigureContractError):
        validate_figure_knowledge(bad)


def test_v0_snapshot_is_counts_only() -> None:
    tree = load_v0_snapshot()
    blob = V0_SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert tree["schema_version"] == SCHEMA_FIGURE_KNOWLEDGE
    assert tree["role_layer"] == list(FIGURE_ROLES)
    obs = tree["observations"]
    assert obs["n_captions"] == obs["n_real"] + obs["n_stub"]
    assert obs["n_unclassified"] > 0
    assert UNCLASSIFIED_FORM in obs["by_form"]
    assert "doi.org" not in blob.lower()
    assert "/Users/" not in blob
    assert '"caption":' not in blob
    for source in tree["sources"]:
        assert "zip_name" in source and "zip_sha256" in source
        assert "zip_path" not in source


def test_stamp_suite_annotates_forms_and_priors() -> None:
    spec = stamp_suite_knowledge(
        {
            "target_venue": "npj Digital Medicine",
            "style_profile": "nature_family",
            "venue_figure_grammar": {"recommended_charts": ["box"]},
            "figures": [
                {
                    "figure_id": "fig:roc",
                    "title": "ROC and PR curves for external validation",
                    "panels": [{"chart": "roc"}],
                },
                {
                    "figure_id": "fig:pca",
                    "title": "PCA projection of the learned latent space",
                },
            ],
        }
    )
    by_id = {fig["figure_id"]: fig for fig in spec["figures"]}
    assert by_id["fig:roc"]["form_id"] == "roc_pr_curve"
    assert by_id["fig:pca"]["form_id"] == UNCLASSIFIED_FORM
    overlay = spec["figure_knowledge"]
    assert overlay["venue_family"] == "npj"
    assert overlay["form_priors"]["roc_pr_curve"] > overlay["form_priors"].get(
        "ablation", 0
    )
    assert spec["venue_figure_grammar"]["figure_knowledge"]["venue_family"] == "npj"
