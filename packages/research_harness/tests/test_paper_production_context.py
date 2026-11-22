from __future__ import annotations

from research_harness.auto_runner.paper_production_context import (
    build_paper_production_readiness_report,
    build_paper_production_runtime_context,
    build_paper_production_state_machine,
)


def test_builds_runtime_context_from_topic_and_target_venue() -> None:
    context = build_paper_production_runtime_context(
        topic=(
            "Evidence-grounded AI agents for literature review with benchmark "
            "evaluation"
        ),
        target_venue="NeurIPS 2026",
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()

    assert context.status == "ready_for_evidence_acquisition"
    assert payload["schema_version"] == "rh.paper_production_runtime_context.v1"
    assert payload["topic_venue_contract"]["schema_version"] == (
        "rh.topic_venue_contract.v1"
    )
    assert payload["topic_venue_contract"]["target_venue"] == "NeurIPS 2026"
    assert payload["venue_overlay"]["format_family"] == "latex-two-column"
    assert payload["venue_overlay"]["anonymization_required"] is True
    assert payload["paper_profile"]["domain_skill"] == "domain-writing-stem"
    assert payload["paper_profile"]["reporting_map"] == "ml-empirical-method"
    assert payload["domain_method_search_profile"]["search_route"] == (
        "ml-baseline-search"
    )
    assert (
        "manuscript_logic_gate_report"
        in payload["paper_plan_requirements"]["required_fields"]
    )
    assert (
        "claims_evidence_matrix"
        in payload["paper_plan_requirements"]["required_fields"]
    )
    assert stage_context["query"].startswith("Evidence-grounded AI agents")
    assert stage_context["target_venue"] == "NeurIPS 2026"
    assert stage_context["target_profile"] == "NeurIPS 2026"
    assert stage_context["venue_overlay"]["venue_family"] == "ml_conference"
    assert stage_context["paper_profile"]["schema_version"] == (
        "rh.delivery.paper_profile.v1"
    )
    assert stage_context["strict_evidence"] is True
    assert "paper_plan" not in stage_context


def test_blocks_unknown_or_missing_venue_without_silent_defaults() -> None:
    context = build_paper_production_runtime_context(
        topic="A broad research topic",
        target_venue="Some Niche Venue",
    )

    assert context.status == "blocked"
    assert "venue_overlay:unknown_venue" in context.blockers
    assert context.to_stage_context()["venue_overlay"]["format_family"] == "unknown"

    missing = build_paper_production_runtime_context(
        topic="A broad research topic",
        target_venue=" ",
    )

    assert missing.status == "blocked"
    assert "topic_venue_contract:missing_target_venue" in missing.blockers
    assert "venue_overlay:missing:target_venue" in missing.blockers


def test_explicit_biomedical_profile_overrides_topic_inference() -> None:
    context = build_paper_production_runtime_context(
        topic="Student mental-health screening intervention in primary care",
        target_venue="The Lancet",
        discipline="public-health",
        research_type="intervention-study",
        study_design="rct",
        paper_type="clinical-study",
    )

    payload = context.to_dict()

    assert context.status == "ready_for_evidence_acquisition"
    assert payload["venue_overlay"]["venue_family"] == "clinical_journal"
    assert payload["venue_overlay"]["required_declarations"] == [
        "ethics_approval",
        "trial_registration",
        "competing_interests",
        "data_availability",
    ]
    assert payload["paper_profile"]["domain_skill"] == "domain-writing-biomedical"
    assert payload["paper_profile"]["reporting_map"] == "biomedical-clinical"
    assert payload["paper_profile"]["evidence_rule"] == (
        "intervention-and-quasi-experiment"
    )


def test_runtime_context_infers_real_journal_domains_from_topic_and_venue() -> None:
    cases = [
        (
            "Reproducible analysis of US cloud-seeding activity records from 2000 to 2025",
            "Environmental Research Letters",
            "environmental_science_journal",
            "physical_science",
            "stem-method-or-system",
            "domain-method-search-stem",
        ),
        (
            "Transparent geospatial cost modeling for African green hydrogen delivery to Europe",
            "Energy Policy",
            "energy_engineering_journal",
            "policy",
            "law-policy-analysis",
            "law-policy-method-search",
        ),
        (
            "Lightweight structural alignment analysis of protein complexes using PDB inputs",
            "Bioinformatics",
            "life_science_journal",
            "life_science",
            "biomedical-observational-or-mechanism",
            "biomedical-method-search",
        ),
        (
            "Multi-modal analysis of zebrafish brain functional, structural, and genetic organization",
            "Network Neuroscience",
            "neuroscience_journal",
            "life_science",
            "biomedical-observational-or-mechanism",
            "biomedical-method-search",
        ),
        (
            "Simulated nitrogen deposition effects on dryland shrub root traits and NSC allocation",
            "Global Change Biology",
            "life_science_journal",
            "ecology",
            "ecology-field-experiment",
            "ecology-method-search",
        ),
    ]
    for topic, venue, family, discipline, reporting_map, method_route in cases:
        context = build_paper_production_runtime_context(
            topic=topic,
            target_venue=venue,
        )
        payload = context.to_dict()

        assert context.status == "ready_for_evidence_acquisition", venue
        assert payload["venue_overlay"]["venue_family"] == family
        assert payload["topic_venue_contract"]["discipline"] == discipline
        assert payload["paper_profile"]["reporting_map"] == reporting_map
        assert payload["paper_profile"]["method_route"] == method_route


def test_ecology_topic_uses_ecology_search_route_not_ml_baseline() -> None:
    context = build_paper_production_runtime_context(
        topic="Simulated nitrogen deposition, dryland shrub root traits, and NSC allocation",
        target_venue="Functional Ecology",
    )
    payload = context.to_dict()
    profile = payload["domain_method_search_profile"]

    assert payload["topic_venue_contract"]["discipline"] == "ecology"
    assert profile["search_route"] == "ecology-evidence-search"
    assert "ml-baseline-search" in profile["excluded_defaults"]
    # Ecology screens OpenAlex/PMC-backed OA sources ahead of arXiv.
    preference = payload["evidence_acquisition_plan"]["provider_preference"]
    assert preference[0] == "openalex"
    assert "arxiv" not in preference


def test_ml_topic_provider_preference_leads_with_arxiv() -> None:
    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
    )
    preference = context.to_dict()["evidence_acquisition_plan"]["provider_preference"]

    assert preference[0] == "arxiv"
    assert "openreview" in preference


def test_hssc_arcgis_sports_consumption_routes_to_social_science() -> None:
    context = build_paper_production_runtime_context(
        topic="利用ArcGIS分析城市体育经济赛事活动消费的时空分布格局",
        target_venue="Humanities and Social Sciences Communications",
    )

    payload = context.to_dict()

    assert context.status == "ready_for_evidence_acquisition"
    assert payload["venue_overlay"]["venue_family"] == "social_science_journal"
    assert payload["venue_overlay"]["format_family"] == "journal-single-column"
    assert payload["topic_venue_contract"]["discipline"] == "social_science"
    assert payload["topic_venue_contract"]["study_design"] == "observational"
    assert payload["paper_profile"]["domain_skill"] == "domain-writing-social-science"
    assert payload["paper_profile"]["reporting_map"] == "social-science-observational"
    assert payload["domain_method_search_profile"]["method_route"] == (
        "social-science-method-search"
    )
    assert (
        payload["evidence_acquisition_plan"]["search_parameters"]["tier_filter"]
        == "cas_q2"
    )
    assert payload["evidence_acquisition_plan"]["minimum_acceptance"][
        "required_baseline_families"
    ] == ["theory", "measurement", "population", "identification"]


def test_stage_context_keeps_plan_requirements_separate_from_active_plan() -> None:
    context = build_paper_production_runtime_context(
        topic="Education intervention study for formative feedback",
        target_venue="ICLR Workshop on Agents",
        discipline="education",
        research_type="survey-correlational",
        study_design="cross-sectional",
        paper_type="empirical-study",
    )

    stage_context = context.to_stage_context()

    assert stage_context["paper_plan_requirements"]["artifact"] == "PAPER_PLAN"
    assert stage_context["paper_plan_requirements"]["owner_skill"] == (
        "section-drafting"
    )
    assert (
        "paper_profile" in stage_context["paper_plan_requirements"]["required_fields"]
    )
    assert "paper_plan" not in stage_context
    assert stage_context["paper_plan_ready"] is False
    assert stage_context["next_actions"][0]["stage"] == (
        "PW02_EVIDENCE_ACQUISITION_AND_READING"
    )


def test_paper_production_state_machine_covers_full_product_chain() -> None:
    state_machine = build_paper_production_state_machine()
    payload = state_machine.to_dict()

    assert payload["schema_version"] == "rh.paper_production_state_machine.v1"
    assert payload["status"] == "product_chain_manifest"
    assert payload["completion_condition"] == (
        "final_bundle_pdf_and_publication_pack_pass_all_quality_gates"
    )
    assert [stage["stage_id"] for stage in payload["stages"]] == [
        "PW01_TOPIC_AND_VENUE_CONTRACT",
        "PW02_EVIDENCE_ACQUISITION_AND_READING",
        "PW03_GAP_BASELINE_NOVELTY_VALIDATION",
        "PW04_EXPERIMENT_AND_RESULT_TO_CLAIM",
        "PW05_PAPER_PLAN_AND_LOGIC_GATES",
        "PW06_SECTION_DRAFTING_AND_REVISION",
        "PW07_FIGURE_TABLE_SOURCE_AND_CITATION_INTEGRITY",
        "PW08_LATEX_FINAL_BUNDLE_AND_PDF",
        "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
        "PW10_REBUTTAL_CAMERA_READY_AND_REPLAY",
    ]
    assert payload["stages"][0]["rh_capabilities"] == [
        "topics",
        "orchestrator_run",
        "auto_runner_checkpoint",
        "venue_overlay",
        "paper_profile_route",
    ]
    assert "protocol_call" in payload["stages"][0]["protocol_capabilities"]
    assert "topic_venue_contract" in payload["stages"][0]["required_artifacts"]
    assert "paper_search" in payload["stages"][1]["rh_capabilities"]
    assert "paper_ingest" in payload["stages"][1]["rh_capabilities"]
    assert "real_or_guarded_evidence_required" in payload["stages"][1]["quality_gates"]
    assert (
        "EXPERIMENT_GROUNDING_PROFILE" in payload["stages"][3]["protocol_capabilities"]
    )
    assert (
        "RESULT_TO_CLAIM_ANALYSIS_PROFILE" in payload["stages"][3]["required_artifacts"]
    )
    assert "PAPER_PLAN" in payload["stages"][4]["required_artifacts"]
    assert "manuscript_logic_gate_report" in payload["stages"][4]["required_artifacts"]
    assert "section_draft" in payload["stages"][5]["rh_capabilities"]
    assert "latex_compile" in payload["stages"][7]["rh_capabilities"]
    assert "final_bundle" in payload["stages"][7]["required_artifacts"]
    assert "publication_pack" in payload["stages"][8]["required_artifacts"]
    assert payload["external_action_boundaries"] == [
        "credential_mutation",
        "third_party_writes",
        "real_zotero_network_apply",
        "public_deployment",
        "commit_push_pr_release_publish",
    ]


def test_runtime_context_includes_full_state_machine_manifest() -> None:
    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()

    assert payload["state_machine"]["schema_version"] == (
        "rh.paper_production_state_machine.v1"
    )
    assert payload["state_machine"]["stage_count"] == 10
    assert payload["state_machine"]["stages"][7]["stage_id"] == (
        "PW08_LATEX_FINAL_BUNDLE_AND_PDF"
    )
    assert stage_context["paper_production_state_machine"]["stage_count"] == 10
    assert stage_context["paper_production_completion_condition"] == (
        "final_bundle_pdf_and_publication_pack_pass_all_quality_gates"
    )


def test_paper_production_readiness_report_blocks_at_next_missing_stage() -> None:
    report = build_paper_production_readiness_report(
        artifact_states={
            "topic_venue_contract": "ready",
            "venue_overlay": "ready",
            "PAPER_PROFILE": "ready",
            "DOMAIN_METHOD_SEARCH_PROFILE": "ready",
        }
    )
    payload = report.to_dict()

    assert payload["schema_version"] == "rh.paper_production_readiness_report.v1"
    assert payload["status"] == "blocked"
    assert payload["summary"] == {
        "total": 10,
        "satisfied": 1,
        "ready_to_advance": 0,
        "blocked": 9,
    }
    assert payload["next_stage"] == "PW02_EVIDENCE_ACQUISITION_AND_READING"
    assert payload["next_action"] == (
        "run paper_search, paper_ingest, paper_verify, paper_summarize, "
        "paper_sync, research_wiki, topic_knowledge"
    )
    first = payload["stages"][0]
    second = payload["stages"][1]
    assert first["status"] == "satisfied"
    assert first["missing_artifacts"] == []
    assert second["status"] == "blocked"
    assert second["missing_artifacts"] == [
        "paper_pool",
        "source_inventory",
        "paper_summary_set",
        "wiki_context_pack.v1",
    ]
    assert "PW02_EVIDENCE_ACQUISITION_AND_READING:paper_pool" in payload["blockers"]


def test_paper_production_readiness_report_completes_with_all_required_artifacts() -> (
    None
):
    state_machine = build_paper_production_state_machine()
    artifact_states = {
        artifact: "recorded"
        for stage in state_machine.stages
        for artifact in stage.required_artifacts
    }
    report = build_paper_production_readiness_report(
        artifact_states=artifact_states,
        gate_states={
            gate: "pass"
            for stage in state_machine.stages
            for gate in stage.quality_gates
        },
    )
    payload = report.to_dict()

    assert payload["status"] == "complete"
    assert payload["next_stage"] == ""
    assert payload["next_action"] == (
        "final_bundle_pdf_and_publication_pack_pass_all_quality_gates"
    )
    assert payload["summary"] == {
        "total": 10,
        "satisfied": 10,
        "ready_to_advance": 0,
        "blocked": 0,
    }
    assert payload["blockers"] == []


def test_runtime_context_includes_initial_readiness_report() -> None:
    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()

    assert payload["readiness_report"]["next_stage"] == (
        "PW02_EVIDENCE_ACQUISITION_AND_READING"
    )
    assert payload["readiness_report"]["summary"]["satisfied"] == 1
    assert stage_context["paper_production_readiness_report"]["schema_version"] == (
        "rh.paper_production_readiness_report.v1"
    )
    assert stage_context["paper_production_next_stage"] == (
        "PW02_EVIDENCE_ACQUISITION_AND_READING"
    )


def test_runtime_context_includes_guarded_evidence_acquisition_plan(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GOOGLE_SCHOLAR_API_URL", "https://scholar.example/search")
    monkeypatch.setenv("SCIVERSE_ENABLE", "1")
    monkeypatch.setenv("SCIVERSE_API_TOKEN", "sciverse-key")
    monkeypatch.setenv("OPENREVIEW_ENABLE", "1")

    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()
    plan = payload["evidence_acquisition_plan"]

    assert plan["schema_version"] == "rh.paper_production_evidence_plan.v1"
    assert plan["status"] == "ready"
    assert plan["stage_id"] == "PW02_EVIDENCE_ACQUISITION_AND_READING"
    assert plan["query"] == "Evidence-grounded AI agents for literature review"
    assert plan["provider_mode"] == "guarded_provider_fanout"
    assert plan["search_parameters"] == {
        "query": "Evidence-grounded AI agents for literature review",
        "max_results": 500,
        "auto_ingest": True,
        "local_only": False,
        "per_provider_limit": 30,
        "provider_allowlist": [
            "papervault",
            "semantic_scholar",
            "openalex",
            "crossref",
            "arxiv",
            "pubmed",
            "openreview",
            "spc",
        ],
        "provider_denylist": ["pasa"],
        "tier_filter": "ccf_a",
        "venue_filter": "",
    }
    assert plan["tool_sequence"] == [
        "paper_search",
        "paper_ingest",
        "paper_acquire",
        "paper_list",
        "paper_coverage_check",
    ]
    assert plan["minimum_acceptance"] == {
        "min_total_papers": 25,
        "min_verified_metadata": 20,
        "min_survey_or_benchmark_papers": 3,
        "min_recent_papers": 10,
        "required_baseline_families": [
            "system",
            "retrieval",
            "evaluation",
            "agent",
        ],
    }
    assert plan["expected_artifacts"] == [
        "paper_pool",
        "source_inventory",
        "paper_summary_set",
        "wiki_context_pack.v1",
    ]
    assert stage_context["paper_production_evidence_plan"] == plan
    assert stage_context["query"] == plan["query"]
    assert stage_context["max_results"] == 500
    assert stage_context["auto_ingest"] is True
    assert stage_context["local_only"] is False
    assert stage_context["per_provider_limit"] == 30
    assert stage_context["provider_allowlist"] == [
        "papervault",
        "semantic_scholar",
        "openalex",
        "crossref",
        "arxiv",
        "pubmed",
        "openreview",
        "spc",
    ]
    assert stage_context["provider_denylist"] == ["pasa"]
    assert stage_context["tier_filter"] == "ccf_a"


def test_runtime_context_can_select_local_only_evidence_acquisition() -> None:
    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        local_only=True,
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()
    plan = payload["evidence_acquisition_plan"]

    assert plan["provider_mode"] == "local_only"
    assert plan["search_parameters"]["local_only"] is True
    assert plan["search_parameters"]["provider_allowlist"] == []
    assert plan["search_parameters"]["provider_denylist"] == ["pasa"]
    assert stage_context["local_only"] is True


def test_runtime_context_includes_experiment_claim_and_paper_plan_gates() -> None:
    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review with benchmark evaluation",
        target_venue="NeurIPS 2026",
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()

    experiment = payload["experiment_grounding_profile"]
    result_claim = payload["result_to_claim_analysis_profile"]
    paper_plan_gate = payload["paper_plan_gate_profile"]

    assert experiment["schema_version"] == (
        "rh.delivery.experiment_grounding_profile.v1"
    )
    assert experiment["status"] == "blocked"
    assert experiment["result_state"] == "planned"
    assert "experiment_goal_not_aligned" in experiment["blockers"]
    assert "pre_deploy_code_review_blocked" in experiment["blockers"]

    assert result_claim["schema_version"] == (
        "rh.delivery.result_to_claim_analysis_profile.v1"
    )
    assert result_claim["status"] == "blocked"
    assert result_claim["result_state"] == "planned"
    assert result_claim["maximum_allowed_claim_strength"] == "B_empirical_strong"
    assert "result_state_planned" in result_claim["blockers"]
    assert "claims_from_results_missing" in result_claim["blockers"]

    assert paper_plan_gate == {
        "schema_version": "rh.paper_production_paper_plan_gate.v1",
        "status": "blocked",
        "stage_id": "PW05_PAPER_PLAN_AND_LOGIC_GATES",
        "required_artifact": "PAPER_PLAN",
        "required_reports": [
            "manuscript_logic_gate_report",
            "fine_logic_audit_report",
            "claims_evidence_matrix",
        ],
        "required_upstream_profiles": [
            "PAPER_PROFILE",
            "DOMAIN_METHOD_SEARCH_PROFILE",
            "EXPERIMENT_GROUNDING_PROFILE",
            "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
        ],
        "drafting_enabled": False,
        "promotion_action": "repair_upstream_profiles_before_paper_plan",
        "blockers": [
            "experiment_grounding_profile_blocked",
            "result_to_claim_analysis_profile_blocked",
            "missing_active_PAPER_PLAN",
        ],
    }
    assert stage_context["experiment_grounding_profile"] == experiment
    assert stage_context["result_to_claim_analysis_profile"] == result_claim
    assert stage_context["paper_plan_gate_profile"] == paper_plan_gate
    assert stage_context["paper_plan_ready"] is False


def test_runtime_context_includes_write_to_pdf_closure_plan() -> None:
    context = build_paper_production_runtime_context(
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
    )

    payload = context.to_dict()
    stage_context = context.to_stage_context()
    closure = payload["write_to_pdf_closure_plan"]

    assert closure == {
        "schema_version": "rh.paper_production_write_to_pdf_closure_plan.v1",
        "status": "blocked_until_paper_plan_ready",
        "stage_ids": [
            "PW06_SECTION_DRAFTING_AND_REVISION",
            "PW07_FIGURE_TABLE_SOURCE_AND_CITATION_INTEGRITY",
            "PW08_LATEX_FINAL_BUNDLE_AND_PDF",
            "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
        ],
        "sections_to_draft": [
            # Abstract is drafted last (writing-quality upgrade): it summarizes
            # prose that must already exist, and drafting it first seeded
            # concept drift across the other sections.
            "introduction",
            "related_work",
            "method",
            "experiments",
            "results",
            "limitations",
            "conclusion",
            "abstract",
        ],
        "latex_template": "latex-two-column",
        "publication_components": [
            "process_summary",
            "citation_integrity",
            "final_bundle",
            "publication_pack",
        ],
        "quality_gates": [
            "active_paper_plan_required",
            "strict_evidence_required",
            "citation_integrity_verified",
            "latex_compiles",
            "final_bundle_quality_passed",
            "publication_pack_present",
        ],
        "tool_sequence": [
            "section_draft",
            "section_review",
            "section_revise",
            "consistency_check",
            "figure_suite_plan",
            "figure_plan",
            "figure_suite_render",
            "figure_generate",
            "paper_verify_numbers",
            "citation_verify",
            "evidence_trace",
            "latex_compile",
            "publication_pack_backfill",
            "publication_run",
        ],
        "blockers": ["paper_plan_gate_blocked"],
    }
    assert stage_context["paper_production_closure_plan"] == closure
    assert stage_context["sections_to_draft"] == closure["sections_to_draft"]
    assert stage_context["template"] == "latex-two-column"
    assert stage_context["publication_components"] == closure["publication_components"]
    assert stage_context["record_artifact"] is True
    assert stage_context["citation_quota"] == 24
    assert stage_context["output_dir"].endswith("paper-production")


def test_generic_cs_engineering_topics_stay_out_of_social_science() -> None:
    """Substring false-positives ("gis" in "logistics", "sport" in
    "transport", "city" in "capacity", "event" in "prevention") and lone
    generic words must not reroute CS/engineering topics to social science."""
    from research_harness.auto_runner.paper_production_context import _infer_discipline

    for topic_key in (
        "eventgraph_gis_urban_event_impact",
        "spatiotemporal_graph_learning_traffic",
        "sound_event_detection_benchmark",
        "battery_capacity_prediction",
        "ultrasonic_transport_logistics_optimization",
        "adversarial_prevention_defense",
    ):
        assert _infer_discipline(topic_key) == "ai", topic_key


def test_guarded_allowlist_keeps_every_managed_route(monkeypatch) -> None:
    """The guarded search must not filter out the managed fan-out lanes."""
    from research_harness.auto_runner.paper_production_context import (
        GUARDED_PROVIDER_ALLOWLIST,
        GUARDED_PROVIDER_DENYLIST,
    )
    from research_harness.paper_source_clients import available_provider_specs
    from research_harness.primitives.impls import _excluded_provider_names

    class Named:
        def __init__(self, name: str) -> None:
            self.name = name

    managed = [Named(spec.name) for spec in available_provider_specs()]
    assert managed
    assert (
        _excluded_provider_names(
            managed,
            provider_allowlist=list(GUARDED_PROVIDER_ALLOWLIST),
            provider_denylist=list(GUARDED_PROVIDER_DENYLIST),
        )
        == ()
    )
