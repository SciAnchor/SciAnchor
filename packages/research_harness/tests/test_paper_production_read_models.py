from __future__ import annotations

from research_harness.auto_runner.paper_production_read_models import (
    BenchmarkResourcePack,
    HypothesisExperimentJob,
    HypothesisStopPolicy,
    HypothesisTreeNode,
    PaperProductionRunSnapshot,
    ReferenceCodebaseResourcePack,
    ResearchHypothesisTree,
    VenueComplianceReport,
    VenueKitResourcePack,
    WritingStyleResourcePack,
)


def test_research_hypothesis_tree_serializes_rh_native_contract() -> None:
    tree = ResearchHypothesisTree(
        topic_id="topic-123",
        paper_plan_artifact_id="artifact-plan",
        nodes=(
            HypothesisTreeNode(
                id="h1",
                statement="Retrieval-grounded agents reduce unsupported claims.",
                rationale="Evidence ledgers expose missing citation support.",
                test="Compare unsupported claim rate against a baseline agent.",
                status="supported",
                stage="supported",
                parent_id=None,
                children=("h1.1",),
                plan_artifact_id="artifact-h1-plan",
                experiment_artifact_id="artifact-h1-experiment",
                result_artifact_id="artifact-h1-result",
                report_artifact_id="artifact-h1-report",
                claim_ids=("claim-1", "claim-2"),
                evidence_refs=(
                    {"paper_id": "paper-1", "locator": "sec:4"},
                    {"artifact_id": "artifact-evidence"},
                ),
                expanded=True,
            ),
            HypothesisTreeNode(
                id="h1.1",
                statement="Citation checking catches most unsupported claims.",
                rationale="The gate inspects draft claims before publication pack.",
                test="Run citation gate on generated manuscript drafts.",
                status="untested",
                stage="planned",
                parent_id="h1",
            ),
        ),
        stop_policy=HypothesisStopPolicy(
            target_supported=2,
            max_tested=8,
            max_depth=3,
        ),
    )

    payload = tree.to_dict()

    assert payload["schema_version"] == "rh.research_hypothesis_tree.v1"
    assert payload["topic_id"] == "topic-123"
    assert payload["paper_plan_artifact_id"] == "artifact-plan"
    assert payload["stop_policy"] == {
        "target_supported": 2,
        "max_tested": 8,
        "max_depth": 3,
    }
    assert payload["status_summary"] == {
        "supported": 1,
        "refuted": 0,
        "inconclusive": 0,
        "blocked": 0,
        "untested": 1,
    }
    assert payload["nodes"][0]["children"] == ["h1.1"]
    assert payload["nodes"][0]["claim_ids"] == ["claim-1", "claim-2"]
    assert payload["nodes"][0]["evidence_refs"] == [
        {"paper_id": "paper-1", "locator": "sec:4"},
        {"artifact_id": "artifact-evidence"},
    ]
    assert payload["nodes"][1]["parent_id"] == "h1"
    assert "final_bundle_ready" not in payload
    assert "publication_pack_ready" not in payload


def test_hypothesis_experiment_job_serializes_ledger_backed_status() -> None:
    job = HypothesisExperimentJob(
        topic_id="topic-123",
        hypothesis_id="h1",
        run_id="run-456",
        status="running",
        effective_config={"max_attempts": 2, "sandbox": "rh-runtime"},
        attempts=(
            {
                "attempt_id": "attempt-1",
                "status": "failed",
                "event_ids": ["event-1"],
            },
            {
                "attempt_id": "attempt-2",
                "status": "running",
                "event_ids": ["event-2", "event-3"],
            },
        ),
        events_ref={"ledger": "runtime_events", "run_id": "run-456"},
    )

    payload = job.to_dict()

    assert payload == {
        "schema_version": "rh.hypothesis_experiment_job.v1",
        "topic_id": "topic-123",
        "hypothesis_id": "h1",
        "run_id": "run-456",
        "status": "running",
        "effective_config": {"max_attempts": 2, "sandbox": "rh-runtime"},
        "attempts": [
            {
                "attempt_id": "attempt-1",
                "status": "failed",
                "event_ids": ["event-1"],
            },
            {
                "attempt_id": "attempt-2",
                "status": "running",
                "event_ids": ["event-2", "event-3"],
            },
        ],
        "events_ref": {"ledger": "runtime_events", "run_id": "run-456"},
        "result_artifact_id": None,
        "report_artifact_id": None,
    }


def test_paper_production_snapshot_keeps_quality_gates_authoritative() -> None:
    snapshot = PaperProductionRunSnapshot(
        topic_id="topic-123",
        current_stage="PW04_EXPERIMENT_AND_RESULT_TO_CLAIM",
        current_milestone="testing_retrieval_grounded_agent_hypothesis",
        active_direction_or_idea="evidence-grounded agent workflow",
        active_hypothesis_id="h1",
        supported=3,
        refuted=1,
        inconclusive=1,
        blocked=0,
        blockers=("publication_pack:missing",),
        next_action="assemble final bundle after citation and provenance gates",
        final_bundle_ready=False,
        publication_pack_ready=False,
        venue_compliance_ready=True,
    )

    payload = snapshot.to_dict()

    assert payload["schema_version"] == "rh.paper_production_run_snapshot.v1"
    assert payload["supported"] == 3
    assert payload["blockers"] == ["publication_pack:missing"]
    assert payload["final_bundle_ready"] is False
    assert payload["publication_pack_ready"] is False
    assert payload["venue_compliance_ready"] is True


def test_venue_compliance_report_serializes_deterministic_latex_checks() -> None:
    report = VenueComplianceReport(
        topic_id="topic-123",
        status="failed",
        latex_compile_success=False,
        disallowed_packages=("minted",),
        disallowed_commands=("\\write18",),
        missing_files=("figures/main.pdf",),
        undefined_citations=("smith2024",),
        undefined_references=("fig:missing",),
        overfull_box_warnings=("main.tex:42 Overfull \\\\hbox",),
        main_text_page_count=10,
        page_limit=8,
        references_appendix_excluded=True,
        blockers=("latex_compile:failed", "page_limit:exceeded"),
    )

    payload = report.to_dict()

    assert payload["schema_version"] == "rh.venue_compliance_report.v1"
    assert payload["latex_compile_success"] is False
    assert payload["disallowed_packages"] == ["minted"]
    assert payload["disallowed_commands"] == ["\\write18"]
    assert payload["missing_files"] == ["figures/main.pdf"]
    assert payload["undefined_citations"] == ["smith2024"]
    assert payload["undefined_references"] == ["fig:missing"]
    assert payload["overfull_box_warnings"] == ["main.tex:42 Overfull \\\\hbox"]
    assert payload["references_appendix_excluded"] is True
    assert payload["blockers"] == ["latex_compile:failed", "page_limit:exceeded"]


def test_resource_packs_serialize_minimal_frontend_read_models() -> None:
    benchmark = BenchmarkResourcePack(
        pack_id="bench-mmlu",
        name="MMLU retrieval grounding benchmark",
        dataset="mmlu",
        metric="unsupported_claim_rate",
        baseline="vanilla_agent",
        cited_leaderboard="https://example.test/leaderboard",
        bibtex_refs=("@misc{mmlu}",),
        protocol="Run identical prompts with and without evidence gate.",
        expected_outputs=("results.json", "claims.csv"),
    )
    writing_style = WritingStyleResourcePack(
        pack_id="style-neurips",
        name="NeurIPS empirical style",
        target_venue="NeurIPS",
        tone="concise empirical systems paper",
        section_guidance={"abstract": "state problem, method, result"},
        bibtex_refs=("@inproceedings{style}",),
    )
    venue_kit = VenueKitResourcePack(
        pack_id="venue-neurips",
        name="NeurIPS venue kit",
        target_venue="NeurIPS",
        template_artifact_id="artifact-template",
        page_limit=9,
        disallowed_packages=("minted",),
        disallowed_commands=("\\write18",),
        required_sections=("Abstract", "Introduction"),
        anonymization_required=True,
    )
    codebase = ReferenceCodebaseResourcePack(
        pack_id="codebase-rh",
        name="Research Harness reference implementation",
        repo_ref="https://example.test/repo.git",
        commit="abc123",
        license="Apache-2.0",
        setup="pip install -e .",
        expected_entrypoints=("rh",),
    )

    assert benchmark.to_dict()["schema_version"] == "rh.resource_pack.benchmark.v1"
    assert benchmark.to_dict()["expected_outputs"] == ["results.json", "claims.csv"]
    assert (
        writing_style.to_dict()["schema_version"] == "rh.resource_pack.writing_style.v1"
    )
    assert writing_style.to_dict()["section_guidance"] == {
        "abstract": "state problem, method, result"
    }
    assert venue_kit.to_dict()["schema_version"] == "rh.resource_pack.venue_kit.v1"
    assert venue_kit.to_dict()["required_sections"] == ["Abstract", "Introduction"]
    assert (
        codebase.to_dict()["schema_version"] == "rh.resource_pack.reference_codebase.v1"
    )
    assert codebase.to_dict()["expected_entrypoints"] == ["rh"]
