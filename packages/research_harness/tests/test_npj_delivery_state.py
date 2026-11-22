"""Delivery ownership must preempt ordinary paper-production recommendations.

NPJ_STATE_CAPTURE_DIR optionally supplies the private binding/topic capture. Its
manifest and original payload hashes are checked before a *derived test copy*
translates only rh_db_path to the temporary DB and recomputes metadata.sha256.
The original capture remains unchanged; the translated hash is not its provenance.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_harness.auto_runner.topic_state import topic_state
from research_harness.cli import main
from research_harness.config import RuntimeConfig
from research_harness.service import ResearchService


def _digest(payload):
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@pytest.fixture(params=["synthetic", "capture"])
def delivery(db, request):
    if request.param == "capture":
        source = os.environ.get("NPJ_STATE_CAPTURE_DIR")
        if not source:
            pytest.skip("private delivery capture not configured")
        source = Path(source)
        index = json.loads((source / "INDEX.json").read_text())
        manifest = json.loads((source / "SOURCE_EXTRA.json").read_text())
        binding_ref = next(row for row in index if row["id"] == 8741)
        topics_ref = next(
            row
            for row in manifest["tables_and_files"]
            if row["file"] == "source-topics.json"
        )
        for ref in (binding_ref, topics_ref):
            assert (
                hashlib.sha256((source / ref["file"]).read_bytes()).hexdigest()
                == ref["sha256"]
            )
        artifact = json.loads((source / binding_ref["file"]).read_text())
        topic = next(
            row
            for row in json.loads((source / topics_ref["file"]).read_text())
            if row["id"] == artifact["topic_id"]
        )
        payload = json.loads(artifact["payload_json"])
        metadata = json.loads(artifact["metadata_json"])
        assert metadata["sha256"] == _digest(payload)
        assert payload["topic_id"] == topic["id"]
        assert topic["name"] == f"ticket-execution-{payload['execution_id']}"
        # Deliberate clone identity translation, not original provenance.
        payload["rh_db_path"] = str(db.db_path)
        metadata["sha256"] = _digest(payload)
        artifact.update(
            payload_json=json.dumps(payload), metadata_json=json.dumps(metadata)
        )
    else:
        topic = {
            "id": 171,
            "name": "ticket-execution-" + "a" * 32,
            "description": "Synthetic delivery control",
            "status": "active",
        }
        payload = {
            "contract_version": "research_execution.v1",
            "execution_id": "a" * 32,
            "execution_mode": "external_simulated",
            "ticket_namespace": "test-tickets",
            "public_id": "control",
            "topic_id": topic["id"],
            "title": "Control",
            "topic_text": "Synthetic control",
            "target_journal": "Test journal",
            "rh_db_path": str(db.db_path),
        }
        artifact = {
            "id": 8741,
            "topic_id": topic["id"],
            "stage": "propose",
            "artifact_type": "research_delivery_binding",
            "status": "active",
            "stale": 0,
            "version": 1,
            "payload_json": json.dumps(payload),
            "metadata_json": json.dumps({"sha256": _digest(payload)}),
        }
    with db.connect() as conn:
        for table, row in (("topics", topic), ("project_artifacts", artifact)):
            fields = ",".join(row)
            placeholders = ",".join("?" for _ in row)
            conn.execute(
                f"INSERT INTO {table} ({fields}) VALUES ({placeholders})",
                tuple(row.values()),
            )
    return db, topic["id"], artifact["id"], payload


def _state(delivery, tmp_path):
    db, topic_id, *_ = delivery
    return topic_state(
        db,
        topic=topic_id,
        base_dir=tmp_path / "state",
        runtime_config=RuntimeConfig(db_path=db.db_path, source="explicit"),
    )


def _assert_owned(result):
    assert result["classification"] == "research_delivery"
    assert result["next_action"]["code"] == "research_delivery_owned"
    assert result["next_action"]["commands"] == []
    assert result["execution"]["binding_status"] == "verified"
    assert result["execution"]["live_state"] == "unknown"
    assert result["blockers"] == []
    assert result["checkpoint"] == {}


def _assert_unknown(result):
    assert result["classification"] == "delivery_state_unknown"
    assert result["next_action"]["code"] == "delivery_state_unknown"
    assert result["next_action"]["commands"] == []
    assert result["execution"]["binding_status"] == "unknown"
    assert result["execution"]["live_state"] == "unknown"
    assert result["blockers"]
    assert not result["state_consistency"]["sources_agree"]


def test_delivery_preempts_ordinary_preflight_and_is_read_only(
    delivery, tmp_path, monkeypatch
):
    import importlib

    module = importlib.import_module("research_harness.auto_runner.topic_state")

    def forbidden(*args, **kwargs):
        raise AssertionError("delivery status must not probe paper-production state")

    monkeypatch.setattr(module, "preflight_paper_production_topic", forbidden)
    monkeypatch.setattr(module, "paper_production_pending_decisions", forbidden)
    monkeypatch.setattr(module.ckpt, "load_checkpoint", forbidden)
    db, topic_id, artifact_id, payload = delivery
    original_connect = db.connect

    def readonly_connect():
        conn = original_connect()
        conn.execute("PRAGMA query_only = ON")
        return conn

    monkeypatch.setattr(db, "connect", readonly_connect)
    result = _state(delivery, tmp_path)
    _assert_owned(result)
    assert result["execution"]["execution_id"] == payload["execution_id"]
    assert result["execution"]["execution_mode"] == payload["execution_mode"]
    assert result["execution"]["binding_artifact_id"] == artifact_id
    assert result["topic"]["id"] == topic_id


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "stale",
        "inactive",
        "conflicting",
        "tampered",
        "corrupt_json",
        "nonobject",
        "corrupt_metadata",
        "missing_hash",
        "wrong_topic",
        "wrong_execution",
        "wrong_db",
        "wrong_name",
        "wrong_contract",
        "wrong_mode",
    ],
)
def test_ambiguous_binding_never_starts_paper_production(delivery, tmp_path, defect):
    db, topic_id, artifact_id, payload = delivery
    with db.connect() as conn:
        if defect == "missing":
            conn.execute("DELETE FROM project_artifacts WHERE id=?", (artifact_id,))
        elif defect in {
            "stale",
            "inactive",
            "corrupt_json",
            "nonobject",
            "corrupt_metadata",
        }:
            field, value = {
                "stale": ("stale", 1),
                "inactive": ("status", "archived"),
                "corrupt_json": ("payload_json", "{"),
                "nonobject": ("payload_json", "[]"),
                "corrupt_metadata": ("metadata_json", "[]"),
            }[defect]
            conn.execute(
                f"UPDATE project_artifacts SET {field}=? WHERE id=?",
                (value, artifact_id),
            )
        elif defect == "conflicting":
            conn.execute(
                "INSERT INTO project_artifacts "
                "(topic_id,stage,artifact_type,payload_json,metadata_json) "
                "SELECT topic_id,stage,artifact_type,payload_json,metadata_json "
                "FROM project_artifacts WHERE id=?",
                (artifact_id,),
            )
        elif defect == "wrong_name":
            conn.execute(
                "UPDATE topics SET name='ordinary-name' WHERE id=?", (topic_id,)
            )
        else:
            metadata = {"sha256": _digest(payload)}
            if defect == "missing_hash":
                metadata = {}
            else:
                key, value = {
                    "tampered": ("title", "Changed after hashing"),
                    "wrong_topic": ("topic_id", topic_id + 1),
                    "wrong_execution": ("execution_id", "b" * 32),
                    "wrong_db": ("rh_db_path", str(tmp_path / "another.db")),
                    "wrong_contract": ("contract_version", "unknown.v1"),
                    "wrong_mode": ("execution_mode", "unknown"),
                }[defect]
                payload[key] = value
                if defect != "tampered":
                    metadata["sha256"] = _digest(payload)
            conn.execute(
                "UPDATE project_artifacts SET payload_json=?,metadata_json=? WHERE id=?",
                (json.dumps(payload), json.dumps(metadata), artifact_id),
            )
    _assert_unknown(_state(delivery, tmp_path))


def test_delivery_precedes_ordinary_archive_action(delivery, tmp_path):
    db, topic_id, *_ = delivery
    with db.connect() as conn:
        conn.execute("UPDATE topics SET status='archived' WHERE id=?", (topic_id,))
    _assert_owned(_state(delivery, tmp_path))


@pytest.mark.parametrize("invalid", [False, True])
def test_public_cli_service_and_mcp_share_delivery_state(
    delivery, tmp_path, monkeypatch, invalid
):
    from research_harness_mcp.tools_service_dispatch import (
        _execute_service_backed_convenience,
    )

    db, topic_id, artifact_id, _ = delivery
    if invalid:
        with db.connect() as conn:
            conn.execute(
                "UPDATE project_artifacts SET stale=1 WHERE id=?", (artifact_id,)
            )
    check = _assert_unknown if invalid else _assert_owned
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db.db_path))
    cli = CliRunner()
    args = [
        "topic",
        "state",
        "--topic",
        str(topic_id),
        "--state-dir",
        str(tmp_path / "state"),
    ]
    result = cli.invoke(main, ["--json", *args])
    assert result.exit_code == 0, type(result.exception).__name__
    check(json.loads(result.output))
    text = cli.invoke(main, args)
    assert text.exit_code == 0, type(text.exception).__name__
    assert (
        "next [delivery_state_unknown]" if invalid else "next [research_delivery_owned]"
    ) in text.output
    assert "paper-production" not in text.output
    service = ResearchService(db=db).invoke("topic_state", {"topic_id": topic_id})
    assert service.status == "success"
    check(service.output["output"])
    assert service.output["next_actions"] == []
    mcp = _execute_service_backed_convenience(
        "topic_state", {"topic_id": topic_id}, db=db
    )
    check(mcp["output"])
    assert mcp["next_actions"] == []
