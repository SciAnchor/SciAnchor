"""Optional config file + backend detection for llm_router.

The config file lets an install pin provider priorities and tier routes
without littering the shell with ``LLM_ROUTE_*`` / ``*_API_KEY`` env vars.
It is entirely optional: everything falls back to env-var behavior when the
file is absent, unreadable, or the TOML parser isn't available.

Discovery order:
  1. ``$LLM_ROUTER_CONFIG`` — explicit path
  2. ``~/.config/llm_router/config.toml`` — default user-wide location

Schema (all keys optional):

.. code-block:: toml

   [routing]
   # Override the built-in auto-detect priority. The first provider whose
   # credentials are available is picked when resolve_llm_config runs.
   provider_order = ["openai", "anthropic", "kimi"]

   # Tier routes consumed by resolve_route. Same format as LLM_ROUTE_{TIER}
   # env vars. Env vars still win when set.
   light  = "openai:gpt-4o-mini"
   medium = "openai:gpt-4o"
   heavy  = "anthropic:claude-opus-4-6"
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderAvailability:
    provider: str
    route_kind: str
    source: str


def _config_path() -> str:
    return os.environ.get(
        "LLM_ROUTER_CONFIG",
        os.path.expanduser("~/.config/llm_router/config.toml"),
    )


def load_config() -> dict[str, Any]:
    """Load the llm_router config file. Returns ``{}`` on any failure."""
    path = _config_path()
    if not os.path.isfile(path):
        return {}
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found]
        except ImportError:
            logger.debug(
                "tomllib/tomli unavailable; skipping llm_router config at %s", path
            )
            return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("llm_router config load failed: %s (%s)", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _is_cli_on_path(binary: str) -> bool:
    try:
        result = subprocess.run(
            ["which", binary],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.returncode == 0
    except Exception:
        return False


def detect_available_providers() -> list[str]:
    """Return built-in provider names whose credentials/CLI appear available."""
    available: list[str] = []
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        available.append("anthropic")
    if (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("CHATGPT_API_KEY")
        or os.environ.get("JD_OPENAI_API_KEY")
    ):
        available.append("openai")
    if os.environ.get("KIMI_API_KEY") or os.environ.get("ANTHROPIC_KIMI_KEY"):
        available.append("kimi")
    if os.environ.get("EVOLINK_API_KEY"):
        available.append("evolink")
    if _env_flag("CURSOR_AGENT_ENABLED") or _is_cli_on_path("agent"):
        available.append("cursor_agent")
    if _env_flag("CODEX_ENABLED") or _is_cli_on_path("codex"):
        available.append("codex")

    # LiteLLM-backed providers (optional).
    try:
        from .litellm_backend import detect_litellm_providers

        for name in detect_litellm_providers():
            if name not in available:
                available.append(name)
    except ImportError:
        pass

    return available


def detect_available_provider_details() -> list[ProviderAvailability]:
    """Describe every built-in route that currently looks usable."""
    details: list[ProviderAvailability] = []
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        details.append(
            ProviderAvailability(
                provider="anthropic",
                route_kind="anthropic-compatible"
                if os.environ.get("ANTHROPIC_BASE_URL")
                else "direct-api",
                source="env",
            )
        )
    if (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("CHATGPT_API_KEY")
        or os.environ.get("JD_OPENAI_API_KEY")
    ):
        details.append(
            ProviderAvailability(
                provider="openai",
                route_kind="openai-compatible"
                if os.environ.get("OPENAI_BASE_URL")
                or os.environ.get("CHATGPT_BASE_URL")
                else "direct-api",
                source="env",
            )
        )
    if os.environ.get("KIMI_API_KEY") or os.environ.get("ANTHROPIC_KIMI_KEY"):
        details.append(
            ProviderAvailability(
                provider="kimi",
                route_kind="direct-api",
                source="env",
            )
        )
    if os.environ.get("EVOLINK_API_KEY"):
        details.append(
            ProviderAvailability(
                provider="evolink",
                route_kind="openai-compatible",
                source="env",
            )
        )
    if _env_flag("CURSOR_AGENT_ENABLED") or _is_cli_on_path("agent"):
        details.append(
            ProviderAvailability(
                provider="cursor_agent",
                route_kind="host-cli",
                source="env" if _env_flag("CURSOR_AGENT_ENABLED") else "path",
            )
        )
    if _env_flag("CODEX_ENABLED") or _is_cli_on_path("codex"):
        details.append(
            ProviderAvailability(
                provider="codex",
                route_kind="host-cli",
                source="env" if _env_flag("CODEX_ENABLED") else "path",
            )
        )
    return details


def get_provider_order(config: dict[str, Any] | None = None) -> list[str] | None:
    """Return the configured provider priority list, or ``None`` if unset."""
    cfg = config if config is not None else load_config()
    routing = cfg.get("routing") if isinstance(cfg, dict) else None
    if not isinstance(routing, dict):
        return None
    order = routing.get("provider_order")
    if not isinstance(order, list):
        return None
    cleaned = [str(x).strip() for x in order if isinstance(x, str) and x.strip()]
    return cleaned or None


def get_tier_route(
    tier: str, config: dict[str, Any] | None = None
) -> tuple[str, str] | None:
    """Return ``(provider, model)`` for a tier from config, or ``None``."""
    cfg = config if config is not None else load_config()
    routing = cfg.get("routing") if isinstance(cfg, dict) else None
    if not isinstance(routing, dict):
        return None
    entry = routing.get(tier.lower())
    if not isinstance(entry, str) or ":" not in entry:
        return None
    provider, model = entry.split(":", 1)
    provider = provider.strip()
    model = model.strip()
    if not provider or not model:
        return None
    return (provider, model)
