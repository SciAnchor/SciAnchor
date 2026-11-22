"""Lightweight Python API — direct access to core functions without MCP.

Usage from Skills or scripts::

    from research_harness.api import ResearchAPI

    api = ResearchAPI()  # auto-resolves DB path
    api.record_artifact(topic_id=1, stage="init", artifact_type="topic_brief", payload={...})
    status = api.orchestrator_status(topic_id=1)
    papers = api.paper_search(query="attention", topic_id=1)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from .config import load_runtime_config
from .service import ResearchService
from .storage.db import Database
from .topic_workspace import discover_topic_id_from_workspace

logger = logging.getLogger(__name__)


_SERVICE_ROUTED_PRIMITIVES = {
    "paper_search",
    "paper_ingest",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "consistency_check",
}


class ResearchAPI:
    """Direct Python API for research harness — no MCP required."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path:
            self._db = Database(Path(db_path))
        else:
            config = load_runtime_config()
            self._db = Database(config.db_path)
        self._db.migrate()

    @property
    def db(self) -> Database:
        return self._db

    @property
    def db_path(self) -> Path:
        return self._db.db_path

    def record_artifact(
        self,
        topic_id: int,
        stage: str,
        artifact_type: str,
        title: str = "",
        payload: dict[str, Any] | None = None,
        dependency_artifact_ids: list[int] | None = None,
        dependency_type: str = "consumed_by",
    ) -> dict[str, Any]:
        """Record a topic artifact (equivalent to orchestrator_record_artifact MCP tool)."""
        output = self._invoke_service_output(
            "orchestrator_record_artifact",
            {
                "topic_id": topic_id,
                "stage": stage,
                "artifact_type": artifact_type,
                "title": title,
                "payload": payload,
                "dependency_artifact_ids": dependency_artifact_ids,
                "dependency_type": dependency_type,
            },
        )
        if not isinstance(output, dict):
            raise RuntimeError(
                "orchestrator_record_artifact returned an invalid payload"
            )
        return output

    def add_artifact_dependency(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        dependency_type: str = "consumed_by",
    ) -> dict[str, Any]:
        """Declare a dependency edge between two artifacts."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.add_artifact_dependency(
            from_artifact_id=from_artifact_id,
            to_artifact_id=to_artifact_id,
            dependency_type=dependency_type,
        )

    def mark_artifact_stale(
        self,
        artifact_id: int,
        reason: str = "",
        propagate: bool = True,
    ) -> dict[str, Any]:
        """Mark an artifact stale and optionally propagate downstream."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.mark_artifact_stale(
            artifact_id=artifact_id,
            reason=reason,
            propagate=propagate,
        )

    def clear_artifact_stale(self, artifact_id: int) -> dict[str, Any]:
        """Clear stale state on an artifact."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.clear_artifact_stale(artifact_id)

    def list_stale_artifacts(self, topic_id: int) -> list[dict[str, Any]]:
        """List stale artifacts for a topic."""
        from dataclasses import asdict

        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return [asdict(item) for item in svc.list_stale_artifacts(topic_id)]

    def orchestrator_status(self, topic_id: int) -> dict[str, Any]:
        """Get orchestrator status for a topic."""
        result = ResearchService(db=self._db).invoke(
            "orchestrator_status", {"topic_id": topic_id}
        )
        if result.status != "success":
            message = (result.error or {}).get("message") or result.summary
            raise RuntimeError(message or "orchestrator_status failed")
        if not isinstance(result.output, dict):
            raise RuntimeError("orchestrator_status returned an invalid payload")
        status = dict(result.output)
        status["db_path"] = str(self._db.db_path)
        return status

    def paper_production_sync_checkpoint(
        self,
        *,
        topic_id: int,
        state_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Sync checkpoint state to the DB run without executing any stage."""
        from .auto_runner.runner import sync_topic_checkpoint

        if isinstance(topic_id, bool) or not isinstance(topic_id, int) or topic_id <= 0:
            raise ValueError("topic_id must be a positive integer")
        return sync_topic_checkpoint(
            topic_id,
            base_dir=Path(state_dir) if state_dir is not None else None,
            db=self._db,
        )

    def gate_check(self, topic_id: int, stage: str | None = None) -> dict[str, Any]:
        """Check gate for current or specified stage."""
        arguments: dict[str, Any] = {"topic_id": topic_id}
        if stage:
            arguments["stage"] = stage
        result = ResearchService(db=self._db).invoke(
            "orchestrator_gate_check", arguments
        )
        if result.status != "success":
            message = (result.error or {}).get("message") or result.summary
            raise RuntimeError(message or "orchestrator_gate_check failed")
        if not isinstance(result.output, dict) or "gate_decision" not in result.output:
            raise RuntimeError("orchestrator_gate_check returned an invalid payload")
        return dict(result.output)

    def paper_search(self, query: str, **kwargs: Any) -> Any:
        """Search papers (delegates to paper_search primitive)."""
        return self._invoke_service_output(
            "paper_search",
            {"query": query, **kwargs},
        )

    def paper_ingest(self, source: str, **kwargs: Any) -> Any:
        """Ingest a paper (delegates to paper_ingest primitive)."""
        return self._invoke_service_output(
            "paper_ingest",
            {"source": source, **kwargs},
        )

    def wiki_context_pack(
        self,
        topic_id: int | None = None,
        workspace_path: str | Path | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build a read-only Research Wiki context-pack preflight payload."""
        resolved_topic_id = topic_id or discover_topic_id_from_workspace(workspace_path)
        if resolved_topic_id is None:
            return {
                "schema_version": "wiki_context_pack.v1",
                "topic_id": None,
                "paper_wiki_status": "not_triggered",
                "status_reason": "topic_id_not_resolved",
                "unavailable_reasons": [
                    "no topic_id was provided and no RH topic id was found in the requested workspace"
                ],
                "warnings": [],
                "preflight": {
                    "priority_evidence_layer": "",
                    "fallback_allowed": True,
                    "fallback_must_be_declared": True,
                },
                "pages": [],
            }
        output = self._invoke_service_output(
            "wiki_context_pack",
            {**kwargs, "topic_id": resolved_topic_id},
        )
        if not isinstance(output, dict):
            raise RuntimeError("wiki_context_pack returned an invalid payload")
        return output

    def delivery_paper_production_snapshot(
        self,
        *,
        topic_id: int | None = None,
        artifact_states: Mapping[str, str] | None = None,
        payloads: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build `rh.delivery.paper_production_snapshot.v1` as a dry run.

        `topic_id` reads recorded topic artifacts, `artifact_states` provides
        hypothetical overrides, and `payloads` supplies candidate artifact
        payloads for validation. The snapshot returns `dry_run=true` and does
        not call orchestrator_record_artifact, does not advance stages, does
        not write artifacts, and does not expose MCP, CLI, or HTTP transport.
        """
        output = self._invoke_service_output(
            "delivery_paper_production_snapshot",
            {
                "topic_id": topic_id,
                "artifact_states": artifact_states,
                "payloads": payloads,
            },
        )
        if not isinstance(output, dict):
            raise RuntimeError(
                "delivery_paper_production_snapshot returned an invalid payload"
            )
        return output

    def execute_primitive(self, name: str, **kwargs: Any) -> Any:
        """Execute any registered primitive by name."""
        if name in _SERVICE_ROUTED_PRIMITIVES:
            return self._invoke_service_output(name, dict(kwargs))

        from .primitives import get_primitive_impl

        impl = get_primitive_impl(name)
        if impl is None:
            raise ValueError(f"Unknown primitive: {name}")
        return impl(db=self._db, **kwargs)

    def _invoke_service_output(
        self,
        command_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        # A facade keyword left at None means "not given". The service's strict contract rejects an
        # explicit null for an optional property (37bac11), so an unset keyword is not sent at all.
        arguments = {
            key: value for key, value in arguments.items() if value is not None
        }
        result = ResearchService(db=self._db).invoke(command_name, arguments)
        if result.status == "success":
            return result.output
        message = (result.error or {}).get("message") or result.summary
        if (result.error or {}).get("code") == "UNKNOWN_COMMAND":
            raise ValueError(f"Unknown primitive: {command_name}")
        raise RuntimeError(message or f"{command_name} failed")
