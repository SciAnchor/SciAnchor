"""UF07: typed assets, fake-provider consumption, fallback provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path

from research_harness.integrations.figure_image_provider import (
    FIGURE_IMAGE_PROVIDER,
    FIGURE_IMAGE_ROUTE,
    FakeFigureImageProvider,
    FigureImageRequest,
    FigureImageResult,
)
from research_harness.visualization.figure_generative_route import (
    render_generative_package,
)
from research_harness.visualization.figure_package_contracts import (
    SCHEMA_FIGURE_DESIGN,
)

_PNG_A = b"\x89PNG\r\n\x1a\nref-a"
_PNG_B = b"\x89PNG\r\n\x1a\nref-b"
_PNG_EDIT = b"\x89PNG\r\n\x1a\nedit-src"


def _design(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_DESIGN,
        "figure_id": "fig:arch",
        "role": "method_architecture",
        "one_sentence_claim": "Named stages map input to output.",
        "evidence_boundary": "conceptual",
        "panel_map": [{"panel_id": "A", "purpose": "pipeline"}],
        "render_route": "generative",
        "target_venue": "Information Processing & Management",
    }
    payload.update(overrides)
    return payload


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def test_text_only_fake_provider(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
    )
    assert result["validation"]["status"] == "pass"
    assert result["assets"]
    assert Path(result["assets"][0]["path"]).read_bytes().startswith(b"\x89PNG")
    assert result["provenance"]["consumption"] == "none"
    assert result["provenance"]["consumed_input_sha256"] == []
    assert result["provenance"]["consumed_operation"] == "generate_figure"
    assert result["provenance"]["fake_provider_no_network"] is True
    assert result["provenance"]["request_shape"]["reference_image_count"] == 0


def test_image_conditioned_consumes_reference_bytes(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
        assets=[
            {
                "asset_id": "ref-a",
                "role": "reference",
                "rights_status": "display_allowed",
                "image_bytes": _PNG_A,
            }
        ],
    )
    assert result["validation"]["status"] == "pass"
    assert result["provenance"]["consumption"] == "provider_input"
    assert result["provenance"]["consumed_input_sha256"] == [_sha(_PNG_A)]
    assert result["provenance"]["consumed_asset_ids"] == ["ref-a"]
    assert result["provenance"]["request_shape"]["reference_image_count"] == 1
    check = next(
        c
        for c in result["validation"]["checks"]
        if c["check_id"] == "asset_consumption"
    )
    assert check["execution_status"] == "completed"
    assert check["verdict"] == "pass"
    assert _sha(_PNG_A) in check["findings"]


def test_edit_consumes_edit_source(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
        assets=[
            {
                "asset_id": "draft-1",
                "role": "edit_source",
                "rights_status": "redistributable",
                "image_bytes": _PNG_EDIT,
            }
        ],
    )
    assert result["provenance"]["consumed_operation"] == "edit_figure"
    assert result["provenance"]["consumed_input_sha256"] == [_sha(_PNG_EDIT)]


def test_dropped_reference_fallback_is_text_only(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
        assets=[
            {
                "asset_id": "secret",
                "role": "reference",
                "rights_status": "internal_retrieval",
                "image_bytes": _PNG_A,
            },
            {
                "asset_id": "unknown",
                "role": "reference",
                "rights_status": "unknown",
                "image_bytes": _PNG_B,
            },
            {
                "asset_id": "empty",
                "role": "reference",
                "rights_status": "display_allowed",
            },
        ],
    )
    assert result["provenance"]["consumption"] == "none"
    assert result["provenance"]["fallback"] == "dropped_reference_text_only"
    reasons = {
        row["asset_id"]: row["reason"] for row in result["provenance"]["dropped_assets"]
    }
    assert reasons["secret"] == "rights:internal_retrieval"
    assert reasons["unknown"] == "rights:unknown"
    assert reasons["empty"] == "missing_bytes"
    assert result["provenance"]["consumed_input_sha256"] == []
    check = next(
        c
        for c in result["validation"]["checks"]
        if c["check_id"] == "asset_consumption"
    )
    assert check["verdict"] == "review_pending"
    assert check["execution_status"] == "completed"
    assert result["validation"]["status"] == "review_pending"


def test_resolution_downgrade(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
        dimensions={"width": 4096, "height": 3072},
    )
    assert result["provenance"]["resolution_downgraded"] is True
    assert result["provenance"]["consumed_dimensions"] == {
        "width": 2048,
        "height": 2048,
    }


def test_retained_draft_on_provider_failure(tmp_path: Path) -> None:
    class _Fail:
        def generate(self, request: FigureImageRequest) -> FigureImageResult:
            FakeFigureImageProvider().generate(request)
            return FigureImageResult(
                success=False,
                provider=FIGURE_IMAGE_PROVIDER,
                route=FIGURE_IMAGE_ROUTE,
                model=request.model,
                model_version="fake-illustration-v1",
                error="fake_fail",
                provenance={"request_shape": request.sanitized_request_shape()},
            )

    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
        assets=[
            {
                "asset_id": "draft-1",
                "role": "edit_source",
                "rights_status": "display_allowed",
                "image_bytes": _PNG_EDIT,
            }
        ],
        provider=_Fail(),
    )
    assert result["validation"]["status"] == "fail"
    assert result["assets"] == []
    assert result["provenance"]["retained_draft"] is True
    assert result["provenance"]["consumed_input_sha256"] == [_sha(_PNG_EDIT)]
    assert result["validation"]["checks"][0]["execution_status"] == "completed"
    assert result["validation"]["checks"][0]["verdict"] == "fail"


def test_no_consumption_when_bytes_never_reach_provider(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(),
        output_dir=tmp_path,
        assets=[
            {
                "asset_id": "ghost",
                "role": "existing",
                "rights_status": "unknown",
                "image_bytes": _PNG_A,
            }
        ],
    )
    assert result["provenance"]["consumption"] == "none"
    assert result["provenance"]["consumed_input_sha256"] == []
    assert "no_consumption" in str(
        next(
            c
            for c in result["validation"]["checks"]
            if c["check_id"] == "asset_consumption"
        )["findings"]
    )


def test_non_generative_route_is_not_run(tmp_path: Path) -> None:
    result = render_generative_package(
        design_contract=_design(render_route="deterministic"),
        output_dir=tmp_path,
        assets=[
            {
                "asset_id": "ref-a",
                "role": "reference",
                "rights_status": "display_allowed",
                "image_bytes": _PNG_A,
            }
        ],
    )
    assert result["validation"]["status"] == "not_run"
    check = result["validation"]["checks"][0]
    assert check["execution_status"] == "not_run"
    assert check["verdict"] is None
    assert result["assets"] == []
