"""UF09 internal workflow: four verticals, pending, no fabricated output."""

from __future__ import annotations

from pathlib import Path

from research_harness.integrations.figure_image_provider import (
    FIGURE_IMAGE_PROVIDER,
    FIGURE_IMAGE_ROUTE,
    FigureImageRequest,
    FigureImageResult,
)
from research_harness.visualization.figure_package_contracts import SCHEMA_FIGURE_TASK
from research_harness.visualization.figure_package_workflow import build_figure_package

_PNG = b"\x89PNG\r\n\x1a\nexisting"

_STAGES = (
    "intake",
    "sufficiency",
    "opportunity",
    "retrieval",
    "contracts",
    "route",
    "render",
    "caption",
    "qa",
)


def _task(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_TASK,
        "task_id": "task-uf09",
        "target_venue": "Information Processing & Management",
        "context_type": "partial_context",
        "requested_action": "create",
    }
    payload.update(overrides)
    return payload


def _unit(role: str, venue: str) -> dict[str, object]:
    return {
        "reference_id": f"ref-{role}",
        "paper_id": f"paper-{role}",
        "figure_id": f"fig:{role}",
        "figure_role": role,
        "information_topology": "pipeline_stages",
        "evidence_grammar": "conceptual",
        "venue_profile": venue,
        "rights_status": "display_allowed",
        "quality": 0.8,
        "publication_year": 2024,
        "verification_status": "verified",
    }


def _trace_names(result: dict[str, object]) -> list[str]:
    return [str(s["stage"]) for s in result["trace"]]


def test_partial_ipm_method_architecture_fake_generative(tmp_path: Path) -> None:
    result = build_figure_package(
        task=_task(
            paper_context={
                "method_elements": ["encoder", "ranker"],
                "method_text": "A ranker maps queries to scored documents.",
            }
        ),
        output_dir=tmp_path,
        units=[_unit("method_architecture", "Information Processing & Management")],
    )
    assert result["status"] == "pass"
    assert result["package"]["design_contract"]["role"] == "method_architecture"
    assert result["package"]["design_contract"]["render_route"] == "generative"
    assert result["package"]["design_contract"].get("form_id")
    assert (
        result["package"]["design_contract"]["figure_knowledge"]["venue_family"]
        == "ipm"
    )
    assert result["package"]["assets"]
    assert Path(result["package"]["assets"][0]["path"]).is_file()
    assert set(_STAGES).issubset(_trace_names(result))


def test_full_ipm_quantitative_comparison_deterministic(tmp_path: Path) -> None:
    result = build_figure_package(
        task=_task(
            context_type="full_paper",
            paper_context={
                "claims": [{"text": "Named methods are compared on F1."}],
                "records": [
                    {
                        "figure_type": "benchmark",
                        "dataset": "DS-A",
                        "method": method,
                        "metric": "F1",
                        "value": value,
                        "unit": "score",
                    }
                    for method, value in (
                        ("Baseline", 0.71),
                        ("Prior", 0.74),
                        ("Ours", 0.81),
                    )
                ],
            },
        ),
        output_dir=tmp_path,
        units=[_unit("quantitative_comparison", "Information Processing & Management")],
    )
    assert result["status"] == "pass"
    assert result["package"]["design_contract"]["role"] == "quantitative_comparison"
    assert result["package"]["design_contract"]["render_route"] == "deterministic"
    assert result["package"]["assets"]
    assert set(_STAGES).issubset(_trace_names(result))


def test_full_npj_study_design_with_real_assets(tmp_path: Path) -> None:
    result = build_figure_package(
        task=_task(
            target_venue="npj Digital Medicine",
            context_type="full_paper",
            paper_context={
                "protocol": "Screening, imaging, endpoint adjudication.",
                "claims": [
                    {
                        "kind": "protocol",
                        "text": "Planned protocol from intake to endpoint.",
                    }
                ],
            },
            render_assets=[
                {
                    "asset_id": "ref-protocol",
                    "role": "reference",
                    "rights_status": "display_allowed",
                    "image_bytes": _PNG,
                }
            ],
        ),
        output_dir=tmp_path,
        units=[_unit("study_or_experiment_design", "npj Digital Medicine")],
    )
    assert result["package"]["design_contract"]["role"] == "study_or_experiment_design"
    assert (
        result["package"]["design_contract"]["target_venue"] == "npj Digital Medicine"
    )
    assert result["status"] == "pass"
    assert result["render"]["provenance"].get("consumed_input_sha256")
    assert result["package"]["assets"]


def test_existing_figure_diagnose_keep_external(tmp_path: Path) -> None:
    existing = tmp_path / "kept.png"
    existing.write_bytes(_PNG)
    result = build_figure_package(
        task=_task(
            context_type="existing_figure",
            requested_action="diagnose",
            paper_context={"method_elements": ["encoder", "ranker"]},
            existing_assets=[
                {
                    "asset_id": "fig1",
                    "figure_id": "fig:1",
                    "role": "method_architecture",
                    "caption": "Overview of the ranking pipeline.",
                    "body_references": ["See Figure 1"],
                    "path": str(existing),
                    "sha256": "abc",
                    "scientific_fidelity": "pass",
                    "communicative_quality": "pass",
                }
            ],
        ),
        output_dir=tmp_path,
    )
    assert result["intake"]["selected_opportunity"]["existing_decision"] == "keep"
    assert result["package"]["design_contract"]["render_route"] == "external_asset"
    assert result["status"] == "pass"
    assert result["package"]["assets"][0]["path"] == str(existing)
    assert not any(
        str(p).endswith("fig_1.png") and p != existing for p in tmp_path.glob("*.png")
    )


def test_insufficient_context_is_pending_without_package(tmp_path: Path) -> None:
    result = build_figure_package(task=_task(paper_context={}), output_dir=tmp_path)
    assert result["status"] == "pending"
    assert result["package"] is None
    assert list(tmp_path.iterdir()) == []


def test_provider_failure_is_fail_without_fabricated_png(tmp_path: Path) -> None:
    class _Fail:
        def generate(self, request: FigureImageRequest) -> FigureImageResult:
            return FigureImageResult(
                success=False,
                provider=FIGURE_IMAGE_PROVIDER,
                route=FIGURE_IMAGE_ROUTE,
                model=request.model,
                model_version="fake-illustration-v1",
                error="upstream",
            )

    result = build_figure_package(
        task=_task(
            paper_context={
                "method_elements": ["encoder"],
                "method_text": "A pipeline scores documents.",
            }
        ),
        output_dir=tmp_path,
        provider=_Fail(),
    )
    assert result["status"] == "fail"
    assert result["package"]["assets"] == []
    assert not list(tmp_path.glob("*.png"))
