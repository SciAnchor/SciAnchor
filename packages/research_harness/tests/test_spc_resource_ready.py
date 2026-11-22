"""Tests for the SPC -> RH workflow_ready import/fetch seam.

The binding-key and content_digest vectors are pinned against the seed-paper-
curator producer so the two implementations cannot silently diverge.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from click.testing import CliRunner

from research_harness.acquisition.resource_ready import (
    RESOURCE_READY_ARTIFACT_TYPE,
    RESOURCE_READY_STAGE,
    ResourceReadyError,
    canonical_json_bytes,
    compute_binding_key,
    content_digest,
    get_ready,
    import_spc_ready,
    parse_ready_report,
    verify_content_digest,
)
from research_harness._workflow.orchestrator.artifacts import ArtifactManager
from research_harness.cli import main
from research_harness.storage.db import Database

# SPC binding-key-gold.v1 fixture.
GOLD_WORKFLOW_REF = "workflow:npj-gene.glioma@provisional-1"
GOLD_HOST_ID = "host:example-host-wsl"
GOLD_KEY_TOPIC_INT = (
    "sha256:cf6e8092ba50c00bcb6dcc113898cebe5beaa66d7d3fff71843c932630858bc4"
)
GOLD_KEY_TOPIC_STR = (
    "sha256:0ef38020c9bef7127299877ff3e8a26de8752bba93747a3bc3bff07939fe13ff"
)


def _make_topic(db: Database, name: str = "spc-resource-test") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)", (name, name)
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _make_report(
    workflow_ref: str = GOLD_WORKFLOW_REF,
    host_id: str = GOLD_HOST_ID,
    *,
    status: str = "ready",
    report_id: str = "urn:uuid:test-report",
    spc_version: str = "0.1.0",
) -> dict:
    report = {
        "schema_version": "spc.workflow-ready.v1",
        "report_id": report_id,
        "workflow": {
            "workflow_ref": workflow_ref,
            "manifest_revision": 1,
            "manifest_digest": "sha256:" + "0" * 64,
        },
        "contract_lifecycle": "provisional",
        "host": {
            "host_id": host_id,
            "platform": "linux",
            "profile_digest": "sha256:" + "1" * 64,
        },
        "producer": {
            "spc_version": spc_version,
            "producer_actor": "tb",
            "produced_at": "2026-08-02T00:00:00+00:00",
        },
        "selected_modules": ["m1"],
        "environments": [],
        "datasets": [],
        "resource_status": status,
        "blockers": [],
    }
    report["content_digest"] = content_digest(report)
    return report


# -- cross-implementation parity ---------------------------------------------


def test_binding_key_matches_spc_gold_integer_case() -> None:
    assert (
        compute_binding_key(16, GOLD_WORKFLOW_REF, GOLD_HOST_ID) == GOLD_KEY_TOPIC_INT
    )


def test_binding_key_string_topic_is_distinct() -> None:
    # RH always uses the integer topics.id; the string form must hash apart,
    # matching the SPC gold fixture so a plumbing type slip cannot go unnoticed.
    raw = canonical_json_bytes(
        {
            "topic_id": "16",
            "workflow_ref": GOLD_WORKFLOW_REF,
            "host_id": GOLD_HOST_ID,
        }
    )
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == GOLD_KEY_TOPIC_STR
    assert GOLD_KEY_TOPIC_STR != GOLD_KEY_TOPIC_INT


def test_content_digest_locked_vectors() -> None:
    assert (
        content_digest(
            {"b": ["x", "y"], "a": 1, "schema_version": "spc.workflow-ready.v1"}
        )
        == "sha256:017b1c6d753847bd191dfaaa491d96ca6bb2b211aab1eb96789893a30070c7a8"
    )
    # Non-ASCII vector locks ensure_ascii=False.
    assert (
        content_digest({"note": "生产检查", "n": 2})
        == "sha256:fc5d486b89dd9ba837f07053565c373f91d2de6bcfa029faf58d9b493571529a"
    )


def test_verify_content_digest_roundtrip_and_tamper() -> None:
    report = _make_report()
    verify_content_digest(report)  # no raise

    tampered = dict(report)
    tampered["resource_status"] = "blocked"
    with pytest.raises(ResourceReadyError, match="content_digest mismatch"):
        verify_content_digest(tampered)


def test_canonical_json_rejects_non_finite() -> None:
    with pytest.raises(ResourceReadyError, match="NaN or infinity"):
        canonical_json_bytes({"x": float("inf")})


# -- parsing ------------------------------------------------------------------


def test_parse_rejects_wrong_schema() -> None:
    bad = json.dumps({"schema_version": "spc.workflow-ready.v2"})
    with pytest.raises(ResourceReadyError, match="unexpected schema_version"):
        parse_ready_report(bad)


def test_parse_rejects_non_object() -> None:
    with pytest.raises(ResourceReadyError, match="must be a JSON object"):
        parse_ready_report("[]")


# -- import / fetch -----------------------------------------------------------


def test_import_and_get_roundtrip(db: Database) -> None:
    topic_id = _make_topic(db)
    report = _make_report()
    result = import_spc_ready(db, topic_id, report, source_path="/tmp/ready.json")

    assert result["binding_key"] == compute_binding_key(
        topic_id, GOLD_WORKFLOW_REF, GOLD_HOST_ID
    )
    assert result["resource_status"] == "ready"
    assert result["superseded_artifact_ids"] == []

    fetched = get_ready(db, topic_id, GOLD_WORKFLOW_REF, GOLD_HOST_ID)
    assert fetched is not None
    assert fetched["found"] is True
    assert fetched["artifact_id"] == result["artifact_id"]
    assert fetched["report"]["content_digest"] == report["content_digest"]

    # Stored as a build-stage spc.resource_ready artifact.
    stored = ArtifactManager(db).get_latest(
        topic_id, RESOURCE_READY_STAGE, RESOURCE_READY_ARTIFACT_TYPE
    )
    assert stored is not None
    assert stored.metadata["binding_key"] == result["binding_key"]


def test_get_ready_unbound_returns_none(db: Database) -> None:
    topic_id = _make_topic(db)
    assert get_ready(db, topic_id, GOLD_WORKFLOW_REF, GOLD_HOST_ID) is None


def test_selective_supersede_only_touches_same_binding(db: Database) -> None:
    topic_id = _make_topic(db)
    host_b = "host:server-wsl"

    a1 = import_spc_ready(db, topic_id, _make_report(status="ready"))
    b1 = import_spc_ready(db, topic_id, _make_report(host_id=host_b, status="blocked"))
    assert a1["binding_key"] != b1["binding_key"]

    # Re-import binding A with a new status -> supersedes only A's prior row.
    a2 = import_spc_ready(db, topic_id, _make_report(status="blocked"))
    assert a2["superseded_artifact_ids"] == [a1["artifact_id"]]

    got_a = get_ready(db, topic_id, GOLD_WORKFLOW_REF, GOLD_HOST_ID)
    got_b = get_ready(db, topic_id, GOLD_WORKFLOW_REF, host_b)
    assert got_a is not None and got_a["artifact_id"] == a2["artifact_id"]
    assert got_a["resource_status"] == "blocked"
    # Binding B untouched by A's re-import.
    assert got_b is not None and got_b["artifact_id"] == b1["artifact_id"]

    # Exactly one active row per binding key.
    active = ArtifactManager(db).list_by_topic(
        topic_id,
        stage=RESOURCE_READY_STAGE,
        artifact_type=RESOURCE_READY_ARTIFACT_TYPE,
        status="active",
    )
    assert len(active) == 2


def test_import_verifies_digest_by_default(db: Database) -> None:
    topic_id = _make_topic(db)
    report = _make_report()
    report["resource_status"] = "blocked"  # break the signature
    with pytest.raises(ResourceReadyError, match="content_digest mismatch"):
        import_spc_ready(db, topic_id, report)

    # --no-verify path accepts the unsigned report.
    result = import_spc_ready(db, topic_id, report, verify=False)
    assert result["verified"] is False


def test_import_expect_guards(db: Database) -> None:
    topic_id = _make_topic(db)
    report = _make_report()
    with pytest.raises(ResourceReadyError, match="workflow_ref mismatch"):
        import_spc_ready(db, topic_id, report, expected_workflow_ref="workflow:other@1")
    with pytest.raises(ResourceReadyError, match="host_id mismatch"):
        import_spc_ready(db, topic_id, report, expected_host_id="host:other")


def test_import_requires_fields(db: Database) -> None:
    topic_id = _make_topic(db)
    with pytest.raises(ResourceReadyError, match="missing 'host.host_id'"):
        import_spc_ready(
            db,
            topic_id,
            {
                "schema_version": "spc.workflow-ready.v1",
                "workflow": {"workflow_ref": "workflow:x@1"},
            },
            verify=False,
        )


# -- CLI ----------------------------------------------------------------------


def test_cli_resource_group_registered() -> None:
    assert "resource" in main.commands
    assert set(main.commands["resource"].commands) >= {"import-spc-ready", "get-ready"}


def _make_topic_in_env_db(name: str = "spc-res-cli") -> str:
    db = Database(os.environ["RESEARCH_HARNESS_DB_PATH"])
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)", (name, name)
        )
        conn.commit()
    finally:
        conn.close()
    return name


def test_cli_import_and_get_ready(runner: CliRunner, tmp_path) -> None:
    topic = _make_topic_in_env_db()
    report_path = tmp_path / "workflow_ready.json"
    report_path.write_text(json.dumps(_make_report()), encoding="utf-8")

    imported = runner.invoke(
        main,
        [
            "--json",
            "resource",
            "import-spc-ready",
            "--topic",
            topic,
            "--file",
            str(report_path),
        ],
    )
    assert imported.exit_code == 0, imported.output
    payload = json.loads(imported.output)
    assert payload["resource_status"] == "ready"
    assert payload["binding_key"].startswith("sha256:")

    got = runner.invoke(
        main,
        [
            "--json",
            "resource",
            "get-ready",
            "--topic",
            topic,
            "--workflow-ref",
            GOLD_WORKFLOW_REF,
            "--host",
            GOLD_HOST_ID,
        ],
    )
    assert got.exit_code == 0, got.output
    got_payload = json.loads(got.output)
    assert got_payload["found"] is True
    assert got_payload["artifact_id"] == payload["artifact_id"]
    assert "source_path" not in got_payload
    assert "report" not in got_payload
    assert str(tmp_path) not in got.output

    report_attempt = runner.invoke(
        main,
        [
            "--json",
            "resource",
            "get-ready",
            "--topic",
            topic,
            "--workflow-ref",
            GOLD_WORKFLOW_REF,
            "--host",
            GOLD_HOST_ID,
            "--report",
        ],
    )
    assert report_attempt.exit_code == 2
    assert str(tmp_path) not in report_attempt.output

    missing = runner.invoke(
        main,
        [
            "--json",
            "resource",
            "get-ready",
            "--topic",
            topic,
            "--workflow-ref",
            GOLD_WORKFLOW_REF,
            "--host",
            "host:nope",
        ],
    )
    assert missing.exit_code == 3, missing.output
    assert json.loads(missing.output)["found"] is False


# -- service dispatcher (MCP resource_ready_get backend) ----------------------


def test_service_command_registered_public_mcp(db: Database) -> None:
    from research_harness.service import ResearchService

    commands = {c.name: c for c in ResearchService(db=db).list_commands()}
    assert "resource_ready_get" in commands
    assert "public_mcp" in commands["resource_ready_get"].visibility
    assert (
        "include_report"
        not in commands["resource_ready_get"].input_schema["properties"]
    )


def test_service_resource_ready_get_roundtrip(db: Database) -> None:
    from research_harness.service import ResearchService

    topic_id = _make_topic(db)
    imported = import_spc_ready(db, topic_id, _make_report())

    found = ResearchService(db=db).invoke(
        "resource_ready_get",
        {
            "topic_id": topic_id,
            "workflow_ref": GOLD_WORKFLOW_REF,
            "host_id": GOLD_HOST_ID,
        },
    )
    assert found.status == "success"
    assert found.output["found"] is True
    assert found.output["artifact_id"] == imported["artifact_id"]
    # Public service results are always status-only summaries.
    assert "report" not in found.output

    with_report = ResearchService(db=db).invoke(
        "resource_ready_get",
        {
            "topic_id": topic_id,
            "workflow_ref": GOLD_WORKFLOW_REF,
            "host_id": GOLD_HOST_ID,
            "include_report": True,
        },
    )
    assert "report" not in with_report.output


def test_service_resource_ready_get_redacts_local_provenance(db: Database) -> None:
    from research_harness.service import ResearchService

    topic_id = _make_topic(db)
    report = _make_report()
    report["private_runtime"] = {
        "source_path": "/Users/operator/private/workflow_ready.json",
        "token_hint": "do-not-expose",
    }
    report["content_digest"] = content_digest(report)
    import_spc_ready(
        db,
        topic_id,
        report,
        source_path="/Users/operator/private/workflow_ready.json",
    )

    result = ResearchService(db=db).invoke(
        "resource_ready_get",
        {
            "topic_id": topic_id,
            "workflow_ref": GOLD_WORKFLOW_REF,
            "host_id": GOLD_HOST_ID,
            "include_report": True,
        },
    )

    assert result.status == "success"
    assert "source_path" not in result.output
    assert "report" not in result.output
    assert "do-not-expose" not in repr(result.output)
    assert "/Users/operator" not in repr(result.output)


def test_service_resource_ready_get_not_found(db: Database) -> None:
    from research_harness.service import ResearchService

    topic_id = _make_topic(db)
    result = ResearchService(db=db).invoke(
        "resource_ready_get",
        {
            "topic_id": topic_id,
            "workflow_ref": GOLD_WORKFLOW_REF,
            "host_id": "host:nope",
        },
    )
    assert result.status == "success"
    assert result.output["found"] is False


def test_service_resource_ready_get_requires_fields(db: Database) -> None:
    from research_harness.service import ResearchService

    result = ResearchService(db=db).invoke(
        "resource_ready_get", {"topic_id": 1, "workflow_ref": GOLD_WORKFLOW_REF}
    )
    assert result.status == "error"
