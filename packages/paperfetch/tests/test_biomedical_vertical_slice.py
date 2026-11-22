from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from paperfetch.cli import root as root_cli
from paperfetch.biomedical.geo import build_geo_dataset_record
from paperfetch.biomedical.gold import (
    biomedical_data_root,
    default_policy_path,
    run_gold_validation,
)
from paperfetch.biomedical.handoff import build_analysis_handoff
from paperfetch.biomedical.models import FieldAssertion
from paperfetch.biomedical.policy import assess_operation_readiness
from paperfetch.observability import events_snapshot


OBSERVED_AT = datetime(2026, 8, 3, tzinfo=timezone.utc)


def _record(accession: str):
    root = biomedical_data_root() / "gold"
    return build_geo_dataset_record(
        root / f"{accession}.provisional.soft",
        filelist_file=root / f"{accession}.filelist.txt",
        observed_at=OBSERVED_AT,
    )


def test_dvt_record_preserves_pooling_and_replication_levels():
    record = _record("GSE221978")

    assert record.lifecycle_status.value == "provisional"
    assert record.disease_terms == ["deep_vein_thrombosis"]
    assert record.measurement_design.time_design == "single_timepoint_cross_sectional"
    assert record.replication_profile.pooling_detected is True
    assert record.replication_profile.biological_group_units_recoverable is False
    animals = next(
        item
        for item in record.replication_profile.levels
        if item.entity_type.value == "animal"
    )
    assert animals.total == 13
    assert animals.per_group == {"dvt_ivc_ligation": 5, "sham_control": 8}
    assert animals.usable_for_group_inference is False
    assert any(item.relation_type.value == "pooled_from" for item in record.relations)
    assert not any(item.entity_type.value == "animal" for item in record.entities)
    assert "8,000 表示每个样本上机加载细胞数" in " ".join(record.unresolved_questions)


def test_dvt_policy_blocks_pseudobulk_and_longitudinal_but_keeps_description_conditional():
    record = _record("GSE221978")
    policy = default_policy_path()

    descriptive = assess_operation_readiness(
        record,
        "descriptive_exploratory",
        policy,
        checked_at=OBSERVED_AT,
    )
    pseudobulk = assess_operation_readiness(
        record,
        "animal_or_patient_level_pseudobulk",
        policy,
        checked_at=OBSERVED_AT,
    )
    longitudinal = assess_operation_readiness(
        record,
        "longitudinal_paired_change",
        policy,
        checked_at=OBSERVED_AT,
    )

    assert descriptive.signal.value == "conditional"
    assert pseudobulk.signal.value == "blocked"
    assert longitudinal.signal.value == "blocked"
    assert "PRE_LIBRARY_POOLING_FORBIDDEN" in {
        item.code for item in pseudobulk.requirements if item.status.value == "blocked"
    }
    assert "PAIRED_LONGITUDINAL_DESIGN_REQUIRED" in {
        item.code
        for item in longitudinal.requirements
        if item.status.value == "blocked"
    }


def test_glioma_record_keeps_patient_mapping_provisional_and_platform_spaces_separate():
    record = _record("GSE131928")

    assert record.disease_terms == ["glioblastoma_idh_wildtype"]
    assert record.replication_profile.subject_sample_mapping == "partial"
    assert record.replication_profile.biological_group_units_recoverable is None
    assert record.measurement_design.measurement_spaces == [
        "10x_droplet_expression",
        "smartseq2_full_length_expression",
    ]
    patient_count = next(
        item.normalized_value
        for item in record.field_assertions
        if item.field_name == "count.reported_patients"
    )
    cell_count = next(
        item.normalized_value
        for item in record.field_assertions
        if item.field_name == "count.reported_single_cells"
    )
    assert patient_count == 28
    assert cell_count == 24131
    assert not any(item.entity_type.value == "patient" for item in record.entities)

    readiness = assess_operation_readiness(
        record,
        "animal_or_patient_level_pseudobulk",
        default_policy_path(),
        checked_at=OBSERVED_AT,
    )
    integration = assess_operation_readiness(
        record,
        "matrix_level_integration",
        default_policy_path(),
        checked_at=OBSERVED_AT,
    )
    assert readiness.signal.value == "not_assessable"
    assert integration.signal.value == "blocked"


def test_record_digest_is_independent_of_materialization_root_and_parse_time(tmp_path):
    source = biomedical_data_root() / "gold"
    first_root = tmp_path / "one"
    second_root = tmp_path / "two"
    first_root.mkdir()
    second_root.mkdir()
    for root in (first_root, second_root):
        shutil.copyfile(
            source / "GSE221978.provisional.soft", root / "GSE221978.provisional.soft"
        )
        shutil.copyfile(
            source / "GSE221978.filelist.txt", root / "GSE221978.filelist.txt"
        )

    first = build_geo_dataset_record(
        first_root / "GSE221978.provisional.soft",
        filelist_file=first_root / "GSE221978.filelist.txt",
        observed_at=OBSERVED_AT,
    )
    second = build_geo_dataset_record(
        second_root / "GSE221978.provisional.soft",
        filelist_file=second_root / "GSE221978.filelist.txt",
        observed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert first.content_digest == second.content_digest


def test_flow_sorted_bulk_is_not_promoted_to_single_cell(tmp_path):
    soft = tmp_path / "GSE1.soft"
    soft.write_text(
        "\n".join(
            [
                "^SERIES = GSE1",
                "!Series_title = Bulk RNA sequencing of flow-sorted immune cells",
                "^SAMPLE = GSM1",
                "!Sample_title = sorted cells",
                "!Sample_source_name_ch1 = blood",
                "!Sample_organism_ch1 = Homo sapiens",
                "!Sample_treatment_protocol_ch1 = Single cells were sorted by flow cytometry and pooled for bulk RNA extraction.",
                "!Sample_library_source = transcriptomic",
                "!Sample_library_strategy = RNA-Seq",
                "!Sample_instrument_model = NovaSeq 6000",
            ]
        ),
        encoding="utf-8",
    )

    record = build_geo_dataset_record(soft, observed_at=OBSERVED_AT)

    assert record.measurement_design.modalities == []
    readiness = assess_operation_readiness(
        record,
        "descriptive_exploratory",
        default_policy_path(),
        checked_at=OBSERVED_AT,
    )
    assert readiness.signal.value == "blocked"


def test_candidate_mapping_requires_explicit_review_flag():
    payload = {
        "field_name": "biological.tissue",
        "raw_value": "adjacent tissue",
        "normalized_value": "adjacent_non_tumor",
        "source_type": "geo_soft",
        "source_locator": "fixture#!Sample_source_name_ch1",
        "observed_at": OBSERVED_AT,
        "availability": "ambiguous",
        "derivation": "candidate_mapping",
        "requires_review": False,
    }

    with pytest.raises(ValidationError, match="requires_review"):
        FieldAssertion.model_validate(payload)


def test_analysis_handoff_preserves_blocked_signal_and_contains_no_algorithm_choice():
    record = _record("GSE221978")
    readiness = assess_operation_readiness(
        record,
        "animal_or_patient_level_pseudobulk",
        default_policy_path(),
        checked_at=OBSERVED_AT,
    )

    handoff = build_analysis_handoff(record, readiness, generated_at=OBSERVED_AT)
    encoded = json.dumps(handoff.model_dump(mode="json"), ensure_ascii=False)

    assert handoff.signal.value == "blocked"
    assert handoff.record_digest == record.content_digest
    assert handoff.readiness_digest == readiness.content_digest
    assert "algorithm" not in encoded.lower()
    assert "论文角色" not in encoded


def test_dvt_glioma_gold_replay_passes_without_upgrading_lifecycle():
    report = run_gold_validation()

    assert report["status"] == "passed"
    assert report["lifecycle_status"] == "provisional"
    assert report["summary"] == {"total": 2, "passed": 2, "failed": 0}


def test_biomedical_cli_localizes_text_status_but_keeps_json_contract(capsys):
    code = root_cli.main(
        ["dataset", "gold-validate", "--output-format", "text", "--no-progress"]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "医学金标回放：通过" in captured.out
    assert "dvt-gse221978：通过" in captured.out
    assert "：passed" not in captured.out

    code = root_cli.main(
        ["dataset", "gold-validate", "--output-format", "json", "--no-progress"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "completed"
    assert payload["data"]["cases"][0]["status"] == "passed"


def test_biomedical_cli_vertical_slice_keeps_json_stdout_and_blocked_terminal(
    tmp_path,
    capsys,
):
    gold = biomedical_data_root() / "gold"
    output = tmp_path / "inspection"
    code = root_cli.main(
        [
            "dataset",
            "inspect",
            "GSE221978",
            "--soft-file",
            str(gold / "GSE221978.provisional.soft"),
            "--filelist-file",
            str(gold / "GSE221978.filelist.txt"),
            "--output-dir",
            str(output),
            "--observed-at",
            "2026-08-03T00:00:00+00:00",
            "--output-format",
            "json",
            "-v",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["status"] == "completed"
    assert payload["data"]["record"]["accession"] == "GSE221978"
    assert payload["data"]["record"]["lifecycle_status"] == "provisional"
    assert {item["type"] for item in payload["files"]} == {
        "dataset_request",
        "dataset_records",
        "entity_graph",
        "run_report",
    }
    assert (
        json.loads((output / "dataset_request.json").read_text(encoding="utf-8"))[
            "network_accessed"
        ]
        is False
    )
    assert "开始检查公共生物医学数据集" in captured.err

    readiness_file = output / "operation_readiness.json"
    code = root_cli.main(
        [
            "dataset",
            "readiness",
            "--record-file",
            str(output / "dataset_records.jsonl"),
            "--operation",
            "animal_or_patient_level_pseudobulk",
            "--checked-at",
            "2026-08-03T00:00:00+00:00",
            "--output-file",
            str(readiness_file),
            "--output-format",
            "json",
            "-v",
        ]
    )
    captured = capsys.readouterr()
    readiness = json.loads(captured.out)

    assert code == 2
    assert readiness["status"] == "failed"
    assert readiness["data"]["signal"] == "blocked"
    assert readiness["error"]["code"] == "readiness_blocked"
    terminals = [
        item for item in events_snapshot() if item.event_code == "cli.command.terminal"
    ]
    assert terminals[-1].outcome == "blocked"
    assert terminals[-1].level == "WARNING"
    assert "就绪门禁未通过" in captured.err

    handoff_file = output / "analysis_handoff.json"
    code = root_cli.main(
        [
            "dataset",
            "handoff",
            "--record-file",
            str(output / "dataset_records.jsonl"),
            "--readiness-file",
            str(readiness_file),
            "--generated-at",
            "2026-08-03T00:00:00+00:00",
            "--output-file",
            str(handoff_file),
            "--output-format",
            "json",
            "-v",
        ]
    )
    handoff = json.loads(capsys.readouterr().out)

    assert code == 2
    assert handoff["status"] == "failed"
    assert handoff["data"]["signal"] == "blocked"
    assert json.loads(handoff_file.read_text(encoding="utf-8"))["signal"] == "blocked"
