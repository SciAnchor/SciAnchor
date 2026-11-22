"""JSON-safe Figure Package contract fixtures (UF01).

Fail-closed dict validation. No provider, parser, corpus, storage, or UI.
Hashes are canonical JSON SHA-256. Extra keys are kept (additive).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_FIGURE_TASK = "rh.figure_task.v1"
SCHEMA_FIGURE_DESIGN = "rh.figure_design_contract.v1"
SCHEMA_CAPTION = "rh.caption_contract.v1"
SCHEMA_FIGURE_PACKAGE = "rh.figure_package.v1"
SCHEMA_CONTEXT_ASSESSMENT = "rh.context_assessment.v1"
SCHEMA_FIGURE_OPPORTUNITY = "rh.figure_opportunity.v1"
SCHEMA_REFERENCE_RECORD = "rh.reference_record.v1"
SCHEMA_VALIDATION_REPORT = "rh.validation_report.v1"

VENUE_NPJ = "npj Digital Medicine"
VENUE_IPM = "Information Processing & Management"
TARGET_VENUES = (VENUE_NPJ, VENUE_IPM)
_VENUE_ALIASES = {
    "npj digital medicine": VENUE_NPJ,
    "information processing & management": VENUE_IPM,
    "information processing and management": VENUE_IPM,
    "ip&m": VENUE_IPM,
}

CONTEXT_TYPES = ("full_paper", "partial_context", "existing_figure")
REQUESTED_ACTIONS = ("create", "improve", "diagnose")
TARGET_WIDTHS = ("single_column", "double_column", "unspecified")
SUFFICIENCY = ("sufficient", "partially_sufficient", "insufficient")
FIGURE_ROLES = (
    "method_architecture",
    "study_or_experiment_design",
    "quantitative_comparison",
    "ablation_or_sensitivity",
    "qualitative_cases",
)
EVIDENCE_BOUNDARIES = (
    "conceptual",
    "planned_protocol",
    "evidence_backed",
    "mixed",
)
PRIORITIES = ("high", "medium", "low")
RENDER_ROUTES = ("generative", "deterministic", "hybrid", "external_asset")
CAPTION_STATUSES = ("draft", "validated", "review_pending", "rejected")
RIGHTS_STATUSES = (
    "internal_retrieval",
    "display_allowed",
    "redistributable",
    "unknown",
)
CHECK_EXECUTION = ("completed", "not_run", "not_applicable", "error")
CHECK_VERDICTS = ("pass", "fail", "review_pending", None)
PACKAGE_VALIDATION = (
    "pass",
    "fail",
    "review_pending",
    "not_run",
    "not_applicable",
)
SEVERITIES = ("critical", "major", "minor", "info")


class FigureContractError(ValueError):
    """Invalid Figure Package contract."""


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FigureContractError(f"value is not JSON-safe: {exc}") from exc


def contract_sha256(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise FigureContractError("hash input must be a JSON object")
    payload = {k: v for k, v in value.items() if k != "package_sha256"}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def normalize_venue(value: str) -> str:
    key = str(value or "").strip()
    if not key:
        raise FigureContractError("target_venue is required")
    mapped = _VENUE_ALIASES.get(key.lower(), key)
    if mapped not in TARGET_VENUES:
        raise FigureContractError(f"unsupported target_venue: {value!r}")
    return mapped


def _as_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FigureContractError(f"{name} must be an object")
    return dict(value)


def _req_str(obj: Mapping[str, Any], key: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise FigureContractError(f"{key} is required")
    return val.strip()


def _req_enum(obj: Mapping[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    val = _req_str(obj, key)
    if val not in allowed:
        raise FigureContractError(f"{key} must be one of {allowed!r}")
    return val


def _req_list(obj: Mapping[str, Any], key: str) -> list[Any]:
    val = obj.get(key)
    if not isinstance(val, list):
        raise FigureContractError(f"{key} must be a list")
    return list(val)


def validate_figure_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "figure_task")
    version = _req_str(obj, "schema_version")
    if version != SCHEMA_FIGURE_TASK:
        raise FigureContractError(
            f"figure_task schema_version must be {SCHEMA_FIGURE_TASK}"
        )
    out = dict(obj)
    out["schema_version"] = version
    out["task_id"] = _req_str(obj, "task_id")
    out["target_venue"] = normalize_venue(_req_str(obj, "target_venue"))
    out["context_type"] = _req_enum(obj, "context_type", CONTEXT_TYPES)
    out["requested_action"] = _req_enum(obj, "requested_action", REQUESTED_ACTIONS)
    if "output_requirement" in obj and obj["output_requirement"] is not None:
        req = _as_dict(obj["output_requirement"], "output_requirement")
        width = req.get("target_width", "unspecified")
        if width not in TARGET_WIDTHS:
            raise FigureContractError("output_requirement.target_width invalid")
        formats = req.get("formats", [])
        if formats is not None and not isinstance(formats, list):
            raise FigureContractError("output_requirement.formats must be a list")
        out["output_requirement"] = dict(req)
        out["output_requirement"]["target_width"] = width
    return out


def validate_context_assessment(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "context_assessment")
    out = dict(obj)
    if obj.get("schema_version"):
        version = _req_str(obj, "schema_version")
        if version != SCHEMA_CONTEXT_ASSESSMENT:
            raise FigureContractError(
                f"context_assessment schema_version must be {SCHEMA_CONTEXT_ASSESSMENT}"
            )
        out["schema_version"] = version
    out["status"] = _req_enum(obj, "status", SUFFICIENCY)
    return out


def validate_figure_opportunity(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "figure_opportunity")
    out = dict(obj)
    if obj.get("schema_version"):
        version = _req_str(obj, "schema_version")
        if version != SCHEMA_FIGURE_OPPORTUNITY:
            raise FigureContractError(
                f"figure_opportunity schema_version must be {SCHEMA_FIGURE_OPPORTUNITY}"
            )
        out["schema_version"] = version
    out["opportunity_id"] = _req_str(obj, "opportunity_id")
    out["role"] = _req_enum(obj, "role", FIGURE_ROLES)
    out["reader_question"] = _req_str(obj, "reader_question")
    out["claim"] = _req_str(obj, "claim")
    out["evidence_boundary"] = _req_enum(obj, "evidence_boundary", EVIDENCE_BOUNDARIES)
    out["priority"] = _req_enum(obj, "priority", PRIORITIES)
    return out


def validate_figure_design_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "figure_design_contract")
    version = _req_str(obj, "schema_version")
    if version != SCHEMA_FIGURE_DESIGN:
        raise FigureContractError(
            f"design_contract schema_version must be {SCHEMA_FIGURE_DESIGN}"
        )
    out = dict(obj)
    out["schema_version"] = version
    out["figure_id"] = _req_str(obj, "figure_id")
    out["role"] = _req_enum(obj, "role", FIGURE_ROLES)
    out["one_sentence_claim"] = _req_str(obj, "one_sentence_claim")
    out["evidence_boundary"] = _req_enum(obj, "evidence_boundary", EVIDENCE_BOUNDARIES)
    out["panel_map"] = _req_list(obj, "panel_map")
    out["render_route"] = _req_enum(obj, "render_route", RENDER_ROUTES)
    out["target_venue"] = normalize_venue(_req_str(obj, "target_venue"))
    return out


def validate_caption_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "caption_contract")
    version = _req_str(obj, "schema_version")
    if version != SCHEMA_CAPTION:
        raise FigureContractError(
            f"caption_contract schema_version must be {SCHEMA_CAPTION}"
        )
    out = dict(obj)
    out["schema_version"] = version
    out["caption_id"] = _req_str(obj, "caption_id")
    out["figure_id"] = _req_str(obj, "figure_id")
    out["one_sentence_claim"] = _req_str(obj, "one_sentence_claim")
    out["panel_descriptions"] = _req_list(obj, "panel_descriptions")
    out["caption_status"] = _req_enum(obj, "caption_status", CAPTION_STATUSES)
    return out


def validate_reference_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "reference_record")
    out = dict(obj)
    if obj.get("schema_version"):
        version = _req_str(obj, "schema_version")
        if version != SCHEMA_REFERENCE_RECORD:
            raise FigureContractError(
                f"reference_record schema_version must be {SCHEMA_REFERENCE_RECORD}"
            )
        out["schema_version"] = version
    out["reference_id"] = _req_str(obj, "reference_id")
    out["rights_status"] = _req_enum(obj, "rights_status", RIGHTS_STATUSES)
    return out


def validate_validation_check(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "validation_check")
    out = dict(obj)
    out["check_id"] = _req_str(obj, "check_id")
    execution = _req_enum(obj, "execution_status", CHECK_EXECUTION)
    out["execution_status"] = execution
    verdict = obj.get("verdict", None)
    if verdict not in CHECK_VERDICTS:
        raise FigureContractError("validation check verdict invalid")
    if execution != "completed" and verdict == "pass":
        raise FigureContractError("unexecuted or failed checks cannot verdict pass")
    out["verdict"] = verdict
    if "severity" in obj and obj["severity"] is not None:
        out["severity"] = _req_enum(obj, "severity", SEVERITIES)
    return out


def validate_validation_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "validation_report")
    out = dict(obj)
    if obj.get("schema_version"):
        version = _req_str(obj, "schema_version")
        if version != SCHEMA_VALIDATION_REPORT:
            raise FigureContractError(
                f"validation_report schema_version must be {SCHEMA_VALIDATION_REPORT}"
            )
        out["schema_version"] = version
    out["status"] = _req_enum(obj, "status", PACKAGE_VALIDATION)
    checks = obj.get("checks", [])
    if not isinstance(checks, list):
        raise FigureContractError("validation.checks must be a list")
    out["checks"] = [validate_validation_check(item) for item in checks]
    if out["status"] == "pass":
        for check in out["checks"]:
            if check["execution_status"] != "completed":
                raise FigureContractError(
                    "package cannot pass while a required check is not completed"
                )
            if check["verdict"] == "fail":
                raise FigureContractError("package cannot pass with a failed check")
    return out


def validate_figure_package(payload: Mapping[str, Any]) -> dict[str, Any]:
    obj = _as_dict(payload, "figure_package")
    version = _req_str(obj, "schema_version")
    if version != SCHEMA_FIGURE_PACKAGE:
        raise FigureContractError(
            f"figure_package schema_version must be {SCHEMA_FIGURE_PACKAGE}"
        )
    out = dict(obj)
    out["schema_version"] = version
    out["package_id"] = _req_str(obj, "package_id")
    out["task_id"] = _req_str(obj, "task_id")
    out["figure_id"] = _req_str(obj, "figure_id")
    out["assets"] = _req_list(obj, "assets")
    caption = _as_dict(obj.get("caption"), "caption")
    if not isinstance(caption.get("text"), str) or not str(caption.get("text")).strip():
        raise FigureContractError("caption.text is required")
    out["caption"] = dict(caption)

    design = validate_figure_design_contract(
        _as_dict(obj.get("design_contract"), "design_contract")
    )
    caption_contract = validate_caption_contract(
        _as_dict(obj.get("caption_contract"), "caption_contract")
    )
    if design["figure_id"] != out["figure_id"]:
        raise FigureContractError("design_contract.figure_id must match package")
    if caption_contract["figure_id"] != out["figure_id"]:
        raise FigureContractError("caption_contract.figure_id must match package")
    out["design_contract"] = design
    out["caption_contract"] = caption_contract

    if "task" in obj and obj["task"] is not None:
        task = validate_figure_task(_as_dict(obj.get("task"), "task"))
        if task["task_id"] != out["task_id"]:
            raise FigureContractError("task.task_id must match package")
        if task["target_venue"] != design["target_venue"]:
            raise FigureContractError("task and design_contract venues conflict")
        out["task"] = task

    if "opportunity" in obj and obj["opportunity"] is not None:
        out["opportunity"] = validate_figure_opportunity(
            _as_dict(obj.get("opportunity"), "opportunity")
        )
    if "context_assessment" in obj and obj["context_assessment"] is not None:
        out["context_assessment"] = validate_context_assessment(
            _as_dict(obj.get("context_assessment"), "context_assessment")
        )
    refs = obj.get("reference_records", obj.get("references", []))
    if refs:
        if not isinstance(refs, list):
            raise FigureContractError("reference_records must be a list")
        out["reference_records"] = [validate_reference_record(item) for item in refs]
    out["validation"] = validate_validation_report(
        _as_dict(obj.get("validation"), "validation")
    )
    return out
