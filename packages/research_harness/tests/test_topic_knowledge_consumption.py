from __future__ import annotations

import dataclasses
from pathlib import Path

from research_harness.storage.db import Database


def _seed_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'consumption topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Consumption Paper', '10.test/consumption', '2501.02020',
                's2_consumption')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, evidence_spans_json)
        VALUES
            (1, 1, 1, 'Hybrid retrieval improves recall', 'Hybrid retrieval',
             'ORB', 'recall@20', 'paper retrieval', '+9', 'higher', 0.84,
             '[{"section":"results","text":"recall improves"}]')
        """
    )
    conn.commit()


def test_latest_topic_knowledge_snapshot_reads_only_current_active_snapshot(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )

    _seed_topic(conn)
    created = build_topic_knowledge_snapshot(db, topic_id=1)

    latest = get_latest_topic_knowledge_snapshot(db, topic_id=1)

    assert latest is not None
    assert latest.topic_id == 1
    assert latest.artifact_id == created.artifact_id
    assert latest.snapshot_id == created.snapshot_id
    assert latest.source_hash == created.source_hash
    assert latest.current_source_hash == created.source_hash
    assert latest.is_current is True
    assert latest.payload["next_actions"]
    assert (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE topic_id = 1 AND artifact_type = 'topic_knowledge_snapshot'
            """
        ).fetchone()[0]
        == 1
    )

    conn.execute(
        "UPDATE normalized_claims SET claim_text = 'Changed evidence claim' WHERE id = 1"
    )
    conn.commit()

    assert get_latest_topic_knowledge_snapshot(db, topic_id=1) is None
    outdated = get_latest_topic_knowledge_snapshot(
        db, topic_id=1, require_current=False
    )
    assert outdated is not None
    assert outdated.is_current is False
    assert outdated.current_source_hash != outdated.source_hash


def test_topic_knowledge_snapshot_status_summary_is_internal_and_read_only(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        summarize_topic_knowledge_snapshot,
    )

    assert summarize_topic_knowledge_snapshot(db, topic_id=1)["status"] == "missing"

    _seed_topic(conn)
    created = build_topic_knowledge_snapshot(db, topic_id=1)

    summary = summarize_topic_knowledge_snapshot(db, topic_id=1)

    assert summary == {
        "status": "current",
        "topic_id": 1,
        "artifact_id": created.artifact_id,
        "snapshot_id": created.snapshot_id,
        "source_hash": created.source_hash,
        "snapshot_version": created.snapshot_version,
        "coverage": created.payload["coverage"],
        "weak_spots": created.payload["weak_spots"],
        "next_actions": created.payload["next_actions"],
    }
    assert (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE topic_id = 1 AND artifact_type = 'topic_knowledge_snapshot'
            """
        ).fetchone()[0]
        == 1
    )


def test_render_topic_knowledge_evidence_map_markdown_uses_snapshot_payload(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
        render_topic_knowledge_evidence_map_markdown,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    latest = get_latest_topic_knowledge_snapshot(db, topic_id=1)

    assert latest is not None
    markdown = render_topic_knowledge_evidence_map_markdown(latest)

    assert markdown.startswith("# Topic Knowledge Evidence Map\n")
    assert f"- Source hash: `{latest.source_hash}`" in markdown
    assert "## Coverage" in markdown
    assert "- normalized_claims: 1" in markdown
    assert "## Claims" in markdown
    assert "- Hybrid retrieval improves recall" in markdown
    assert "## Next Actions" in markdown
    assert "- paper_summarize" in markdown


def test_export_topic_knowledge_evidence_map_writes_workspace_markdown(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        export_topic_knowledge_evidence_map_markdown,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    workspace = tmp_path / "workspace"

    result = export_topic_knowledge_evidence_map_markdown(
        db, topic_id=1, topic_workspace_path=workspace
    )

    assert result is not None
    assert result.path == workspace / "02-evidence-map" / "topic-knowledge-snapshot.md"
    assert result.path.read_text(encoding="utf-8") == result.markdown
    assert "Hybrid retrieval improves recall" in result.markdown


def test_export_topic_knowledge_evidence_map_constrains_filename_to_workspace(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        export_topic_knowledge_evidence_map_markdown,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    workspace = tmp_path / "workspace"

    result = export_topic_knowledge_evidence_map_markdown(
        db,
        topic_id=1,
        topic_workspace_path=workspace,
        filename="../outside.md",
    )

    assert result is not None
    assert result.path == workspace / "02-evidence-map" / "outside.md"
    assert result.path.is_file()
    assert not (workspace / "outside.md").exists()


def test_topic_knowledge_readiness_report_aggregates_private_wiki_signals(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.topic_knowledge_readiness import (
        EXISTING_RH_ACTION_NAMES,
        build_topic_knowledge_readiness_report,
        topic_knowledge_readiness_report_to_dict,
    )
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    latest = get_latest_topic_knowledge_snapshot(db, topic_id=1)
    assert latest is not None
    latest = dataclasses.replace(
        latest,
        payload={
            **latest.payload,
            "next_actions": [*latest.payload["next_actions"], "research_wiki_publish"],
        },
    )
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    report = build_topic_knowledge_readiness_report(
        latest,
        export,
        search_queries=("hybrid recall",),
    )
    payload = topic_knowledge_readiness_report_to_dict(report)

    assert report.topic_id == 1
    assert report.status == "ready"
    assert report.coverage["normalized_claims"] == 1
    assert report.wiki["page_count"] == len(export.pages)
    assert report.wiki["searchable_page_count"] > 0
    assert report.validation["valid"] is True
    assert report.validation["issue_count"] == 0
    assert report.insights["count"] >= 0
    assert report.search["query_count"] == 1
    assert report.search["sample_queries"][0]["hit_count"] > 0
    assert set(report.next_actions) <= EXISTING_RH_ACTION_NAMES
    assert "research_wiki_publish" not in report.next_actions
    assert payload["status"] == "ready"
    assert payload["next_actions"] == list(report.next_actions)


def test_topic_knowledge_to_research_wiki_private_pipeline_end_to_end(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.research_wiki import (
        materialize_research_wiki_vault,
    )
    from research_harness.knowledge.research_wiki_bundle import (
        materialize_research_wiki_bundle,
    )
    from research_harness.knowledge.research_wiki_insights import (
        find_research_wiki_insights,
    )
    from research_harness.knowledge.research_wiki_search import (
        search_research_wiki_pages,
    )
    from research_harness.knowledge.research_wiki_validation import (
        validate_research_wiki_export,
    )
    from research_harness.knowledge.topic_knowledge_readiness import (
        EXISTING_RH_ACTION_NAMES,
        build_topic_knowledge_readiness_report,
    )
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )

    _seed_topic(conn)
    snapshot_result = build_topic_knowledge_snapshot(db, topic_id=1)
    snapshot = get_latest_topic_knowledge_snapshot(db, topic_id=1)
    assert snapshot is not None

    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )
    insight_report = find_research_wiki_insights(export)
    validation_report = validate_research_wiki_export(export)
    bundle = materialize_research_wiki_bundle(
        export,
        bundle_path=tmp_path / "bundle",
        insight_report=insight_report,
        validation_report=validation_report,
    )
    search_result = search_research_wiki_pages(export, "hybrid recall")
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        export,
        insight_report=insight_report,
        validation_report=validation_report,
        search_queries=("hybrid recall",),
    )

    assert snapshot_result.artifact_id == snapshot.artifact_id
    assert export.pages
    assert insight_report.topic_id == 1
    assert validation_report.valid is True
    assert bundle.manifest["validation"]["valid"] is True
    assert (tmp_path / "bundle" / "manifest.json").is_file()
    assert search_result.hits
    assert search_result.hits[0].evidence
    assert readiness.status == "ready"
    assert readiness.search["sample_queries"][0]["hit_count"] == len(
        search_result.hits[:5]
    )
    assert set(readiness.next_actions) <= EXISTING_RH_ACTION_NAMES


def test_knowledge_context_contract_preserves_evidence_and_marks_degraded(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.knowledge_consumption import (
        KnowledgeContextRequest,
        assemble_knowledge_context,
        knowledge_context_pack_to_dict,
    )
    from research_harness.knowledge.research_wiki import (
        ResearchWikiExport,
        materialize_research_wiki_vault,
    )
    from research_harness.knowledge.research_wiki_validation import (
        validate_research_wiki_export,
    )
    from research_harness.knowledge.topic_knowledge_readiness import (
        build_topic_knowledge_readiness_report,
    )
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    snapshot = get_latest_topic_knowledge_snapshot(db, topic_id=1)
    assert snapshot is not None
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )
    first_page = export.pages[0]
    broken_sources = [
        {**source, "source_hash": ""}
        for source in first_page.frontmatter.get("sources", [])
    ]
    broken_page = dataclasses.replace(
        first_page,
        frontmatter={**first_page.frontmatter, "sources": broken_sources},
        body=f"{first_page.body}\n\nSee [[missing/page.md]].\n",
    )
    broken_export = ResearchWikiExport(
        topic_id=export.topic_id,
        vault_path=export.vault_path,
        pages=(broken_page, *export.pages[1:]),
        graph=export.graph,
    )
    validation = validate_research_wiki_export(broken_export)
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        broken_export,
        validation_report=validation,
        search_queries=("hybrid recall",),
    )

    pack = assemble_knowledge_context(
        KnowledgeContextRequest(
            topic_id=1,
            query="hybrid recall",
            action_name="claim_extract",
            user_brief="Extract evidence-backed recall claims.",
            max_sections=2,
            max_evidence_anchors=3,
            max_chars_per_section=120,
        ),
        snapshot=snapshot,
        wiki_export=broken_export,
        readiness_report=readiness,
        validation_report=validation,
    )
    payload = knowledge_context_pack_to_dict(pack)

    assert pack.status == "degraded"
    assert pack.degraded is True
    assert "unresolved_wikilink" in pack.coverage_warnings
    assert "missing_evidence_anchor" in pack.coverage_warnings
    assert pack.artifact_refs == (
        f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}",
    )
    assert 0 < len(pack.sections) <= 2
    assert 0 < len(pack.evidence_anchors) <= 3
    assert all(
        anchor.snapshot_artifact_id == snapshot.artifact_id
        for anchor in pack.evidence_anchors
    )
    assert all(
        section.snapshot_artifact_id == snapshot.artifact_id
        for section in pack.sections
    )
    assert payload["status"] == "degraded"
    assert payload["evidence_anchors"][0]["source_hash"]


def test_knowledge_guided_planner_and_runspec_bridge_are_private_and_bounded(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.knowledge_consumption import (
        KnowledgeContextRequest,
        build_knowledge_execution_plan,
        knowledge_execution_plan_to_runspec,
        plan_knowledge_action,
    )
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.topic_knowledge_readiness import (
        build_topic_knowledge_readiness_report,
    )
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    snapshot = get_latest_topic_knowledge_snapshot(db, topic_id=1)
    assert snapshot is not None
    snapshot = dataclasses.replace(
        snapshot,
        payload={
            **snapshot.payload,
            "next_actions": ["claim_extract", "paper_ingest"],
        },
    )
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        export,
        search_queries=("hybrid recall",),
    )
    request = KnowledgeContextRequest(
        topic_id=1,
        query="hybrid recall",
        action_name="",
        user_brief="Find whether hybrid retrieval improves recall.",
    )
    recommendation = plan_knowledge_action(
        request,
        snapshot=snapshot,
        wiki_export=export,
        readiness_report=readiness,
    )
    plan = build_knowledge_execution_plan(
        request,
        snapshot=snapshot,
        wiki_export=export,
        readiness_report=readiness,
        recommendation=recommendation,
    )
    runspec = knowledge_execution_plan_to_runspec(plan)

    assert recommendation.action_name == "claim_extract"
    assert recommendation.mode == "executable"
    assert recommendation.required_inputs["topic_id"] == 1
    assert recommendation.required_inputs["paper_ids"] == [1]
    assert "paper_ingest" not in plan.service_arguments
    assert plan.executable is True
    assert runspec.topic_id == 1
    assert runspec.task_type.value == "analysis"
    assert runspec.visible_inputs.artifact_refs == (
        f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}",
    )
    assert runspec.visible_inputs.literal_inputs["action_name"] == "claim_extract"
    assert runspec.visible_inputs.literal_inputs["service_arguments"]["paper_ids"] == [
        1
    ]
    assert runspec.forbidden_inputs == (
        "hidden_gold",
        "benchmark_reference",
        "unreviewed_private_notes",
    )

    advisory_snapshot = dataclasses.replace(
        snapshot,
        payload={**snapshot.payload, "next_actions": ["gap_detect"]},
    )
    advisory_readiness = build_topic_knowledge_readiness_report(
        advisory_snapshot,
        export,
        search_queries=("hybrid recall",),
    )
    advisory = plan_knowledge_action(
        request,
        snapshot=advisory_snapshot,
        wiki_export=export,
        readiness_report=advisory_readiness,
    )

    assert advisory.action_name == "gap_detect"
    assert advisory.mode == "advisory"
    assert advisory.blocked_reason == "action_gate_deferred"


def test_private_knowledge_execution_loop_invokes_one_service_action_and_evals(
    db: Database,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.knowledge.knowledge_consumption import (
        KnowledgeContextRequest,
        evaluate_knowledge_quality,
        run_private_knowledge_execution_loop,
    )
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.topic_knowledge_readiness import (
        build_topic_knowledge_readiness_report,
    )
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )

    class FakeService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def invoke(self, command_name: str, arguments: dict | None = None) -> dict:
            self.calls.append((command_name, dict(arguments or {})))
            return {
                "command": command_name,
                "status": "success",
                "summary": "fake service result",
                "output": {"claim_count": 1},
            }

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    snapshot = get_latest_topic_knowledge_snapshot(db, topic_id=1)
    assert snapshot is not None
    snapshot = dataclasses.replace(
        snapshot,
        payload={**snapshot.payload, "next_actions": ["claim_extract"]},
    )
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        export,
        search_queries=("hybrid recall",),
    )
    service = FakeService()

    report = run_private_knowledge_execution_loop(
        KnowledgeContextRequest(
            topic_id=1,
            query="hybrid recall",
            user_brief="Advance the seeded topic once.",
        ),
        snapshot=snapshot,
        wiki_export=export,
        readiness_report=readiness,
        service=service,
        refresh_readiness=lambda: readiness,
    )
    metrics = evaluate_knowledge_quality(
        report.context_pack,
        report.recommendation,
        expected_action="claim_extract",
        expected_pages=("findings/hybrid-retrieval-improves-recall.md",),
    )

    assert service.calls == [
        (
            "claim_extract",
            {
                "paper_ids": [1],
                "topic_id": 1,
                "focus": "hybrid recall",
            },
        )
    ]
    assert report.executed is True
    assert report.failure_mode == ""
    assert report.before_readiness["status"] == "ready"
    assert report.after_readiness["status"] == "ready"
    assert report.service_result["status"] == "success"
    assert metrics["action_recommendation_agreement"] == 1.0
    assert metrics["context_recall"] == 1.0
    assert metrics["tool_call_input_correctness"] == 1.0
    assert metrics["anchor_resolvability"] == 1.0


def test_private_knowledge_evaluation_corpus_covers_grounding_edges() -> None:
    from research_harness.knowledge.knowledge_evaluation import (
        build_private_knowledge_evaluation_corpus,
        evaluate_private_knowledge_corpus,
    )

    cases = build_private_knowledge_evaluation_corpus()
    outcomes = evaluate_private_knowledge_corpus(cases)
    by_name = {outcome.case_name: outcome for outcome in outcomes}

    assert tuple(case.name for case in cases) == (
        "evidence_rich",
        "missing_paper_card_or_summary",
        "contradiction_heavy",
        "weak_unresolved_wikilink",
        "stale_snapshot",
    )
    assert set(by_name) == {case.name for case in cases}
    assert by_name["evidence_rich"].metrics == {
        "anchor_resolvability": 1.0,
        "source_support_precision": 1.0,
        "context_recall": 1.0,
        "action_recommendation_agreement": 1.0,
        "stale_degraded_detection": 1.0,
        "tool_call_input_correctness": 1.0,
    }
    assert by_name["missing_paper_card_or_summary"].action_name == "paper_summarize"
    assert by_name["missing_paper_card_or_summary"].mode == "blocked"
    assert (
        by_name["missing_paper_card_or_summary"].blocked_reason
        == "missing_required_inputs"
    )
    assert (
        by_name["missing_paper_card_or_summary"].metrics["tool_call_input_correctness"]
        == 0.0
    )
    assert by_name["contradiction_heavy"].action_name == "consistency_check"
    assert by_name["contradiction_heavy"].required_inputs["sections"]
    assert (
        by_name["contradiction_heavy"].metrics["action_recommendation_agreement"] == 1.0
    )
    assert by_name["weak_unresolved_wikilink"].status == "degraded"
    assert (
        "unresolved_wikilink" in by_name["weak_unresolved_wikilink"].coverage_warnings
    )
    assert (
        by_name["weak_unresolved_wikilink"].metrics["source_support_precision"] == 0.5
    )
    assert (
        by_name["weak_unresolved_wikilink"].metrics["stale_degraded_detection"] == 1.0
    )
    assert by_name["stale_snapshot"].status == "degraded"
    assert "snapshot_stale" in by_name["stale_snapshot"].coverage_warnings
    assert by_name["stale_snapshot"].metrics["stale_degraded_detection"] == 1.0


def test_private_knowledge_loop_runs_through_research_service_and_refreshes_readiness(
    db: Database,
    conn,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.service.handlers as handlers_module
    from research_harness.knowledge.knowledge_consumption import (
        KnowledgeContextRequest,
        knowledge_execution_plan_to_runspec,
        run_private_knowledge_execution_loop,
    )
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.topic_knowledge_readiness import (
        build_topic_knowledge_readiness_report,
    )
    from research_harness.knowledge.topic_layer import (
        build_topic_knowledge_snapshot,
        get_latest_topic_knowledge_snapshot,
    )
    from research_harness.primitives.types import (
        Claim,
        ClaimExtractOutput,
        EvidenceSpan,
        PrimitiveResult,
    )
    from research_harness.service import ResearchService

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    snapshot = get_latest_topic_knowledge_snapshot(db, topic_id=1)
    assert snapshot is not None
    snapshot = dataclasses.replace(
        snapshot,
        payload={**snapshot.payload, "next_actions": ["claim_extract"]},
    )
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki-before",
    )
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        export,
        search_queries=("hybrid recall",),
    )
    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        service_conn = ctx.db.connect()
        try:
            service_conn.execute(
                """
                INSERT INTO normalized_claims
                    (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
                     value, direction, confidence, evidence_spans_json)
                VALUES
                    (2, 1, 1, 'Hybrid retrieval improves precision',
                     'Hybrid retrieval', 'ORB', 'precision@20',
                     'paper retrieval', '+4', 'higher', 0.77,
                     '[{"section":"results","text":"precision improves"}]')
                """
            )
            service_conn.commit()
        finally:
            service_conn.close()
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=ClaimExtractOutput(
                claims=[
                    Claim(
                        claim_id="claim_precision",
                        content="Hybrid retrieval improves precision",
                        paper_ids=[1],
                        evidence_type="result",
                        confidence=0.77,
                        source_section="results",
                        evidence_spans=[
                            EvidenceSpan(
                                paper_id=1,
                                section="results",
                                snippet="precision improves",
                            )
                        ],
                    )
                ],
                papers_processed=1,
            ),
            started_at="2026-06-09T03:45:00+00:00",
            finished_at="2026-06-09T03:45:01+00:00",
            backend="local-test",
            model_used="stub",
            cost_usd=0.0,
            prompt_tokens=0,
            completion_tokens=0,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    def refresh_readiness():
        build_topic_knowledge_snapshot(db, topic_id=1)
        refreshed = get_latest_topic_knowledge_snapshot(db, topic_id=1)
        assert refreshed is not None
        refreshed_export = materialize_research_wiki_vault(
            db,
            topic_id=1,
            vault_path=tmp_path / "wiki-after",
        )
        return build_topic_knowledge_readiness_report(
            refreshed,
            refreshed_export,
            search_queries=("hybrid precision",),
        )

    report = run_private_knowledge_execution_loop(
        KnowledgeContextRequest(
            topic_id=1,
            query="hybrid recall",
            user_brief="Advance this topic with one evidence-backed claim action.",
        ),
        snapshot=snapshot,
        wiki_export=export,
        readiness_report=readiness,
        service=ResearchService(db=db),
        refresh_readiness=refresh_readiness,
    )
    runspec = knowledge_execution_plan_to_runspec(report.execution_plan)

    assert calls == [
        (
            "claim_extract",
            {"paper_ids": [1], "topic_id": 1, "focus": "hybrid recall"},
        )
    ]
    assert report.executed is True
    assert report.failure_mode == ""
    assert report.before_readiness["coverage"]["normalized_claims"] == 1
    assert report.after_readiness["coverage"]["normalized_claims"] == 2
    assert report.service_result["command"] == "claim_extract"
    assert report.service_result["status"] == "success"
    assert report.service_result["output"]["claims"][0]["content"] == (
        "Hybrid retrieval improves precision"
    )
    assert runspec.visible_inputs.literal_inputs["action_name"] == "claim_extract"
    assert runspec.visible_inputs.literal_inputs["service_arguments"] == {
        "paper_ids": [1],
        "topic_id": 1,
        "focus": "hybrid recall",
    }
