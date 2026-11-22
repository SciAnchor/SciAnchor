"""FastAPI route registration for domain trends endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel


_DEFAULT_TRENDS_SCOPE = "discipline:cs"


class TrendsRefreshRequest(BaseModel):
    tier: str = "standard"
    scope: str | None = None
    dry_run: bool = False

    model_config = {"extra": "forbid"}


def _validate_scope(scope: str | None) -> str:
    """Accepted forms: `discipline:<name>`, `domain:<int>`, `topic:<int>`."""
    if not scope:
        return _DEFAULT_TRENDS_SCOPE
    if ":" not in scope:
        raise HTTPException(
            status_code=400,
            detail=f"scope must be `kind:value`, got {scope!r}",
        )
    kind, _, value = scope.partition(":")
    if kind not in {"discipline", "domain", "topic"}:
        raise HTTPException(
            status_code=400,
            detail=f"scope kind must be discipline|domain|topic, got {kind!r}",
        )
    if kind in {"domain", "topic"}:
        try:
            int(value)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"scope `{kind}:` expects an integer, got {value!r}",
            )
    return scope


def register_domain_trends_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> None:
    """Register domain trends routes on an existing FastAPI app."""

    @app.get("/api/domains/trends")
    def get_domain_trends(
        tier: str | None = None,
        scope: str | None = None,
        limit: int = Query(default=10, ge=1, le=100),
    ):
        resolved_scope = _validate_scope(scope)
        with get_db_context() as conn:
            conditions = ["scope = ?"]
            params: list[Any] = [resolved_scope]
            if tier:
                conditions.append("tier = ?")
                params.append(tier)
            where_sql = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM domain_trends WHERE {where_sql}"
                " ORDER BY publishability_score DESC LIMIT ?",
                (*params, limit),
            ).fetchall()

        if not rows:
            # Editorial seed fallback only makes sense for the discipline view.
            if resolved_scope == _DEFAULT_TRENDS_SCOPE:
                seed_path = (
                    Path(__file__).resolve().parents[2]
                    / "research_harness"
                    / "research_harness"
                    / "data"
                    / "domain_trends_seed.json"
                )
                if seed_path.exists():
                    seed = json.loads(seed_path.read_text())
                    return [
                        {
                            **cluster,
                            # Tag seed fallback clusters so the UI can label them
                            # honestly ("editorial baseline", not computed).
                            "source": "seed",
                            "paper_count": len(cluster.get("seed_papers", [])),
                        }
                        for cluster in seed[:limit]
                    ]
            return []

        results = []
        for row in rows:
            trend = row_to_dict(row)
            for field in ("top_venues", "seed_papers"):
                if isinstance(trend.get(field), str):
                    trend[field] = parse_json_field(trend[field], [])
            # Clusters written to the DB by the pipeline are "computed", derived
            # from real papers in the scope. (Semantic clustering is stubbed in
            # v0.3.x so we still only produce one "Landscape Overview" per scope;
            # the label is honest about what we have.)
            trend.setdefault("source", "computed")
            if "paper_count" not in trend:
                trend["paper_count"] = len(trend.get("seed_papers") or [])
            results.append(trend)
        return results

    @app.post("/api/domains/trends/refresh")
    def refresh_domain_trends(body: TrendsRefreshRequest | None = None):
        """Run the trends pipeline for a single scope and persist clusters."""
        from research_harness.trends import refresh_trends

        payload = body or TrendsRefreshRequest()
        resolved_scope = _validate_scope(payload.scope)
        with get_db_context() as conn:
            try:
                clusters = refresh_trends(
                    conn,
                    tier=payload.tier,
                    scope=resolved_scope,
                    dry_run=payload.dry_run,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        return {
            "tier": payload.tier,
            "scope": resolved_scope,
            "dry_run": payload.dry_run,
            "cluster_count": len(clusters),
            "clusters": [
                {
                    "name": cluster.name,
                    "publishability_score": cluster.publishability_score,
                    "velocity_yoy": cluster.velocity_yoy,
                    "paper_count": cluster.paper_count,
                }
                for cluster in clusters
            ],
        }

    @app.get("/api/trends/yearly")
    def get_trends_yearly(
        scope: str | None = None,
        years: int = Query(default=5, ge=1, le=30),
    ):
        """Yearly aggregates for the given scope."""
        from research_harness.trends import yearly_counts

        resolved_scope = _validate_scope(scope)
        with get_db_context() as conn:
            try:
                rows = yearly_counts(conn, scope=resolved_scope, years=years)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        return {"scope": resolved_scope, "years": years, "rows": rows}
