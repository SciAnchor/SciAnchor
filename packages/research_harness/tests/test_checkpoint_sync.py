from __future__ import annotations

from threading import Event, Thread
from pathlib import Path

import pytest

from research_harness.api import ResearchAPI
from research_harness.auto_runner.checkpoint import (
    SCHEMA_VERSION,
    checkpoint_path,
    load_checkpoint,
    new_checkpoint,
    save_checkpoint,
)
from research_harness.auto_runner.runner import sync_topic_checkpoint
from research_harness.orchestrator import OrchestratorService
from research_harness.storage.db import Database


def _topic_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "pool.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (1, 'sync-topic', 'sync')"
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _checkpoint(state_dir: Path, *, mode: str = "explore") -> Path:
    path = checkpoint_path(state_dir, 1)
    save_checkpoint(path, new_checkpoint(1, mode=mode))
    return path


def test_sync_topic_checkpoint_reconciles_without_executing_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = _topic_db(tmp_path)
    service = OrchestratorService(db)
    service.init_run(1, mode="explore")
    service.resume_run(1, mode="explore", force_stage="build")
    state_dir = tmp_path / "state"
    path = _checkpoint(state_dir, mode="standard")

    def fail_if_executed(**_kwargs):
        raise AssertionError("sync-only operation must not execute a stage")

    monkeypatch.setattr(
        "research_harness.auto_runner.runner.execute_stage",
        fail_if_executed,
    )

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result == {
        "schema_version": "rh.paper_production_checkpoint_sync.v1",
        "status": "synced",
        "topic_id": 1,
        "changed": True,
        "before": {"stage": "init", "state": "pending", "mode": "standard"},
        "after": {"stage": "build", "state": "pending", "mode": "explore"},
        "checkpoint_path": str(path),
    }
    saved = load_checkpoint(path)
    assert saved is not None
    assert saved["current_stage"] == "build"
    assert saved["stage_state"] == "pending"
    assert saved["mode"] == "explore"
    assert saved["history"][-1]["event"] == "checkpoint_db_recovery"


def test_sync_topic_checkpoint_is_idempotent(tmp_path: Path) -> None:
    db = _topic_db(tmp_path)
    service = OrchestratorService(db)
    service.init_run(1, mode="explore")
    service.resume_run(1, mode="explore", force_stage="analyze")
    state_dir = tmp_path / "state"
    path = _checkpoint(state_dir)

    first = sync_topic_checkpoint(1, base_dir=state_dir, db=db)
    history_count = len((load_checkpoint(path) or {})["history"])
    second = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert first["status"] == "synced"
    assert second["status"] == "unchanged"
    assert second["changed"] is False
    assert second["before"] == second["after"]
    assert len((load_checkpoint(path) or {})["history"]) == history_count


def test_sync_topic_checkpoint_refuses_to_write_mid_stage_checkpoint(
    tmp_path: Path,
) -> None:
    db = _topic_db(tmp_path)
    OrchestratorService(db).init_run(1, mode="explore")
    state_dir = tmp_path / "state"
    path = checkpoint_path(state_dir, 1)
    checkpoint = new_checkpoint(1, mode="standard")
    checkpoint["stage_state"] = "running"
    save_checkpoint(path, checkpoint)
    before = path.read_bytes()
    active_tmp = path.parent / "active-save.tmp"
    active_tmp.write_text("in-flight checkpoint write", encoding="utf-8")

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result == {
        "schema_version": "rh.paper_production_checkpoint_sync.v1",
        "status": "error",
        "topic_id": 1,
        "changed": False,
        "error": "checkpoint_running",
        "checkpoint_path": str(path),
    }
    assert path.read_bytes() == before
    assert active_tmp.read_text(encoding="utf-8") == "in-flight checkpoint write"


def test_sync_topic_checkpoint_fails_closed_when_checkpoint_is_missing(
    tmp_path: Path,
) -> None:
    db = _topic_db(tmp_path)
    OrchestratorService(db).init_run(1, mode="explore")
    state_dir = tmp_path / "state"
    path = checkpoint_path(state_dir, 1)

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result == {
        "schema_version": "rh.paper_production_checkpoint_sync.v1",
        "status": "error",
        "topic_id": 1,
        "changed": False,
        "error": "checkpoint_not_found",
        "checkpoint_path": str(path),
    }
    assert not path.exists()


def test_sync_topic_checkpoint_rejects_wrong_topic_without_writing(
    tmp_path: Path,
) -> None:
    db = _topic_db(tmp_path)
    OrchestratorService(db).init_run(1, mode="explore")
    state_dir = tmp_path / "state"
    path = checkpoint_path(state_dir, 1)
    save_checkpoint(path, new_checkpoint(2, mode="explore"))
    before = path.read_bytes()

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result["status"] == "error"
    assert result["error"] == "checkpoint_topic_mismatch"
    assert result["changed"] is False
    assert path.read_bytes() == before


def test_sync_topic_checkpoint_rejects_wrong_schema_without_writing(
    tmp_path: Path,
) -> None:
    db = _topic_db(tmp_path)
    OrchestratorService(db).init_run(1, mode="explore")
    state_dir = tmp_path / "state"
    path = checkpoint_path(state_dir, 1)
    checkpoint = new_checkpoint(1, mode="explore")
    checkpoint["schema_version"] = SCHEMA_VERSION + 1
    save_checkpoint(path, checkpoint)
    before = path.read_bytes()

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result["status"] == "error"
    assert result["error"] == "checkpoint_schema_mismatch"
    assert result["changed"] is False
    assert path.read_bytes() == before


def test_sync_topic_checkpoint_serializes_a_concurrent_running_writer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.auto_runner.runner as runner_module

    db = _topic_db(tmp_path)
    service = OrchestratorService(db)
    service.init_run(1, mode="explore")
    service.resume_run(1, mode="explore", force_stage="build")
    state_dir = tmp_path / "state"
    path = _checkpoint(state_dir, mode="standard")
    writer_started = Event()
    writer_done = Event()
    writer_threads: list[Thread] = []
    real_sync = runner_module._sync_checkpoint_with_orchestrator

    def race_with_runner_writer(**kwargs):
        changed = real_sync(**kwargs)

        def write_running_checkpoint() -> None:
            writer_started.set()
            running = new_checkpoint(1, mode="explore")
            running["current_stage"] = "build"
            running["stage_state"] = "running"
            save_checkpoint(path, running)
            writer_done.set()

        writer = Thread(target=write_running_checkpoint)
        writer_threads.append(writer)
        writer.start()
        assert writer_started.wait(timeout=1)
        writer_done.wait(timeout=0.1)
        return changed

    monkeypatch.setattr(
        runner_module,
        "_sync_checkpoint_with_orchestrator",
        race_with_runner_writer,
    )

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)
    for writer in writer_threads:
        writer.join(timeout=1)

    assert result["status"] == "synced"
    assert writer_done.is_set()
    assert (load_checkpoint(path) or {})["stage_state"] == "running"


def test_sync_topic_checkpoint_fails_closed_when_run_is_missing(
    tmp_path: Path,
) -> None:
    db = _topic_db(tmp_path)
    state_dir = tmp_path / "state"
    path = _checkpoint(state_dir)

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result["status"] == "error"
    assert result["error"] == "orchestrator_run_not_found"
    assert result["checkpoint_path"] == str(path)


def test_sync_topic_checkpoint_carries_blocked_run_state(tmp_path: Path) -> None:
    db = _topic_db(tmp_path)
    OrchestratorService(db).init_run(1, mode="explore")
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE orchestrator_runs SET stage_status = 'blocked' WHERE topic_id = 1"
        )
        conn.commit()
    finally:
        conn.close()
    state_dir = tmp_path / "state"
    _checkpoint(state_dir)

    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result["status"] == "synced"
    assert result["after"]["state"] == "blocked"


def test_sync_topic_checkpoint_recovers_same_stage_after_unblock(
    tmp_path: Path,
) -> None:
    db = _topic_db(tmp_path)
    service = OrchestratorService(db)
    service.init_run(1, mode="explore")
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE orchestrator_runs SET stage_status = 'blocked' WHERE topic_id = 1"
        )
        conn.commit()
    finally:
        conn.close()
    state_dir = tmp_path / "state"
    path = checkpoint_path(state_dir, 1)
    checkpoint = new_checkpoint(1, mode="explore")
    checkpoint["stage_state"] = "blocked"
    save_checkpoint(path, checkpoint)

    service.transition_to(1, "init", rationale="resolve same-stage gate")
    result = sync_topic_checkpoint(1, base_dir=state_dir, db=db)

    assert result["status"] == "synced"
    assert result["before"]["state"] == "blocked"
    assert result["after"] == {
        "stage": "init",
        "state": "pending",
        "mode": "explore",
    }
    assert (load_checkpoint(path) or {})["stage_state"] == "pending"


def test_python_facade_exposes_sync_only_checkpoint_operation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[int, Path | None, object]] = []

    def fake_sync(
        topic_id: int,
        *,
        base_dir: Path | None = None,
        db=None,
    ) -> dict:
        calls.append((topic_id, base_dir, db))
        return {"status": "unchanged", "topic_id": topic_id}

    monkeypatch.setattr(
        "research_harness.auto_runner.runner.sync_topic_checkpoint",
        fake_sync,
    )
    api = ResearchAPI(db_path=tmp_path / "facade.db")
    state_dir = tmp_path / "state"

    assert api.paper_production_sync_checkpoint(
        topic_id=7,
        state_dir=state_dir,
    ) == {"status": "unchanged", "topic_id": 7}
    assert calls == [(7, state_dir, api.db)]


@pytest.mark.parametrize("topic_id", [0, -1, True])
def test_python_facade_rejects_invalid_sync_topic_id(
    tmp_path: Path,
    topic_id,
) -> None:
    api = ResearchAPI(db_path=tmp_path / "facade.db")

    with pytest.raises(ValueError, match="positive integer"):
        api.paper_production_sync_checkpoint(topic_id=topic_id)
