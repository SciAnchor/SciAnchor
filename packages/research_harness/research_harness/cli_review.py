"""Review command group for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register review commands on the root CLI group."""

    @main.group()
    def review() -> None:
        """Manage gate reviews."""

    @review.command("add")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option(
        "--gate",
        required=True,
        type=click.Choice(["novelty", "method", "writing", "final"]),
    )
    @click.option(
        "--reviewer", required=True, type=click.Choice(["claude", "codex", "human"])
    )
    @click.option(
        "--verdict",
        required=True,
        type=click.Choice(["pass", "conditional_pass", "fail"]),
    )
    @click.option("--score", type=float, default=None)
    @click.option("--findings", "-f", default="")
    @click.pass_context
    def review_add(
        ctx: click.Context,
        topic_name: str,
        gate: str,
        reviewer: str,
        verdict: str,
        score: float | None,
        findings: str,
    ) -> None:
        from .core.review_manager import ReviewManager

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            review_id = ReviewManager(conn).add_review(
                topic_id, gate, reviewer, verdict, score, findings
            )
        finally:
            conn.close()
        echo(
            ctx,
            {
                "id": review_id,
                "topic": topic_name,
                "gate": gate,
                "reviewer": reviewer,
                "verdict": verdict,
                "score": score,
            },
            f"Review recorded: id={review_id}, {gate}/{reviewer} -> {verdict}",
        )

    @review.command("list")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.pass_context
    def review_list(ctx: click.Context, topic_name: str) -> None:
        from .core.review_manager import ReviewManager

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            reviews = ReviewManager(conn).list_reviews(topic_id)
        finally:
            conn.close()

        if ctx.obj.get("json"):
            click.echo(
                json.dumps(
                    [dataclasses.asdict(item) for item in reviews],
                    ensure_ascii=False,
                    default=str,
                )
            )
            return
        for item in reviews:
            score_str = f" ({item.score})" if item.score is not None else ""
            click.echo(
                f"[{item.id}] {item.gate}/{item.reviewer} -> {item.verdict}{score_str}  {item.created_at}"
            )
