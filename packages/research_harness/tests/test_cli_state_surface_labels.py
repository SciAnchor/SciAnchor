"""BUG-06: status commands must name the state surface they read.

RH exposes two run-progress state surfaces for a topic:

* ``orchestrator_run`` (authoritative) — the ``orchestrator_runs`` row read by
  ``rh orchestrator status``.
* ``local_auto_runner_checkpoint`` — the local checkpoint JSON read by
  ``rh paper-production status``.

They can disagree. Neither command used to say which one it read, which caused
a real misdiagnosis (topic 73: orchestrator at ``build``/``in_progress`` while
the stale checkpoint still said ``init``). These tests lock the labelling and
the divergence warning, and assert that labelling stays observability-only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from research_harness.cli import main


def _json_invoke(runner: CliRunner, args: list[str]) -> dict:
    result = runner.invoke(main, ["--json", *args])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, dict)
    return payload


def _seed_orchestrator_run(runner: CliRunner) -> None:
    topic = _json_invoke(
        runner,
        ["topic", "init", "surface-demo", "--description", "state surface fixture"],
    )
    assert topic["id"] == 1
    run = _json_invoke(runner, ["orchestrator", "init", "--topic", "surface-demo"])
    assert run["current_stage"] == "init"


def _start_paper_production(runner: CliRunner, state_dir: Path) -> dict:
    return _json_invoke(
        runner,
        [
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


def _force_orchestrator_stage(state_dir: Path, topic_id: int, stage: str) -> int:
    """Advance the DB run out from under the checkpoint (the topic-73 shape)."""
    conn = sqlite3.connect(state_dir / "pool.db")
    try:
        conn.execute(
            "UPDATE orchestrator_runs SET current_stage = ?, stage_status = ? "
            "WHERE topic_id = ?",
            (stage, "in_progress", topic_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM orchestrator_runs WHERE topic_id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


# --------------------------------------------------------------------------
# rh orchestrator status -> authoritative surface
# --------------------------------------------------------------------------


def test_orchestrator_status_json_names_authoritative_state_surface(runner) -> None:
    _seed_orchestrator_run(runner)

    status = _json_invoke(runner, ["orchestrator", "status", "--topic", "surface-demo"])

    assert status["state_surface"] == "orchestrator_run"
    assert status["authoritative_state_surface"] == "orchestrator_run"
    assert status["state_surface_authoritative"] is True
    assert status["state_surface_source"] == {
        "orchestrator_run_id": status["run"]["id"]
    }
    assert status["state_surface_divergence"] is None


def test_orchestrator_status_human_output_names_state_surface(runner) -> None:
    _seed_orchestrator_run(runner)

    result = runner.invoke(main, ["orchestrator", "status", "--topic", "surface-demo"])

    assert result.exit_code == 0, result.output
    assert "state_surface=orchestrator_run" in result.output
    assert "authoritative" in result.output
    assert "orchestrator_run_id=1" in result.output


# --------------------------------------------------------------------------
# rh paper-production status -> local checkpoint surface
# --------------------------------------------------------------------------


def test_paper_production_status_json_names_local_checkpoint_surface(
    runner, tmp_path
) -> None:
    state_dir = tmp_path / ".research-harness"
    _start_paper_production(runner, state_dir)

    status = _json_invoke(
        runner,
        ["paper-production", "status", "--topic", "1", "--state-dir", str(state_dir)],
    )

    assert status["state_surface"] == "local_auto_runner_checkpoint"
    assert status["authoritative_state_surface"] == "orchestrator_run"
    assert status["state_surface_authoritative"] is False
    checkpoint_path = status["state_surface_source"]["checkpoint_path"]
    assert checkpoint_path.endswith("auto_runner/checkpoints/topic_1.json")
    assert Path(checkpoint_path).is_file()


def test_paper_production_status_human_output_names_local_checkpoint_surface(
    runner, tmp_path
) -> None:
    state_dir = tmp_path / ".research-harness"
    _start_paper_production(runner, state_dir)

    result = runner.invoke(
        main,
        ["paper-production", "status", "--topic", "1", "--state-dir", str(state_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "state_surface=local_auto_runner_checkpoint" in result.output
    assert "topic_1.json" in result.output


def test_paper_production_status_reports_no_divergence_when_surfaces_agree(
    runner, tmp_path
) -> None:
    state_dir = tmp_path / ".research-harness"
    _start_paper_production(runner, state_dir)

    status = _json_invoke(
        runner,
        ["paper-production", "status", "--topic", "1", "--state-dir", str(state_dir)],
    )

    assert status["state_surface_divergence"] is None


# --------------------------------------------------------------------------
# divergence warning (the topic-73 misdiagnosis)
# --------------------------------------------------------------------------


def test_paper_production_status_json_flags_stale_checkpoint_divergence(
    runner, tmp_path
) -> None:
    state_dir = tmp_path / ".research-harness"
    _start_paper_production(runner, state_dir)
    run_id = _force_orchestrator_stage(state_dir, 1, "build")

    status = _json_invoke(
        runner,
        ["paper-production", "status", "--topic", "1", "--state-dir", str(state_dir)],
    )

    divergence = status["state_surface_divergence"]
    assert divergence["detected"] is True
    assert divergence["read_surface"] == "local_auto_runner_checkpoint"
    assert divergence["read_stage"] == "init"
    assert divergence["authoritative_surface"] == "orchestrator_run"
    assert divergence["authoritative_stage"] == "build"
    assert divergence["authoritative_stage_status"] == "in_progress"
    assert divergence["orchestrator_run_id"] == run_id
    assert divergence["checkpoint_path"].endswith("topic_1.json")
    assert "orchestrator_run" in divergence["message"]
    assert "authoritative" in divergence["message"]


def test_paper_production_status_human_output_warns_on_divergence(
    runner, tmp_path
) -> None:
    state_dir = tmp_path / ".research-harness"
    _start_paper_production(runner, state_dir)
    _force_orchestrator_stage(state_dir, 1, "build")

    result = runner.invoke(
        main,
        ["paper-production", "status", "--topic", "1", "--state-dir", str(state_dir)],
    )

    assert result.exit_code == 0, result.output
    output = result.output
    assert "STATE SURFACE DIVERGENCE" in output
    # names both surfaces and both stages
    assert "local_auto_runner_checkpoint" in output
    assert "orchestrator_run" in output
    assert "init" in output
    assert "build" in output
    # states which surface wins
    assert "authoritative" in output


def test_status_labelling_does_not_mutate_either_state_surface(
    runner, tmp_path
) -> None:
    state_dir = tmp_path / ".research-harness"
    _start_paper_production(runner, state_dir)
    _force_orchestrator_stage(state_dir, 1, "build")
    checkpoint = state_dir / "auto_runner" / "checkpoints" / "topic_1.json"
    before_checkpoint = checkpoint.read_text(encoding="utf-8")

    _json_invoke(
        runner,
        ["paper-production", "status", "--topic", "1", "--state-dir", str(state_dir)],
    )

    conn = sqlite3.connect(state_dir / "pool.db")
    try:
        row = conn.execute(
            "SELECT current_stage, stage_status FROM orchestrator_runs "
            "WHERE topic_id = 1"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("build", "in_progress")
    assert checkpoint.read_text(encoding="utf-8") == before_checkpoint
