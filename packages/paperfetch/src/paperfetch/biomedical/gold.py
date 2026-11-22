"""DVT/Glioma provisional 金标回放。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from paperfetch.biomedical.geo import build_geo_dataset_record
from paperfetch.biomedical.policy import assess_operation_readiness


def biomedical_data_root() -> Path:
    """从当前已导入模块定位 wheel/editable 内的静态数据。

    顶层 ``paperfetch`` 是 namespace package；Python 3.12 在 editable
    安装中会对 ``resources.files`` 返回不可直接转为 ``Path`` 的
    ``MultiplexedPath``。模块相对路径在源码和 wheel 中同形。
    """
    return Path(__file__).resolve().parents[1] / "data" / "biomedical"


def default_policy_path() -> Path:
    return biomedical_data_root() / "policies" / "transcriptomics.provisional-1.json"


def default_gold_path() -> Path:
    return biomedical_data_root() / "gold" / "dvt-glioma.provisional-1.jsonl"


def _assertion_value(record, field_name: str):
    values = [
        item.normalized_value
        for item in record.field_assertions
        if item.field_name == field_name
    ]
    return values[0] if values else None


def _evaluate_case(
    case: dict[str, Any], base: Path, policy_path: Path
) -> dict[str, Any]:
    observed_at = datetime.fromisoformat(case["observed_at"])
    record = build_geo_dataset_record(
        base / case["soft_file"],
        filelist_file=base / case["filelist_file"],
        observed_at=observed_at,
    )
    expected = case["expected"]
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, wanted: Any) -> None:
        checks.append(
            {
                "name": name,
                "passed": actual == wanted,
                "actual": actual,
                "expected": wanted,
            }
        )

    check("accession", record.accession, case["accession"])
    check("organisms", record.organisms, expected["organisms"])
    check("disease_terms", record.disease_terms, expected["disease_terms"])
    check(
        "pooling_detected",
        record.replication_profile.pooling_detected,
        expected["pooling_detected"],
    )
    check(
        "subject_sample_mapping",
        record.replication_profile.subject_sample_mapping,
        expected["subject_sample_mapping"],
    )
    check(
        "biological_group_units_recoverable",
        record.replication_profile.biological_group_units_recoverable,
        expected["biological_group_units_recoverable"],
    )
    check("time_design", record.measurement_design.time_design, expected["time_design"])
    check(
        "measurement_spaces",
        record.measurement_design.measurement_spaces,
        expected["measurement_spaces"],
    )
    if "subject_total" in expected:
        level = next(
            item
            for item in record.replication_profile.levels
            if item.entity_type.value == "animal"
        )
        check("subject_total", level.total, expected["subject_total"])
        check("subject_per_group", level.per_group, expected["subject_per_group"])
    if "reported_patients" in expected:
        check(
            "reported_patients",
            _assertion_value(record, "count.reported_patients"),
            expected["reported_patients"],
        )
        check(
            "reported_single_cells",
            _assertion_value(record, "count.reported_single_cells"),
            expected["reported_single_cells"],
        )
    operation_results = {}
    for operation, wanted in expected["operations"].items():
        readiness = assess_operation_readiness(
            record,
            operation,
            policy_path,
            checked_at=observed_at,
        )
        operation_results[operation] = readiness.signal.value
        check(f"operation:{operation}", readiness.signal.value, wanted)
    passed = all(item["passed"] for item in checks)
    return {
        "case_id": case["case_id"],
        "accession": record.accession,
        "status": "passed" if passed else "failed",
        "record_digest": record.content_digest,
        "official_source_artifacts": case.get("official_source_artifacts", {}),
        "operation_results": operation_results,
        "checks": checks,
    }


def run_gold_validation(
    gold_path: str | Path | None = None,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(gold_path).expanduser().resolve() if gold_path else default_gold_path()
    policy = (
        Path(policy_path).expanduser().resolve()
        if policy_path
        else default_policy_path()
    )
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    results = [_evaluate_case(case, path.parent, policy) for case in cases]
    passed = sum(item["status"] == "passed" for item in results)
    return {
        "schema_version": "spc.biomedical-gold-report.v0.1",
        "lifecycle_status": "provisional",
        "status": "passed" if passed == len(results) else "failed",
        "gold_file": path.name,
        "policy_file": policy.name,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "cases": results,
    }
