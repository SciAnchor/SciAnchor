"""UF07 single-package generative/edit route.

Wraps FakeFigureImageProvider. Typed reference/existing/edit assets. Records
what the fake provider actually received. No network, credentials, or real
provider.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from research_harness.integrations.figure_image_provider import (
    FakeFigureImageProvider,
    FigureImageRequest,
    FigureImageResult,
)

from .figure_package_contracts import (
    SCHEMA_VALIDATION_REPORT,
    validate_figure_design_contract,
    validate_validation_report,
)

_ASSET_ROLES = frozenset({"reference", "existing", "edit_source"})
_CONSUMABLE_RIGHTS = frozenset({"display_allowed", "redistributable"})
_MAX_DIM = 2048
_MAX_REFS = 4


def render_generative_package(
    *,
    design_contract: Mapping[str, Any],
    output_dir: str | Path,
    assets: list[Mapping[str, Any]] | None = None,
    prompt: str | None = None,
    dimensions: Mapping[str, int] | None = None,
    provider: Any | None = None,
    figure_id: str | None = None,
) -> dict[str, Any]:
    design = validate_figure_design_contract(design_contract)
    fid = str(figure_id or design["figure_id"])
    if design["render_route"] != "generative":
        return _report(
            status="not_run",
            checks=[
                _check(
                    "generative_render",
                    execution="not_run",
                    verdict=None,
                    findings=[f"render_route={design['render_route']}"],
                )
            ],
            assets=[],
            provenance={"reason": "render_route_not_generative"},
            figure_id=fid,
        )

    selected, dropped = _select_assets(assets or [])
    requested = dict(dimensions or {"width": 1536, "height": 1024})
    width, height, downgraded = _clamp_dims(requested)
    operation = (
        "edit_figure"
        if any(a["role"] == "edit_source" for a in selected)
        else "generate_figure"
    )
    text = (prompt or str(design["one_sentence_claim"])).strip()
    request = FigureImageRequest(
        prompt=text,
        figure_id=fid,
        figure_contract={
            "title": fid,
            "purpose": str(design["one_sentence_claim"]),
            "role": design["role"],
        },
        evidence_boundary=str(design["evidence_boundary"]),
        dimensions={"width": width, "height": height},
        reference_images=tuple(a["image_bytes"] for a in selected),
        operation=operation,
        model="illustration-fake",
    )
    consumed_hashes = [hashlib.sha256(b).hexdigest() for b in request.reference_images]
    result = (provider or FakeFigureImageProvider()).generate(request)
    if not isinstance(result, FigureImageResult):
        raise TypeError("generative provider must return FigureImageResult")

    provenance = {
        **dict(result.provenance),
        "consumed_input_sha256": consumed_hashes,
        "consumed_operation": request.operation,
        "consumed_dimensions": {"width": width, "height": height},
        "consumed_asset_ids": [a["asset_id"] for a in selected],
        "dropped_assets": dropped,
        "resolution_downgraded": downgraded,
        "consumption": "none" if not consumed_hashes else "provider_input",
        "fake_provider_no_network": True,
    }
    if assets and not consumed_hashes:
        provenance["fallback"] = "dropped_reference_text_only"

    if not result.success:
        return _report(
            status="fail",
            checks=[
                _check(
                    "generative_render",
                    execution="completed",
                    verdict="fail",
                    findings=[result.error or "provider_failed"],
                    severity="critical",
                )
            ],
            assets=[],
            provenance={**provenance, "retained_draft": True},
            figure_id=fid,
        )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{fid.replace(':', '_')}.png"
    blob = result.image_bytes
    path.write_bytes(blob)
    package_assets = [
        {
            "path": str(path),
            "media_type": "image/png",
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
    ]
    consumption_verdict = "pass"
    consumption_findings: list[str] = list(consumed_hashes)
    if assets and not consumed_hashes:
        consumption_verdict = "review_pending"
        consumption_findings = ["no_consumption"]
    return _report(
        status="pass" if consumption_verdict == "pass" else "review_pending",
        checks=[
            _check(
                "generative_render",
                execution="completed",
                verdict="pass",
                findings=[],
            ),
            _check(
                "asset_consumption",
                execution="completed",
                verdict=consumption_verdict,
                findings=consumption_findings,
            ),
        ],
        assets=package_assets,
        provenance=provenance,
        figure_id=fid,
    )


def _select_assets(
    assets: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for raw in assets:
        asset_id = str(raw.get("asset_id") or raw.get("reference_id") or "")
        role = str(raw.get("role") or "reference")
        rights = str(raw.get("rights_status") or "unknown")
        blob = raw.get("image_bytes")
        if role not in _ASSET_ROLES:
            dropped.append({"asset_id": asset_id, "reason": f"role:{role}"})
            continue
        if rights not in _CONSUMABLE_RIGHTS:
            dropped.append({"asset_id": asset_id, "reason": f"rights:{rights}"})
            continue
        if not isinstance(blob, (bytes, bytearray)) or not blob:
            dropped.append({"asset_id": asset_id, "reason": "missing_bytes"})
            continue
        if len(selected) >= _MAX_REFS:
            dropped.append(
                {"asset_id": asset_id, "reason": "over_max_reference_images"}
            )
            continue
        selected.append(
            {
                "asset_id": asset_id or f"asset-{len(selected)}",
                "role": role,
                "rights_status": rights,
                "image_bytes": bytes(blob),
            }
        )
    return selected, dropped


def _clamp_dims(requested: Mapping[str, int]) -> tuple[int, int, bool]:
    width = int(requested.get("width") or 1536)
    height = int(requested.get("height") or 1024)
    clamped_w = min(max(width, 1), _MAX_DIM)
    clamped_h = min(max(height, 1), _MAX_DIM)
    return clamped_w, clamped_h, (clamped_w, clamped_h) != (width, height)


def _check(
    check_id: str,
    *,
    execution: str,
    verdict: str | None,
    findings: list[str],
    severity: str = "info",
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "execution_status": execution,
        "verdict": verdict,
        "severity": severity,
        "findings": findings,
        "evidence": [],
    }


def _report(
    *,
    status: str,
    checks: list[Mapping[str, Any]],
    assets: list[Mapping[str, Any]],
    provenance: Mapping[str, Any],
    figure_id: str,
) -> dict[str, Any]:
    validation = validate_validation_report(
        {
            "schema_version": SCHEMA_VALIDATION_REPORT,
            "status": status,
            "checks": list(checks),
        }
    )
    return {
        "figure_id": figure_id,
        "assets": list(assets),
        "validation": validation,
        "provenance": dict(provenance),
    }
