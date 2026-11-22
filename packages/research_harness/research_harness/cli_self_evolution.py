"""Self-evolution command group for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def _self_evolution_archive_summary_text(payload: dict[str, object]) -> str:
    lines = [
        "Self-evolution archive assembled",
        f"records: {int(payload.get('record_count') or 0)}",
        f"champions: {int(payload.get('champion_entry_count') or 0)}",
        f"mutation_performed: {bool(payload.get('mutation_performed'))}",
    ]
    archive_id = payload.get("archive_artifact_id")
    champion_id = payload.get("champion_artifact_id")
    if archive_id:
        lines.append(f"candidate_archive_pack: {archive_id}")
    if champion_id:
        lines.append(f"champion_registry_pack: {champion_id}")
    return "\n".join(lines)


def _normalize_rfb_score_report_payload(
    raw: object,
    *,
    benchmark_id: str,
    split: str,
    score_file: Path,
) -> dict[str, object]:
    if isinstance(raw, list):
        return {
            "schema_version": "researchflowbench.score_report.v0.1",
            "benchmark_id": benchmark_id,
            "split": split,
            "scores": raw,
            "source_file": str(score_file),
        }
    if not isinstance(raw, dict):
        return {}
    scores = raw.get("scores") or raw.get("task_scores") or raw.get("results")
    normalized_scores = scores if isinstance(scores, list) else []
    resolved_benchmark_id = str(raw.get("benchmark_id") or benchmark_id)
    return {
        "schema_version": str(
            raw.get("schema_version") or "researchflowbench.score_report.v0.1"
        ),
        **raw,
        "benchmark_id": resolved_benchmark_id,
        "split": str(raw.get("split") or split),
        "scores": normalized_scores,
        "source_file": str(raw.get("source_file") or score_file),
    }


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register self-evolution commands on the root CLI group."""

    @main.group("self-evolution")
    def self_evolution_group() -> None:
        """Project-level self-evolution evidence management."""

    @self_evolution_group.command("archive-from-artifacts")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--limit", type=int, default=100, help="Maximum source artifacts to read"
    )
    @click.option(
        "--stage",
        default="project_self_evolution",
        help="Stage for generated archive artifacts",
    )
    @click.pass_context
    def self_evolution_archive_from_artifacts_cli(
        ctx: click.Context,
        topic_name: str,
        limit: int,
        stage: str,
    ) -> None:
        """Build candidate archive and champion registry packs from eval artifacts."""
        from .evolution.harness import record_self_evolution_archive_from_artifacts
        from .orchestrator.service import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        payload = record_self_evolution_archive_from_artifacts(
            OrchestratorService(db),
            db,
            topic_id=topic_id,
            stage=stage,
            limit=limit,
        )
        echo(ctx, payload, _self_evolution_archive_summary_text(payload))

    @self_evolution_group.command("record-rfb-score-report")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--score-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="JSON file containing a ResearchFlowBench score report or score list.",
    )
    @click.option(
        "--benchmark-id",
        default="",
        help="Benchmark id when the score file does not include one.",
    )
    @click.option(
        "--split",
        default="mutate_dev",
        help="Replay split role for scores that do not specify one.",
    )
    @click.option("--title", default="", help="Artifact title")
    @click.pass_context
    def self_evolution_record_rfb_score_report_cli(
        ctx: click.Context,
        topic_name: str,
        score_file: Path,
        benchmark_id: str,
        split: str,
        title: str,
    ) -> None:
        """Record a local ResearchFlowBench score JSON as a durable artifact."""
        from .orchestrator.service import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        raw = json.loads(score_file.read_text(encoding="utf-8"))
        payload = _normalize_rfb_score_report_payload(
            raw,
            benchmark_id=benchmark_id,
            split=split,
            score_file=score_file,
        )
        if not payload.get("benchmark_id"):
            raise click.ClickException(
                "benchmark_id is required in the score file or via --benchmark-id"
            )
        if not payload.get("scores"):
            raise click.ClickException("score report must contain at least one score")

        artifact = OrchestratorService(db).record_artifact(
            topic_id=topic_id,
            stage="project_self_evolution",
            artifact_type="researchflowbench_score_report",
            title=title or f"ResearchFlowBench score report: {payload['benchmark_id']}",
            payload=payload,
            metadata={
                "source": "researchflowbench",
                "benchmark_id": payload["benchmark_id"],
                "score_count": len(payload["scores"]),
            },
        )
        result = {
            "schema_version": 1,
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "benchmark_id": payload["benchmark_id"],
            "score_count": len(payload["scores"]),
        }
        echo(
            ctx,
            result,
            (
                "Recorded ResearchFlowBench score report "
                f"{artifact.id}: {payload['benchmark_id']} ({len(payload['scores'])} scores)"
            ),
        )

    @self_evolution_group.command("record-rfb-gate-report")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--gate-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="JSON file containing a ResearchFlowBench score comparison gate.",
    )
    @click.option("--title", default="", help="Artifact title")
    @click.pass_context
    def self_evolution_record_rfb_gate_report_cli(
        ctx: click.Context,
        topic_name: str,
        gate_file: Path,
        title: str,
    ) -> None:
        """Record a ResearchFlowBench optimization gate as a durable artifact."""
        from .orchestrator.service import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        payload = json.loads(gate_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise click.ClickException("gate report must be a JSON object")
        if not str(payload.get("schema_version") or "").startswith(
            "researchflowbench.score_comparison_gate"
        ):
            raise click.ClickException(
                "gate report schema_version must be researchflowbench.score_comparison_gate*"
            )

        artifact = OrchestratorService(db).record_artifact(
            topic_id=topic_id,
            stage="project_self_evolution",
            artifact_type="researchflowbench_score_comparison_gate",
            title=title or f"ResearchFlowBench gate: {payload.get('benchmark_id', '')}",
            path=str(gate_file),
            payload=payload,
            metadata={
                "source": "researchflowbench",
                "benchmark_id": str(payload.get("benchmark_id") or ""),
                "status": str(payload.get("status") or ""),
                "baseline_id": str(payload.get("baseline_id") or ""),
                "candidate_id": str(payload.get("candidate_id") or ""),
            },
        )
        result = {
            "schema_version": 1,
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "benchmark_id": str(payload.get("benchmark_id") or ""),
            "status": str(payload.get("status") or ""),
            "candidate_id": str(payload.get("candidate_id") or ""),
        }
        echo(
            ctx,
            result,
            (
                "Recorded ResearchFlowBench gate report "
                f"{artifact.id}: {payload.get('benchmark_id', '')} "
                f"status={payload.get('status', '')}"
            ),
        )

    @self_evolution_group.command("record-human-feedback")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--stage", required=True, help="Workflow stage or surface receiving feedback"
    )
    @click.option("--section", default="", help="Section, module, or quality surface")
    @click.option(
        "--feedback-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Text or JSON file containing human feedback.",
    )
    @click.option(
        "--workspace-path", default="", help="RH workspace path where feedback occurred"
    )
    @click.option(
        "--agent",
        "agent_name",
        default="",
        help="Agent receiving feedback, e.g. claude-code or codex",
    )
    @click.option(
        "--trigger-class", default="human_feedback", help="Feedback trigger class"
    )
    @click.pass_context
    def self_evolution_record_human_feedback_cli(
        ctx: click.Context,
        topic_name: str,
        stage: str,
        section: str,
        feedback_file: Path,
        workspace_path: str,
        agent_name: str,
        trigger_class: str,
    ) -> None:
        """Record human feedback as durable RH self-evolution experience."""
        from .evolution.topic.experience import ExperienceRecord, ExperienceStore
        from .orchestrator.service import OrchestratorService

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        raw_text = feedback_file.read_text(encoding="utf-8")
        metadata: dict[str, Any] = {
            "schema_version": "rh.human_feedback.v1",
            "feedback_file": str(feedback_file),
            "workspace_path": workspace_path,
            "agent": agent_name,
            "trigger_class": trigger_class,
            "source": "rh self-evolution record-human-feedback",
        }
        feedback_text = raw_text.strip()
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            feedback_text = str(
                parsed.get("feedback")
                or parsed.get("text")
                or parsed.get("message")
                or raw_text
            ).strip()
            metadata["payload"] = parsed

        record = ExperienceRecord(
            source_kind="human_edit",
            stage=stage,
            section=section,
            after_text=feedback_text,
            diff_summary=feedback_text,
            topic_id=topic_id,
            metadata=metadata,
            gate_verdict="pending",
        )
        record_id = ExperienceStore(db).ingest(record)
        stored = ExperienceStore(db).get(record_id)
        lesson_id = stored.lesson_id if stored is not None else None
        artifact_payload = {
            "schema_version": "rh.human_feedback.v1",
            "experience_record_id": record_id,
            "lesson_id": lesson_id,
            "topic_id": topic_id,
            "stage": stage,
            "section": section,
            "workspace_path": workspace_path,
            "agent": agent_name,
            "trigger_class": trigger_class,
            "feedback_excerpt": feedback_text[:500],
        }
        artifact = OrchestratorService(db).record_artifact(
            topic_id=topic_id,
            stage="project_self_evolution",
            artifact_type="human_feedback_record",
            title=f"Human feedback: {stage}/{section or 'general'}",
            path=str(feedback_file),
            payload=artifact_payload,
            metadata={
                "source": "human_feedback",
                "agent": agent_name,
                "trigger_class": trigger_class,
                "experience_record_id": record_id,
            },
        )
        result = {
            "schema_version": "rh.self_evolution.record_human_feedback.v1",
            "topic_id": topic_id,
            "experience_record_id": record_id,
            "lesson_id": lesson_id,
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "stage": stage,
            "section": section,
            "agent": agent_name,
            "trigger_class": trigger_class,
        }
        echo(
            ctx,
            result,
            (
                "Recorded human feedback "
                f"experience={record_id} lesson={lesson_id or 'pending'} artifact={artifact.id}"
            ),
        )

    @self_evolution_group.command("record-note")
    @click.option(
        "--topic",
        "topic_name",
        default="",
        help="Optional topic name; omit for project-level self-dev notes",
    )
    @click.option(
        "--stage",
        default="project_self_evolution",
        help="Stage label for the note (default: project_self_evolution)",
    )
    @click.option(
        "--section",
        default="self_dev_note",
        help="Section / surface the note is about",
    )
    @click.option(
        "--note", default="", help="Note text (mutually exclusive with --note-file)"
    )
    @click.option(
        "--note-file",
        "note_file",
        default=None,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="Path to a text/JSON note file",
    )
    @click.option(
        "--agent",
        "agent_name",
        default="",
        help="Agent writing the note, e.g. claude-code or codex",
    )
    @click.option(
        "--trigger-class",
        default="self_dev_reflection",
        help="Capture trigger class",
    )
    @click.pass_context
    def self_evolution_record_note_cli(
        ctx: click.Context,
        topic_name: str,
        stage: str,
        section: str,
        note: str,
        note_file: Path | None,
        agent_name: str,
        trigger_class: str,
    ) -> None:
        """Record a non-MCP self-dev note into experience_records (D3)."""
        from .evolution.topic.experience import ExperienceRecord, ExperienceStore

        note_text = (note or "").strip()
        note_path = note_file if isinstance(note_file, Path) else None
        if note_path is not None:
            raw = note_path.read_text(encoding="utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                note_text = str(
                    parsed.get("note")
                    or parsed.get("text")
                    or parsed.get("message")
                    or raw
                ).strip()
            else:
                note_text = raw.strip()
        if not note_text:
            raise click.UsageError(
                "Provide --note or an existing --note-file with content"
            )

        db = get_db(ctx)
        topic_id: int | None = None
        if topic_name.strip():
            conn = db.connect()
            try:
                topic_id = topic_id_or_exit(conn, topic_name.strip())
            finally:
                conn.close()

        metadata: dict[str, Any] = {
            "schema_version": "rh.self_dev_note.v1",
            "agent": agent_name,
            "trigger_class": trigger_class,
            "source": "rh self-evolution record-note",
            "topic_name": topic_name.strip(),
        }
        if note_path is not None:
            metadata["note_file"] = str(note_path)

        record = ExperienceRecord(
            source_kind="auto_extracted",
            stage=stage or "project_self_evolution",
            section=section or "self_dev_note",
            after_text=note_text,
            diff_summary=note_text[:500],
            topic_id=topic_id,
            metadata=metadata,
            gate_verdict="pending",
        )
        record_id = ExperienceStore(db).ingest(record)
        stored = ExperienceStore(db).get(record_id)
        lesson_id = stored.lesson_id if stored is not None else None

        artifact_id = None
        if topic_id is not None:
            from .orchestrator.service import OrchestratorService

            artifact = OrchestratorService(db).record_artifact(
                topic_id=topic_id,
                stage="project_self_evolution",
                artifact_type="self_dev_note",
                title=f"Self-dev note: {section or 'general'}",
                path=str(note_path) if note_path is not None else "",
                payload={
                    "schema_version": "rh.self_dev_note.v1",
                    "experience_record_id": record_id,
                    "lesson_id": lesson_id,
                    "note_excerpt": note_text[:500],
                    "agent": agent_name,
                    "trigger_class": trigger_class,
                },
                metadata={
                    "source": "self_dev_note",
                    "agent": agent_name,
                    "experience_record_id": record_id,
                },
            )
            artifact_id = artifact.id

        result = {
            "schema_version": "rh.self_evolution.record_note.v1",
            "topic_id": topic_id,
            "experience_record_id": record_id,
            "lesson_id": lesson_id,
            "artifact_id": artifact_id,
            "stage": stage,
            "section": section,
            "agent": agent_name,
            "trigger_class": trigger_class,
        }
        echo(
            ctx,
            result,
            (
                "Recorded self-dev note "
                f"experience={record_id} lesson={lesson_id or 'pending'}"
                + (f" artifact={artifact_id}" if artifact_id is not None else "")
            ),
        )

    @self_evolution_group.command("trajectory-list")
    @click.option("--topic", "topic_name", default="", help="Optional topic filter")
    @click.option("--stage", default="", help="Optional stage filter")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.pass_context
    def self_evolution_trajectory_list_cli(
        ctx: click.Context,
        topic_name: str,
        stage: str,
        limit: int,
    ) -> None:
        """List raw trajectory sessions (D5 direct-trace path)."""
        from .evolution.topic.trajectory import TrajectoryRecorder

        db = get_db(ctx)
        topic_id: int | None = None
        if topic_name.strip():
            conn = db.connect()
            try:
                topic_id = topic_id_or_exit(conn, topic_name.strip())
            finally:
                conn.close()
        sessions = TrajectoryRecorder.list_sessions(
            db, topic_id=topic_id, stage=stage, limit=max(1, limit)
        )
        payload = {
            "schema_version": "rh.self_evolution.trajectory_list.v1",
            "topic_id": topic_id,
            "stage": stage,
            "sessions": sessions,
            "count": len(sessions),
        }
        echo(
            ctx,
            payload,
            f"trajectory sessions: {len(sessions)}"
            + (
                ""
                if not sessions
                else "\n"
                + "\n".join(
                    f"- {s['session_id']} events={s['event_count']} fails={s['fail_count']}"
                    for s in sessions[:10]
                )
            ),
        )

    @self_evolution_group.command("trajectory-show")
    @click.option("--session", "session_id", required=True, help="Session id")
    @click.option("--limit", default=200, show_default=True, type=int)
    @click.pass_context
    def self_evolution_trajectory_show_cli(
        ctx: click.Context,
        session_id: str,
        limit: int,
    ) -> None:
        """Show raw trajectory events for one session (no distillation)."""
        from .evolution.topic.trajectory import TrajectoryRecorder

        db = get_db(ctx)
        events = TrajectoryRecorder(db, session_id).get_session_trajectory(session_id)
        if limit > 0:
            events = events[:limit]
        text = TrajectoryRecorder.format_trajectory_text(events)
        payload = {
            "schema_version": "rh.self_evolution.trajectory_show.v1",
            "session_id": session_id,
            "event_count": len(events),
            "events": [
                {
                    "id": e.id,
                    "sequence_number": e.sequence_number,
                    "event_type": e.event_type,
                    "tool_name": e.tool_name,
                    "stage": e.stage,
                    "success": e.success,
                    "input_summary": e.input_summary,
                    "output_summary": e.output_summary,
                    "reasoning": e.reasoning,
                    "cost_usd": e.cost_usd,
                    "latency_ms": e.latency_ms,
                }
                for e in events
            ],
            "text": text,
        }
        echo(ctx, payload, text)

    @self_evolution_group.command("trajectory-diff")
    @click.option("--session-a", required=True, help="First session id")
    @click.option("--session-b", required=True, help="Second session id")
    @click.pass_context
    def self_evolution_trajectory_diff_cli(
        ctx: click.Context,
        session_a: str,
        session_b: str,
    ) -> None:
        """Diff two raw trajectory sessions (D5 run-diff face)."""
        from .evolution.topic.trajectory import TrajectoryRecorder

        db = get_db(ctx)
        diff = TrajectoryRecorder.diff_sessions(db, session_a, session_b)
        payload = {
            "schema_version": "rh.self_evolution.trajectory_diff.v1",
            **{k: v for k, v in diff.items() if k not in {"text_a", "text_b"}},
        }
        summary = (
            f"diff {session_a} vs {session_b}: "
            f"count={diff['count_a']}/{diff['count_b']} "
            f"only_a={len(diff['only_a'])} only_b={len(diff['only_b'])} "
            f"first_mismatch={diff['first_mismatch_index']}"
        )
        echo(ctx, payload, summary)
