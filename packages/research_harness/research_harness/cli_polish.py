"""CLI for first-class final-draft polish (终稿打磨).

``rh polish run`` orchestrates a multi-angle reviewer critique + RH's deterministic
and consistency QA into a prioritized-findings report with a submission-readiness
verdict (ready | needs_revision | blocked).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import click

_STAGE = "write"


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _print_findings(findings) -> None:
    icon = {"high": "!!", "medium": " *", "low": "  "}
    for f in findings:
        click.echo(
            f"  [{f.severity:6}]{icon.get(f.severity, '')} ({f.angle}/{f.location or '-'}) {f.issue[:96]}"
        )
        if f.fix:
            click.echo(f"           fix: {f.fix[:96]}")


def register(
    main: click.Group,
    get_db: Callable[[click.Context], Any],
    echo: Callable[..., None] | None = None,
) -> None:
    @main.group("polish")
    def polish() -> None:
        """Final-draft polish: reviewer-style critique + QA gates -> submission-readiness."""

    @polish.command("doctor")
    def doctor() -> None:
        from research_harness.primitives import registry as R

        names = sorted(
            n
            for n in R.PRIMITIVE_REGISTRY
            if n in ("manuscript_review", "manuscript_polish")
        )
        click.echo("primitives: " + ", ".join(names))
        click.echo("angles    : methods_stats, domain, editorial")

    @polish.command("review")
    @click.option("--manuscript-file", "mfile", required=True)
    @click.option("--venue", default="")
    @click.option("--angles", default=None, help="Comma-separated (default all three).")
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.pass_context
    def review(ctx, mfile, venue, angles, model, llm) -> None:
        """Multi-angle reviewer critique of a manuscript file."""
        if llm == "direct":
            import os

            os.environ["RH_EAG_LLM"] = "openai_direct"
        from research_harness.primitives.polish_impls import manuscript_review

        angle_list = [a.strip() for a in angles.split(",")] if angles else None
        try:
            out = manuscript_review(
                manuscript=_read(mfile), venue=venue, angles=angle_list, _model=model
            )
        except Exception as exc:
            raise click.ClickException("Manuscript review did not complete.") from exc
        click.echo(
            f"findings: {len(out.findings)} (high {out.n_high} / medium {out.n_medium} / low {out.n_low}) "
            f"across angles {out.angles} model={out.model_used}"
        )
        _print_findings(out.findings)

    @polish.command("run")
    @click.option("--manuscript-file", "mfile", required=True)
    @click.option(
        "--topic",
        type=int,
        default=None,
        help="Topic id (enables consistency_check + artifact recording).",
    )
    @click.option("--venue", default="")
    @click.option("--no-consistency", "no_consistency", is_flag=True, default=False)
    @click.option("--no-deterministic", "no_deterministic", is_flag=True, default=False)
    @click.option("--model", default=None)
    @click.option("--llm", type=click.Choice(["auto", "direct"]), default="auto")
    @click.option(
        "--record/--no-record",
        default=True,
        help="Record a manuscript_polish_report artifact.",
    )
    @click.option("--json", "as_json", is_flag=True, default=False)
    @click.pass_context
    def run(
        ctx,
        mfile,
        topic,
        venue,
        no_consistency,
        no_deterministic,
        model,
        llm,
        record,
        as_json,
    ) -> None:
        """Orchestrated final-draft polish -> prioritized findings + submission-readiness verdict."""
        if llm == "direct":
            import os

            os.environ["RH_EAG_LLM"] = "openai_direct"
        from research_harness.primitives.polish_impls import manuscript_polish
        from research_harness.primitives.types import _to_jsonable

        db = get_db(ctx) if topic is not None else None
        try:
            out = manuscript_polish(
                db=db,
                topic_id=topic,
                manuscript=_read(mfile),
                venue=venue,
                run_consistency=(not no_consistency),
                run_deterministic=(not no_deterministic),
                _model=model,
            )
        except Exception as exc:
            raise click.ClickException("Manuscript polish did not complete.") from exc
        if as_json:
            click.echo(json.dumps(_to_jsonable(out), ensure_ascii=False, indent=2))
        else:
            verdict = {
                "ready": "READY",
                "needs_revision": "NEEDS REVISION",
                "blocked": "BLOCKED",
            }
            click.echo(
                f"submission_readiness: {verdict.get(out.submission_readiness, out.submission_readiness)}  "
                f"({out.n_high} high / {out.n_medium} medium / {out.n_low} low; checks={out.checks_run})"
            )
            _print_findings(out.findings)
        if record and topic is not None and db is not None:
            from research_harness.orchestrator import OrchestratorService

            art = OrchestratorService(db).record_artifact(
                topic_id=topic,
                stage=_STAGE,
                artifact_type="manuscript_polish_report",
                title=f"final-draft polish: {out.submission_readiness} ({out.n_high}h/{out.n_medium}m/{out.n_low}l)",
                payload=_to_jsonable(out),
                metadata={
                    "submission_readiness": out.submission_readiness,
                    "n_high": out.n_high,
                    "n_medium": out.n_medium,
                    "n_low": out.n_low,
                },
            )
            click.echo(
                f"recorded manuscript_polish_report #{art.id} v{art.version} "
                f"(submission_readiness={out.submission_readiness})"
            )
