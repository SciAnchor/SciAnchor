"""Topic Knowledge subcommands for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click

from .service import ResearchService
from .topic_workspace import discover_topic_id_from_workspace


def _wiki_context_not_triggered_payload() -> dict[str, Any]:
    return {
        "schema_version": "wiki_context_pack.v1",
        "topic_id": None,
        "paper_wiki_status": "not_triggered",
        "status_reason": "topic_id_not_resolved",
        "unavailable_reasons": [
            "no --topic-id was provided and no RH topic id was found in the current workspace"
        ],
        "warnings": [],
        "preflight": {
            "priority_evidence_layer": "",
            "fallback_allowed": True,
            "fallback_must_be_declared": True,
        },
        "pages": [],
    }


def register(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    positive_topic_id_or_exit: Callable[..., int],
    exit_with_public_error: Callable[..., None],
    json_requested: Callable[[click.Context, bool], bool],
) -> None:
    """Register Topic Knowledge commands on the existing topic group."""

    def invoke_service_or_public_error(
        ctx: click.Context,
        command_name: str,
        arguments: dict[str, Any],
        *,
        json_output: bool,
    ) -> dict[str, Any]:
        result = ResearchService(db=get_db(ctx)).invoke(command_name, arguments)
        if result.status == "success" and isinstance(result.output, dict):
            return result.output
        error = result.error or {}
        exit_with_public_error(
            ctx,
            code=str(error.get("code") or f"{command_name}_failed"),
            message=str(error.get("message") or result.summary or command_name),
            exit_code=1,
            command_json=json_output,
        )
        raise click.ClickException(str(error.get("message") or command_name))

    @topic.command("knowledge-status")
    @click.option("--topic-id", required=True, help="Positive RH topic id.")
    @click.option(
        "--json", "json_output", is_flag=True, default=False, help="JSON output"
    )
    @click.pass_context
    def topic_knowledge_status(
        ctx: click.Context,
        topic_id: str,
        json_output: bool,
    ) -> None:
        """Show the Topic Knowledge status payload."""
        parsed_topic_id = positive_topic_id_or_exit(
            ctx,
            topic_id,
            command_json=json_output,
        )
        payload = invoke_service_or_public_error(
            ctx,
            "topic_knowledge_status",
            {"topic_id": parsed_topic_id},
            json_output=json_output,
        )

        if json_requested(ctx, json_output):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            "Knowledge status "
            f"topic={payload['topic_id']} "
            f"status={payload['status']} "
            f"readiness={payload['readiness_status']}"
        )

    @topic.command("knowledge-refresh")
    @click.option("--topic-id", default=None, help="Positive RH topic id.")
    @click.option("--all", "all_topics", is_flag=True, default=False)
    @click.option(
        "--json", "json_output", is_flag=True, default=False, help="JSON output"
    )
    @click.pass_context
    def topic_knowledge_refresh(
        ctx: click.Context,
        topic_id: str | None,
        all_topics: bool,
        json_output: bool,
    ) -> None:
        """Refresh Topic Knowledge snapshots."""
        if all_topics and topic_id is not None:
            exit_with_public_error(
                ctx,
                code="invalid_refresh_scope",
                message="pass either --topic-id or --all, not both",
                exit_code=2,
                command_json=json_output,
            )
        if not all_topics and topic_id is None:
            exit_with_public_error(
                ctx,
                code="invalid_refresh_scope",
                message="pass --topic-id or --all",
                exit_code=2,
                command_json=json_output,
            )

        if all_topics:
            payload = invoke_service_or_public_error(
                ctx,
                "topic_knowledge_refresh",
                {"all": True},
                json_output=json_output,
            )
            if json_requested(ctx, json_output):
                click.echo(json.dumps(payload, ensure_ascii=False, default=str))
                return
            counts = payload["counts"]
            click.echo(
                "Knowledge refresh "
                f"topics={payload['topic_count']} "
                f"refreshed={counts['refreshed']} "
                f"reused={counts['reused']} "
                f"failed={counts['failed']}"
            )
            return

        parsed_topic_id = positive_topic_id_or_exit(
            ctx,
            topic_id or "",
            command_json=json_output,
        )
        payload = invoke_service_or_public_error(
            ctx,
            "topic_knowledge_refresh",
            {"topic_id": parsed_topic_id},
            json_output=json_output,
        )
        if json_requested(ctx, json_output):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            "Knowledge refresh "
            f"topic={payload['topic_id']} "
            f"status={payload['status']} "
            f"artifact={payload['artifact_id'] or '-'}"
        )

    @topic.command("wiki-context-pack")
    @click.option(
        "--topic-id",
        default=None,
        help="Positive RH topic id. Defaults to the current rh-workspace metadata.",
    )
    @click.option("--query", default="", help="Optional ranking query.")
    @click.option("--action-name", default="", help="Workflow action name.")
    @click.option("--anchor-paper-id", type=int, default=None)
    @click.option("--max-pages", type=int, default=8, show_default=True)
    @click.option("--max-anchors", type=int, default=24, show_default=True)
    @click.option(
        "--json", "json_output", is_flag=True, default=False, help="JSON output"
    )
    @click.pass_context
    def topic_wiki_context_pack(
        ctx: click.Context,
        topic_id: str | None,
        query: str,
        action_name: str,
        anchor_paper_id: int | None,
        max_pages: int,
        max_anchors: int,
        json_output: bool,
    ) -> None:
        """Preflight the Research Wiki context pack for an agent workflow."""
        if topic_id is not None:
            parsed_topic_id = positive_topic_id_or_exit(
                ctx,
                topic_id,
                command_json=json_output,
            )
        else:
            parsed_topic_id = discover_topic_id_from_workspace()
            if parsed_topic_id is None:
                payload = _wiki_context_not_triggered_payload()
                if json_requested(ctx, json_output):
                    click.echo(json.dumps(payload, ensure_ascii=False, default=str))
                    return
                click.echo(
                    "Wiki context pack "
                    "topic=- paper_wiki_status=not_triggered "
                    "reason=topic_id_not_resolved"
                )
                return
        arguments: dict[str, Any] = {
            "topic_id": parsed_topic_id,
            "query": query.strip(),
            "action_name": action_name.strip(),
            "max_pages": max_pages,
            "max_anchors": max_anchors,
        }
        if anchor_paper_id is not None:
            arguments["anchor_paper_id"] = anchor_paper_id

        payload = invoke_service_or_public_error(
            ctx,
            "wiki_context_pack",
            arguments,
            json_output=json_output,
        )

        if json_requested(ctx, json_output):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            "Wiki context pack "
            f"topic={payload['topic_id']} "
            f"paper_wiki_status={payload['paper_wiki_status']} "
            f"reason={payload['status_reason']}"
        )

    @topic.command("cross-topic-atlas")
    @click.option(
        "--topic-id",
        "topic_ids",
        multiple=True,
        required=True,
        help="Positive RH topic id. Repeat for at least two topics.",
    )
    @click.option("--query", default="", help="Optional ranking query.")
    @click.option("--max-results", type=int, default=10, show_default=True)
    @click.option(
        "--json", "json_output", is_flag=True, default=False, help="JSON output"
    )
    @click.pass_context
    def topic_cross_topic_atlas(
        ctx: click.Context,
        topic_ids: tuple[str, ...],
        query: str,
        max_results: int,
        json_output: bool,
    ) -> None:
        """Preview read-only cross-topic atlas links for existing snapshots."""
        parsed_topic_ids = tuple(
            positive_topic_id_or_exit(ctx, topic_id, command_json=json_output)
            for topic_id in topic_ids
        )
        distinct_topic_ids = tuple(dict.fromkeys(parsed_topic_ids))
        if len(distinct_topic_ids) < 2:
            exit_with_public_error(
                ctx,
                code="invalid_topic_ids",
                message="at least two distinct topic ids are required",
                exit_code=2,
                command_json=json_output,
            )
        if max_results <= 0 or max_results > 20:
            exit_with_public_error(
                ctx,
                code="invalid_max_results",
                message="max_results must be between 1 and 20",
                exit_code=2,
                command_json=json_output,
            )
        payload = invoke_service_or_public_error(
            ctx,
            "cross_topic_atlas",
            {
                "topic_ids": list(distinct_topic_ids),
                "query": query.strip(),
                "max_results": max_results,
            },
            json_output=json_output,
        )

        if json_requested(ctx, json_output):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            "Cross-topic atlas "
            f"topics={','.join(str(topic_id) for topic_id in payload['topic_ids'])} "
            f"links={payload['link_count']}"
        )
