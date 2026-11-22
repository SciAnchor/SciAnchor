"""Tests for figure-fallback, experiment-evidence, venue-template, and
content-metric invariants.

The dream content-floor gates were retired with the dream protocol in the base
edition; the fail-closed replacement is covered in
test_dream_firewall.py.
"""

from __future__ import annotations

from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.orchestrator.invariants import InvariantChecker


def _create_topic(db, name: str) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (name, "topic for content completeness tests", "CCF-A"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_figure_provider_failure_without_asset_is_blocked(db):
    topic_id = _create_topic(db, "figure-fallback-topic")
    plan = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={
            "mode": "dream/advisor_ideal",
            "architecture_figure": {
                "generation_status": "ILLUSTRATION_PROVIDER_FAILED",
                "output_path": None,
            },
        },
    )

    violations = InvariantChecker(db).check_figure_provider_fallback(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "figure_fallback_policy"
    assert violations[0].artifact_id == plan.id
    assert violations[0].severity == "high"


def test_figure_provider_failure_with_local_fallback_passes(db):
    topic_id = _create_topic(db, "figure-fallback-ok-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={
            "architecture_figure": {
                "generation_status": "ILLUSTRATION_PENDING",
                "fallback_asset_path": "figures/arch_local.pdf",
            },
        },
    )

    violations = InvariantChecker(db).check_figure_provider_fallback(topic_id, "write")

    assert violations == []


def test_completed_status_with_fallback_stage_is_blocked(db):
    topic_id = _create_topic(db, "figure-fallback-status-conflict-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={
            "architecture_figure": {
                "illustration_required": True,
                "generation_status": "provider_completed",
                "provider_route": "gpt_image",
                "fallback": True,
                "selected_stage_key": "target_diagram_desc0_base64_jpg",
                "output_path": "figures/fig1.png",
            },
        },
    )

    violations = InvariantChecker(db).check_figure_provider_fallback(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].metadata["status"] == "provider_completed"
    assert violations[0].metadata["fallback"] is True


def test_experiment_result_without_logs_or_dream_declaration_is_blocked(db):
    topic_id = _create_topic(db, "experiment-evidence-topic")
    result = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_result",
        title="Experiment Result",
        payload={
            "mode": "main",
            "result_status": "completed",
            "observed_experiment_logs": [],
            "metrics": {"f1": 0.5},
        },
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert any(
        violation.check == "experiment_execution_evidence"
        and violation.artifact_id == result.id
        for violation in violations
    )


def test_dream_experiment_result_requires_target_values(db):
    topic_id = _create_topic(db, "experiment-dream-target-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_result",
        title="Experiment Result",
        payload={
            "mode": "dream/advisor_ideal",
            "result_status": "target_results_pending_validation",
            "observed_experiment_logs": [],
            "metrics": {},
            "expected_proposed_results": [],
        },
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert [v.check for v in violations] == ["experiment_execution_evidence"]


def test_target_pack_without_observed_logs_is_refused(db):
    topic_id = _create_topic(db, "experiment-target-pack-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_result",
        title="Experiment Result",
        payload={
            "mode": "dream/advisor_ideal",
            "result_status": "target_results_pending_validation",
            "observed_experiment_logs": [],
            "metrics": {},
            "expected_proposed_results": [
                {"method": "Ours", "metric": "f1", "target_value": "0.78"}
            ],
        },
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert [v.check for v in violations] == ["experiment_execution_evidence"]
    assert "no observed experiment logs" in violations[0].message


def test_experiment_result_with_incomplete_ablation_contract_is_blocked(db):
    topic_id = _create_topic(db, "experiment-ablation-coverage-topic")
    result = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_result",
        title="Experiment Result",
        payload={
            "result_status": "observed",
            "canonical_components": ["retriever", "reranker"],
            "ablation_components": ["retriever"],
            "repeats": 3,
            "variance_estimates": [0.02],
            "acceptance_criteria": ["recall improves by at least 0.5%"],
            "evidence_kind": "final",
        },
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert len(violations) == 1
    assert violations[0].check == "ablation_coverage_and_variance"
    assert violations[0].artifact_id == result.id
    assert violations[0].metadata["missing_components"] == ["reranker"]


def test_experiment_result_with_complete_ablation_contract_passes(db):
    topic_id = _create_topic(db, "experiment-ablation-coverage-ok-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_result",
        title="Experiment Result",
        payload={
            "result_status": "observed",
            "canonical_components": ["retriever", "reranker"],
            "ablation_components": ["retriever", "reranker"],
            "repeats": 3,
            "variance_estimates": [0.02, 0.03],
            "acceptance_criteria": ["recall improves by at least 0.5%"],
            "evidence_kind": "final",
        },
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert violations == []


def test_experiment_result_memory_contract_without_observed_outcome_is_blocked(db):
    topic_id = _create_topic(db, "experiment-ablation-memory-missing-outcome")
    result = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_result",
        title="Experiment Result",
        payload={
            "result_status": "observed",
            "canonical_components": ["retriever"],
            "ablation_components": ["retriever"],
            "repeats": 3,
            "variance_estimates": [0.0001],
            "acceptance_criteria": [],
            "evidence_kind": "final",
            "component_provenance": [
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ],
            "metric_direction": "maximize",
            "ablation_outcomes": [],
        },
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert len(violations) == 1
    assert violations[0].artifact_id == result.id
    assert violations[0].metadata["blockers"] == ["invalid_ablation_memory"]


def test_planned_only_experiment_code_in_main_mode_is_blocked(db):
    topic_id = _create_topic(db, "experiment-planned-code-topic")
    code = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="experiment",
        artifact_type="experiment_code",
        title="Experiment Code",
        payload={"mode": "main", "status": "planned_code_not_executed"},
    )

    violations = InvariantChecker(db).check_experiment_execution_evidence(
        topic_id, "experiment"
    )

    assert any(
        violation.check == "experiment_execution_evidence"
        and violation.artifact_id == code.id
        for violation in violations
    )


PENDING_FIGURE_PLAN_PAYLOAD = {
    "figures": [
        {
            "figure_id": "F1",
            "generation_status": "ILLUSTRATION_PROVIDER_PENDING_FOR_GENERATION",
            "fallback_asset_path": "figs/f1.pdf",
        }
    ]
}


def test_pending_marker_with_ready_provider_is_blocked(db, monkeypatch):
    from research_harness.orchestrator import invariants as invariants_module

    monkeypatch.setattr(
        invariants_module, "_illustration_generation_ready", lambda: True
    )
    topic_id = _create_topic(db, "pending-ready-provider-topic")
    plan = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure plan",
        payload=PENDING_FIGURE_PLAN_PAYLOAD,
    )

    violations = InvariantChecker(db).check_figure_provider_pending_readiness(
        topic_id, "write"
    )

    assert violations
    assert all(
        violation.check == "figure_provider_pending_with_ready_provider"
        for violation in violations
    )
    assert all(violation.severity == "high" for violation in violations)
    assert any(violation.artifact_id == plan.id for violation in violations)


def test_pending_marker_without_ready_provider_stays_acceptable(db, monkeypatch):
    from research_harness.orchestrator import invariants as invariants_module

    monkeypatch.setattr(
        invariants_module, "_illustration_generation_ready", lambda: False
    )
    topic_id = _create_topic(db, "pending-no-provider-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure plan",
        payload=PENDING_FIGURE_PLAN_PAYLOAD,
    )

    violations = InvariantChecker(db).check_figure_provider_pending_readiness(
        topic_id, "write"
    )

    assert violations == []


def test_pending_marker_in_notes_list_is_detected(db, monkeypatch):
    """Markers inside list-of-string fields (e.g. notes) must also count."""
    from research_harness.orchestrator import invariants as invariants_module

    monkeypatch.setattr(
        invariants_module, "_illustration_generation_ready", lambda: True
    )
    topic_id = _create_topic(db, "pending-notes-topic")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle_quality_report",
        title="QA report",
        payload={
            "report": {
                "notes": ["Architecture figure route: ILLUSTRATION_PENDING fallback."]
            }
        },
    )

    violations = InvariantChecker(db).check_figure_provider_pending_readiness(
        topic_id, "write"
    )

    assert len(violations) == 1


def _insert_run_with_mode(db, topic_id: int, mode: str) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) "
            "VALUES (?, ?, 'stub', 'stub')",
            (topic_id, topic_id),
        )
        conn.execute(
            "INSERT INTO orchestrator_runs "
            "(project_id, topic_id, mode, current_stage, stage_status, gate_status) "
            "VALUES (?, ?, ?, 'write', 'in_progress', 'not_evaluated')",
            (topic_id, topic_id, mode),
        )
        conn.commit()
    finally:
        conn.close()


def test_demo_scoped_artifact_blocks_strict_run_gate(db):
    topic_id = _create_topic(db, "demo-scope-strict-topic")
    _insert_run_with_mode(db, topic_id, "strict")
    bundle = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Demo final PDF bundle",
        payload={
            "readiness_scope": "demo_pdf_smoke",
            "evidence_boundary": "demo_limited_seed_pool",
        },
    )

    violations = InvariantChecker(db).check_demo_scope_boundary(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "demo_scope_boundary"
    assert violations[0].severity == "high"
    assert violations[0].artifact_id == bundle.id


def test_demo_scoped_artifact_allowed_inside_demo_run(db):
    topic_id = _create_topic(db, "demo-scope-demo-topic")
    _insert_run_with_mode(db, topic_id, "demo")
    ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Demo final PDF bundle",
        payload={"readiness_scope": "demo_pdf_smoke"},
    )

    violations = InvariantChecker(db).check_demo_scope_boundary(topic_id, "write")

    assert violations == []


def test_tex_figure_count_mixed_sources():
    from research_harness.orchestrator.invariants import _tex_figure_count

    tex = "\n".join(
        [
            # One figure env with two subfigure graphics counts once.
            r"\begin{figure}",
            r"\includegraphics{a.pdf}\includegraphics{b.pdf}",
            r"\end{figure}",
            # A TikZ figure env counts once.
            r"\begin{figure*}\begin{tikzpicture}x\end{tikzpicture}\end{figure*}",
            # A standalone graphic outside any figure env counts once.
            r"\includegraphics{inline.pdf}",
            # A caption-only placeholder env counts zero.
            r"\begin{figure}\fbox{placeholder}\end{figure}",
        ]
    )

    assert _tex_figure_count(tex) == 3


# ---------------------------------------------------------------------------
# Narrative figure cross-reference measurement.
#
# 2026-08-08 postmortem: a manuscript carried six \label{fig:...} declarations
# and ZERO \ref{fig:...} citations in the body, so the prose never pointed at
# any figure. The build report only counted graphic assets, so "6" was read as
# "six figures are referenced" — false and misleading. These are PURE metrics:
# they add no invariant, no threshold, and no pass/fail decision.
# ---------------------------------------------------------------------------

SIX_FIGURES_ZERO_NARRATIVE_REFS_TEX = "\n".join(
    [r"\documentclass{article}", r"\begin{document}"]
    + [
        "\n".join(
            [
                r"\begin{figure}",
                rf"\includegraphics{{fig{index}.pdf}}",
                rf"\caption{{Panel {index}.}}",
                rf"\label{{fig:panel{index}}}",
                r"\end{figure}",
            ]
        )
        for index in range(1, 7)
    ]
    + [
        r"\section{Results}",
        r"The method improves accuracy across every split.",
        r"\end{document}",
    ]
)


def test_content_metrics_expose_zero_narrative_refs_for_six_orphan_figures():
    """The real postmortem case: six figure labels, zero prose references."""
    from research_harness.orchestrator.invariants import _tex_content_metrics

    metrics = _tex_content_metrics(SIX_FIGURES_ZERO_NARRATIVE_REFS_TEX)

    assert metrics["figure_count"] == 6
    assert metrics["figure_label_count"] == 6
    assert metrics["figure_narrative_reference_count"] == 0
    assert metrics["unreferenced_figure_labels"] == [
        "fig:panel1",
        "fig:panel2",
        "fig:panel3",
        "fig:panel4",
        "fig:panel5",
        "fig:panel6",
    ]


def test_figure_count_key_still_measures_assets_not_references():
    """figure_count semantics are unchanged: it counts graphic assets."""
    from research_harness.orchestrator.invariants import (
        _tex_content_metrics,
        _tex_figure_count,
    )

    tex = SIX_FIGURES_ZERO_NARRATIVE_REFS_TEX

    assert _tex_content_metrics(tex)["figure_count"] == _tex_figure_count(tex) == 6


def test_refs_inside_figure_environments_are_not_narrative_references():
    """A \\ref living inside the float itself is markup, not prose narration."""
    from research_harness.orchestrator.invariants import _tex_content_metrics

    tex = "\n".join(
        [
            r"\begin{figure}",
            r"\includegraphics{a.pdf}",
            r"\caption{Panel A, to be compared with \ref{fig:beta}.}",
            r"\label{fig:alpha}",
            r"\end{figure}",
            r"\begin{figure*}",
            r"\includegraphics{b.pdf}",
            r"\caption{Panel B, see \autoref{fig:alpha}.}",
            r"\label{fig:beta}",
            r"\end{figure*}",
            r"\section{Results}",
            r"Accuracy improves on every split.",
        ]
    )

    metrics = _tex_content_metrics(tex)

    assert metrics["figure_label_count"] == 2
    assert metrics["figure_narrative_reference_count"] == 0
    assert metrics["unreferenced_figure_labels"] == ["fig:alpha", "fig:beta"]


def test_repeated_narrative_refs_to_one_label_count_once():
    """Distinct labels are measured, not reference occurrences."""
    from research_harness.orchestrator.invariants import _tex_content_metrics

    tex = "\n".join(
        [
            r"\begin{figure}\includegraphics{a.pdf}\label{fig:alpha}\end{figure}",
            r"\begin{figure}\includegraphics{b.pdf}\label{fig:beta}\end{figure}",
            r"\section{Results}",
            r"As \ref{fig:alpha} shows, and again in \autoref{fig:alpha},",
            r"the trend holds; \Cref{ fig:alpha } summarizes it.",
        ]
    )

    metrics = _tex_content_metrics(tex)

    assert metrics["figure_label_count"] == 2
    assert metrics["figure_narrative_reference_count"] == 1
    assert metrics["unreferenced_figure_labels"] == ["fig:beta"]


def test_cref_multi_key_form_marks_each_listed_label_referenced():
    """\\cref{fig:a,fig:b} narrates two figures, not one."""
    from research_harness.orchestrator.invariants import _tex_content_metrics

    tex = "\n".join(
        [
            r"\begin{figure}\includegraphics{a.pdf}\label{fig:a}\end{figure}",
            r"\begin{figure}\includegraphics{b.pdf}\label{fig:b}\end{figure}",
            r"\begin{figure}\includegraphics{c.pdf}\label{fig:c}\end{figure}",
            r"\section{Results}",
            r"See \cref{fig:a,fig:b} for the ablation.",
        ]
    )

    metrics = _tex_content_metrics(tex)

    assert metrics["figure_label_count"] == 3
    assert metrics["figure_narrative_reference_count"] == 2
    assert metrics["unreferenced_figure_labels"] == ["fig:c"]


def test_starred_and_spaced_reference_macros_are_measured():
    """Starred variants and whitespace padding still count as narration."""
    from research_harness.orchestrator.invariants import _tex_content_metrics

    tex = "\n".join(
        [
            r"\begin{figure}\includegraphics{a.pdf}\label{ fig:a }\end{figure}",
            r"\begin{figure}\includegraphics{b.pdf}\label{fig:b}\end{figure}",
            r"\section{Results}",
            r"See \ref* {fig:a} and \Cref*{ fig:b }.",
        ]
    )

    metrics = _tex_content_metrics(tex)

    assert metrics["figure_label_count"] == 2
    assert metrics["figure_narrative_reference_count"] == 2
    assert metrics["unreferenced_figure_labels"] == []


def test_document_without_figures_reports_zero_reference_metrics():
    """Non-figure cross-references must never inflate the figure metrics."""
    from research_harness.orchestrator.invariants import _tex_content_metrics

    tex = "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            r"\section{Method}\label{sec:method}",
            r"We describe the approach in \cref{sec:method} and",
            r"restate it in \autoref{tab:main} and \ref{eq:loss}.",
            r"\end{document}",
        ]
    )

    metrics = _tex_content_metrics(tex)

    assert metrics["figure_count"] == 0
    assert metrics["figure_label_count"] == 0
    assert metrics["figure_narrative_reference_count"] == 0
    assert metrics["unreferenced_figure_labels"] == []


def _create_topic_with_venue(db, name: str, venue: str) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (name, "topic for venue template tests", venue),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _record_plain_bundle(db, topic_id: int, tex_path):
    return ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"files": {"tex": str(tex_path)}},
    )


AAAI_A4_ARTICLE_TEX = (
    "\\documentclass[11pt,a4paper]{article}\\begin{document}"
    "\\section{Method}x\\end{document}"
)
AAAI_DRAFT_TEMPLATE_TEX = (
    "\\documentclass[letterpaper]{article}"
    "\\usepackage[letterpaper,top=0.75in]{geometry}"
    "\\begin{document}\\twocolumn[x]\\section{Method}x\\end{document}"
)


def test_aaai_bundle_on_a4_article_is_blocked_at_write_gate(db, tmp_path):
    topic_id = _create_topic_with_venue(db, "aaai-a4-topic", "AAAI 2026")
    tex = tmp_path / "paper.tex"
    tex.write_text(AAAI_A4_ARTICLE_TEX, encoding="utf-8")
    bundle = _record_plain_bundle(db, topic_id, tex)

    violations = InvariantChecker(db).check_venue_template_compliance(topic_id, "write")

    assert violations
    assert all(v.check == "venue_template_compliance" for v in violations)
    assert all(v.artifact_id == bundle.id for v in violations)


def test_aaai_bundle_letterpaper_two_column_passes(db, tmp_path):
    topic_id = _create_topic_with_venue(db, "aaai-draft-topic", "AAAI 2026")
    tex = tmp_path / "paper.tex"
    tex.write_text(AAAI_DRAFT_TEMPLATE_TEX, encoding="utf-8")
    _record_plain_bundle(db, topic_id, tex)

    violations = InvariantChecker(db).check_venue_template_compliance(topic_id, "write")

    assert violations == []


def test_aaai_bundle_with_official_class_passes(db, tmp_path):
    topic_id = _create_topic_with_venue(db, "aaai-official-topic", "AAAI-26")
    tex = tmp_path / "paper.tex"
    tex.write_text(
        "\\documentclass[letterpaper]{aaai25}\\begin{document}x\\end{document}",
        encoding="utf-8",
    )
    _record_plain_bundle(db, topic_id, tex)

    violations = InvariantChecker(db).check_venue_template_compliance(topic_id, "write")

    assert violations == []


def test_aaai_bundle_with_bundled_style_file_passes(db, tmp_path):
    topic_id = _create_topic_with_venue(db, "aaai-bundled-sty-topic", "AAAI 2026")
    tex = tmp_path / "paper.tex"
    tex.write_text(AAAI_A4_ARTICLE_TEX, encoding="utf-8")
    (tmp_path / "aaai26.sty").write_text("% official style", encoding="utf-8")
    _record_plain_bundle(db, topic_id, tex)

    violations = InvariantChecker(db).check_venue_template_compliance(topic_id, "write")

    assert violations == []


def test_non_aaai_venue_skips_template_gate(db, tmp_path):
    topic_id = _create_topic(db, "ccf-a-template-topic")
    tex = tmp_path / "paper.tex"
    tex.write_text(AAAI_A4_ARTICLE_TEX, encoding="utf-8")
    _record_plain_bundle(db, topic_id, tex)

    violations = InvariantChecker(db).check_venue_template_compliance(topic_id, "write")

    assert violations == []


def test_layout_overflow_findings_flag_wide_boxes():
    """A table spilling past the margin is a basic defect, not a nitpick."""
    from research_harness._workflow.orchestrator.invariants import (
        latex_layout_findings,
    )

    clean = "Overfull \\hbox (1.62pt too wide) in paragraph at lines 120--121"
    assert latex_layout_findings(clean) == []

    bad = (
        "Overfull \\hbox (174.43pt too wide) in paragraph at lines 68--79\n"
        "Overfull \\hbox (41.41pt too wide) in paragraph at lines 157--162\n"
        "Overfull \\hbox (1.60pt too wide) in paragraph at lines 3--4\n"
    )
    found = latex_layout_findings(bad)
    assert len(found) == 1
    assert found[0]["metadata"]["overfull_pt"][0] == 174.43
    assert "resizebox" in found[0]["message"]


def test_figure_route_findings_reject_adhoc_plotting():
    """Nature-grade output is a property of the renderer, not of intent."""
    from research_harness._workflow.orchestrator.invariants import (
        figure_route_findings,
    )

    ok = {
        "records": [
            {"figure_id": "f1", "figure_provider": "rh_experiment_figures_renderer"},
            {"figure_id": "f2", "figure_provider": "owner_supplied_placeholder"},
        ]
    }
    assert figure_route_findings(ok) == []

    bad = {
        "records": [
            {"figure_id": "f3", "figure_provider": "custom matplotlib script"},
            {"figure_id": "f4", "figure_provider": "hand-written pgfplots"},
        ]
    }
    found = figure_route_findings(bad)
    assert len(found) == 2
    assert all("not an approved rendering route" in f["message"] for f in found)
