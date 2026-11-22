from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CAPABILITY_DOC = REPO_ROOT / "docs/contracts/end-to-end-paper-writing-capability.md"
PUBLIC_SURFACE_GATE = (
    REPO_ROOT / "docs/contracts/delivery-protocol-public-surface-gate.md"
)
E2E_DATASET = (
    REPO_ROOT
    / "packages/research_harness/tests/fixtures/writing/e2e_paper_generation_dataset.json"
)
E2E_TRACE_FIXTURE = (
    REPO_ROOT / "packages/research_harness/tests/fixtures/writing/"
    "e2e_paper_generation_trace_cases.json"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return " ".join(text.split())


def test_end_to_end_paper_writing_capability_names_full_pipeline() -> None:
    text = _read(CAPABILITY_DOC)
    normalized = _normalize(text)

    assert (
        "Research Harness should take a topic from research intent to a "
        "reviewable, submission-grade manuscript package"
    ) in normalized
    for stage in (
        "PW01_TOPIC_AND_VENUE_CONTRACT",
        "PW02_EVIDENCE_ACQUISITION_AND_READING",
        "PW03_GAP_BASELINE_NOVELTY_VALIDATION",
        "PW04_EXPERIMENT_RESULT_INGESTION",
        "PW05_PAPER_PLAN_AND_STORYLINE",
        "PW06_SECTION_DRAFTING_AND_REVISION",
        "PW07_FIGURE_TABLE_AND_ASSET_QUALITY",
        "PW08_LATEX_CITATION_AND_FINAL_BUNDLE",
        "PW09_REVIEW_AUDIT_AND_PUBLICATION_PACK",
        "PW10_REBUTTAL_CAMERA_READY_AND_REPLAY",
    ):
        assert stage in text


def test_end_to_end_paper_writing_capability_reuses_existing_rh_protocols() -> None:
    text = _read(CAPABILITY_DOC)
    normalized = _normalize(text)

    for required_fragment in (
        "RH remains the evidence and state source of truth",
        "The protocol has no external runtime dependency",
        "protocol_call",
        "human_in_loop_call",
        "orchestrator_record_artifact",
        "RESEARCH_BRIEF",
        "IDEA_REPORT",
        "RESEARCH_PROPOSAL",
        "EVALUATION",
        "EXPERIMENT_PLAN",
        "IMPACT_REPORT",
        "CLAIMS_FROM_RESULTS",
        "PAPER_PLAN",
        "CORE_CLAIM_CONTRACT",
        "ARGUMENT_TREE",
        "TERM_REGISTRY",
        "PROMISE_REALIZATION_MATRIX",
        "PARAGRAPH_INTENT_TREE",
        "manuscript_logic_gate_report",
        "DOMAIN_WRITING_PROFILE",
        "PAPER_PROFILE",
        "reporting_map",
        "evidence_rule",
        "DOMAIN_METHOD_SEARCH_PROFILE",
        "method_route",
        "search_route",
        "search_strategies",
        "method_requirements",
        "baseline_anchor_fields",
        "EXPERIMENT_GROUNDING_PROFILE",
        "variable_grounding",
        "codebook",
        "pre_deploy_code_review",
        "claim-bound",
        "domain-writing-stem",
        "domain-writing-biomedical",
        "domain-writing-social-science",
        "domain-writing-humanities",
        "domain-writing-law-policy",
        "AUTO_REVIEW",
        "PRESUBMISSION_AUDIT",
        "PAPER_PACKAGE",
        "REBUTTAL_PACKAGE",
        "paper_storyline_graph.v1",
        "wiki_context_pack.v1",
        "publication_pack",
        "final_bundle_quality_report",
        "LG78",
        "LG78B",
        "LG78C",
        "LG78D",
        "LG78E",
        "LG78F",
        "LG78G",
        "LG78H",
        "e2e_paper_generation_dataset.json",
        "e2e_paper_generation_trace_cases.json",
        "rh.e2e_paper_generation_trace_shape_contract.v1",
    ):
        assert required_fragment in normalized


def test_end_to_end_paper_writing_capability_declares_boundaries_and_non_goals() -> (
    None
):
    text = _read(CAPABILITY_DOC)

    for boundary in (
        "no unsupported claims",
        "no chat-only source of truth",
        "no invented BibTeX",
        "no invented experiment results",
        "no public readiness claim without QA evidence",
        "no credential mutation",
        "no external action",
    ):
        assert boundary in text

    for non_goal in (
        "fully autonomous science",
        "real public deployment",
        "real Zotero network sync/apply",
        "commits, pushes, PRs, releases, or publishing",
    ):
        assert non_goal in text


def test_end_to_end_paper_writing_requires_manuscript_logic_gate() -> None:
    text = _read(CAPABILITY_DOC)
    normalized = _normalize(text)

    for required_fragment in (
        "manuscript logic gate",
        "CORE_CLAIM_CONTRACT",
        "ARGUMENT_TREE",
        "TERM_REGISTRY",
        "PROMISE_REALIZATION_MATRIX",
        "PARAGRAPH_INTENT_TREE",
        "manuscript_logic_gate_report",
        "refuse abstract, introduction, and manuscript-scale drafting",
    ):
        assert required_fragment in normalized


def test_delivery_public_surface_gate_selects_first_surface() -> None:
    text = _read(PUBLIC_SURFACE_GATE)
    normalized = _normalize(text)

    for required_fragment in (
        "first implementation surface: Python facade",
        "delivery_paper_production_snapshot",
        "rh.delivery.paper_production_snapshot.v1",
        "No MCP tool in LG50",
        "No CLI command in LG50",
        "No HTTP route in LG50",
        "shape-lock tests",
        "rollback boundary",
        "no image-provider work",
        "no real orchestrator_record_artifact call",
    ):
        assert required_fragment in normalized


def test_end_to_end_paper_generation_dataset_contract_is_registered() -> None:
    capability = _read(CAPABILITY_DOC)
    dataset = _read(E2E_DATASET)
    trace_fixture = _read(E2E_TRACE_FIXTURE)

    for required_fragment in (
        "LG78_E2E_PAPER_GENERATION_TEST_DATA",
        "rh.e2e_paper_generation_dataset.v1",
        "reviewable_package_ready",
        "blocked",
        "external-action denial",
        "rh.e2e_paper_generation_trace_shape_contract.v1",
    ):
        assert required_fragment in capability

    assert "rh.e2e_paper_generation_dataset.v1" in dataset
    assert "PW10_REBUTTAL_CAMERA_READY_AND_REPLAY" in dataset
    assert "rh.e2e_paper_generation_trace_cases.v1" in trace_fixture
    assert "stem_result_overclaim" in trace_fixture
