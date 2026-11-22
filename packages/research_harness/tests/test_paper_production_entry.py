from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.auto_runner.checkpoint import load_checkpoint
from research_harness.auto_runner.paper_production_entry import (
    PAPER_PRODUCTION_STAGE_CROSSWALK,
    preflight_paper_production_topic,
    prepare_paper_production_entry,
    preview_paper_production_execution,
    preview_paper_production_execution_chain,
    run_paper_production_entry,
)
from research_harness.cli import main
from research_harness.orchestrator.service import OrchestratorService
from research_harness.storage.db import Database


def test_prepare_entry_creates_topic_run_and_checkpoint(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"

    result = prepare_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        mode="demo",
        execute=False,
    )

    assert result["schema_version"] == "rh.paper_production_entry.v1"
    assert result["action"] == "prepared"
    assert result["execution"]["will_execute"] is False
    assert result["topic"]["id"] == 1
    assert result["topic"]["created"] is True
    assert result["topic"]["target_venue"] == "NeurIPS 2026"
    assert result["run"]["current_stage"] == "init"
    assert result["run"]["sync_status"] == "RH_SYNCED"
    assert result["run"]["active_paper_plan_artifact_id"] == 1
    assert result["rh_state"] == {
        "topic_id": 1,
        "run_id": 1,
        "stage": "init",
        "artifact_ids": [1],
        "gate_result_ids": [],
        "sync_status": "RH_SYNCED",
        "next_action": "rh auto-runner start --topic-id 1 --mode demo",
    }
    assert result["checkpoint"]["path"].endswith(
        ".research-harness/auto_runner/checkpoints/topic_1.json"
    )
    assert result["checkpoint"]["exists"] is True
    assert result["runtime_context"]["schema_version"] == (
        "rh.paper_production_runtime_context.v1"
    )
    assert result["runtime_context"]["status"] == "ready_for_evidence_acquisition"
    assert result["stage_context"]["paper_plan_ready"] is False
    assert (
        result["stage_context"]["paper_production_readiness_report"]["next_stage"]
        == "PW02_EVIDENCE_ACQUISITION_AND_READING"
    )
    assert result["stage_context"]["paper_production_evidence_plan"]["status"] == (
        "ready"
    )
    assert result["stage_context"]["paper_plan_gate_profile"]["status"] == "blocked"
    assert result["stage_context"]["paper_production_closure_plan"]["status"] == (
        "blocked_until_paper_plan_ready"
    )
    checkpoint = load_checkpoint(base_dir / "auto_runner/checkpoints/topic_1.json")
    assert checkpoint is not None
    run_policy = checkpoint["paper_production_run_policy"]
    assert {
        key: run_policy[key]
        for key in (
            "schema_version",
            "autonomous_completion",
            "stop_on_gate_failure",
            "local_only",
            "external_actions",
        )
    } == {
        "schema_version": "rh.paper_production_run_policy.v2",
        "autonomous_completion": True,
        "stop_on_gate_failure": True,
        "local_only": False,
        "external_actions": [],
    }
    assert run_policy["mode"] == "demo"
    assert run_policy["evidence_boundary"] == "demo_limited_seed_pool"
    assert result["next_commands"] == ["rh auto-runner start --topic-id 1 --mode demo"]

    with db.connect() as conn:
        artifact = conn.execute(
            """
            SELECT artifact_type, stage, payload_json, metadata_json
            FROM project_artifacts
            WHERE id = ?
            """,
            (result["run"]["active_paper_plan_artifact_id"],),
        ).fetchone()
    assert artifact is not None
    assert artifact["artifact_type"] == "paper_plan"
    assert artifact["stage"] == "init"
    payload = json.loads(artifact["payload_json"])
    metadata = json.loads(artifact["metadata_json"])
    assert payload["schema_version"] == "rh.paper_plan.v1"
    assert payload["raw_user_task"] == (
        "Evidence-grounded AI agents for literature review"
    )
    assert payload["target_venue"] == "NeurIPS 2026"
    assert payload["sync_status"] == "RH_SYNCED"
    assert payload["validation_policy"]["human_eval_default"] is False
    assert payload["provenance_policy"]["chat_only_progress_allowed"] is False
    assert metadata["schema_version"] == "rh.paper_plan.v1"
    assert metadata["sync_status"] == "RH_SYNCED"


def test_prepare_entry_reuses_existing_topic_by_name(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()

    first = prepare_paper_production_entry(
        db=db,
        base_dir=tmp_path / "state",
        topic="AI agents for literature review",
        target_venue="ICLR",
    )
    second = prepare_paper_production_entry(
        db=db,
        base_dir=tmp_path / "state",
        topic="AI agents for literature review",
        target_venue="ICLR",
    )

    assert first["topic"]["id"] == second["topic"]["id"]
    assert second["topic"]["created"] is False


def test_paper_production_crosswalk_covers_pw01_to_pw10() -> None:
    expected_pw_stages = [
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

    assert [stage["pw_stage"] for stage in PAPER_PRODUCTION_STAGE_CROSSWALK] == (
        expected_pw_stages
    )
    assert {
        stage["orchestrator_stage"] for stage in PAPER_PRODUCTION_STAGE_CROSSWALK
    } <= {"init", "build", "analyze", "propose", "experiment", "write"}
    assert PAPER_PRODUCTION_STAGE_CROSSWALK[3]["orchestrator_stage"] == "experiment"
    assert PAPER_PRODUCTION_STAGE_CROSSWALK[4]["orchestrator_stage"] == "write"


def test_preflight_reports_workspace_checkpoint_and_gate_state(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"
    workspace = tmp_path / "rh-workspace" / "water" / "topic"
    duplicate = tmp_path / "rh-workspace" / "topic"
    workspace.mkdir(parents=True)
    duplicate.mkdir(parents=True)

    prepared = prepare_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        mode="demo",
    )

    result = preflight_paper_production_topic(
        db=db,
        topic=prepared["topic"]["id"],
        base_dir=base_dir,
        workspace_dir=workspace,
        duplicate_workspace_dir=duplicate,
    )

    assert result["schema_version"] == "rh.paper_production_preflight.v1"
    assert result["topic"]["id"] == prepared["topic"]["id"]
    assert result["workspace"]["path"] == str(workspace)
    assert result["workspace"]["exists"] is True
    assert result["workspace"]["duplicate_path"] == str(duplicate)
    assert result["workspace"]["duplicate_exists"] is True
    assert result["workspace"]["artifacts"] == {}
    assert result["checkpoint"]["exists"] is True
    assert result["checkpoint"]["parseable"] is True
    assert result["checkpoint"]["current_stage"] == "init"
    assert result["orchestrator"]["run"]["current_stage"] == "init"
    assert result["classification"] in {"missing_required_artifacts", "gate_blocked"}
    assert "duplicate_workspace_ambiguity" in result["warnings"]
    assert "external_actions" in result and result["external_actions"] == []


def test_preflight_warns_when_workspace_brief_is_not_synced_to_db(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    workspace = tmp_path / "rh-workspace" / "water" / "topic"
    brief = workspace / "00-brief" / "topic-brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("# Topic brief", encoding="utf-8")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            ("brief-not-synced", "brief-not-synced", "Venue"),
        )
        topic_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            "INSERT INTO orchestrator_runs (topic_id, mode, current_stage, stage_status) VALUES (?, ?, ?, ?)",
            (topic_id, "demo", "init", "in_progress"),
        )
        conn.commit()

    result = preflight_paper_production_topic(
        db=db,
        topic=topic_id,
        base_dir=tmp_path / ".research-harness",
        workspace_dir=workspace,
    )

    assert result["classification"] == "missing_required_artifacts"
    assert result["workspace"]["artifacts"]["topic_brief"] == str(brief)
    assert "missing_checkpoint" in result["blockers"]
    assert "workspace_topic_brief_not_synced_to_db" in result["warnings"]


def test_preflight_detects_checkpoint_db_stage_mismatch(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"
    prepared = prepare_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        mode="demo",
    )
    checkpoint_path = base_dir / "auto_runner/checkpoints/topic_1.json"
    checkpoint = load_checkpoint(checkpoint_path)
    assert checkpoint is not None
    checkpoint["current_stage"] = "build"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    result = preflight_paper_production_topic(
        db=db,
        topic=prepared["topic"]["id"],
        base_dir=base_dir,
    )

    assert result["classification"] == "db_checkpoint_mismatch"
    assert "db_checkpoint_mismatch" in result["blockers"]
    assert result["checkpoint"]["current_stage"] == "build"
    assert result["orchestrator"]["run"]["current_stage"] == "init"


def test_preflight_detects_checkpoint_db_mode_mismatch(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"
    prepared = prepare_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        mode="demo",
    )
    svc = OrchestratorService(db)
    svc.resume_run(prepared["topic"]["id"], mode="strict")

    result = preflight_paper_production_topic(
        db=db,
        topic=prepared["topic"]["id"],
        base_dir=base_dir,
    )

    assert result["classification"] == "db_checkpoint_mismatch"
    assert "db_checkpoint_mismatch" in result["blockers"]
    assert "checkpoint_run_mode_mismatch" in result["warnings"]
    assert result["checkpoint"]["mode"] == "demo"
    assert result["orchestrator"]["run"]["mode"] == "strict"


def test_paper_production_cli_preflight_outputs_diagnostics(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    workspace = tmp_path / "rh-workspace" / "water" / "topic"
    workspace.mkdir(parents=True)
    start = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "start",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert start.exit_code == 0, start.output

    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "preflight",
            "--topic",
            "1",
            "--state-dir",
            str(state_dir),
            "--workspace-dir",
            str(workspace),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "rh.paper_production_preflight.v1"
    assert payload["topic"]["id"] == 1
    assert payload["workspace"]["exists"] is True
    assert payload["checkpoint"]["parseable"] is True
    assert payload["orchestrator"]["stage"]["missing_artifacts"] == ["topic_brief"]
    assert payload["external_actions"] == []


def test_paper_production_cli_plan_outputs_runtime_shape(runner: CliRunner) -> None:
    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "plan",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "rh.paper_production_entry.v1"
    assert payload["action"] == "planned"
    assert payload["execution"]["will_execute"] is False
    assert payload["topic"]["id"] is None
    assert payload["rh_state"] == {
        "topic_id": None,
        "run_id": None,
        "stage": "init",
        "artifact_ids": [],
        "gate_result_ids": [],
        "sync_status": "RH_PENDING_TOPIC_ID",
        "next_action": (
            "rh paper-production start --topic "
            "'Evidence-grounded AI agents for literature review' "
            "--target-venue 'NeurIPS 2026'"
        ),
    }
    assert payload["runtime_context"]["status"] == "ready_for_evidence_acquisition"
    assert payload["stage_context"]["local_only"] is False
    assert payload["next_commands"] == [
        (
            "rh paper-production start --topic "
            "'Evidence-grounded AI agents for literature review' "
            "--target-venue 'NeurIPS 2026'"
        )
    ]


def test_paper_production_cli_start_prepares_checkpoint_without_running(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "start",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] == "prepared"
    assert payload["topic"]["id"] == 1
    assert payload["checkpoint"]["exists"] is True
    assert payload["checkpoint"]["path"].startswith(str(state_dir))
    assert payload["execution"] == {
        "will_execute": False,
        "reason": "start prepares local DB/run/checkpoint only",
    }


def test_paper_production_cli_plan_can_select_local_only_evidence(
    runner: CliRunner,
) -> None:
    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "plan",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--local-only",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    evidence_plan = payload["runtime_context"]["evidence_acquisition_plan"]
    assert evidence_plan["provider_mode"] == "local_only"
    assert evidence_plan["search_parameters"]["local_only"] is True
    assert payload["stage_context"]["local_only"] is True


def test_paper_production_cli_help_registered() -> None:
    result = CliRunner().invoke(main, ["paper-production", "start", "--help"])

    assert result.exit_code == 0, result.output
    assert "--topic" in result.output
    assert "--target-venue" in result.output
    assert "--mode" in result.output
    assert "--state-dir" in result.output


def test_paper_production_cli_preview_chain_help_registered() -> None:
    result = CliRunner().invoke(main, ["paper-production", "preview-chain", "--help"])

    assert result.exit_code == 0, result.output
    assert "--topic" in result.output
    assert "--target-venue" in result.output
    assert "--mode" in result.output
    assert "--state-dir" in result.output


def test_paper_production_cli_run_prepares_and_invokes_real_runner_dry_run(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "run",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "rh.paper_production_run.v1"
    assert payload["action"] == "dry_run"
    assert payload["prepared"]["topic"]["id"] == 1
    assert payload["runner"]["status"] == "dry_run"
    assert [stage["stage"] for stage in payload["runner"]["plan"]] == [
        "init",
        "build",
        "analyze",
        "propose",
        "experiment",
        "write",
    ]
    write_plan = payload["runner"]["plan"][-1]
    assert "publication_pack_backfill" in write_plan["tools"]
    assert "publication_run" in write_plan["tools"]
    assert payload["external_actions"] == []


def test_paper_production_cli_run_local_only_execute_stops_at_gate(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "run",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
            "--local-only",
            "--execute",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["action"] == "run"
    assert payload["prepared"]["stage_context"]["local_only"] is True
    assert payload["runner"]["status"] == "blocked"
    assert payload["runner"]["blocker_code"] == "paper_production_evidence_gate"
    assert payload["runner"]["current_stage"] == "init"
    assert "insufficient_seed_papers" in payload["runner"]["summary"]
    human_decision = payload["runner"]["human_decision"]
    assert human_decision["requested"] is True
    assert human_decision["reason_code"] == "insufficient_seed_papers"
    assert {option["action"] for option in human_decision["options"]} == {
        "broaden_search",
        "stop",
    }
    checkpoint = load_checkpoint(state_dir / "auto_runner/checkpoints/topic_1.json")
    assert checkpoint is not None
    assert checkpoint["human_decision"]["requested"] is True
    assert payload["external_actions"] == []


def test_paper_production_cli_decide_broaden_search_and_resume(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    run = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "run",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
            "--local-only",
            "--execute",
        ],
    )
    assert run.exit_code == 0, run.output

    status = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "status",
            "--topic",
            "1",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["human_decision"]["requested"] is True
    assert status_payload["next_commands"]

    pending_resume = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "resume",
            "--topic",
            "1",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert pending_resume.exit_code == 0, pending_resume.output
    pending_payload = json.loads(pending_resume.output)
    assert pending_payload["status"] == "paused"
    assert pending_payload["human_decision"]["requested"] is True

    decide = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "decide",
            "--topic",
            "1",
            "--action",
            "broaden_search",
            "--reasoning",
            "User approved expanded evidence acquisition.",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert decide.exit_code == 0, decide.output
    decision_payload = json.loads(decide.output)
    assert decision_payload["schema_version"] == "rh.paper_production_decision.v1"
    assert decision_payload["status"] == "accepted"
    assert decision_payload["choice"] == "broaden_search"

    checkpoint = load_checkpoint(state_dir / "auto_runner/checkpoints/topic_1.json")
    assert checkpoint is not None
    assert checkpoint["human_decision"]["requested"] is False
    assert checkpoint["human_decision"]["selected"] == "broaden_search"
    assert checkpoint["paper_production_run_policy"]["local_only"] is False
    assert checkpoint["stage_state"] == "pending"

    resumed = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "resume",
            "--topic",
            "1",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    resumed_payload = json.loads(resumed.output)
    assert resumed_payload["status"] in {"blocked", "paused", "error", "completed"}
    if resumed_payload["status"] == "blocked":
        assert resumed_payload.get("human_decision") is None


def test_paper_production_cli_decide_stop_marks_resume_stopped(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    run = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "run",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
            "--local-only",
            "--execute",
        ],
    )
    assert run.exit_code == 0, run.output

    decide = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "decide",
            "--topic",
            "1",
            "--action",
            "stop",
            "--reasoning",
            "User chose to stop.",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert decide.exit_code == 0, decide.output
    assert json.loads(decide.output)["status"] == "stopped"

    resumed = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "resume",
            "--topic",
            "1",
            "--state-dir",
            str(state_dir),
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    resumed_payload = json.loads(resumed.output)
    assert resumed_payload["status"] == "stopped"
    assert resumed_payload["human_decision"]["selected"] == "stop"


def test_run_entry_passes_prepared_db_to_real_runner(monkeypatch, tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"
    captured: dict[str, object] = {}

    def fake_run_topic(topic_id: int, **kwargs: object) -> dict[str, object]:
        captured["topic_id"] = topic_id
        captured["db"] = kwargs.get("db")
        captured["dry_run"] = kwargs.get("dry_run")
        return {
            "status": "dry_run",
            "current_stage": "init",
            "stages_completed": [],
            "plan": [],
            "summary": "captured",
        }

    monkeypatch.setattr(
        "research_harness.auto_runner.runner.run_topic",
        fake_run_topic,
    )

    result = run_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
    )

    assert result["schema_version"] == "rh.paper_production_run.v1"
    assert result["prepared"]["topic"]["id"] == 1
    assert captured == {"topic_id": 1, "db": db, "dry_run": True}


def test_paper_production_cli_text_output_names_next_command(runner: CliRunner) -> None:
    result = runner.invoke(
        main,
        [
            "paper-production",
            "plan",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Paper-production topic new planned at stage init." in result.output
    assert "Next: rh paper-production start" in result.output


def test_paper_production_cli_preview_chain_runs_fake_chain(
    runner: CliRunner,
    tmp_path,
) -> None:
    state_dir = tmp_path / ".research-harness"
    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "preview-chain",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(state_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == (
        "rh.paper_production_execution_chain_preview.v1"
    )
    assert payload["status"] == "complete"
    assert payload["stages"] == ["init", "build"]
    assert payload["topic"]["target_venue"] == "NeurIPS 2026"
    assert payload["checkpoint"]["path"].startswith(str(state_dir))
    assert payload["checkpoint"]["current_stage"] == "build"
    assert payload["control_artifacts"][0]["artifact_type"] == (
        "evidence_acquisition_control_preview"
    )
    assert payload["external_actions"] == []


def test_paper_production_cli_preview_chain_text_output_is_plain(
    runner: CliRunner,
    tmp_path,
) -> None:
    result = runner.invoke(
        main,
        [
            "paper-production",
            "preview-chain",
            "--topic",
            "Evidence-grounded AI agents for literature review",
            "--target-venue",
            "NeurIPS 2026",
            "--mode",
            "demo",
            "--state-dir",
            str(tmp_path / ".research-harness"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Paper-production fake preview complete for topic 1" in result.output
    assert "Stages: init -> build" in result.output
    assert "External actions: none" in result.output


def test_execution_preview_runs_prepared_checkpoint_with_fake_tools(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"
    prepared = prepare_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        mode="demo",
    )

    preview = preview_paper_production_execution(
        db=db,
        base_dir=base_dir,
        topic_id=prepared["topic"]["id"],
        mode="demo",
    )

    assert preview["schema_version"] == "rh.paper_production_execution_preview.v1"
    assert preview["status"] == "complete"
    assert preview["stage"] == "init"
    assert preview["external_actions"] == []
    assert preview["stage_result"]["status"] == "complete"
    assert preview["tool_preview"] == {
        "tool": "paper_production_preview",
        "success": True,
        "target_venue": "NeurIPS 2026",
        "paper_production_context_status": "ready_for_evidence_acquisition",
    }
    assert preview["trace_summary"]["step_count"] >= 4
    assert "paper_production_entry_prepared" in preview["trace_summary"]["events"]
    assert "stage_complete" in preview["trace_summary"]["events"]

    checkpoint = load_checkpoint(base_dir / "auto_runner/checkpoints/topic_1.json")
    assert checkpoint is not None
    assert checkpoint["stage_state"] == "complete"
    assert (
        checkpoint["stage_context"]["paper_production_runtime_context"]["status"]
        == "ready_for_evidence_acquisition"
    )


def test_execution_preview_reports_missing_checkpoint(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()

    preview = preview_paper_production_execution(
        db=db,
        base_dir=tmp_path / ".research-harness",
        topic_id=999,
    )

    assert preview["schema_version"] == "rh.paper_production_execution_preview.v1"
    assert preview["status"] == "blocked"
    assert preview["blockers"] == ["missing_checkpoint"]


def test_execution_chain_preview_runs_init_to_build_with_fake_tools(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()
    base_dir = tmp_path / ".research-harness"
    prepared = prepare_paper_production_entry(
        db=db,
        base_dir=base_dir,
        topic="Evidence-grounded AI agents for literature review",
        target_venue="NeurIPS 2026",
        mode="demo",
    )

    preview = preview_paper_production_execution_chain(
        db=db,
        base_dir=base_dir,
        topic_id=prepared["topic"]["id"],
        mode="demo",
        stages=("init", "build"),
    )

    assert preview["schema_version"] == (
        "rh.paper_production_execution_chain_preview.v1"
    )
    assert preview["status"] == "complete"
    assert preview["topic_id"] == 1
    assert preview["stages"] == ["init", "build"]
    assert preview["external_actions"] == []
    assert preview["blockers"] == []
    assert [stage["stage"] for stage in preview["stage_results"]] == ["init", "build"]
    assert all(stage["status"] == "complete" for stage in preview["stage_results"])
    assert [tool["stage"] for tool in preview["tool_previews"]] == ["init", "build"]
    assert preview["tool_previews"][1] == {
        "tool": "paper_production_preview",
        "stage": "build",
        "success": True,
        "target_venue": "NeurIPS 2026",
        "paper_production_context_status": "ready_for_evidence_acquisition",
        "control_artifact_type": "evidence_acquisition_control_preview",
        "next_control_action": "evidence_acquisition_fake_ready",
    }
    assert preview["checkpoint"]["current_stage"] == "build"
    assert preview["checkpoint"]["stage_state"] == "complete"
    assert preview["checkpoint"]["paper_production_context_status"] == (
        "ready_for_evidence_acquisition"
    )
    assert preview["control_artifacts"] == [
        {
            "schema_version": "rh.paper_production_control_artifact_preview.v1",
            "stage": "build",
            "artifact_type": "evidence_acquisition_control_preview",
            "status": "fake_ready",
            "target_venue": "NeurIPS 2026",
            "external_actions": [],
        }
    ]
    assert "paper_production_entry_prepared" in preview["trace_summary"]["events"]
    assert "stage_complete" in preview["trace_summary"]["events"]
    assert "paper_production_chain_stage_complete" in preview["trace_summary"]["events"]
    assert (
        "paper_production_chain_preview_complete" in preview["trace_summary"]["events"]
    )

    checkpoint = load_checkpoint(base_dir / "auto_runner/checkpoints/topic_1.json")
    assert checkpoint is not None
    assert checkpoint["current_stage"] == "build"
    assert checkpoint["stage_state"] == "complete"
    assert (
        checkpoint["stage_context"]["paper_production_runtime_context"]["status"]
        == "ready_for_evidence_acquisition"
    )
    assert checkpoint["stage_context"]["paper_production_control_artifacts"] == [
        {
            "schema_version": "rh.paper_production_control_artifact_preview.v1",
            "stage": "build",
            "artifact_type": "evidence_acquisition_control_preview",
            "status": "fake_ready",
            "target_venue": "NeurIPS 2026",
            "external_actions": [],
        }
    ]


def test_execution_chain_preview_reports_missing_checkpoint(tmp_path) -> None:
    db = Database(tmp_path / "paper-production-entry.db")
    db.migrate()

    preview = preview_paper_production_execution_chain(
        db=db,
        base_dir=tmp_path / ".research-harness",
        topic_id=999,
    )

    assert preview["schema_version"] == (
        "rh.paper_production_execution_chain_preview.v1"
    )
    assert preview["status"] == "blocked"
    assert preview["stage_results"] == []
    assert preview["tool_previews"] == []
    assert preview["control_artifacts"] == []
    assert preview["blockers"] == ["missing_checkpoint"]
    assert preview["external_actions"] == []


def test_paper_production_reset_run_help_exposes_options() -> None:
    result = CliRunner().invoke(main, ["paper-production", "reset-run", "--help"])

    assert result.exit_code == 0, result.output
    for fragment in ("--topic", "--stages", "--types", "--dry-run"):
        assert fragment in result.output


def _seed_reset_run_state(db_path) -> None:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO projects (topic_id, name) VALUES (1, 'reset-run-project')"
    )
    rows = [
        ("write", "draft_pack", "active", 4),
        ("write", "final_bundle", "active", 3),
        ("write", "gate_decision", "active", 2),
        ("write", "provenance_record", "active", 1),
        ("write", "draft_pack", "superseded", 3),
        ("analysis", "topic_knowledge_snapshot", "active", 40),
    ]
    conn.executemany(
        """
        INSERT INTO project_artifacts
            (project_id, topic_id, stage, artifact_type, status, version)
        VALUES (1, 1, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.execute(
        "INSERT INTO topic_summaries (topic_id, summary, paper_count)"
        " VALUES (1, 'stale broad-field overview', 0)"
    )
    conn.commit()
    conn.close()


def test_paper_production_reset_run_supersedes_content_and_clears_cache(
    runner: CliRunner, tmp_path
) -> None:
    import sqlite3

    assert runner.invoke(main, ["topic", "init", "reset-topic"]).exit_code == 0
    db_path = tmp_path / "cli.db"
    _seed_reset_run_state(db_path)

    dry = runner.invoke(
        main,
        ["--json", "paper-production", "reset-run", "--topic", "1", "--dry-run"],
    )
    assert dry.exit_code == 0, dry.output
    dry_payload = json.loads(dry.output)
    dry_types = {a["type"] for a in dry_payload["superseded"]}
    assert dry_types == {"draft_pack", "final_bundle", "topic_knowledge_snapshot"}
    assert dry_payload["dry_run"] is True

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    active_after_dry = conn.execute(
        "SELECT COUNT(*) AS n FROM project_artifacts WHERE status='active'"
    ).fetchone()["n"]
    assert active_after_dry == 5  # dry-run changes nothing

    result = runner.invoke(
        main, ["--json", "paper-production", "reset-run", "--topic", "1"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {a["type"] for a in payload["superseded"]} == dry_types
    assert payload["summary_cache_invalidated"] is True

    statuses = {
        (r["artifact_type"], r["version"]): r["status"]
        for r in conn.execute(
            "SELECT artifact_type, version, status FROM project_artifacts"
        )
    }
    assert statuses[("draft_pack", 4)] == "superseded"
    assert statuses[("final_bundle", 3)] == "superseded"
    assert statuses[("topic_knowledge_snapshot", 40)] == "superseded"
    # Decision history is never reset.
    assert statuses[("gate_decision", 2)] == "active"
    assert statuses[("provenance_record", 1)] == "active"
    cache_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM topic_summaries WHERE topic_id=1"
    ).fetchone()["n"]
    conn.close()
    assert cache_rows == 0


def test_paper_production_reset_run_types_override_protects_decisions(
    runner: CliRunner, tmp_path
) -> None:

    assert runner.invoke(main, ["topic", "init", "reset-topic-2"]).exit_code == 0
    _seed_reset_run_state(tmp_path / "cli.db")

    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "reset-run",
            "--topic",
            "1",
            "--types",
            "draft_pack,gate_decision",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # gate_decision is stripped from the override; only draft_pack resets.
    assert {a["type"] for a in payload["superseded"]} == {"draft_pack"}


def test_paper_production_commit_version_records_trio_and_rejects_stale(
    runner: CliRunner, tmp_path
) -> None:
    assert runner.invoke(main, ["topic", "init", "commit-topic"]).exit_code == 0

    tex = tmp_path / "main.tex"
    tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-1.5 fake")
    quality = tmp_path / "quality.json"
    quality.write_text('{"overfull_boxes": 0}')

    first = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "commit-version",
            "--topic",
            "1",
            "--tex",
            str(tex),
            "--pdf",
            str(pdf),
            "--quality-report",
            str(quality),
        ],
    )
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["success"] is True
    assert set(payload) >= {
        "tex_sha256",
        "pdf_sha256",
        "draft_pack",
        "final_bundle",
        "final_bundle_quality_report",
    }
    old_draft_id = payload["draft_pack"]["artifact_id"]

    second = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "commit-version",
            "--topic",
            "1",
            "--tex",
            str(tex),
        ],
    )
    assert second.exit_code == 0, second.output

    rejected = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "commit-version",
            "--topic",
            "1",
            "--tex",
            str(tex),
            "--depends-on",
            str(old_draft_id),
        ],
    )
    assert rejected.exit_code == 1
    rejected_payload = json.loads(rejected.output)
    assert rejected_payload["success"] is False
    assert rejected_payload["invalid_dependencies"][0]["artifact_id"] == old_draft_id
