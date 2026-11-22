"""Paper-production convenience CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from research_harness.config import default_state_dir


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], object],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register paper-production entry commands."""

    @main.group("paper-production")
    def paper_production_group() -> None:
        """Prepare a paper-production run from topic and target venue."""

    @paper_production_group.command("plan")
    @click.option("--topic", required=True, help="Broad research topic.")
    @click.option("--target-venue", required=True, help="Target journal or venue.")
    @click.option(
        "--mode",
        type=click.Choice(["explore", "standard", "strict", "demo"]),
        default="standard",
    )
    @click.option(
        "--local-only",
        is_flag=True,
        default=False,
        help="Use only the local paper pool for evidence acquisition planning.",
    )
    @click.pass_context
    def paper_production_plan(
        ctx: click.Context,
        topic: str,
        target_venue: str,
        mode: str,
        local_only: bool,
    ) -> None:
        """Preview the paper-production context without creating local state."""
        from .auto_runner.paper_production_entry import plan_paper_production_entry

        result = plan_paper_production_entry(
            topic=topic,
            target_venue=target_venue,
            mode=mode,
            local_only=local_only,
        )
        echo(ctx, result, _text_summary(result))

    @paper_production_group.command("preflight")
    @click.option("--topic", required=True, help="Topic id, name, or description.")
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.option(
        "--workspace-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Workspace directory to inspect for this topic.",
    )
    @click.option(
        "--duplicate-workspace-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Optional duplicate workspace path to warn about.",
    )
    @click.pass_context
    def paper_production_preflight(
        ctx: click.Context,
        topic: str,
        state_dir: Path | None,
        workspace_dir: Path | None,
        duplicate_workspace_dir: Path | None,
    ) -> None:
        """Inspect local paper-production state without running stages."""
        from .auto_runner.paper_production_entry import preflight_paper_production_topic

        db = _db_for_state_dir(ctx, state_dir, get_db)
        result = preflight_paper_production_topic(
            db=db,
            topic=topic,
            base_dir=state_dir,
            workspace_dir=workspace_dir,
            duplicate_workspace_dir=duplicate_workspace_dir,
        )
        echo(ctx, result, _text_summary(result))

    @paper_production_group.command("start")
    @click.option(
        "--topic",
        required=True,
        help="Topic id, name, or description (existing topics are reused, not duplicated).",
    )
    @click.option("--target-venue", required=True, help="Target journal or venue.")
    @click.option(
        "--mode",
        type=click.Choice(["explore", "standard", "strict", "demo"]),
        default="standard",
    )
    @click.option(
        "--interaction-mode",
        type=click.Choice(["autonomous", "checkpoint", "interactive"]),
        default=None,
        help=(
            "Unified interaction mode: autonomous (AI makes all decisions), "
            "checkpoint (pause at decision points), interactive (ask questions). "
            "Overrides --mode if specified."
        ),
    )
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.option(
        "--local-only",
        is_flag=True,
        default=False,
        help="Use only the local paper pool for evidence acquisition.",
    )
    @click.pass_context
    def paper_production_start(
        ctx: click.Context,
        topic: str,
        target_venue: str,
        mode: str,
        interaction_mode: str | None,
        state_dir: Path | None,
        local_only: bool,
    ) -> None:
        """Create local topic/run/checkpoint state for paper production."""
        from .auto_runner.interaction_mode import (
            interaction_mode_description,
            resolve_interaction_mode,
        )
        from .auto_runner.paper_production_entry import prepare_paper_production_entry

        db = _db_for_state_dir(ctx, state_dir, get_db)

        # Store interaction_mode in result for display
        resolved_mode = resolve_interaction_mode(
            mode=mode, interaction_mode=interaction_mode
        )
        if interaction_mode and ctx.obj.get("json"):
            click.echo(
                f"# Using interaction mode: {resolved_mode}\n# {interaction_mode_description(resolved_mode)}",
                err=True,
            )

        result = prepare_paper_production_entry(
            db=db,
            topic=topic,
            target_venue=target_venue,
            mode=mode,
            base_dir=state_dir,
            local_only=local_only,
        )
        if interaction_mode:
            result["interaction_mode"] = resolved_mode
        echo(ctx, result, _text_summary(result))

    @paper_production_group.command("run")
    @click.option("--topic", required=True, help="Broad research topic.")
    @click.option("--target-venue", required=True, help="Target journal or venue.")
    @click.option(
        "--mode",
        type=click.Choice(["explore", "standard", "strict", "demo"]),
        default="demo",
    )
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.option(
        "--execute",
        is_flag=True,
        default=False,
        help="Run the real local auto-runner instead of only showing its plan.",
    )
    @click.option(
        "--auto-approve",
        is_flag=True,
        default=False,
        help="Auto-approve eligible non-high-risk checkpoints.",
    )
    @click.option(
        "--local-only",
        is_flag=True,
        default=False,
        help="Use only the local paper pool for evidence acquisition.",
    )
    @click.pass_context
    def paper_production_run(
        ctx: click.Context,
        topic: str,
        target_venue: str,
        mode: str,
        state_dir: Path | None,
        execute: bool,
        auto_approve: bool,
        local_only: bool,
    ) -> None:
        """Prepare state and invoke the real local auto-runner path."""
        from .auto_runner.paper_production_entry import run_paper_production_entry

        db = _db_for_state_dir(ctx, state_dir, get_db)
        result = run_paper_production_entry(
            db=db,
            topic=topic,
            target_venue=target_venue,
            mode=mode,
            base_dir=state_dir,
            dry_run=not execute,
            auto_approve=auto_approve,
            local_only=local_only,
        )
        echo(ctx, result, _text_summary(result))

    @paper_production_group.command("reset-run")
    @click.option("--topic", "topic_id", required=True, type=int, help="Topic id.")
    @click.option(
        "--stages",
        default="write,analysis",
        help="Comma-separated stages whose content artifacts are superseded.",
    )
    @click.option(
        "--types",
        "types_override",
        default=None,
        help="Comma-separated artifact types to reset (overrides the default set).",
    )
    @click.option(
        "--section",
        "sections",
        multiple=True,
        help=(
            "Narrow section_draft supersede to sections matching this name "
            "(repeatable). Assembly artifacts in scope are still superseded."
        ),
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="List what would be superseded without changing anything.",
    )
    @click.pass_context
    def paper_production_reset_run(
        ctx: click.Context,
        topic_id: int,
        stages: str,
        types_override: str | None,
        sections: tuple[str, ...],
        dry_run: bool,
    ) -> None:
        """Supersede prior-run manuscript artifacts in one pass.

        Marks active manuscript-content artifacts (draft packs, bundles,
        figure plans, knowledge snapshots, ...) as superseded and invalidates
        the cached topic literature overview, so a rerun starts from clean
        state instead of chasing stale consistency findings one source at a
        time. Decision history (gate_decision, rollback_event,
        provenance_record, human_feedback_record) is never touched.
        """
        from ._workflow.execution.artifact_reset import (
            supersede_manuscript_artifacts,
        )
        from ._workflow.execution.compiled_summary import invalidate_topic_summary

        stage_list = [s.strip() for s in stages.split(",") if s.strip()]
        reset_types = (
            {t.strip() for t in types_override.split(",") if t.strip()}
            if types_override
            else None
        )

        db = get_db(ctx)
        result = supersede_manuscript_artifacts(
            db,  # type: ignore[arg-type]
            topic_id=topic_id,
            stages=stage_list,
            types=reset_types,
            sections=list(sections) or None,
            dry_run=dry_run,
        )
        affected = result["superseded"]

        cache_invalidated = False
        if not dry_run:
            cache_invalidated = invalidate_topic_summary(db, topic_id)

        lines = [
            f"[{a['id']}] {a['type']} v{a['version']} stage={a['stage']}"
            for a in affected
        ]
        verb = "would supersede" if dry_run else "superseded"
        message = (
            f"{verb} {len(affected)} artifacts"
            + (", summary cache invalidated" if cache_invalidated else "")
            + (
                "\nWARNING: no section_draft matched the --section filter; "
                "all in-scope section drafts included"
                if result.get("section_match_fallback")
                else ""
            )
            + ("\n" + "\n".join(lines) if lines else "")
        )
        echo(
            ctx,
            {
                "topic_id": topic_id,
                "dry_run": dry_run,
                "superseded": affected,
                "section_filter": result.get("section_filter", []),
                "section_match_fallback": result.get("section_match_fallback", False),
                "summary_cache_invalidated": cache_invalidated,
            },
            message,
        )

    @paper_production_group.command("commit-version")
    @click.option("--topic", "topic_id", required=True, type=int, help="Topic id.")
    @click.option(
        "--tex",
        "tex_path",
        required=True,
        type=click.Path(exists=True, dir_okay=False),
        help="Manuscript TeX file to hash and record as draft_pack.",
    )
    @click.option(
        "--pdf",
        "pdf_path",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Compiled PDF to record as final_bundle.",
    )
    @click.option("--stage", default="write", help="Orchestrator stage.")
    @click.option("--title", default="", help="Artifact title.")
    @click.option(
        "--quality-report",
        "quality_report_path",
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="JSON file recorded as final_bundle_quality_report.",
    )
    @click.option(
        "--depends-on",
        "depends_on",
        multiple=True,
        type=int,
        help="Upstream artifact ids; commit is rejected if any is not active.",
    )
    @click.option("--notes", default="", help="Free-form change notes.")
    @click.option(
        "--force-reason",
        default="",
        help=(
            "Record an audited human override when gate findings would "
            "otherwise block the commit."
        ),
    )
    @click.pass_context
    def paper_production_commit_version(
        ctx: click.Context,
        topic_id: int,
        tex_path: str,
        pdf_path: str | None,
        stage: str,
        title: str,
        quality_report_path: str | None,
        depends_on: tuple[int, ...],
        notes: str,
        force_reason: str,
    ) -> None:
        """Commit one manuscript version as an atomic artifact trio.

        Hashes the TeX/PDF, records draft_pack + final_bundle (+ quality
        report) with lineage wired between them, and refuses to commit
        against superseded dependencies — replacing the manual shasum +
        three-record-call sequence per version.
        """
        import json as _json

        from .orchestrator.service import OrchestratorService

        quality_report = None
        if quality_report_path:
            quality_report = _json.loads(
                Path(quality_report_path).read_text(encoding="utf-8")
            )

        db = get_db(ctx)
        result = OrchestratorService(db).commit_manuscript_version(  # type: ignore[arg-type]
            topic_id=topic_id,
            tex_path=tex_path,
            pdf_path=pdf_path or "",
            stage=stage,
            title=title,
            quality_report=quality_report,
            dependency_artifact_ids=list(depends_on) or None,
            notes=notes,
            force_reason=force_reason,
        )
        if not result.get("success"):
            lines = [f"commit rejected: {result.get('error')}"]
            for finding in result.get("gate_findings") or []:
                if isinstance(finding, dict):
                    lines.append(
                        f"- [{finding.get('severity')}] {finding.get('check')}: "
                        f"{finding.get('message')}"
                    )
            echo(ctx, result, "\n".join(lines))
            raise SystemExit(1)
        parts = [
            f"draft_pack v{result['draft_pack']['version']} "
            f"(#{result['draft_pack']['artifact_id']})"
        ]
        if "final_bundle" in result:
            parts.append(
                f"final_bundle v{result['final_bundle']['version']} "
                f"(#{result['final_bundle']['artifact_id']})"
            )
        if "final_bundle_quality_report" in result:
            parts.append(
                "quality_report v"
                f"{result['final_bundle_quality_report']['version']} "
                f"(#{result['final_bundle_quality_report']['artifact_id']})"
            )
        echo(ctx, result, "committed " + ", ".join(parts))

    @paper_production_group.command("status")
    @click.option("--topic", required=True, type=int, help="Topic id.")
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.pass_context
    def paper_production_status(
        ctx: click.Context,
        topic: int,
        state_dir: Path | None,
    ) -> None:
        """Show paper-production status from the local auto-runner checkpoint.

        This reads the *local checkpoint* state surface, which can go stale
        while the authoritative orchestrator run advances. The surface is named
        in the output and any stage divergence is reported rather than silently
        resolved.
        """
        from .auto_runner.runner import get_status

        db = _db_for_state_dir(ctx, state_dir, get_db)
        db_path = Path(str(db.db_path)) if getattr(db, "db_path", None) else None
        result = get_status(topic, base_dir=state_dir, db_path=db_path)
        _annotate_local_checkpoint_surface(
            result,
            db=db,
            topic_id=topic,
            state_dir=state_dir,
            db_path=db_path,
        )
        echo(ctx, result, _paper_production_status_text(result))

    @paper_production_group.command("decide")
    @click.option("--topic", required=True, type=int, help="Topic id.")
    @click.option(
        "--action",
        required=True,
        help=(
            "Decision action to record; validated against the pending "
            "decision's options (e.g. broaden_search, add_papers_manually, "
            "select_direction_2, stop)."
        ),
    )
    @click.option(
        "--reasoning", default="", help="Reasoning to store with the decision."
    )
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.pass_context
    def paper_production_decide(
        ctx: click.Context,
        topic: int,
        action: str,
        reasoning: str,
        state_dir: Path | None,
    ) -> None:
        """Record a human decision for a paused paper-production run."""
        from .auto_runner.runner import decide_human_checkpoint

        db = _db_for_state_dir(ctx, state_dir, get_db)
        result = decide_human_checkpoint(
            topic,
            choice=action,
            reasoning=reasoning,
            base_dir=state_dir,
            db=db,
        )
        echo(ctx, result, _text_summary(result))

    @paper_production_group.command("resume")
    @click.option("--topic", required=True, type=int, help="Topic id.")
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.option(
        "--auto-approve",
        is_flag=True,
        default=False,
        help="Auto-approve eligible non-high-risk checkpoints.",
    )
    @click.pass_context
    def paper_production_resume(
        ctx: click.Context,
        topic: int,
        state_dir: Path | None,
        auto_approve: bool,
    ) -> None:
        """Resume a paper-production run from checkpoint."""
        from .auto_runner.runner import resume_topic

        db = _db_for_state_dir(ctx, state_dir, get_db)
        result = resume_topic(
            topic,
            base_dir=state_dir,
            auto_approve=auto_approve,
            db=db,
        )
        echo(ctx, result, _text_summary(result))

    @paper_production_group.command("preview-chain")
    @click.option("--topic", required=True, help="Broad research topic.")
    @click.option("--target-venue", required=True, help="Target journal or venue.")
    @click.option(
        "--mode",
        type=click.Choice(["explore", "standard", "strict", "demo"]),
        default="demo",
    )
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.option(
        "--local-only",
        is_flag=True,
        default=False,
        help="Use only the local paper pool for evidence acquisition planning.",
    )
    @click.pass_context
    def paper_production_preview_chain(
        ctx: click.Context,
        topic: str,
        target_venue: str,
        mode: str,
        state_dir: Path | None,
        local_only: bool,
    ) -> None:
        """Prepare local state and run the fake init-to-build preview chain."""
        from .auto_runner.paper_production_entry import (
            prepare_paper_production_entry,
            preview_paper_production_execution_chain,
        )

        db = _db_for_state_dir(ctx, state_dir, get_db)
        prepared = prepare_paper_production_entry(
            db=db,
            topic=topic,
            target_venue=target_venue,
            mode=mode,
            base_dir=state_dir,
            local_only=local_only,
        )
        topic_payload = prepared.get("topic", {})
        checkpoint = prepared.get("checkpoint", {})
        topic_id = (
            int(topic_payload.get("id", 0)) if isinstance(topic_payload, dict) else 0
        )
        preview_base_dir = _base_dir_from_checkpoint(checkpoint) or state_dir
        preview = preview_paper_production_execution_chain(
            db=db,
            topic_id=topic_id,
            base_dir=preview_base_dir or default_state_dir(),
            mode=mode,
        )
        if isinstance(topic_payload, dict):
            preview["topic"] = topic_payload
        echo(ctx, preview, _text_summary(preview))


def _db_for_state_dir(
    ctx: click.Context,
    state_dir: Path | None,
    get_db: Callable[[click.Context], object],
) -> object:
    if state_dir is None:
        return get_db(ctx)

    from .storage.db import Database

    db = Database(state_dir / "pool.db")
    db.migrate()
    return db


def _annotate_local_checkpoint_surface(
    result: dict[str, object],
    *,
    db: object,
    topic_id: int,
    state_dir: Path | None,
    db_path: Path | None,
) -> None:
    """Label ``result`` as read from the local checkpoint state surface.

    Also compares the checkpoint stage against the authoritative orchestrator
    run so a stale checkpoint cannot be mistaken for the real run state. This
    is observability only: nothing here reads a different surface into the
    payload, and no run state is written.
    """
    from ._core.config import default_state_dir
    from .auto_runner import checkpoint as ckpt
    from .runtime.state_surface import (
        detect_checkpoint_divergence,
        local_checkpoint_surface_labels,
    )

    checkpoint_path = result.get("checkpoint_path")
    if not checkpoint_path:
        base_dir = state_dir if state_dir is not None else default_state_dir(db_path)
        checkpoint_path = str(ckpt.checkpoint_path(base_dir, topic_id))

    run = _orchestrator_run_for_divergence(db, topic_id)
    divergence = None
    if run is not None:
        divergence = detect_checkpoint_divergence(
            checkpoint_path=str(checkpoint_path),
            checkpoint_stage=result.get("current_stage"),
            orchestrator_run_id=getattr(run, "id", None),
            orchestrator_stage=getattr(run, "current_stage", None),
            orchestrator_stage_status=getattr(run, "stage_status", None),
        )
    result.update(
        local_checkpoint_surface_labels(
            checkpoint_path=str(checkpoint_path),
            divergence=divergence,
        )
    )


def _orchestrator_run_for_divergence(db: object, topic_id: int) -> object | None:
    """Read-only peek at the authoritative run, for divergence reporting only."""
    from .orchestrator.service import OrchestratorService

    try:
        return OrchestratorService(db).get_run(topic_id)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - diagnostics must never break status
        return None


def _paper_production_status_text(result: dict[str, object]) -> str:
    """Human summary for ``paper-production status``, always naming the surface."""
    human_decision = result.get("human_decision")
    if isinstance(human_decision, dict) and human_decision.get("requested"):
        base = _text_summary(result)
    else:
        base = (
            f"Paper-production status for topic {result.get('topic_id')}: "
            f"{result.get('status', 'unknown')}"
            f"\nStage: {result.get('current_stage', '?')} "
            f"[{result.get('stage_state', '?')}]"
        )
    from .runtime.state_surface import append_state_surface_text

    return append_state_surface_text(base, result)


def _text_summary(result: dict[str, object]) -> str:
    if result.get("schema_version") == "rh.paper_production_decision.v1":
        next_commands = result.get("next_commands")
        next_line = ""
        if isinstance(next_commands, list) and next_commands:
            next_line = f"\nNext: {next_commands[0]}"
        return (
            f"Paper-production decision for topic {result.get('topic_id')}: "
            f"{result.get('status')}."
            f"\nChoice: {result.get('choice')}"
            f"\n{result.get('summary', '')}"
            f"{next_line}"
        )

    human_decision = result.get("human_decision")
    if isinstance(human_decision, dict) and human_decision.get("requested"):
        options = human_decision.get("options")
        option_text = ""
        if isinstance(options, list):
            labels = []
            for option in options:
                if isinstance(option, dict) and option.get("action"):
                    marker = " (recommended)" if option.get("recommended") else ""
                    labels.append(f"{option['action']}{marker}")
            option_text = ", ".join(labels)
        next_commands = result.get("next_commands")
        next_line = ""
        if isinstance(next_commands, list) and next_commands:
            next_line = f"\nNext: {next_commands[1] if len(next_commands) > 1 else next_commands[0]}"
        return (
            f"Paper-production is waiting for a human decision for topic {result.get('topic_id')}."
            f"\nReason: {human_decision.get('reason_code', 'unknown')}"
            f"\nOptions: {option_text or 'none'}"
            f"{next_line}"
        )

    if result.get("schema_version") == "rh.paper_production_preflight.v1":
        topic = result.get("topic")
        topic_id = "missing"
        if isinstance(topic, dict) and topic.get("id"):
            topic_id = str(topic["id"])
        blockers = result.get("blockers")
        blocker_text = (
            ", ".join(str(item) for item in blockers)
            if isinstance(blockers, list)
            else ""
        )
        return (
            f"Paper-production preflight for topic {topic_id}: "
            f"{result.get('classification', 'unknown')}."
            f"\nBlockers: {blocker_text or 'none'}"
            "\nExternal actions: none"
        )

    if result.get("schema_version") == "rh.paper_production_run.v1":
        runner = result.get("runner")
        prepared = result.get("prepared")
        topic_id = "unknown"
        if isinstance(prepared, dict):
            topic = prepared.get("topic")
            if isinstance(topic, dict) and topic.get("id"):
                topic_id = str(topic["id"])
        summary = runner.get("summary", "") if isinstance(runner, dict) else ""
        return (
            f"Paper-production run prepared for topic {topic_id}."
            f"\nAction: {result.get('action')}"
            f"\n{summary}"
            "\nExternal actions: none"
        )

    if result.get("schema_version") == "rh.paper_production_execution_chain_preview.v1":
        topic = result.get("topic")
        checkpoint = result.get("checkpoint")
        stages = result.get("stages")
        topic_id = result.get("topic_id")
        stage_text = (
            " -> ".join(str(stage) for stage in stages)
            if isinstance(stages, list)
            else ""
        )
        checkpoint_line = ""
        if isinstance(checkpoint, dict) and checkpoint.get("path"):
            checkpoint_line = f"\nCheckpoint: {checkpoint['path']}"
        if isinstance(topic, dict) and topic.get("id"):
            topic_id = topic["id"]
        return (
            f"Paper-production fake preview complete for topic {topic_id}."
            f"\nStages: {stage_text or 'init -> build'}"
            f"{checkpoint_line}"
            "\nExternal actions: none"
        )

    topic = result.get("topic")
    run = result.get("run")
    checkpoint = result.get("checkpoint")
    next_commands = result.get("next_commands")
    if not isinstance(topic, dict) or not isinstance(run, dict):
        return "Paper-production entry prepared"
    topic_id = topic.get("id") or "new"
    stage = run.get("current_stage") or "init"
    next_line = ""
    if isinstance(next_commands, list) and next_commands:
        next_line = f"\nNext: {next_commands[0]}"
    if isinstance(checkpoint, dict) and checkpoint.get("path"):
        return (
            f"Paper-production topic {topic_id} prepared at stage {stage}. "
            f"Checkpoint: {checkpoint['path']}"
            f"{next_line}"
        )
    return f"Paper-production topic {topic_id} planned at stage {stage}.{next_line}"


def _base_dir_from_checkpoint(checkpoint: object) -> Path | None:
    if not isinstance(checkpoint, dict) or not checkpoint.get("path"):
        return None
    path = Path(str(checkpoint["path"]))
    try:
        return path.parents[2]
    except IndexError:
        return None
