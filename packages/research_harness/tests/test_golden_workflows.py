from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_harness.primitives.types import (
    Baseline,
    BaselineIdentifyOutput,
    Claim,
    ClaimExtractOutput,
    ConsistencyCheckOutput,
    DraftText,
    EvidenceMapping,
    Gap,
    GapDetectOutput,
    PaperIngestOutput,
    PaperRef,
    PaperSearchOutput,
    PrimitiveResult,
    SectionDraftOutput,
)
from research_harness.service import ResearchService


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_FIXTURE = (
    REPO_ROOT
    / "packages/research_harness/tests/fixtures/workflows/lg15_workflow_wrappers.json"
)
WORKFLOW_CONTRACT_DOC = REPO_ROOT / "docs/contracts/workflow-wrapper-contracts.md"


class _GoldenBackend:
    def __init__(self, db) -> None:
        self._db = db

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        output = self._output_for(primitive, kwargs)
        return PrimitiveResult(
            primitive=primitive,
            success=True,
            output=output,
            started_at="2026-06-15T00:00:00+00:00",
            finished_at="2026-06-15T00:00:01+00:00",
            backend="golden-fixture",
            model_used="fake-local",
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
        )

    def get_info(self):
        return {"name": "golden-fixture"}

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        del primitive, kwargs
        return 0.0

    def supports(self, primitive: str) -> bool:
        del primitive
        return True

    def _output_for(self, primitive: str, kwargs: dict[str, Any]) -> Any:
        if primitive == "paper_search":
            return PaperSearchOutput(
                papers=[
                    PaperRef(
                        title="Deterministic Workflow Evidence",
                        authors=["A. Fixture"],
                        year=2026,
                        venue="GoldenConf",
                        doi="10.0000/golden.workflow",
                        relevance_score=0.99,
                    )
                ],
                provider="fixture",
                query_used=str(kwargs["query"]),
                total_before_filter=1,
            )
        if primitive == "paper_ingest":
            return self._ingest_fixture_paper(kwargs)
        if primitive == "claim_extract":
            return ClaimExtractOutput(
                claims=[
                    Claim(
                        claim_id="claim-golden-1",
                        content="Deterministic workflows preserve evidence links.",
                        paper_ids=[int(kwargs["paper_ids"][0])],
                        evidence_type="finding",
                        confidence=0.93,
                        source_section="results",
                    )
                ],
                papers_processed=1,
            )
        if primitive == "gap_detect":
            return GapDetectOutput(
                gaps=[
                    Gap(
                        gap_id="gap-golden-1",
                        description="Workflow contracts need local closure evidence.",
                        gap_type="productization",
                        severity="high",
                        related_paper_ids=[1],
                        confidence=0.86,
                    )
                ],
                papers_analyzed=1,
            )
        if primitive == "baseline_identify":
            return BaselineIdentifyOutput(
                baselines=[
                    Baseline(
                        name="Manual agent checklist",
                        baseline_id="baseline-golden-1",
                        method_family="workflow",
                        facets=["audit", "recovery"],
                        relationship_to_proposal="baseline",
                        paper_ids=[1],
                    )
                ]
            )
        if primitive == "section_draft":
            return SectionDraftOutput(
                draft=DraftText(
                    section=str(kwargs["section"]),
                    content="Golden workflows bind claims, gaps, and drafts.",
                    citations_used=[1],
                    evidence_ids=["claim:claim-golden-1"],
                    word_count=7,
                ),
                evidence_map=[
                    EvidenceMapping(
                        sentence_index=0,
                        sentence_text=(
                            "Golden workflows bind claims, gaps, and drafts."
                        ),
                        source_paper_id=1,
                        relation_type="compression",
                        source_span="results",
                        confidence=0.9,
                    )
                ],
            )
        if primitive == "consistency_check":
            return ConsistencyCheckOutput(
                issues=[],
                sections_checked=list(kwargs["sections"]),
            )
        raise AssertionError(f"unexpected primitive: {primitive}")

    def _ingest_fixture_paper(self, kwargs: dict[str, Any]) -> PaperIngestOutput:
        topic_id = int(kwargs["topic_id"])
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO papers
                    (title, authors, year, venue, doi, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Deterministic Workflow Evidence",
                    json.dumps(["A. Fixture"]),
                    2026,
                    "GoldenConf",
                    "10.0000/golden.workflow",
                    "meta_only",
                ),
            )
            paper_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO paper_topics (paper_id, topic_id, relevance)
                VALUES (?, ?, ?)
                """,
                (paper_id, topic_id, kwargs.get("relevance", "high")),
            )
            conn.commit()
        finally:
            conn.close()
        return PaperIngestOutput(
            paper_id=paper_id,
            title="Deterministic Workflow Evidence",
            status="new",
            merged_fields=[],
            enriched_fields={"venue": "GoldenConf"},
        )


def _install_golden_backend(monkeypatch) -> None:
    import research_harness.service.handlers as handlers_module

    def create_fake_backend(_name: str, **kwargs: Any) -> _GoldenBackend:
        return _GoldenBackend(kwargs["db"])

    monkeypatch.setattr(handlers_module, "create_backend", create_fake_backend)


def _seed_topic(db, name: str) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
            (name, "Golden workflow topic", "active"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (?, ?, ?)",
            (topic_id, f"{name}-project", "Golden workflow project"),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def _seed_topic_paper(db, topic_id: int) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"Seed paper for topic {topic_id}",
                json.dumps(["A. Fixture"]),
                2026,
                "GoldenConf",
                f"10.0000/golden.seed.{topic_id}",
                "meta_only",
            ),
        )
        paper_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (paper_id, topic_id, "high"),
        )
        conn.commit()
        return paper_id
    finally:
        conn.close()


def test_literature_search_ingest_golden_workflow_closes_minimal_loop(
    db,
    monkeypatch,
):
    from research_harness._selfdev.golden_workflows import (
        build_golden_workflow_contract,
    )

    _install_golden_backend(monkeypatch)
    topic_id = _seed_topic(db, "golden-literature")
    service = ResearchService(db=db)

    service.invoke("orchestrator_resume", {"topic_id": topic_id})
    search = service.invoke(
        "paper_search",
        {"topic_id": topic_id, "query": "deterministic workflow evidence"},
    )
    ingest = service.invoke(
        "paper_ingest",
        {
            "topic_id": topic_id,
            "source": "10.0000/golden.workflow",
            "relevance": "high",
        },
    )
    artifact = service.invoke(
        "orchestrator_record_artifact",
        {
            "topic_id": topic_id,
            "stage": "build",
            "artifact_type": "literature_map",
            "title": "Golden literature map",
            "payload": {
                "query": search.output.query_used,
                "paper_id": ingest.output.paper_id,
            },
        },
    )
    gate = service.invoke("orchestrator_gate_check", {"topic_id": topic_id})

    contract = build_golden_workflow_contract(
        db=db,
        workflow_name="literature_search_ingest",
        topic_id=topic_id,
        service_results=[search, ingest, artifact, gate],
        require_gate=True,
    )

    assert contract.status == "success"
    assert contract.topic_name == "golden-literature"
    assert contract.paper_ids == (ingest.output.paper_id,)
    assert contract.primitive_commands == ("paper_search", "paper_ingest")
    assert contract.provenance_primitives == ("paper_search", "paper_ingest")
    assert "paper:1" in contract.artifact_refs
    assert any(ref.endswith(":literature_map") for ref in contract.artifact_refs)
    assert any("paper_ingest top results" in action for action in contract.next_actions)
    assert contract.gate_decisions == ("needs_approval",)


def test_evidence_to_draft_golden_workflow_links_primitives_to_draft_artifact(
    db,
    monkeypatch,
):
    from research_harness._selfdev.golden_workflows import (
        build_golden_workflow_contract,
    )

    _install_golden_backend(monkeypatch)
    topic_id = _seed_topic(db, "golden-evidence")
    paper_id = _seed_topic_paper(db, topic_id)
    service = ResearchService(db=db)

    service.invoke("orchestrator_resume", {"topic_id": topic_id})
    claims = service.invoke(
        "claim_extract",
        {"topic_id": topic_id, "paper_ids": [paper_id], "focus": "workflow"},
    )
    gaps = service.invoke("gap_detect", {"topic_id": topic_id, "focus": "workflow"})
    baselines = service.invoke(
        "baseline_identify",
        {"topic_id": topic_id, "focus": "workflow"},
    )
    draft = service.invoke(
        "section_draft",
        {
            "topic_id": topic_id,
            "section": "related_work",
            "evidence_ids": ["claim:claim-golden-1", "gap:gap-golden-1"],
            # All sections are gated now; supply a passing plan (consumed and
            # stripped by the gate before the primitive runs).
            "paper_plan": {
                "manuscript_logic_gate_report": {
                    "schema_version": "rh.manuscript.logic_gate_report.v1",
                    "status": "pass",
                    "blockers": [],
                },
                "fine_logic_audit_report": {
                    "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
                    "status": "pass",
                    "blockers": [],
                },
            },
        },
    )
    draft_artifact = service.invoke(
        "orchestrator_record_artifact",
        {
            "topic_id": topic_id,
            "stage": "write",
            "artifact_type": "section_draft",
            "title": "Golden related work",
            "payload": {
                "claim_artifacts": list(claims.artifacts),
                "gap_artifacts": list(gaps.artifacts),
                "baseline_summary": baselines.summary,
                "draft_artifacts": list(draft.artifacts),
            },
        },
    )

    contract = build_golden_workflow_contract(
        db=db,
        workflow_name="evidence_to_draft",
        topic_id=topic_id,
        service_results=[claims, gaps, baselines, draft, draft_artifact],
    )

    assert contract.status == "success"
    assert contract.paper_ids == (paper_id,)
    assert contract.primitive_commands == (
        "claim_extract",
        "gap_detect",
        "baseline_identify",
        "section_draft",
    )
    assert contract.provenance_primitives == (
        "claim_extract",
        "gap_detect",
        "baseline_identify",
        "section_draft",
    )
    assert "claim:claim-golden-1" in contract.artifact_refs
    assert "gap:gap-golden-1" in contract.artifact_refs
    assert "draft:related_work" in contract.artifact_refs
    assert any(ref.endswith(":section_draft") for ref in contract.artifact_refs)
    assert any(
        "paper_search targeting high-severity gaps" in action
        for action in contract.next_actions
    )
    assert any(
        "Record missing artifacts for init" in action
        for action in contract.next_actions
    )


def test_workflow_wrapper_fixture_defines_private_runtime_contracts():
    fixture = json.loads(WORKFLOW_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == "rh.workflow_wrappers.v1"
    assert fixture["public_surface"] == "none"
    assert fixture["boundaries"] == {
        "adds_public_tool": False,
        "adds_cli_command": False,
        "adds_http_route": False,
        "adds_python_facade_method": False,
        "uses_real_zotero": False,
        "uses_network": False,
        "uses_real_llm": False,
    }

    wrappers = {wrapper["id"]: wrapper for wrapper in fixture["wrappers"]}
    assert tuple(wrappers) == (
        "literature_search_ingest",
        "evidence_to_draft",
        "artifact_provenance_gate_audit",
    )

    for wrapper in wrappers.values():
        assert wrapper["entrypoint_type"] == "skill_runtime_orchestration"
        assert wrapper["adds_public_tool"] is False
        assert wrapper["uses_real_zotero"] is False
        assert wrapper["uses_network"] is False
        assert wrapper["uses_real_llm"] is False
        assert wrapper["composed_tools"]
        assert wrapper["requires_records"]["provenance"] is True
        assert wrapper["requires_records"]["artifact"] is True
        assert wrapper["requires_records"]["next_actions"] is True
        assert wrapper["failure_recovery"]["resume_from"] in {
            "service_next_actions",
            "orchestrator_gate",
        }
        assert wrapper["failure_recovery"]["record_handoff"] is True
        assert wrapper["fixture_only"] is True

    assert wrappers["literature_search_ingest"]["composed_tools"] == [
        "paper_search",
        "paper_ingest",
        "orchestrator_record_artifact",
        "orchestrator_gate_check",
    ]
    assert wrappers["evidence_to_draft"]["composed_tools"] == [
        "claim_extract",
        "gap_detect",
        "baseline_identify",
        "section_draft",
        "orchestrator_record_artifact",
    ]
    assert wrappers["artifact_provenance_gate_audit"]["composed_tools"] == [
        "consistency_check",
        "orchestrator_record_artifact",
        "orchestrator_gate_check",
    ]


def test_workflow_wrapper_contract_doc_matches_fixture_contracts():
    fixture = json.loads(WORKFLOW_FIXTURE.read_text(encoding="utf-8"))
    doc = WORKFLOW_CONTRACT_DOC.read_text(encoding="utf-8")

    for section in (
        "## No New Public Surface",
        "## Failure Recovery",
        "## Provenance And Artifact Rules",
        "## Wrapper Contracts",
    ):
        assert section in doc

    assert "MCP tools, CLI commands, HTTP routes, Python facade methods" in doc
    assert "does not call real Zotero, network providers, real LLMs, Cloud" in doc

    for wrapper in fixture["wrappers"]:
        assert f"### `{wrapper['id']}`" in doc
        assert wrapper["contract"] in doc
        for tool in wrapper["composed_tools"]:
            assert f"`{tool}`" in doc


def test_artifact_provenance_gate_audit_golden_workflow_reports_gate_evidence(
    db,
    monkeypatch,
):
    from research_harness._selfdev.golden_workflows import (
        build_golden_workflow_contract,
    )

    _install_golden_backend(monkeypatch)
    topic_id = _seed_topic(db, "golden-audit")
    _seed_topic_paper(db, topic_id)
    service = ResearchService(db=db)

    service.invoke("orchestrator_resume", {"topic_id": topic_id})
    consistency = service.invoke(
        "consistency_check",
        {"topic_id": topic_id, "sections": ["related_work", "method"]},
    )
    audit_artifact = service.invoke(
        "orchestrator_record_artifact",
        {
            "topic_id": topic_id,
            "stage": "analyze",
            "artifact_type": "workflow_audit",
            "title": "Golden audit",
            "payload": {
                "primitive": consistency.command,
                "sections_checked": consistency.output.sections_checked,
                "next_actions": list(consistency.next_actions),
            },
        },
    )
    gate = service.invoke("orchestrator_gate_check", {"topic_id": topic_id})

    contract = build_golden_workflow_contract(
        db=db,
        workflow_name="artifact_provenance_gate_audit",
        topic_id=topic_id,
        service_results=[consistency, audit_artifact, gate],
        require_gate=True,
    )

    assert contract.status == "success"
    assert contract.primitive_commands == ("consistency_check",)
    assert contract.provenance_primitives == ("consistency_check",)
    assert any(ref.endswith(":workflow_audit") for ref in contract.artifact_refs)
    assert contract.gate_decisions == ("needs_approval",)
    assert (
        "No issues found. Ready for formal_review or finalize" in contract.next_actions
    )
    assert any(
        "Record missing artifacts for init" in action
        for action in contract.next_actions
    )
