from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "skills").exists()
)


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _skill_text(name: str) -> str:
    return _read_repo_text(f"skills/{name}/SKILL.md")


def test_delivery_docs_are_discoverable_from_doc_index_and_python_api() -> None:
    index_text = _read_repo_text("docs/index.md")
    python_api_text = _read_repo_text("docs/python-api.md")

    assert "[RH 科研交付协议](research-delivery-protocol.md)" in index_text
    assert (
        "[RH research delivery protocol](research-delivery-protocol.md)"
        in python_api_text
    )
    assert "read-only paper-production snapshot protocol" in " ".join(
        python_api_text.split()
    )


def test_python_api_doc_includes_delivery_snapshot_reference() -> None:
    text = _read_repo_text("docs/python-api.md")
    normalized = " ".join(text.split())
    lowered = normalized.lower()

    assert "## Research Delivery Paper-Production Snapshot" in text
    assert (
        "`delivery_paper_production_snapshot(topic_id=None, artifact_states=None, payloads=None)`"
        in text
    )
    assert "rh.delivery.paper_production_snapshot.v1" in text
    assert "read-only dry-run" in normalized
    assert "`topic_id` reads existing recorded topic artifacts" in normalized
    assert "`artifact_states` overrides topic-derived state" in normalized
    assert (
        "`payloads` supplies candidate artifact payloads for validation" in normalized
    )
    assert "does not call `orchestrator_record_artifact`" in lowered
    assert "does not advance stages" in normalized
    assert "does not write artifacts" in normalized
    assert "not exposed as MCP, CLI, or HTTP" in normalized


def test_delivery_protocol_doc_preserves_rh_as_source_of_truth() -> None:
    text = _read_repo_text("docs/research-delivery-protocol.md")

    assert "RH research delivery protocol" in text
    assert "Research Harness remains the evidence and state source of truth" in text
    assert "The protocol has no external runtime dependency" in text
    assert "No storage schema migration is part of this protocol" in text
    assert "protocol_call" in text
    assert "human_in_loop_call" in text
    assert "orchestrator_record_artifact" in text


def test_delivery_protocol_doc_describes_read_only_python_snapshot() -> None:
    text = _read_repo_text("docs/research-delivery-protocol.md")
    normalized = " ".join(text.split())

    assert "ResearchAPI.delivery_paper_production_snapshot" in text
    assert "rh.delivery.paper_production_snapshot.v1" in text
    assert "read-only, dry-run runbook" in normalized
    assert "optional topic artifact state" in normalized
    assert (
        "Caller-supplied `artifact_states` override topic-derived states" in normalized
    )
    assert "Python-only `ResearchService` command" in normalized
    assert "not registered as public MCP, CLI, or HTTP transport" in normalized
    assert "includes an `inputs` summary" in text
    assert "but not artifact payload contents or stored artifact contents" in normalized
    assert "does not call `orchestrator_record_artifact`" in text
    assert "advance stages" in text
    assert "write the database" in normalized
    assert "open MCP, CLI, or HTTP transport" in normalized


def test_delivery_snapshot_docs_include_python_usage_example() -> None:
    text = _read_repo_text("docs/research-delivery-protocol.md")
    normalized = " ".join(text.split())

    assert "## Python usage example" in text
    assert "from research_harness import ResearchAPI" in text
    assert "api = ResearchAPI()" in text
    assert "api.delivery_paper_production_snapshot(" in text
    assert "topic_id=42" in text
    assert '"RESEARCH_BRIEF": "active"' in text
    assert '"IDEA_REPORT": {' in text
    assert '"schema_version": "rh.delivery.idea_report.v1"' in text
    assert 'snapshot["dry_run"] is True' in text
    assert 'snapshot["inputs"]["artifact_states"]["sources"]' in text
    assert "Use `topic_id` for recorded topic state" in normalized
    assert "Use `artifact_states` for hypothetical overrides" in normalized
    assert "The example does not record artifacts or advance stages" in normalized


def test_delivery_artifact_mapping_is_rh_native() -> None:
    text = _read_repo_text("docs/research-delivery-protocol.md")

    required_artifacts = [
        "RESEARCH_BRIEF",
        "IDEA_REPORT",
        "RESEARCH_PROPOSAL",
        "EVALUATION",
        "EXPERIMENT_GOAL",
        "EXPERIMENT_PLAN",
        "IMPACT_REPORT",
        "CLAIMS_FROM_RESULTS",
        "PAPER_PLAN",
        "AUTO_REVIEW",
        "PRESUBMISSION_AUDIT",
        "REBUTTAL_PACKAGE",
    ]
    for artifact in required_artifacts:
        assert artifact in text

    assert "These names are RH artifact conventions, not new database tables" in text
    assert ".aris/" not in text


def test_relevant_skills_carry_delivery_protocol_without_new_public_surface() -> None:
    required = {
        "research-init": ("RESEARCH_BRIEF", "protocol_call", "human_in_loop_call"),
        "gap-analysis": ("IDEA_REPORT", "RESEARCH_PROPOSAL", "EVALUATION"),
        "evidence-gating": ("research delivery protocol", "EXPERIMENT_PLAN"),
        "section-drafting": ("PAPER_PLAN", "Claims-Evidence Matrix"),
        "paper-writing": ("PRESUBMISSION_AUDIT", "REBUTTAL_PACKAGE"),
        "publication-pack": ("PAPER_PACKAGE", "REBUTTAL_PACKAGE"),
        "provenance-review": (
            "research delivery protocol",
            "recorded as RH artifacts",
        ),
    }

    for skill_name, fragments in required.items():
        text = _skill_text(skill_name)
        assert "RH research delivery protocol" in text
        for fragment in fragments:
            assert fragment in text
        assert "The protocol has no external runtime dependency" in text


def test_skill_manifest_keeps_existing_public_surface_and_mentions_delivery_protocol() -> (
    None
):
    manifest = json.loads(_read_repo_text("skills/manifest.json"))
    skill_names = {skill["name"] for skill in manifest["skills"]}

    assert "delivery-protocol" not in skill_names

    skills_by_name = {skill["name"]: skill for skill in manifest["skills"]}
    assert "manuscript-logic-gate" in skills_by_name
    assert (
        "CORE_CLAIM_CONTRACT"
        in skills_by_name["manuscript-logic-gate"]["extras"]["artifact_schemas"]
    )
    assert "manuscript-logic-gate" in skills_by_name["paper-writing"]["extras"]["gates"]
    assert (
        "RESEARCH_BRIEF"
        in skills_by_name["research-init"]["extras"]["artifact_schemas"]
    )
    assert "PAPER_PLAN" in skills_by_name["paper-writing"]["extras"]["artifact_schemas"]
    assert (
        "REBUTTAL_PACKAGE"
        in skills_by_name["publication-pack"]["extras"]["artifact_schemas"]
    )
