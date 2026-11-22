"""Panorama command group for the RH CLI (Domain Panorama KB)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

#: How long a project-certification verdict stays live. Short on purpose: the
#: areas this gate is used on move faster than the verdict does, and an expired
#: verdict that has to be re-certified is far cheaper than a stale one that
#: quietly suppresses a candidate.
CERTIFICATION_TTL_DAYS = 90

# NOV02 residual: panel arm budget-25 dropped cases on 502/timeout because the
# calibrate loop only retried "temporarily unavailable". Keep attempts small;
# sleep stays fixed (gateway cooldown), not exponential.
_CALIBRATE_VERIFY_ATTEMPTS = 5
_CALIBRATE_VERIFY_SLEEP_S = 120
_TRANSIENT_ERROR_MARKERS = (
    "temporarily unavailable",
    "timeout",
    "timed out",
    "gateway",
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "connection reset",
    "connection aborted",
    "remote end closed",
    "cloudflare",
)


def is_transient_calibrate_error(message: str | None) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


def execute_with_calibrate_retry(
    execute: Callable[..., Any],
    *,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = _CALIBRATE_VERIFY_ATTEMPTS,
    sleep_s: float = _CALIBRATE_VERIFY_SLEEP_S,
    **kwargs: Any,
) -> Any:
    """Run gap_ground_verify with bounded retries on transient gateway faults."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    result = None
    for attempt in range(attempts):
        result = execute("gap_ground_verify", **kwargs)
        if getattr(result, "success", False):
            return result
        err = getattr(result, "error", None) or "gap_ground_verify failed"
        if not is_transient_calibrate_error(err) or attempt >= attempts - 1:
            raise RuntimeError(err)
        sleep(sleep_s)
    raise RuntimeError(getattr(result, "error", None) or "gap_ground_verify failed")


DEFAULT_PWC_KEYWORDS = (
    "automated machine learning",
    "automl",
    "scientific discovery",
    "hypothesis generation",
    "research agent",
    "idea generation",
    "peer review",
    "neural architecture search",
)


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
    create_backend: Callable[[click.Context], Any] | None = None,
) -> None:
    """Register panorama commands on the root CLI group."""

    def _store(ctx: click.Context, root: str | None):
        from .panorama import PanoramaStore, default_panorama_root

        if root:
            return PanoramaStore(Path(root))
        db = get_db(ctx)
        return PanoramaStore(default_panorama_root(db.db_path))

    def _direction_or_exit(store: Any, slug: str) -> dict[str, Any]:
        direction = store.direction(slug)
        if direction is None:
            raise click.ClickException(
                f"Unknown panorama direction: {slug} (run `rh panorama init` first)"
            )
        return direction

    @main.group()
    def panorama() -> None:
        """Domain Panorama KB: direction-level living knowledge base."""

    @panorama.command("init")
    @click.argument("slug")
    @click.option("--title", default=None, help="Display title (default: slug).")
    @click.option("-d", "--description", default="")
    @click.option("--rh-domain-id", type=int, default=None)
    @click.option("--root", default=None, help="Panorama root dir override.")
    @click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
    @click.pass_context
    def panorama_init(
        ctx: click.Context,
        slug: str,
        title: str | None,
        description: str,
        rh_domain_id: int | None,
        root: str | None,
        as_json: bool,
    ) -> None:
        """Initialize the panorama store and create a direction."""
        store = _store(ctx, root)
        store.init()
        direction_id = store.get_or_create_direction(
            slug,
            title or slug,
            description=description,
            rh_domain_id=rh_domain_id,
        )
        payload = {
            "root": str(store.root),
            "direction_id": direction_id,
            "slug": slug,
        }
        echo(ctx, payload, f"panorama ready at {store.root} (direction {slug})")

    @panorama.command("import")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option(
        "--source",
        "sources",
        multiple=True,
        type=click.Choice(["pool", "pwc", "kb"]),
        help="Importers to run (default: all).",
    )
    @click.option("--archive-dir", default=None, help="PwC archive dir (L0).")
    @click.option("--kb-dir", default=None, help="innovation-kb dir.")
    @click.option(
        "--pwc-keyword",
        "pwc_keywords",
        multiple=True,
        help="Benchmark filter keywords (default: built-in automated-research set).",
    )
    @click.pass_context
    def panorama_import(
        ctx: click.Context,
        slug: str,
        root: str | None,
        sources: tuple[str, ...],
        archive_dir: str | None,
        kb_dir: str | None,
        pwc_keywords: tuple[str, ...],
    ) -> None:
        """Run importers (pool papers / PwC archive / innovation-kb) for a direction."""
        from .panorama.importers import (
            import_innovation_kb,
            import_pool_papers,
            import_pwc_benchmarks,
            import_pwc_code_links,
        )

        store = _store(ctx, root)
        direction = _direction_or_exit(store, slug)
        direction_id = int(direction["id"])
        run = set(sources or ("pool", "pwc", "kb"))
        results: dict[str, Any] = {}
        if "pool" in run:
            rh_domain_id = direction.get("rh_domain_id")
            if rh_domain_id is None:
                raise click.ClickException(
                    "Direction has no rh_domain_id; re-init with --rh-domain-id "
                    "to import pool papers."
                )
            db = get_db(ctx)
            results["pool"] = import_pool_papers(
                store, direction_id, db.db_path, int(rh_domain_id)
            )
        if "pwc" in run:
            archive = Path(archive_dir) if archive_dir else store.l0_dir / "pwc-archive"
            if not archive.is_dir():
                raise click.ClickException(f"PwC archive dir not found: {archive}")
            results["pwc_code"] = import_pwc_code_links(store, direction_id, archive)
            results["pwc_benchmarks"] = import_pwc_benchmarks(
                store,
                direction_id,
                archive,
                list(pwc_keywords) or list(DEFAULT_PWC_KEYWORDS),
            )
        if "kb" in run:
            kb = Path(kb_dir) if kb_dir else Path("docs/innovation-kb")
            if not kb.is_dir():
                raise click.ClickException(f"innovation-kb dir not found: {kb}")
            results["kb"] = import_innovation_kb(store, direction_id, kb)
        echo(ctx, results, json.dumps(results, ensure_ascii=False, indent=2))

    @panorama.command("views")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.pass_context
    def panorama_views(ctx: click.Context, slug: str, root: str | None) -> None:
        """Regenerate the L2 markdown vault for a direction."""
        from .panorama.views import generate_views

        store = _store(ctx, root)
        _direction_or_exit(store, slug)
        result = generate_views(store, slug)
        result["vault"] = str(store.vault_dir)
        echo(ctx, result, json.dumps(result, ensure_ascii=False, indent=2))

    @panorama.command("pack")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option("--max-chars", type=int, default=80_000)
    @click.option("--out", default=None, help="Write to file instead of stdout.")
    @click.pass_context
    def panorama_pack(
        ctx: click.Context,
        slug: str,
        root: str | None,
        max_chars: int,
        out: str | None,
    ) -> None:
        """Build the agent-facing context pack for a direction."""
        from .panorama.context_pack import build_context_pack, write_context_pack

        store = _store(ctx, root)
        _direction_or_exit(store, slug)
        if out:
            path = write_context_pack(store, slug, max_chars=max_chars)
            echo(ctx, {"path": str(path)}, str(path))
        else:
            click.echo(build_context_pack(store, slug, max_chars=max_chars))

    @panorama.command("harvest")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option(
        "--source",
        "sources",
        multiple=True,
        type=click.Choice(["openalex", "s2", "arxiv"]),
        help="Academic sources (default: all three).",
    )
    @click.option("--round", "round_no", type=int, default=1)
    @click.option("--per-query-limit", type=int, default=25)
    @click.option("--import-budget", type=int, default=150)
    @click.option(
        "--since",
        default=None,
        help="Recency mode: only papers published on/after YYYY-MM-DD "
        "(arXiv switches to newest-first). Default: relevance ranking.",
    )
    @click.option(
        "--external-jsonl",
        default=None,
        help="Import an offline snapshot (normalized JSONL) as a harvest source.",
    )
    @click.option("--external-source-name", default="pwc-archive")
    @click.pass_context
    def panorama_harvest(
        ctx: click.Context,
        slug: str,
        root: str | None,
        sources: tuple[str, ...],
        round_no: int,
        per_query_limit: int,
        import_budget: int,
        since: str | None,
        external_jsonl: str | None,
        external_source_name: str,
    ) -> None:
        """Run logged multi-source academic harvest (capture-recapture substrate)."""
        from .panorama.harvest import harvest_academic, record_external_source

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        direction_id = int(direction["id"])
        results: dict[str, Any] = {}
        if external_jsonl:
            records = []
            with open(external_jsonl, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            results["external"] = record_external_source(
                store,
                direction_id,
                external_source_name,
                records,
                round_no=round_no,
            )
        else:
            results["academic"] = harvest_academic(
                store,
                direction_id,
                direction_slug=slug,
                sources=sources or ("managed",),
                per_query_limit=per_query_limit,
                since=since,
                round_no=round_no,
                import_budget=import_budget,
            )
        echo(ctx, results, json.dumps(results, ensure_ascii=False, indent=2))

    @panorama.command("absorb-verify")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option(
        "--since",
        default=None,
        help="Only absorb pool search_cache rows created on/after this "
        "timestamp (e.g. 2026-08-01). Default: all cached retrieval.",
    )
    @click.option("--round", "round_no", type=int, default=1)
    @click.option("--import-budget", type=int, default=400)
    @click.pass_context
    def panorama_absorb_verify(
        ctx: click.Context,
        slug: str,
        root: str | None,
        since: str | None,
        round_no: int,
        import_budget: int,
    ) -> None:
        """Absorb gap_ground_verify retrieval (pool search_cache) as a capture source."""
        from .panorama.importers import absorb_verify_cache

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        db = get_db(ctx)
        result = absorb_verify_cache(
            store,
            int(direction["id"]),
            db.db_path,
            since=since,
            round_no=round_no,
            import_budget=import_budget,
        )
        echo(ctx, result, json.dumps(result, ensure_ascii=False, indent=2))

    @panorama.command("extract")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option("--limit", type=int, default=None, help="Max papers this run.")
    @click.option(
        "--all",
        "extract_all",
        is_flag=True,
        help="Re-extract even papers that already have claims.",
    )
    @click.pass_context
    def panorama_extract(
        ctx: click.Context,
        slug: str,
        root: str | None,
        limit: int | None,
        extract_all: bool,
    ) -> None:
        """LLM contribution-claim extraction batch (fills the territory map)."""
        from .panorama.extract import extract_claims

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        result = extract_claims(
            store,
            int(direction["id"]),
            limit=limit,
            only_missing=not extract_all,
        )
        echo(ctx, result, json.dumps(result, ensure_ascii=False, indent=2))

    @panorama.command("calibrate")
    @click.argument("fixture", type=click.Path(exists=True, dir_okay=False))
    @click.option("--topic", "topic_id", type=int, required=True)
    @click.option(
        "--budgets", default="5,15,25", help="Comma-separated max_candidates levels."
    )
    @click.option(
        "--out", "out_path", default=None, help="Write the full JSON report here."
    )
    @click.option(
        "--no-cutoff",
        "no_cutoff",
        is_flag=True,
        help="Disable the per-case temporal cutoff (leaky replay, contrast runs).",
    )
    @click.option(
        "--judge-mode",
        "judge_mode",
        type=click.Choice(["single", "panel"]),
        default="single",
        show_default=True,
        help=(
            "Opt-in NOV02 judge arm: 'panel' replays each case through one judge "
            "per perspective (coverage/mechanism_equivalence/narrowness, plus "
            "residual_depth on whether the residual is worth occupying) "
            "with vote aggregation; 'single' is the unchanged default. "
            "High-stakes novelty certification / release-quality curves: use panel "
            "with budgets ≥15 (see nov02-three-arm-report-2026-08-13)."
        ),
    )
    @click.option(
        "--resume-from",
        "resume_from",
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help=(
            "Prior calibrate JSON: reuse successful (budget, case_id) records and "
            "retry only missing cells / prior errors."
        ),
    )
    @click.pass_context
    def panorama_calibrate(
        ctx: click.Context,
        fixture: str,
        topic_id: int,
        budgets: str,
        out_path: str | None,
        no_cutoff: bool,
        judge_mode: str,
        resume_from: str | None,
    ) -> None:
        """Replay seed gap cases through gap_ground_verify: false-open curve (NOV02)."""
        import dataclasses as _dc

        from .execution.tracked import TrackedBackend
        from .panorama.calibration import load_cases, run_calibration
        from .provenance import ProvenanceRecorder

        if create_backend is None:
            raise click.ClickException(
                "calibrate requires an execution backend (create_backend not wired)"
            )
        cases = load_cases(fixture)
        budget_list = [int(b) for b in budgets.split(",") if b.strip()]
        prior = None
        if resume_from:
            prior = json.loads(Path(resume_from).read_text(encoding="utf-8"))
        backend = TrackedBackend(
            create_backend(ctx),
            ProvenanceRecorder(get_db(ctx)),
            default_topic_id=topic_id,
        )
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

        def verify(case: Any, budget: int) -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "topic_id": topic_id,
                "gap": case.gap,
                "max_candidates": budget,
                "judge_mode": judge_mode,
            }
            if not no_cutoff and case.judged_at:
                kwargs["published_before"] = case.judged_at[:7]
            # ponytail: fixed N x 120s retry for gateway cooldown / 502 / timeout
            result = execute_with_calibrate_retry(backend.execute, **kwargs)
            usage["prompt_tokens"] += result.prompt_tokens or 0
            usage["completion_tokens"] += result.completion_tokens or 0
            usage["cost_usd"] += result.cost_usd or 0.0
            out = _dc.asdict(result.output)
            return {
                "verdict": out.get("verdict"),
                "occupying": out.get("occupying") or [],
                "candidates": out.get("retrieved") or [],
                "grounded_confidence": out.get("grounded_confidence"),
                "governance_action": out.get("governance_action"),
                "coverage_note": out.get("coverage_note"),
                "judge_votes": out.get("judge_votes") or [],
                "narrowness": out.get("narrowness") or {},
            }

        report = run_calibration(cases, verify, budget_list, prior=prior)
        report.update(
            fixture=str(fixture),
            topic_id=topic_id,
            temporal_cutoff=not no_cutoff,
            judge_mode=judge_mode,
            resume_from=str(resume_from) if resume_from else None,
            usage=usage,
        )
        if out_path:
            Path(out_path).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        summary = [
            {
                k: point[k]
                for k in (
                    "budget",
                    "n_cases",
                    "false_open_rate",
                    "missed_occupation_rate",
                    "preemptor_retrieval_recall",
                    "judge_miss_rate_given_retrieved",
                )
            }
            | {"errors": len(point["errors"])}
            for point in report["curve"]
        ]
        echo(
            ctx,
            report,
            json.dumps(
                {"curve": summary, "usage": usage}, ensure_ascii=False, indent=2
            ),
        )

    @panorama.command("canonicalize")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option(
        "--apply",
        "do_apply",
        is_flag=True,
        help="Apply the proposed merges (default: dry run).",
    )
    @click.pass_context
    def panorama_canonicalize(
        ctx: click.Context,
        slug: str,
        root: str | None,
        do_apply: bool,
    ) -> None:
        """Merge synonym territory-map tags (dry run unless --apply)."""
        from .panorama.canonicalize import canonicalize_tags

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        result = canonicalize_tags(store, int(direction["id"]), apply=do_apply)
        echo(ctx, result, json.dumps(result, ensure_ascii=False, indent=2))

    @panorama.command("coverage")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option("--epsilon", type=float, default=0.10)
    @click.option("--marginal-threshold", type=float, default=0.02)
    @click.option(
        "--write", "write_md", is_flag=True, help="Also write vault/coverage.md."
    )
    @click.pass_context
    def panorama_coverage(
        ctx: click.Context,
        slug: str,
        root: str | None,
        epsilon: float,
        marginal_threshold: float,
        write_md: bool,
    ) -> None:
        """Coverage estimate (Chao2) + stopping-criterion verdict + freshness."""
        from .panorama.coverage import (
            coverage_data,
            coverage_verdict,
            render_coverage_md,
        )

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        data = coverage_data(store, int(direction["id"]))
        verdict = coverage_verdict(
            data, epsilon=epsilon, marginal_threshold=marginal_threshold
        )
        md = render_coverage_md(data, verdict)
        if write_md:
            store.vault_dir.mkdir(parents=True, exist_ok=True)
            (store.vault_dir / "coverage.md").write_text(md, encoding="utf-8")
        click.echo(md)
        click.echo("\n" + json.dumps(verdict, ensure_ascii=False, indent=2))

    @panorama.command("collect")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.option(
        "--realm",
        "realms",
        multiple=True,
        type=click.Choice(["github", "blogs"]),
        help="Collectors to run (default: both).",
    )
    @click.pass_context
    def panorama_collect(
        ctx: click.Context,
        slug: str,
        root: str | None,
        realms: tuple[str, ...],
    ) -> None:
        """Run code/industry collectors (GitHub patrol + blog whitelist)."""
        from .panorama.collectors import patrol_github, snapshot_blogs

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        direction_id = int(direction["id"])
        run = set(realms or ("github", "blogs"))
        results: dict[str, Any] = {}
        if "github" in run:
            results["github"] = patrol_github(store, direction_id)
        if "blogs" in run:
            results["blogs"] = snapshot_blogs(store, direction_id)
        echo(ctx, results, json.dumps(results, ensure_ascii=False, indent=2))

    @panorama.command("certify")
    @click.argument("slug")
    @click.option("--claim", required=True, help="Direction/gap claim being certified.")
    @click.option(
        "--panel-json",
        required=True,
        help="Reviewer-panel result JSON: {auto_verdict, reviewers:[{axis,overall,"
        "verdict,note}], preemptors:[...]}.",
    )
    @click.option("--target", default="iclr-main")
    @click.option("--root", default=None)
    @click.pass_context
    def panorama_certify(
        ctx: click.Context,
        slug: str,
        claim: str,
        panel_json: str,
        target: str,
        root: str | None,
    ) -> None:
        """Certify a mined candidate: gap_ground_verify + reviewer panel.

        Produces two separate artifacts. A candidate-scoped novelty verdict
        (refuted / not_refuted_by_retrieved_evidence / unclear) answers only
        whether the core contribution is refuted by the evidence retrieved. A
        promotion decision (advance / incubate / hold / stop) answers whether to
        invest now, and may cite methodology, significance, rigor, resources, or
        venue fit without ever rewriting the novelty verdict.

        Neither artifact can express a conclusion about a field, domain, or
        research area; a low score on a non-novelty axis is a hold, not evidence
        that the area is exhausted. `--target` selects the venue bar and is
        actually applied.
        """
        from .panorama.certify import evaluate_certification, parse_panel
        from .panorama.coverage import coverage_data, coverage_verdict

        store = _store(ctx, root)
        store.init()
        direction = _direction_or_exit(store, slug)
        try:
            panel = json.loads(panel_json)
        except ValueError as exc:
            raise click.ClickException(f"--panel-json is not valid JSON: {exc}")
        auto_verdict, reviewers, preemptors = parse_panel(panel)
        # The quantitative Chao2 stopping verdict gates coverage_sufficient;
        # with no computable signal it degrades to the categorical check.
        coverage = coverage_verdict(coverage_data(store, int(direction["id"])))
        decision = evaluate_certification(
            auto_verdict=auto_verdict,
            reviewers=reviewers,
            target=target,
            preemptors=preemptors,
            coverage=coverage,
        )
        # Record the promotion decision, not a binary. `hold` and `incubate`
        # must stay distinguishable from `stop` in the durable record, or a
        # resource-driven pause reads later as a settled refutation.
        #
        # The verdict is scoped to the claim it was decided about and expires,
        # so it cannot keep influencing ranking indefinitely in a fast-moving
        # area. Re-certifying is cheap; a stale conclusion is not.
        store.record_verdict(
            int(direction["id"]),
            claim,
            f"project-{decision.promotion.decision}",
            tool="project-certification",
            evidence={**decision.to_dict(), "coverage": coverage},
            scope_kind="candidate_version",
            scope_ref=claim,
            ttl_days=CERTIFICATION_TTL_DAYS,
            revival_triggers=[
                "new work published in the candidate's neighbourhood",
                "a stronger model, dataset, or benchmark becomes available",
                "the candidate is revised into a new version",
            ],
        )
        echo(
            ctx,
            decision.to_dict(),
            json.dumps(decision.to_dict(), ensure_ascii=False, indent=2),
        )

    @panorama.command("status")
    @click.argument("slug")
    @click.option("--root", default=None)
    @click.pass_context
    def panorama_status(ctx: click.Context, slug: str, root: str | None) -> None:
        """Show entity/edge/cell/verdict counts for a direction."""
        store = _store(ctx, root)
        direction = _direction_or_exit(store, slug)
        stats = store.stats(int(direction["id"]))
        stats["direction"] = slug
        stats["root"] = str(store.root)
        echo(ctx, stats, json.dumps(stats, ensure_ascii=False, indent=2))

    @panorama.command("verdict")
    @click.argument("slug")
    @click.option("--claim", required=True, help="Contribution-level claim text.")
    @click.option("--verdict", "verdict_value", required=True)
    @click.option("--cell-id", type=int, default=None)
    @click.option("--tool", default="gap_ground_verify")
    @click.option("--evidence-json", default=None, help="JSON evidence payload.")
    @click.option("--root", default=None)
    @click.pass_context
    def panorama_verdict(
        ctx: click.Context,
        slug: str,
        claim: str,
        verdict_value: str,
        cell_id: int | None,
        tool: str,
        evidence_json: str | None,
        root: str | None,
    ) -> None:
        """Persist a novelty-certification verdict onto the territory map."""
        store = _store(ctx, root)
        direction = _direction_or_exit(store, slug)
        evidence = None
        if evidence_json:
            try:
                evidence = json.loads(evidence_json)
            except ValueError as exc:
                raise click.ClickException(f"--evidence-json is not valid JSON: {exc}")
        verdict_id = store.record_verdict(
            int(direction["id"]),
            claim,
            verdict_value,
            cell_id=cell_id,
            tool=tool,
            evidence=evidence,
        )
        payload = {"verdict_id": verdict_id, "cell_id": cell_id}
        echo(ctx, payload, f"verdict {verdict_id} recorded")
