"""CS workflow command group for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register CS workflow commands on the root CLI group."""

    @main.group()
    def cs() -> None:
        """CS-workflow bulk operations (harvest, classify, red-ocean)."""

    @cs.command("harvest")
    @click.option(
        "--year", type=int, required=True, help="Publication year to harvest."
    )
    @click.option(
        "--target",
        type=int,
        default=1000,
        show_default=True,
        help="Keep top-N head papers after deterministic ranking.",
    )
    @click.option(
        "--per-provider-limit",
        type=int,
        default=50,
        show_default=True,
        help="Per-provider cap per (category × seed_query) call.",
    )
    @click.option(
        "--classify/--no-classify",
        default=False,
        show_default=True,
        help="After harvest, LLM-classify head papers into research_areas.",
    )
    @click.option(
        "--red-ocean/--no-red-ocean",
        "red_ocean",
        default=False,
        show_default=True,
        help="After classify, compute red-ocean score for affected areas. "
        "No-op without --classify.",
    )
    @click.pass_context
    def cs_harvest_cmd(
        ctx: click.Context,
        year: int,
        target: int,
        per_provider_limit: int,
        classify: bool,
        red_ocean: bool,
    ) -> None:
        """Harvest CS papers across 14 arxiv categories × seed queries.

        Ingests with topic_id=NULL (pool-only), dedupes, ranks with
        head_paper_rank. With --classify, runs cs_classify on the head set
        (LLM cost ≈ N * 1 call). With --red-ocean, scores all touched
        research_areas (deterministic).
        """
        from .primitives.cs_harvest import cs_harvest as _cs_harvest

        db = get_db(ctx)
        result = _cs_harvest(
            db=db,
            year=year,
            target=target,
            per_provider_limit=per_provider_limit,
            classify=classify,
            compute_red_ocean=red_ocean,
        )
        payload = result.to_dict()
        summary_parts = [
            f"Harvested year={result.year}: {result.ingested} kept as head,",
            f"{result.discovered} unique discovered,",
            f"{result.total_ingested} total ingested across",
            f"{len(result.categories_covered)} categories.",
        ]
        if classify:
            summary_parts.append(f"Classified {result.classified} papers.")
        if red_ocean:
            summary_parts.append(f"Scored {result.areas_scored} research_areas.")
        echo(ctx, payload, " ".join(summary_parts))
