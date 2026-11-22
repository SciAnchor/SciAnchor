"""FastAPI route registration for agent, preference, and demo endpoints."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from research_harness.agents.families import get_family


class CreateAgentRequest(BaseModel):
    nickname: str
    provider: str
    model: str
    api_key_env: str
    role_prefs: dict[str, bool] = Field(
        default_factory=lambda: {"generator": True, "judge": True}
    )
    monthly_budget_usd: float | None = None


class PatchAgentRequest(BaseModel):
    nickname: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    role_prefs: dict[str, bool] | None = None
    monthly_budget_usd: float | None = None
    status: str | None = None

    model_config = {"extra": "forbid"}


class CreatePairingRequest(BaseModel):
    name: str
    generator_agent_id: int
    judge_agent_id: int
    challenger_agent_id: int | None = None
    topic_id: int | None = None
    is_global_default: int = 0


class UserPreferencesRequest(BaseModel):
    language: str | None = None
    discipline: str | None = None
    default_venue_tier: str | None = None
    default_quality_tier: str | None = None
    default_autonomy: str | None = None
    monthly_budget_cap_usd: float | None = None
    onboarding_complete: int | None = None
    auto_rollback_live: int | None = None  # 0 = shadow (default), 1 = live

    model_config = {"extra": "forbid"}


class _ProviderTestRequest(BaseModel):
    provider: str
    model: str
    base_url: str = ""

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("base_url must use https:// scheme")
        return v


class DemoReplayRequest(BaseModel):
    stage: str
    primitive: str
    prompt: str


AGENT_PRESETS = [
    {
        "id": "heavy",
        "name": "Opus 4.7 + Gemini 2.5 Pro",
        "description": "Maximum quality — heavy tier",
        "agents": [
            {
                "nickname": "opus-gen",
                "provider": "anthropic",
                "model": "claude-opus-4-7",
                "api_key_env": "ANTHROPIC_API_KEY",
                "role_prefs": {"generator": True},
            },
            {
                "nickname": "gemini-judge",
                "provider": "google",
                "model": "gemini-2.5-pro",
                "api_key_env": "GOOGLE_API_KEY",
                "role_prefs": {"judge": True},
            },
        ],
    },
    {
        "id": "balanced",
        "name": "GPT-5 + Claude Sonnet 4.6",
        "description": "Balanced cost and quality",
        "agents": [
            {
                "nickname": "gpt5-gen",
                "provider": "openai",
                "model": "gpt-5",
                "api_key_env": "OPENAI_API_KEY",
                "role_prefs": {"generator": True},
            },
            {
                "nickname": "sonnet-judge",
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key_env": "ANTHROPIC_API_KEY",
                "role_prefs": {"judge": True},
            },
        ],
    },
    {
        "id": "cost-optimised",
        "name": "Claude Sonnet + Kimi K2",
        "description": "Cost-optimised — good for exploration",
        "agents": [
            {
                "nickname": "sonnet-gen",
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key_env": "ANTHROPIC_API_KEY",
                "role_prefs": {"generator": True},
            },
            {
                "nickname": "kimi-judge",
                "provider": "kimi",
                "model": "kimi-k2",
                "api_key_env": "KIMI_API_KEY",
                "role_prefs": {"judge": True},
            },
        ],
    },
]


def register_agent_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    rows_to_list: Callable[[list[Any]], list[dict[str, Any]]],
    parse_json_field: Callable[[str | None, Any], Any],
    demo_list_entries: Callable[[], Any],
    demo_lookup: Callable[[str, str, str], dict[str, Any] | None],
    logger: logging.Logger | None = None,
) -> None:
    """Register agent, preference, and demo routes on an existing FastAPI app."""

    route_logger = logger or logging.getLogger(__name__)

    @app.get("/api/agents")
    def list_agents(status: str | None = Query(None)):
        with get_db_context() as conn:
            conditions: list[str] = []
            params: list[Any] = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM agent_registry {where} ORDER BY id", params
            ).fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            d["role_prefs"] = parse_json_field(d.get("role_prefs"), {})
            result.append(d)
        return result

    @app.get("/api/llm/providers")
    def list_llm_providers():
        """Return LLM providers available via env/CLI plus resolved tier routes.

        The agent_registry table holds user-registered personas; this endpoint
        exposes the system-level availability (env vars, CLI tools) so the UI
        never falsely claims "demo mode" when real credentials exist.
        """
        try:
            from llm_router.config import (
                detect_available_providers,
                get_tier_route,
                load_config,
            )
        except Exception as exc:
            route_logger.warning("llm_router import failed: %s", exc)
            return {"providers": [], "tier_routes": {}, "config_loaded": False}

        available = detect_available_providers()
        try:
            cfg = load_config()
        except Exception:
            cfg = {}

        # Collect litellm provider metadata for display and tier suggestions.
        _litellm_meta: dict[str, Any] = {}
        try:
            from llm_router.litellm_backend import (
                LITELLM_PROVIDERS,
                resolve_provider_api_key,
            )

            _litellm_meta = {name: meta for name, meta in LITELLM_PROVIDERS.items()}
        except ImportError:
            pass

        providers = []
        for p in available:
            entry: dict[str, Any] = {
                "provider": p,
                "family": get_family(p),
                "source": "litellm" if p in _litellm_meta else "env",
            }
            meta = _litellm_meta.get(p)
            if meta is not None:
                entry["display_name"] = meta.display_name
                entry["has_key"] = bool(resolve_provider_api_key(meta))
                entry["tier_suggestions"] = dict(meta.tier_suggestions)
            providers.append(entry)

        tier_routes: dict[str, dict[str, str]] = {}
        _default_models: dict[str, dict[str, str]] = {
            "anthropic": {
                "light": "claude-haiku-4-5-20251001",
                "medium": "claude-sonnet-4-6",
                "heavy": "claude-opus-4-6",
            },
            "openai": {"light": "gpt-4o-mini", "medium": "gpt-4o", "heavy": "o3"},
            "kimi": {
                "light": "kimi-for-coding",
                "medium": "kimi-for-coding",
                "heavy": "kimi-for-coding",
            },
        }
        for name, meta in _litellm_meta.items():
            if name not in _default_models and meta.tier_suggestions:
                _default_models[name] = dict(meta.tier_suggestions)
        for tier in ("light", "medium", "heavy"):
            env_key = f"LLM_ROUTE_{tier.upper()}"
            env_val = os.environ.get(env_key, "").strip()
            source = None
            provider = ""
            model = ""
            if env_val and ":" in env_val:
                provider, model = env_val.split(":", 1)
                source = "env"
            else:
                route = get_tier_route(tier, cfg)
                if route:
                    provider, model = route
                    source = "config"
            if not provider:
                for p in available:
                    if p in _default_models and tier in _default_models[p]:
                        provider = p
                        model = _default_models[p][tier]
                        source = "default"
                        break
            if provider and model:
                tier_routes[tier] = {
                    "provider": provider.strip(),
                    "model": model.strip(),
                    "source": source or "",
                }

        return {
            "providers": providers,
            "tier_routes": tier_routes,
            "config_loaded": bool(cfg),
        }

    @app.get("/api/llm/tier-suggestions")
    def get_tier_suggestions():
        """Return auto-suggested tier mapping from currently available providers."""
        try:
            from llm_router.config import detect_available_providers
            from llm_router.litellm_backend import suggest_tier_mapping

            available = detect_available_providers()
            suggested = suggest_tier_mapping(available)
            return {
                "available": available,
                "suggestions": {
                    tier: {"provider": prov, "model": model}
                    for tier, (prov, model) in suggested.items()
                },
            }
        except ImportError:
            return {"available": [], "suggestions": {}}

    @app.post("/api/llm/providers/test")
    def test_provider(body: _ProviderTestRequest):
        """Send a minimal completion to validate a provider config."""
        try:
            from llm_router import get_provider

            fn = get_provider(body.provider)
            result = fn(
                "Say 'ok' and nothing else.",
                body.model,
                base_url=body.base_url,
                temperature=0.0,
            )
            return {"ok": True, "response_preview": result[:200]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/agents", status_code=201)
    def create_agent(body: CreateAgentRequest):
        provider_family = get_family(body.provider)
        now = datetime.now(timezone.utc).isoformat()
        with get_db_context() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO agent_registry
                        (nickname, provider, provider_family, model, api_key_env, role_prefs, monthly_budget_usd, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        body.nickname,
                        body.provider,
                        provider_family,
                        body.model,
                        body.api_key_env,
                        json.dumps(body.role_prefs),
                        body.monthly_budget_usd,
                        now,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            row = conn.execute(
                "SELECT * FROM agent_registry WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        d = row_to_dict(row)
        d["role_prefs"] = parse_json_field(d.get("role_prefs"), {})
        return d

    # Agent pairings must be before {agent_id} to avoid route collision.
    @app.get("/api/agents/pairings")
    def list_pairings(topic_id: int | None = Query(None)):
        with get_db_context() as conn:
            conditions: list[str] = []
            params: list[Any] = []
            if topic_id is not None:
                conditions.append("(ap.topic_id = ? OR ap.topic_id IS NULL)")
                params.append(topic_id)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = conn.execute(
                f"""
                SELECT ap.*,
                       g.nickname AS generator_name, g.provider AS generator_provider, g.model AS generator_model,
                       j.nickname AS judge_name, j.provider AS judge_provider, j.model AS judge_model,
                       c.nickname AS challenger_name, c.provider AS challenger_provider, c.model AS challenger_model
                FROM agent_pairings ap
                JOIN agent_registry g ON g.id = ap.generator_agent_id
                JOIN agent_registry j ON j.id = ap.judge_agent_id
                LEFT JOIN agent_registry c ON c.id = ap.challenger_agent_id
                {where}
                ORDER BY ap.id
                """,
                params,
            ).fetchall()
        return rows_to_list(rows)

    @app.post("/api/agents/pairings", status_code=201)
    def create_pairing(body: CreatePairingRequest):
        with get_db_context() as conn:
            gen = conn.execute(
                "SELECT provider_family FROM agent_registry WHERE id = ?",
                (body.generator_agent_id,),
            ).fetchone()
            if not gen:
                raise HTTPException(status_code=404, detail="Generator agent not found")
            judge = conn.execute(
                "SELECT provider_family FROM agent_registry WHERE id = ?",
                (body.judge_agent_id,),
            ).fetchone()
            if not judge:
                raise HTTPException(status_code=404, detail="Judge agent not found")

            if gen["provider_family"] == judge["provider_family"]:
                raise HTTPException(
                    status_code=422,
                    detail=f"Generator and Judge must belong to different provider families. "
                    f"Both are '{gen['provider_family']}'. "
                    f"This ensures adversarial diversity in rubric scoring.",
                )

            if body.generator_agent_id == body.judge_agent_id:
                raise HTTPException(
                    status_code=422,
                    detail="Generator and Judge must be different agents.",
                )

            now = datetime.now(timezone.utc).isoformat()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO agent_pairings
                        (name, generator_agent_id, judge_agent_id, challenger_agent_id,
                         topic_id, is_global_default, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        body.name,
                        body.generator_agent_id,
                        body.judge_agent_id,
                        body.challenger_agent_id,
                        body.topic_id,
                        body.is_global_default,
                        now,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            row = conn.execute(
                "SELECT * FROM agent_pairings WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return row_to_dict(row)

    @app.get("/api/agents/presets")
    def list_presets():
        return AGENT_PRESETS

    # Token ledger must be before {agent_id} to avoid route collision.
    @app.get("/api/agents/ledger")
    def get_ledger(
        topic_id: int | None = Query(None),
        agent_id: int | None = Query(None),
        since: str | None = Query(None, description="ISO date, e.g. 2026-04-01"),
        group_by: str | None = Query(
            None, description="Grouping: agent, topic, stage, month"
        ),
    ):
        try:
            with get_db_context() as conn:
                conditions: list[str] = []
                params: list[Any] = []
                if topic_id is not None:
                    conditions.append("tl.topic_id = ?")
                    params.append(topic_id)
                if agent_id is not None:
                    conditions.append("tl.agent_id = ?")
                    params.append(agent_id)
                if since:
                    conditions.append("tl.ts >= ?")
                    params.append(since)

                where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

                if group_by == "agent":
                    rows = conn.execute(
                        f"""
                        SELECT tl.agent_id, ar.nickname, ar.model,
                               SUM(tl.prompt_tokens) AS total_prompt,
                               SUM(tl.completion_tokens) AS total_completion,
                               SUM(tl.cost_usd) AS total_cost,
                               COUNT(*) AS call_count
                        FROM token_ledger tl
                        LEFT JOIN agent_registry ar ON ar.id = tl.agent_id
                        {where}
                        GROUP BY tl.agent_id
                        ORDER BY total_cost DESC
                        """,
                        params,
                    ).fetchall()
                elif group_by == "stage":
                    rows = conn.execute(
                        f"""
                        SELECT tl.stage,
                               SUM(tl.prompt_tokens) AS total_prompt,
                               SUM(tl.completion_tokens) AS total_completion,
                               SUM(tl.cost_usd) AS total_cost,
                               COUNT(*) AS call_count
                        FROM token_ledger tl
                        {where}
                        GROUP BY tl.stage
                        ORDER BY total_cost DESC
                        """,
                        params,
                    ).fetchall()
                elif group_by == "month":
                    rows = conn.execute(
                        f"""
                        SELECT substr(tl.ts, 1, 7) AS month,
                               SUM(tl.cost_usd) AS total_cost,
                               COUNT(*) AS call_count
                        FROM token_ledger tl
                        {where}
                        GROUP BY month
                        ORDER BY month DESC
                        """,
                        params,
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"""
                        SELECT tl.*, ar.nickname AS agent_name, ar.model AS agent_model
                        FROM token_ledger tl
                        LEFT JOIN agent_registry ar ON ar.id = tl.agent_id
                        {where}
                        ORDER BY tl.ts DESC
                        LIMIT 200
                        """,
                        params,
                    ).fetchall()

                return rows_to_list(rows)
        except sqlite3.OperationalError:
            return []

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM agent_registry WHERE id = ?", (agent_id,)
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Agent {agent_id} not found"
                )
        d = row_to_dict(row)
        d["role_prefs"] = parse_json_field(d.get("role_prefs"), {})
        return d

    @app.patch("/api/agents/{agent_id}")
    def update_agent(agent_id: int, body: PatchAgentRequest):
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")

        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT * FROM agent_registry WHERE id = ?", (agent_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(
                    status_code=404, detail=f"Agent {agent_id} not found"
                )

            if "provider" in patch:
                patch["provider_family"] = get_family(patch["provider"])
            if "role_prefs" in patch:
                patch["role_prefs"] = json.dumps(patch["role_prefs"])

            allowed = {
                "nickname",
                "provider",
                "provider_family",
                "model",
                "api_key_env",
                "role_prefs",
                "monthly_budget_usd",
                "status",
            }
            updates = {k: v for k, v in patch.items() if k in allowed}
            if not updates:
                raise HTTPException(status_code=400, detail="No valid fields")

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [agent_id]
            conn.execute(f"UPDATE agent_registry SET {set_clause} WHERE id = ?", params)
            conn.commit()
            row = conn.execute(
                "SELECT * FROM agent_registry WHERE id = ?", (agent_id,)
            ).fetchone()

        d = row_to_dict(row)
        d["role_prefs"] = parse_json_field(d.get("role_prefs"), {})
        return d

    @app.delete("/api/agents/{agent_id}", status_code=204)
    def delete_agent(agent_id: int):
        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM agent_registry WHERE id = ?", (agent_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(
                    status_code=404, detail=f"Agent {agent_id} not found"
                )
            conn.execute("DELETE FROM agent_registry WHERE id = ?", (agent_id,))
            conn.commit()

    @app.get("/api/user/preferences")
    def get_user_preferences():
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM user_preferences ORDER BY id LIMIT 1"
            ).fetchone()
        if not row:
            return {
                "language": "en",
                "discipline": "cs",
                "default_venue_tier": "B",
                "default_quality_tier": "standard",
                "default_autonomy": "L2",
                "monthly_budget_cap_usd": 100,
                "onboarding_complete": 0,
                "auto_rollback_live": 0,
            }
        return row_to_dict(row)

    @app.patch("/api/user/preferences")
    def update_user_preferences(body: UserPreferencesRequest):
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")

        now = datetime.now(timezone.utc).isoformat()
        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM user_preferences ORDER BY id LIMIT 1"
            ).fetchone()
            if existing:
                allowed = {
                    "language",
                    "discipline",
                    "default_venue_tier",
                    "default_quality_tier",
                    "default_autonomy",
                    "monthly_budget_cap_usd",
                    "onboarding_complete",
                    "auto_rollback_live",
                }
                updates = {
                    k: v for k, v in patch.items() if k in allowed and v is not None
                }
                updates["updated_at"] = now
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                params = list(updates.values()) + [existing["id"]]
                conn.execute(
                    f"UPDATE user_preferences SET {set_clause} WHERE id = ?", params
                )
            else:
                cols = {
                    "language": patch.get("language", "en"),
                    "discipline": patch.get("discipline", "cs"),
                    "default_venue_tier": patch.get("default_venue_tier", "B"),
                    "default_quality_tier": patch.get(
                        "default_quality_tier", "standard"
                    ),
                    "default_autonomy": patch.get("default_autonomy", "L2"),
                    "monthly_budget_cap_usd": patch.get("monthly_budget_cap_usd", 100),
                    "onboarding_complete": patch.get("onboarding_complete", 0),
                    "auto_rollback_live": patch.get("auto_rollback_live", 0),
                    "created_at": now,
                    "updated_at": now,
                }
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols.keys())
                conn.execute(
                    f"INSERT INTO user_preferences ({col_names}) VALUES ({placeholders})",
                    list(cols.values()),
                )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM user_preferences ORDER BY id LIMIT 1"
            ).fetchone()
        return row_to_dict(row)

    @app.get("/api/demo/replay")
    def demo_replay_list():
        return {"entries": demo_list_entries()}

    @app.post("/api/demo/replay")
    def demo_replay(body: DemoReplayRequest):
        result = demo_lookup(body.stage, body.primitive, body.prompt)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No canned response for {body.stage}:{body.primitive}",
            )
        return {"canned": True, "cost_usd": 0, **result}
