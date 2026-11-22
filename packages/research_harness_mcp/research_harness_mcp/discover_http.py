"""FastAPI route registration for RH Discover endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class DiscoverHandoffRequest(BaseModel):
    user_profile: dict[str, Any] = Field(default_factory=dict)
    selected_goal_preview_ids: list[str] = Field(default_factory=list)


def register_discover_routes(
    app: FastAPI, *, get_db_context: Callable[[], Any]
) -> None:
    """Register RH Discover endpoints on an existing FastAPI app."""

    @app.get("/api/discover/sources")
    def get_discover_sources(family: str | None = None):
        """Return the RH Discover seed source registry for API clients."""
        from research_harness.discover import list_source_definitions

        valid_families = {None, "papers", "blogs", "product", "repos_models", "social"}
        if family not in valid_families:
            raise HTTPException(
                status_code=400, detail=f"unsupported source family: {family}"
            )
        sources = list_source_definitions(family=family)  # type: ignore[arg-type]
        return [source.to_dict() for source in sources]

    @app.get("/api/discover/weekly")
    def get_discover_weekly(
        sample: bool = True,
        generated_at: str | None = None,
    ):
        """Return a complete RH Discover Weekly report.

        The current product-ready MVP intentionally exposes the curated sample
        report. Live connector-backed generation comes after manual content
        validation.
        """
        from research_harness.discover import (
            build_sample_weekly_report,
            load_latest_discover_report,
        )

        if not sample:
            try:
                return load_latest_discover_report(cadence="weekly").to_dict()
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail="no published RH Discover weekly issue found",
                ) from exc
        return build_sample_weekly_report(generated_at=generated_at).to_dict()

    @app.get("/api/discover/issues")
    def get_discover_issues(
        cadence: str | None = None,
        include_drafts: bool = False,
    ):
        """Return the curated RH Discover issue archive."""

        from research_harness.discover import list_discover_issues

        valid_cadences = {None, "daily", "weekly", "special"}
        if cadence not in valid_cadences:
            raise HTTPException(
                status_code=400, detail=f"unsupported cadence: {cadence}"
            )
        issues = list_discover_issues(cadence=cadence, include_drafts=include_drafts)
        return [issue.to_dict() for issue in issues]

    @app.get("/api/discover/issues/{issue_id}")
    def get_discover_issue(
        issue_id: str,
        cadence: str | None = "weekly",
        include_drafts: bool = False,
    ):
        """Return one curated RH Discover issue, or latest by cadence."""

        from research_harness.discover import (
            load_discover_issue,
            load_latest_discover_report,
        )

        try:
            if issue_id == "latest":
                return load_latest_discover_report(
                    cadence=cadence,
                    include_drafts=include_drafts,
                ).to_dict()
            return load_discover_issue(
                issue_id,
                include_drafts=include_drafts,
            ).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"RH Discover issue not found: {issue_id}",
            ) from exc

    @app.get("/api/discover/opportunities")
    def get_discover_opportunities(
        sample: bool = True,
        cadence: str | None = "weekly",
    ):
        """Return flattened opportunities for the Discovery 1.0 explorer."""

        from research_harness.discover import (
            list_opportunity_cards,
            load_opportunity_report,
        )

        try:
            report = load_opportunity_report(sample=sample, cadence=cadence)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="no RH Discover opportunity report found",
            ) from exc

        return {
            "issue_id": report.issue_id,
            "cadence": report.cadence,
            "generated_at": report.generated_at,
            "opportunities": list_opportunity_cards(report),
        }

    @app.get("/api/discover/opportunities/{slug}")
    def get_discover_opportunity(
        slug: str,
        sample: bool = True,
        cadence: str | None = "weekly",
    ):
        """Return one Discovery opportunity by stable slug."""

        from research_harness.discover import (
            find_opportunity,
            load_opportunity_report,
            opportunity_slug,
        )

        try:
            report = load_opportunity_report(sample=sample, cadence=cadence)
            brief = find_opportunity(report, slug)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="no RH Discover opportunity report found",
            ) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"RH Discover opportunity not found: {slug}",
            ) from exc

        return {
            "issue_id": report.issue_id,
            "slug": opportunity_slug(brief),
            "brief": brief.to_dict(),
        }

    @app.post("/api/discover/opportunities/{slug}/handoff")
    def handoff_discover_opportunity(
        slug: str,
        body: DiscoverHandoffRequest,
        sample: bool = True,
        cadence: str | None = "weekly",
    ):
        """Create an RH Core topic from a selected Discovery opportunity.

        The endpoint deliberately persists only the topic seed and selected goal
        previews. Full RH Core ``goal_pool`` construction remains a downstream
        action after field brief and intake data are available.
        """

        from research_harness.discover import (
            find_opportunity,
            load_opportunity_report,
        )

        try:
            report = load_opportunity_report(sample=sample, cadence=cadence)
            brief = find_opportunity(report, slug)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="no RH Discover opportunity report found",
            ) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"RH Discover opportunity not found: {slug}",
            ) from exc

        payload = brief.to_dict()
        handoff = payload["rh_handoff"]
        selected_ids = set(body.selected_goal_preview_ids)
        selected_goals = [
            goal
            for goal in payload["goal_previews"]
            if not selected_ids or goal["id"] in selected_ids
        ]
        if body.selected_goal_preview_ids and not selected_goals:
            raise HTTPException(
                status_code=400,
                detail="selected goal previews do not belong to this opportunity",
            )

        now = datetime.now(timezone.utc).isoformat()
        topic_name = handoff["topic_name"]
        description = (
            "RH Discovery handoff\n\n"
            f"Source issue: {report.issue_id}\n"
            f"Opportunity: {payload['title']}\n"
            f"Why now: {payload['why_now']}\n"
            f"Initial queries: {json.dumps(handoff['initial_queries'], ensure_ascii=False)}\n"
            f"Selected goal previews: {json.dumps(selected_goals, ensure_ascii=False)}\n"
            f"User profile: {json.dumps(body.user_profile, ensure_ascii=False)}"
        )

        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM topics WHERE name = ?",
                (topic_name,),
            ).fetchone()
            if existing:
                topic_id = existing["id"]
                created = False
            else:
                cur = conn.execute(
                    """
                    INSERT INTO topics (name, description, status, target_venue, deadline, created_at)
                    VALUES (?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        topic_name,
                        description,
                        str(body.user_profile.get("preferred_venue") or ""),
                        str(body.user_profile.get("deadline") or ""),
                        now,
                    ),
                )
                conn.commit()
                topic_id = cur.lastrowid
                created = True

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "created": created,
            "seed_queries": handoff["initial_queries"],
            "goal_seeds": selected_goals,
            "next_url": f"/topics/{topic_id}",
        }
