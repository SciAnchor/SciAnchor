"""CLI tests for semi-automatic offload commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from research_harness import offload
from research_harness.cli import main
from research_harness.cli_offload import register
from research_harness.storage.db import Database


def _seed_topic(db_path: Path) -> None:
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, 'demo-topic', 'Demo', 'active')"
        )
        conn.commit()
    finally:
        conn.close()


def _write_minimal_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% CLI offload test PDF\n%%EOF\n")


def _remote_library_snapshot() -> dict[str, object]:
    return {
        "schema_version": "remote_library_snapshot.v1",
        "created_at": "2026-06-20T00:00:00+00:00",
        "query": "time series",
        "host_alias_hash": "a" * 64,
        "library_root_hash": "b" * 64,
        "max_files_scanned": 100,
        "scanned_file_count": 10,
        "matched_file_count": 1,
        "truncated": False,
        "extension_counts": {".pdf": 10},
        "samples": [
            {
                "basename": "forecasting.pdf",
                "extension": ".pdf",
                "size_bytes": 42,
                "relative_path_hash": "c" * 64,
                "path_depth": 1,
                "matched_terms": ["time", "series"],
            }
        ],
        "warnings": [],
    }


def test_cli_offload_module_exports_register() -> None:
    assert callable(register)
    assert "offload" in main.commands


def test_offload_prepare_status_upload_fetch_import_flow(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)

    task_dir = tmp_path / "task-pack"
    prepare = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "paper_text_extraction_batch",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
        ],
    )
    assert prepare.exit_code == 0, prepare.output
    prepared_payload = json.loads(prepare.output)
    assert prepared_payload["task_type"] == "paper_text_extraction_batch"
    task_id = prepared_payload["task_id"]

    status = runner.invoke(main, ["--json", "offload", "status", str(task_dir)])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["status"] == "prepared"

    remote_root = tmp_path / "remote"
    upload = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "upload",
            str(task_dir),
            "--host",
            "worker",
            "--remote-root",
            str(remote_root),
            "--local-copy",
        ],
    )
    assert upload.exit_code == 0, upload.output
    upload_payload = json.loads(upload.output)
    assert upload_payload["status"] == "uploaded"

    command = runner.invoke(main, ["offload", "command", task_id, "--host", "worker"])
    assert command.exit_code == 0, command.output
    assert "ssh worker" in command.output
    assert task_id in command.output

    run_local = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "run-local",
            task_id,
            "--remote-root",
            str(remote_root),
        ],
    )
    assert run_local.exit_code == 0, run_local.output
    assert json.loads(run_local.output)["status"] == "partial"

    result_dir = remote_root / "results" / task_id
    assert (result_dir / "result_manifest.json").exists()
    assert (result_dir / "outputs" / "summary.json").exists()

    local_results = tmp_path / "results"
    fetch = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "fetch",
            task_id,
            "--host",
            "worker",
            "--remote-root",
            str(remote_root),
            "--local-root",
            str(local_results),
            "--local-copy",
        ],
    )
    assert fetch.exit_code == 0, fetch.output
    fetched_path = Path(json.loads(fetch.output)["local_path"])

    imported = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "import",
            str(fetched_path),
            "--topic",
            "demo-topic",
        ],
    )
    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.output)["artifact_type"] == "remote_offload_diagnostic"


def test_offload_prepare_accepts_remote_library_snapshot_cli(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_remote_library_snapshot()))

    task_dir = tmp_path / "retrieval-task"
    prepared = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "retrieval_eval_sweep",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
            "--library-snapshot",
            str(snapshot_path),
        ],
    )

    assert prepared.exit_code == 0, prepared.output
    inputs = json.loads(
        (task_dir / "inputs" / "retrieval_eval_inputs.json").read_text()
    )
    assert inputs["external_corpus_snapshot"]["matched_file_count"] == 1
    assert "/data5" not in json.dumps(inputs)


def test_offload_prepare_can_explicitly_include_pdf_files_cli(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)
    pdf_path = workspace / "papers" / "demo.pdf"
    _write_minimal_pdf(pdf_path)
    conn = Database(db_path).connect()
    try:
        conn.execute(
            "INSERT INTO papers (id, title, pdf_path, pdf_hash, status) VALUES (1, 'Demo PDF', ?, '', 'pending')",
            (str(pdf_path),),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    task_dir = tmp_path / "pdf-task"
    prepared = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "paper_text_extraction_batch",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
            "--include-pdf-files",
            "--max-pdf-bytes",
            "1000000",
        ],
    )

    assert prepared.exit_code == 0, prepared.output
    payload = json.loads(
        (task_dir / "inputs" / "paper_text_extraction_inputs.json").read_text()
    )
    paper = payload["papers"][0]
    assert paper["pdf_file"].startswith("pdfs/")
    assert (task_dir / "inputs" / paper["pdf_file"]).is_file()
    packed = json.dumps(payload)
    assert str(pdf_path) not in packed
    assert "demo.pdf" not in packed


def test_offload_doctor_passes_timeout_seconds(runner: CliRunner, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_doctor(**kwargs):
        captured.update(kwargs)
        return {"host": kwargs["host"], "read_only": True, "checks": []}

    monkeypatch.setattr(offload, "doctor", fake_doctor)

    result = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "doctor",
            "--host",
            "worker",
            "--timeout-seconds",
            "120",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["timeout_seconds"] == 120


def test_offload_remote_library_scan_passes_timeout_seconds(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    snapshot_path = tmp_path / "snapshot.json"

    def fake_scan_remote_library(**kwargs):
        captured.update(kwargs)
        snapshot_path.write_text(json.dumps(_remote_library_snapshot()))
        return snapshot_path

    monkeypatch.setattr(offload, "scan_remote_library", fake_scan_remote_library)

    result = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "remote-library-scan",
            "--host",
            "worker",
            "--library-root",
            "/remote/library",
            "--query",
            "time series",
            "--out",
            str(snapshot_path),
            "--timeout-seconds",
            "180",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["timeout_seconds"] == 180


def test_offload_retrieval_eval_snapshot_flow_imports_success_result(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot = _remote_library_snapshot()
    snapshot["samples"] = [
        {
            "basename": "demo-topic-forecasting.pdf",
            "extension": ".pdf",
            "size_bytes": 123,
            "relative_path_hash": "c" * 64,
            "path_depth": 2,
            "matched_terms": ["demo", "forecasting"],
        }
    ]
    snapshot_path.write_text(json.dumps(snapshot))

    task_dir = tmp_path / "retrieval-task"
    prepared = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "retrieval_eval_sweep",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
            "--library-snapshot",
            str(snapshot_path),
        ],
    )
    assert prepared.exit_code == 0, prepared.output
    task_id = json.loads(prepared.output)["task_id"]
    remote_root = tmp_path / "remote"

    uploaded = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "upload",
            str(task_dir),
            "--remote-root",
            str(remote_root),
            "--local-copy",
        ],
    )
    assert uploaded.exit_code == 0, uploaded.output

    local_run = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "run-local",
            task_id,
            "--remote-root",
            str(remote_root),
        ],
    )
    assert local_run.exit_code == 0, local_run.output
    assert json.loads(local_run.output)["status"] == "succeeded"

    local_results = tmp_path / "results"
    fetched = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "fetch",
            task_id,
            "--remote-root",
            str(remote_root),
            "--local-root",
            str(local_results),
            "--local-copy",
        ],
    )
    assert fetched.exit_code == 0, fetched.output
    fetched_path = Path(json.loads(fetched.output)["local_path"])

    imported = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "import",
            str(fetched_path),
            "--topic",
            "demo-topic",
        ],
    )
    assert imported.exit_code == 0, imported.output
    imported_payload = json.loads(imported.output)
    assert imported_payload["status"] == "succeeded"
    assert imported_payload["artifact_type"] == "remote_offload_result"

    report = json.loads(
        (fetched_path / "outputs" / "retrieval_eval_report.json").read_text()
    )
    assert report["method"] == "bm25_remote_snapshot_rerank"


def test_offload_batch_plan_and_status_cli(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)

    task_dir = tmp_path / "task-pack"
    prepared = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "paper_text_extraction_batch",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
        ],
    )
    assert prepared.exit_code == 0, prepared.output
    prepared_payload = json.loads(prepared.output)
    plan_path = tmp_path / "batch_plan.json"

    planned = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "batch-plan",
            str(task_dir),
            "--out",
            str(plan_path),
            "--host",
            "worker",
            "--remote-root",
            "remote-offload-root",
            "--concurrency",
            "2",
        ],
    )
    assert planned.exit_code == 0, planned.output
    plan_payload = json.loads(planned.output)
    assert plan_payload["item_count"] == 1
    assert plan_payload["path"] == str(plan_path)

    status = runner.invoke(
        main,
        ["--json", "offload", "batch-status", str(plan_path)],
    )
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["total"] == 1
    assert status_payload["ready_to_upload"] == 1

    reconciled = runner.invoke(
        main,
        ["--json", "offload", "batch-reconcile", str(plan_path)],
    )
    assert reconciled.exit_code == 0, reconciled.output
    reconcile_payload = json.loads(reconciled.output)
    assert reconcile_payload["total"] == 1
    assert reconcile_payload["drift_count"] == 0
    assert reconcile_payload["resume"]["ready_to_upload"] == [
        prepared_payload["task_id"]
    ]

    capabilities_path = tmp_path / "capabilities.json"
    capabilities_path.write_text(
        json.dumps(
            {
                "schema_version": "rh_offload_worker_capabilities.v1",
                "supported_task_types": ["paper_text_extraction_batch"],
                "resources": {"gpu": False, "cpu": 8, "memory_gb": 32},
                "features": {"pdf_parsers": ["pypdf"]},
                "cache_policy": {
                    "max_gb": 50,
                    "cleanup": "manual",
                    "cache_root": "cache/",
                },
            }
        )
    )
    preflight = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "batch-preflight",
            str(plan_path),
            "--capabilities",
            str(capabilities_path),
        ],
    )
    assert preflight.exit_code == 0, preflight.output
    preflight_payload = json.loads(preflight.output)
    assert preflight_payload["total"] == 1
    assert preflight_payload["allowed_count"] == 1
    assert preflight_payload["blocked_count"] == 0
    assert preflight_payload["items"][0]["features"]["pdf_parsers"] == ["pypdf"]
    assert preflight_payload["items"][0]["cache_policy"]["cleanup"] == "manual"


def test_offload_batch_preflight_cli_reports_model_cache_policy(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            """
            INSERT INTO project_artifacts
                (topic_id, stage, artifact_type, title, path, payload_json, metadata_json)
            VALUES
                (
                    1,
                    'build',
                    'wiki_context_pack',
                    'Wiki context',
                    '/Users/example/private/wiki.json',
                    '{"summary": "time series wiki summary"}',
                    '{}'
                )
            """
        )
        conn.commit()

    task_dir = tmp_path / "wiki-task"
    prepare = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "wiki_embedding_batch",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
        ],
    )
    assert prepare.exit_code == 0, prepare.output
    plan_path = tmp_path / "batch_plan.json"
    planned = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "batch-plan",
            str(task_dir),
            "--out",
            str(plan_path),
            "--host",
            "worker",
            "--remote-root",
            "remote-offload-root",
        ],
    )
    assert planned.exit_code == 0, planned.output
    capabilities_path = tmp_path / "capabilities.json"
    capabilities_path.write_text(
        json.dumps(
            {
                "schema_version": "rh_offload_worker_capabilities.v1",
                "supported_task_types": ["wiki_embedding_batch"],
                "resources": {"gpu": True, "cpu": 8, "memory_gb": 64},
                "features": {
                    "embedding": {
                        "backends": ["sentence-transformers"],
                        "models": ["generic-local-model"],
                        "default_device": "cuda",
                    }
                },
                "cache_policy": {
                    "max_gb": 100,
                    "cleanup": "manual",
                    "cache_root": "cache/",
                },
            }
        )
    )

    preflight = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "batch-preflight",
            str(plan_path),
            "--capabilities",
            str(capabilities_path),
        ],
    )

    assert preflight.exit_code == 0, preflight.output
    payload = json.loads(preflight.output)
    assert payload["blocked_count"] == 0
    item = payload["items"][0]
    assert item["model_policy"]["capability"] == "embedding"
    assert item["model_policy"]["available"] is True
    assert item["cache_policy"]["max_gb"] == 100


def test_offload_remote_status_and_cleanup_cli(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)
    task_dir = tmp_path / "task-pack"
    prepare = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "paper_text_extraction_batch",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
        ],
    )
    assert prepare.exit_code == 0, prepare.output
    task_id = json.loads(prepare.output)["task_id"]
    remote_root = tmp_path / "remote"
    upload = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "upload",
            str(task_dir),
            "--host",
            "worker",
            "--remote-root",
            str(remote_root),
            "--local-copy",
        ],
    )
    assert upload.exit_code == 0, upload.output

    status = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "remote-status",
            "--remote-root",
            str(remote_root),
            "--local",
        ],
    )
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["sections"]["incoming"]["count"] == 1
    assert status_payload["sections"]["incoming"]["items"][0]["path"] == (
        f"incoming/{task_id}"
    )

    cleanup = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "remote-cleanup",
            "--remote-root",
            str(remote_root),
            "--task-id",
            task_id,
            "--local",
        ],
    )
    assert cleanup.exit_code == 0, cleanup.output
    cleanup_payload = json.loads(cleanup.output)
    assert cleanup_payload["dry_run"] is True
    assert cleanup_payload["deleted_count"] == 0
    assert (remote_root / "incoming" / task_id).is_dir()

    execute_cleanup = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "remote-cleanup",
            "--remote-root",
            str(remote_root),
            "--task-id",
            task_id,
            "--local",
            "--execute",
        ],
    )
    assert execute_cleanup.exit_code == 0, execute_cleanup.output
    execute_payload = json.loads(execute_cleanup.output)
    assert execute_payload["dry_run"] is False
    assert execute_payload["deleted_count"] == 1
    assert not (remote_root / "incoming" / task_id).exists()


def test_offload_queue_create_status_and_step_cli(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    _seed_topic(db_path)
    task_dir = tmp_path / "task-pack"
    prepare = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "prepare",
            "--type",
            "paper_text_extraction_batch",
            "--topic",
            "demo-topic",
            "--out",
            str(task_dir),
        ],
    )
    assert prepare.exit_code == 0, prepare.output
    task_id = json.loads(prepare.output)["task_id"]
    queue_path = tmp_path / "queue.json"
    remote_root = tmp_path / "remote"

    created = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "queue-create",
            str(task_dir),
            "--out",
            str(queue_path),
            "--host",
            "worker",
            "--remote-root",
            str(remote_root),
        ],
    )
    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.output)
    assert created_payload["item_count"] == 1

    status = runner.invoke(
        main,
        ["--json", "offload", "queue-status", str(queue_path)],
    )
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["by_next_action"] == {"upload": 1}

    step = runner.invoke(
        main,
        [
            "--json",
            "offload",
            "queue-step",
            str(queue_path),
            "--local-copy",
        ],
    )
    assert step.exit_code == 0, step.output
    step_payload = json.loads(step.output)
    assert step_payload["task_id"] == task_id
    assert step_payload["action"] == "upload"
    assert step_payload["status"] == "uploaded"
    assert (remote_root / "incoming" / task_id).is_dir()


def test_offload_doctor_is_read_only_and_reports_commands(
    runner: CliRunner, monkeypatch
) -> None:
    monkeypatch.setenv("RH_OFFLOAD_HOST", "worker")
    result = runner.invoke(
        main,
        ["--json", "offload", "doctor", "--skip-ssh"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["host"] == "worker"
    assert payload["checks"][0]["check"] == "ssh"
    assert payload["checks"][0]["skipped"] is True
    assert payload["read_only"] is True


def test_offload_command_requires_host(runner: CliRunner) -> None:
    result = runner.invoke(
        main,
        [
            "offload",
            "command",
            "paper_text_extraction_batch-20260619T000000Z-demo",
        ],
    )

    assert result.exit_code != 0
    assert "host is required" in result.output
