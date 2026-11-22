"""SPC -> RH direction of the paperfetch contract bridge.

Consumes ``spc.workflow-ready.v1`` reports produced by paperfetch's
``spc workflow check`` and binds each report to an RH topic as a build-stage
``spc.resource_ready`` artifact. Like :mod:`.spc_bridge`, this module never
imports ``paperfetch``: the seam is the JSON contract only.

Canonical JSON rules here MUST match the SPC producer byte-for-byte, or the
``content_digest`` verification and the ``binding_key`` will diverge:

* UTF-8, sorted object keys, compact ``(",", ":")`` separators,
* ``ensure_ascii=False`` (NOT Python's default), ``allow_nan=False``,
* digest is over the *present keys only* (never re-serialise through a model
  that injects null defaults), lowercase hex with a ``sha256:`` prefix.

The binding key is ``sha256:`` + sha256 of the canonical JSON of
``{"topic_id": <int>, "workflow_ref": <str>, "host_id": <str>}``. ``topic_id``
is RH's integer ``topics.id`` and is intentionally int-typed: the SPC gold
fixture proves ``16`` (int) and ``"16"`` (str) hash differently, so the binding
key is only meaningful within one RH database.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..storage.db import Database
from .._workflow.orchestrator.artifacts import ArtifactManager

READY_SCHEMA_VERSION = "spc.workflow-ready.v1"
RESOURCE_READY_STAGE = "build"
RESOURCE_READY_ARTIFACT_TYPE = "spc.resource_ready"


class ResourceReadyError(ValueError):
    """Raised when a workflow_ready report is malformed or fails verification."""


# -- canonical JSON / digests (must mirror the SPC producer exactly) ----------


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ResourceReadyError("canonical JSON does not allow NaN or infinity")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite(item)


def canonical_json_bytes(
    value: Mapping[str, Any], *, exclude_content_digest: bool = False
) -> bytes:
    """Encode a contract object using the cross-project canonical JSON rules."""

    if not isinstance(value, Mapping):
        raise ResourceReadyError("canonical contract value must be a JSON object")
    normalized = dict(value)
    if exclude_content_digest:
        normalized.pop("content_digest", None)
    _reject_non_finite(normalized)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_digest(value: Mapping[str, Any]) -> str:
    """Return the ``sha256:``-prefixed digest of ``value`` sans ``content_digest``."""

    digest = hashlib.sha256(
        canonical_json_bytes(value, exclude_content_digest=True)
    ).hexdigest()
    return f"sha256:{digest}"


def verify_content_digest(report: Mapping[str, Any]) -> None:
    """Raise :class:`ResourceReadyError` when the embedded digest is wrong.

    Operates on the parsed JSON object as authored (present keys only), which is
    the only way to reproduce the SPC producer's signature.
    """

    actual = str(report.get("content_digest") or "")
    expected = content_digest(report)
    if actual != expected:
        raise ResourceReadyError(
            f"content_digest mismatch: expected {expected}, "
            f"received {actual or '<missing>'}"
        )


def compute_binding_key(topic_id: int, workflow_ref: str, host_id: str) -> str:
    """Return the v0.1 RH Artifact binding key for one (topic, workflow, host)."""

    identity = {
        "topic_id": int(topic_id),
        "workflow_ref": workflow_ref,
        "host_id": host_id,
    }
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return f"sha256:{digest}"


# -- report parsing -----------------------------------------------------------


def _require_str(report: Mapping[str, Any], *path: str) -> str:
    node: Any = report
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            raise ResourceReadyError(f"workflow_ready is missing '{'.'.join(path)}'")
        node = node[key]
    if not isinstance(node, str) or not node:
        raise ResourceReadyError(
            f"workflow_ready '{'.'.join(path)}' must be a non-empty string"
        )
    return node


def parse_ready_report(raw: str | bytes) -> dict[str, Any]:
    """Parse and shallow-validate a workflow_ready payload."""

    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResourceReadyError(f"workflow_ready is not valid JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise ResourceReadyError("workflow_ready must be a JSON object")
    schema = report.get("schema_version")
    if schema != READY_SCHEMA_VERSION:
        raise ResourceReadyError(
            f"unexpected schema_version {schema!r}; expected {READY_SCHEMA_VERSION!r}"
        )
    return report


# -- artifact binding ---------------------------------------------------------


def _active_binding_matches(
    manager: ArtifactManager, topic_id: int, binding_key: str
) -> list[Any]:
    rows = manager.list_by_topic(
        topic_id,
        stage=RESOURCE_READY_STAGE,
        artifact_type=RESOURCE_READY_ARTIFACT_TYPE,
        status="active",
    )
    return [a for a in rows if a.metadata.get("binding_key") == binding_key]


def _supersede_binding(db: Database, artifact_ids: list[int]) -> None:
    if not artifact_ids:
        return
    conn = db.connect()
    try:
        conn.executemany(
            "UPDATE project_artifacts SET status = 'superseded', "
            "updated_at = datetime('now') WHERE id = ?",
            [(artifact_id,) for artifact_id in artifact_ids],
        )
        conn.commit()
    finally:
        conn.close()


def import_spc_ready(
    db: Database,
    topic_id: int,
    report: Mapping[str, Any],
    *,
    source_path: str | Path | None = None,
    verify: bool = True,
    expected_workflow_ref: str | None = None,
    expected_host_id: str | None = None,
) -> dict[str, Any]:
    """Bind one workflow_ready report to ``topic_id`` as a resource-ready artifact.

    Enforces the single-active-per-binding-key invariant by superseding only the
    prior active rows that share this binding key, leaving other bindings intact
    (the artifact kernel supersedes by ``(topic, stage, type)`` and would
    otherwise clobber unrelated bindings).
    """

    workflow_ref = _require_str(report, "workflow", "workflow_ref")
    host_id = _require_str(report, "host", "host_id")
    resource_status = _require_str(report, "resource_status")

    if verify:
        verify_content_digest(report)
    if expected_workflow_ref is not None and expected_workflow_ref != workflow_ref:
        raise ResourceReadyError(
            f"workflow_ref mismatch: report has {workflow_ref!r}, "
            f"expected {expected_workflow_ref!r}"
        )
    if expected_host_id is not None and expected_host_id != host_id:
        raise ResourceReadyError(
            f"host_id mismatch: report has {host_id!r}, expected {expected_host_id!r}"
        )

    binding_key = compute_binding_key(topic_id, workflow_ref, host_id)
    manager = ArtifactManager(db)
    superseded = [a.id for a in _active_binding_matches(manager, topic_id, binding_key)]
    _supersede_binding(db, superseded)

    producer = report.get("producer")
    producer = producer if isinstance(producer, Mapping) else {}
    metadata = {
        "binding_key": binding_key,
        "workflow_ref": workflow_ref,
        "host_id": host_id,
        "resource_status": resource_status,
        "content_digest": report.get("content_digest"),
        "report_id": report.get("report_id"),
        "spc_version": producer.get("spc_version"),
        "produced_at": producer.get("produced_at"),
        "source_path": str(source_path) if source_path else None,
        "verified": bool(verify),
    }
    artifact = manager.record(
        topic_id=topic_id,
        stage=RESOURCE_READY_STAGE,
        artifact_type=RESOURCE_READY_ARTIFACT_TYPE,
        title=f"SPC resource-ready {workflow_ref} @ {host_id} [{resource_status}]",
        path=str(source_path) if source_path else "",
        payload=dict(report),
        metadata=metadata,
        supersede_previous=False,
    )
    return {
        "artifact_id": artifact.id,
        "binding_key": binding_key,
        "workflow_ref": workflow_ref,
        "host_id": host_id,
        "resource_status": resource_status,
        "version": artifact.version,
        "content_digest": report.get("content_digest"),
        "verified": bool(verify),
        "superseded_artifact_ids": superseded,
    }


def get_ready(
    db: Database, topic_id: int, workflow_ref: str, host_id: str
) -> dict[str, Any] | None:
    """Return the single active resource-ready binding, or ``None`` if unbound."""

    binding_key = compute_binding_key(topic_id, workflow_ref, host_id)
    manager = ArtifactManager(db)
    matches = _active_binding_matches(manager, topic_id, binding_key)
    if not matches:
        return None
    # Single-active is the invariant; if a stray duplicate exists, prefer the
    # highest version so callers still get the newest binding.
    best = max(matches, key=lambda a: (a.version, a.id or 0))
    return {
        "found": True,
        "artifact_id": best.id,
        "binding_key": binding_key,
        "workflow_ref": workflow_ref,
        "host_id": host_id,
        "resource_status": best.metadata.get("resource_status"),
        "version": best.version,
        "content_digest": best.metadata.get("content_digest"),
        "source_path": best.metadata.get("source_path"),
        "created_at": best.created_at,
        "report": best.payload,
    }


def ready_status_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the path-free status projection allowed on user-visible surfaces."""

    public_fields = (
        "found",
        "artifact_id",
        "binding_key",
        "workflow_ref",
        "host_id",
        "resource_status",
        "version",
        "content_digest",
        "created_at",
    )
    return {key: result.get(key) for key in public_fields}
