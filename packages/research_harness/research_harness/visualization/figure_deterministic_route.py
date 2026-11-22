"""UF06 single-package deterministic route.

Wraps figure_suite_spec rendering for one Figure Package. Recorded nulls are
retained. Missing records block the package. No generative provider.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .experiment_figures import render_figure_suite_spec
from .figure_package_contracts import (
    SCHEMA_VALIDATION_REPORT,
    validate_figure_design_contract,
    validate_validation_report,
)

_ROLE_CHART = {
    "quantitative_comparison": "grouped_bar",
    "ablation_or_sensitivity": "grouped_bar",
}


def render_deterministic_package(
    *,
    design_contract: Mapping[str, Any],
    records: list[Mapping[str, Any]] | None,
    output_dir: str | Path,
    figure_id: str | None = None,
) -> dict[str, Any]:
    design = validate_figure_design_contract(design_contract)
    fid = str(figure_id or design["figure_id"])
    if design["render_route"] != "deterministic":
        return _report(
            status="not_run",
            checks=[
                _check(
                    "deterministic_render",
                    execution="not_run",
                    verdict=None,
                    findings=[f"render_route={design['render_route']}"],
                )
            ],
            assets=[],
            provenance={"reason": "render_route_not_deterministic"},
            figure_id=fid,
        )
    if not records:
        return _report(
            status="fail",
            checks=[
                _check(
                    "records_present",
                    execution="completed",
                    verdict="fail",
                    findings=["missing_records"],
                    severity="critical",
                )
            ],
            assets=[],
            provenance={"reason": "missing_records"},
            figure_id=fid,
        )

    chart = _ROLE_CHART.get(str(design["role"]), "grouped_bar")
    spec = {
        "figures": [
            {
                "figure_id": fid,
                "role": design["role"],
                "panels": [
                    {
                        "panel_id": str(panel.get("panel_id") or "A"),
                        "chart": str(panel.get("chart") or chart),
                    }
                    for panel in design["panel_map"]
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec,
        records=list(records),
        output_dir=output_dir,
    )
    limitations = [str(x) for x in list(suite.provenance.get("limitations") or [])]
    missing = [n for n in limitations if "no_matching_records" in n]
    if missing:
        return _report(
            status="fail",
            checks=[
                _check(
                    "records_present",
                    execution="completed",
                    verdict="fail",
                    findings=missing,
                    severity="critical",
                )
            ],
            assets=[],
            provenance={"limitations": limitations, "suite_status": suite.status},
            figure_id=fid,
        )
    if not suite.figures:
        return _report(
            status="fail",
            checks=[
                _check(
                    "deterministic_render",
                    execution="completed",
                    verdict="fail",
                    findings=["no_renderable_figures"],
                    severity="critical",
                )
            ],
            assets=[],
            provenance={"limitations": limitations, "suite_status": suite.status},
            figure_id=fid,
        )

    assets = []
    for figure in suite.figures:
        for fmt, path in dict(figure.paths).items():
            blob = Path(path).read_bytes()
            assets.append(
                {
                    "path": path,
                    "media_type": f"image/{fmt}" if fmt != "pdf" else "application/pdf",
                    "sha256": hashlib.sha256(blob).hexdigest(),
                }
            )
    retained = [
        n
        for n in limitations
        if n.startswith("retained_empty_effect") or "retained_empty_effect" in n
    ]
    return _report(
        status="pass",
        checks=[
            _check(
                "records_present",
                execution="completed",
                verdict="pass",
                findings=[],
            ),
            _check(
                "deterministic_render",
                execution="completed",
                verdict="pass",
                findings=retained,
            ),
            _check(
                "asset_hash",
                execution="completed",
                verdict="pass",
                findings=[a["sha256"] for a in assets],
            ),
        ],
        assets=assets,
        provenance={
            "limitations": limitations,
            "suite_status": suite.status,
            "null_effect_retained": bool(retained),
        },
        figure_id=fid,
    )


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
