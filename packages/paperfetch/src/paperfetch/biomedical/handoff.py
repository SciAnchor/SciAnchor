"""从事实记录和操作就绪度生成可验证的 AnalysisHandoff。"""

from __future__ import annotations

from datetime import datetime, timezone

from paperfetch.biomedical.models import (
    AnalysisHandoff,
    BiomedicalDatasetRecord,
    OperationInputReadiness,
    attach_digest,
)


def build_analysis_handoff(
    record: BiomedicalDatasetRecord,
    readiness: OperationInputReadiness,
    *,
    generated_at: datetime | None = None,
) -> AnalysisHandoff:
    if readiness.dataset_ref != record.dataset_ref:
        raise ValueError("readiness 与 dataset record 的 dataset_ref 不一致")
    if readiness.record_digest != record.content_digest:
        raise ValueError("readiness 与 dataset record 的内容摘要不一致")
    generated = generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at 必须包含 UTC 偏移")
    payload = {
        "schema_version": "spc.analysis-handoff.v0.1",
        "lifecycle_status": "provisional",
        "dataset_ref": record.dataset_ref,
        "record_digest": record.content_digest,
        "readiness_digest": readiness.content_digest,
        "intended_operation": readiness.intended_operation,
        "signal": readiness.signal.value,
        "artifacts": [item.model_dump(mode="json") for item in record.artifacts],
        "entities": [item.model_dump(mode="json") for item in record.entities],
        "relations": [item.model_dump(mode="json") for item in record.relations],
        "replication_profile": record.replication_profile.model_dump(mode="json"),
        "measurement_design": record.measurement_design.model_dump(mode="json"),
        "limitations": readiness.limitations,
        "generated_at": generated.isoformat(),
    }
    return AnalysisHandoff.model_validate(
        attach_digest(
            payload,
            excluded_fields=frozenset({"content_digest", "generated_at"}),
        )
    )
