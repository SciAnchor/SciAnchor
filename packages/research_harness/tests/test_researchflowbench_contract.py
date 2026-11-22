from __future__ import annotations

import pytest

from research_harness.eval.researchflowbench import (
    DATASET_ARTIFACT_TYPES_V0,
    DATASET_SPLITS_V0,
    LEAKAGE_POLICY_V0,
    MINIMUM_ARCHIVE_LINKAGE_FIELDS_V0,
    MINIMUM_LICENSE_FIELDS_V0,
    MINIMUM_SCORE_REPORT_FIELDS_V0,
    MINIMUM_TASK_FIELDS_V0,
    ResearchFlowBenchArchiveLinkage,
    ResearchFlowBenchLicenseContract,
    ResearchFlowBenchTaskContract,
    dataset_contract_v0_payload,
)


def test_dataset_contract_v0_defines_required_public_interfaces():
    payload = dataset_contract_v0_payload()

    assert payload["schema_version"] == "researchflowbench.dataset_contract.v0"
    assert payload["task_schema"]["minimum_fields"] == MINIMUM_TASK_FIELDS_V0
    assert payload["score_schema"]["minimum_report_fields"] == (
        MINIMUM_SCORE_REPORT_FIELDS_V0
    )
    assert payload["split_names"] == DATASET_SPLITS_V0
    assert payload["artifact_types"] == DATASET_ARTIFACT_TYPES_V0
    assert payload["license_fields"] == MINIMUM_LICENSE_FIELDS_V0
    assert payload["leakage_policy"] == LEAKAGE_POLICY_V0
    assert payload["archive_champion_linkage"]["minimum_fields"] == (
        MINIMUM_ARCHIVE_LINKAGE_FIELDS_V0
    )
    assert payload["archive_champion_linkage"]["automatic_mutation_enabled"] is False


def test_task_contract_materializes_archive_linkage_metadata():
    license_contract = ResearchFlowBenchLicenseContract(
        dataset_license="cc0-1.0",
        data_source_url="https://example.invalid/rfb/synthetic",
        redistribution_policy="repo_safe_synthetic",
        gold_storage_policy="public_safe_synthetic",
    )

    task = ResearchFlowBenchTaskContract(
        benchmark_id="researchflowbench.synthetic_public_pilot20_v0",
        task_id="rfb.synthetic.full_context_citation_eval.0001",
        split="draft_dev",
        input={"prompt_path": "prompt.md"},
        expected_rh_axes=("citation.integrity", "retrieval.provenance_coverage"),
        artifact_policy={"gold_visible": False, "judge_visible": False},
        license=license_contract,
    )

    payload = task.to_dict()
    assert payload["archive_linkage"] == {
        "artifact_refs": [],
        "benchmark_id": "researchflowbench.synthetic_public_pilot20_v0",
        "candidate_id": "",
        "champion_candidate_id": "",
        "rh_axis_ids": [
            "citation.integrity",
            "retrieval.provenance_coverage",
        ],
        "split": "draft_dev",
        "task_id": "rfb.synthetic.full_context_citation_eval.0001",
    }
    assert payload["license"]["third_party_data_vendored"] is False
    assert payload["leakage_policy"]["gold_blind_visible_inputs"] is True


def test_contract_rejects_unsupported_split_and_gold_policy():
    with pytest.raises(ValueError, match="unsupported gold_storage_policy"):
        ResearchFlowBenchLicenseContract(
            dataset_license="noassertion",
            data_source_url="https://example.invalid",
            redistribution_policy="unknown",
            gold_storage_policy="commit_third_party_gold",
        )

    with pytest.raises(ValueError, match="unsupported ResearchFlowBench split"):
        ResearchFlowBenchArchiveLinkage(
            benchmark_id="litsearch",
            task_id="litsearch.q1",
            split="public_test",
            rh_axis_ids=("paper_search.recall",),
        )
