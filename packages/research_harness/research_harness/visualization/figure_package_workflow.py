"""UF09 internal Figure Package workflow.

Wires UF03–UF08 into one top-one package. No public MCP/CLI/skill surface.
Generative execution stays on the fake provider unless a caller injects one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .figure_caption_qa import check_figure_caption_evidence, realize_caption
from .figure_codesign import codesign_figure
from .figure_deterministic_route import render_deterministic_package
from .figure_exemplar_retrieval import retrieve_figure_exemplars
from .figure_generative_route import render_generative_package
from .figure_intake import assess_intake
from .figure_package_contracts import (
    SCHEMA_FIGURE_PACKAGE,
    contract_sha256,
    validate_figure_package,
    validate_validation_report,
)


def build_figure_package(
    *,
    task: Mapping[str, Any],
    output_dir: str | Path,
    units: list[Mapping[str, Any]] | None = None,
    provider: Any | None = None,
    figure_id: str | None = None,
) -> dict[str, Any]:
    intake = assess_intake(task)
    trace = [_step("intake", "completed", intake["assessment"]["status"])]
    assessment = intake["assessment"]
    selected = intake["selected_opportunity"]
    if assessment["status"] == "insufficient" or selected is None:
        trace.append(_step("sufficiency", "completed", "pending"))
        return {
            "status": "pending",
            "trace": trace,
            "package": None,
            "intake": intake,
        }

    trace.append(_step("sufficiency", "completed", assessment["status"]))
    trace.append(
        _step("opportunity", "completed", str(selected.get("opportunity_id") or ""))
    )
    venue = str(intake["task"]["target_venue"])
    fid = str(
        figure_id or task.get("figure_id") or selected.get("figure_id") or "fig:1"
    )
    retrieval = retrieve_figure_exemplars(
        opportunity=selected,
        units=list(units or []),
        target_venue=venue,
        topic=str((task.get("paper_context") or {}).get("topic") or ""),
    )
    trace.append(_step("retrieval", "completed", f"ranked={len(retrieval['ranked'])}"))

    records = _records(task, selected)
    assets = [
        a
        for a in list(task.get("existing_assets") or [])
        + list(task.get("render_assets") or [])
        if isinstance(a, Mapping)
    ]
    codesign = codesign_figure(
        opportunity=selected,
        target_venue=venue,
        figure_id=fid,
        records=records,
        assets=assets,
        references=retrieval["ranked"],
    )
    trace.append(_step("contracts", "completed", codesign["render_route"]))
    design = _stamp_design_knowledge(codesign["design_contract"], selected)
    caption_contract = codesign["caption_contract"]

    render = _render(
        design=design,
        route=str(codesign["render_route"]),
        records=records,
        assets=assets,
        output_dir=output_dir,
        provider=provider,
        existing_decision=str(selected.get("existing_decision") or ""),
    )
    trace.append(_step("route", "completed", str(codesign["render_route"])))
    trace.append(
        _step(
            "render",
            render["validation"]["status"],
            render["provenance"].get("reason") or "",
        )
    )

    realized = realize_caption(
        caption_contract=caption_contract,
        design_contract=design,
        records=records,
        render=_render_view(design, render),
    )
    qa = check_figure_caption_evidence(
        caption_contract=realized["caption_contract"],
        caption_text=realized["caption_text"],
        design_contract=design,
        records=records,
        render=_render_view(design, render),
    )
    trace.append(
        _step("caption", "completed", qa["caption_contract"]["caption_status"])
    )
    trace.append(_step("qa", qa["validation"]["status"], ""))

    checks = list(render["validation"]["checks"]) + list(qa["validation"]["checks"])
    status = _merge_status(render["validation"]["status"], qa["validation"]["status"])
    if status == "pass" and not render["assets"]:
        status = "fail"
        checks.append(
            {
                "check_id": "package_assets",
                "execution_status": "completed",
                "verdict": "fail",
                "severity": "critical",
                "findings": ["no_assets"],
                "evidence": [],
            }
        )
    validation = validate_validation_report(
        {
            "schema_version": "rh.validation_report.v1",
            "status": status,
            "checks": checks,
        }
    )
    package = validate_figure_package(
        {
            "schema_version": SCHEMA_FIGURE_PACKAGE,
            "package_id": f"pkg:{intake['task']['task_id']}:{fid}",
            "task_id": intake["task"]["task_id"],
            "figure_id": fid,
            "assets": list(render["assets"]),
            "caption": {
                "text": realized["caption_text"],
                "contract_id": qa["caption_contract"]["caption_id"],
            },
            "task": _json_safe_task(intake["task"]),
            "design_contract": design,
            "caption_contract": qa["caption_contract"],
            "context_assessment": assessment,
            "opportunity": selected,
            "reference_records": retrieval["ranked"],
            "validation": validation,
            "provenance": dict(render.get("provenance") or {}),
            "trace": trace,
        }
    )
    package["package_sha256"] = contract_sha256(package)
    return {
        "status": status,
        "trace": trace,
        "package": package,
        "intake": intake,
        "retrieval": retrieval,
        "codesign": codesign,
        "render": render,
    }


def _stamp_design_knowledge(
    design: Mapping[str, Any], selected: Mapping[str, Any]
) -> dict[str, Any]:
    from .figure_knowledge import (
        annotate_figure,
        knowledge_overlay,
        load_v0_snapshot,
        venue_family_from_venue,
    )

    out = dict(design)
    family = venue_family_from_venue(str(out.get("target_venue") or ""))
    annotated = annotate_figure(
        {
            "title": str(out.get("one_sentence_claim") or selected.get("claim") or ""),
            "purpose": str(selected.get("reader_question") or ""),
            "role": str(out.get("role") or ""),
        },
        venue_family=family,
    )
    out["form_id"] = annotated.get("form_id")
    out["form_ids"] = annotated.get("form_ids")
    out["figure_knowledge"] = knowledge_overlay(load_v0_snapshot(), family)
    return out


def _records(
    task: Mapping[str, Any], selected: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    context = (
        task.get("paper_context")
        if isinstance(task.get("paper_context"), Mapping)
        else {}
    )
    records = [r for r in list(context.get("records") or []) if isinstance(r, Mapping)]
    records.extend(
        r for r in list(task.get("source_data") or []) if isinstance(r, Mapping)
    )
    if str(selected.get("role")) == "ablation_or_sensitivity":
        records.extend(
            r
            for r in list(context.get("ablation_records") or [])
            if isinstance(r, Mapping)
        )
    return records


def _render(
    *,
    design: Mapping[str, Any],
    route: str,
    records: list[Mapping[str, Any]],
    assets: list[Mapping[str, Any]],
    output_dir: str | Path,
    provider: Any | None,
    existing_decision: str,
) -> dict[str, Any]:
    if route == "deterministic":
        return render_deterministic_package(
            design_contract=design, records=records, output_dir=output_dir
        )
    if route == "external_asset":
        return _wrap_external(design, assets, output_dir)
    generative_design = dict(design)
    if route == "hybrid":
        generative_design["render_route"] = "generative"
    mapped = _generative_assets(assets, existing_decision)
    result = render_generative_package(
        design_contract=generative_design,
        output_dir=output_dir,
        assets=mapped,
        provider=provider,
    )
    if route == "hybrid":
        result["provenance"] = {**result["provenance"], "original_route": "hybrid"}
    return result


def _wrap_external(
    design: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
    output_dir: str | Path,
) -> dict[str, Any]:
    kept: list[dict[str, Any]] = []
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        path = asset.get("path")
        blob = asset.get("image_bytes")
        if blob and not path:
            path = out / f"{str(design['figure_id']).replace(':', '_')}_existing.png"
            Path(path).write_bytes(bytes(blob))
            path = str(path)
        if not path:
            continue
        kept.append(
            {
                "path": str(path),
                "media_type": str(asset.get("media_type") or "image/png"),
                "sha256": str(asset.get("sha256") or ""),
            }
        )
    status = "pass" if kept else "fail"
    return {
        "figure_id": design["figure_id"],
        "assets": kept,
        "validation": validate_validation_report(
            {
                "schema_version": "rh.validation_report.v1",
                "status": status,
                "checks": [
                    {
                        "check_id": "external_asset",
                        "execution_status": "completed",
                        "verdict": "pass" if kept else "fail",
                        "severity": "info" if kept else "critical",
                        "findings": [] if kept else ["missing_existing_asset"],
                        "evidence": [],
                    }
                ],
            }
        ),
        "provenance": {"reason": "external_asset", "kept": len(kept)},
    }


def _generative_assets(
    assets: list[Mapping[str, Any]], existing_decision: str
) -> list[dict[str, Any]]:
    role = "edit_source" if existing_decision == "improve" else "reference"
    out: list[dict[str, Any]] = []
    for asset in assets:
        blob = asset.get("image_bytes")
        if not blob:
            continue
        out.append(
            {
                "asset_id": str(
                    asset.get("asset_id") or asset.get("figure_id") or "asset"
                ),
                "role": str(asset.get("role") or role),
                "rights_status": str(asset.get("rights_status") or "display_allowed"),
                "image_bytes": bytes(blob),
            }
        )
    return out


def _render_view(
    design: Mapping[str, Any], render: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "panels": list(design.get("panel_map") or []),
        "encodings": list(design.get("visual_encoding") or []),
        "sample_size": (render.get("provenance") or {}).get("sample_size"),
    }


def _merge_status(render_status: str, qa_status: str) -> str:
    for status in ("fail", "review_pending", "not_run"):
        if status in {render_status, qa_status}:
            return status
    return "pass"


def _step(stage: str, execution: str, detail: str) -> dict[str, str]:
    return {"stage": stage, "execution": execution, "detail": str(detail or "")}


def _json_safe_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Drop raw image bytes so the package remains JSON-safe."""
    out = dict(task)
    for key in ("existing_assets", "render_assets"):
        rows = out.get(key)
        if not isinstance(rows, list):
            continue
        cleaned = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            row = {k: v for k, v in item.items() if k != "image_bytes"}
            if "image_bytes" in item:
                blob = item.get("image_bytes")
                row["bytes_present"] = bool(blob)
                row["bytes_sha256"] = (
                    hashlib.sha256(bytes(blob)).hexdigest() if blob else ""
                )
            cleaned.append(row)
        out[key] = cleaned
    return out
