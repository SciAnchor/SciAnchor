"""Daily freshness check for the writing-tier model route.

Policy (user requirement): manuscript prose must always run on the strongest
available Claude/GPT model. Model vendors ship new flagships without notice,
so once per day the router asks both Models APIs what exists, ranks the
results, and — when a strictly newer model in the same family appears —
smoke-tests it and rewrites the ``[routing] writing`` entry in the llm_router
config file. Cross-family jumps (e.g. opus → fable, which doubles cost) are
reported but not auto-applied unless ``auto_family_upgrade`` is set.

Entry points:
  - ``maybe_refresh_writing_route()`` — daily gate for operators/hooks and
    legacy non-accounted RH writing clients; accounted calls skip it.
  - ``python -m llm_router.model_freshness [--force] [--quiet]`` — CLI, used
    by the Claude Code SessionStart hook and ``rh`` tooling.

Config (``~/.config/llm_router/config.toml``)::

    [model_freshness]
    enabled = true                # false disables the check entirely
    pin = "anthropic:claude-..."  # exact route; disables auto-updates
    auto_family_upgrade = false   # allow e.g. opus -> fable switches

State: ``~/.research-harness/model_check.json`` (last check time + decision).
Failures are never fatal — the current route always keeps working.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_PATH = (
    Path(os.environ.get("RESEARCH_HARNESS_HOME", "~/.research-harness")).expanduser()
    / "model_check.json"
)
CHECK_INTERVAL_S = 24 * 3600

# Family rank: higher wins. Version numbers break ties within a family.
_ANTHROPIC_FAMILIES: list[tuple[str, int]] = [
    (r"^claude-fable-(\d+)(?:-(\d+))?$", 3),
    (r"^claude-opus-(\d+)(?:-(\d+))?$", 2),
    (r"^claude-sonnet-(\d+)(?:-(\d+))?$", 1),
]
_OPENAI_FAMILIES: list[tuple[str, int]] = [
    # Bare flagship ids and their top-tier variants; dated snapshots and
    # mini/nano/audio/embedding variants are deliberately excluded.
    (r"^gpt-(\d+)(?:\.(\d+))?(?:-(?:sol|pro))?$", 2),
]


@dataclass
class ModelRank:
    model_id: str
    family_rank: int
    version: tuple[int, ...]

    def sort_key(self) -> tuple[int, tuple[int, ...]]:
        return (self.family_rank, self.version)


def _rank_model(model_id: str, families: list[tuple[str, int]]) -> ModelRank | None:
    for pattern, family_rank in families:
        m = re.match(pattern, model_id)
        if m:
            version = tuple(int(g) for g in m.groups() if g and g.isdigit())
            return ModelRank(
                model_id=model_id, family_rank=family_rank, version=version
            )
    return None


def _http_json(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _list_anthropic_models() -> list[str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return []
    data = _http_json(
        "https://api.anthropic.com/v1/models?limit=100",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return [m.get("id", "") for m in data.get("data", []) if m.get("id")]


def _list_openai_models() -> list[str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return []
    data = _http_json(
        "https://api.openai.com/v1/models",
        {"Authorization": f"Bearer {key}"},
    )
    return [m.get("id", "") for m in data.get("data", []) if m.get("id")]


def _best_available(provider: str) -> ModelRank | None:
    if provider == "anthropic":
        ids, families = _list_anthropic_models(), _ANTHROPIC_FAMILIES
    elif provider == "openai":
        ids, families = _list_openai_models(), _OPENAI_FAMILIES
    else:
        return None
    ranked = [r for r in (_rank_model(i, families) for i in ids) if r]
    return max(ranked, key=ModelRank.sort_key) if ranked else None


def _freshness_config() -> dict[str, Any]:
    try:
        from .config import load_config

        cfg = load_config().get("model_freshness")
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _current_writing_route() -> tuple[str, str] | None:
    env = os.environ.get("LLM_ROUTE_WRITING", "").strip()
    if env and ":" in env:
        provider, model = env.split(":", 1)
        return provider.strip(), model.strip()
    try:
        from .config import get_tier_route

        route = get_tier_route("writing")
        if route:
            return route
    except Exception:
        pass
    try:
        from .client import _DEFAULT_ROUTES

        return _DEFAULT_ROUTES.get("writing")
    except Exception:
        return None


def _smoke_test(provider: str, model: str) -> bool:
    """One tiny request; True means the candidate model actually serves."""
    try:
        from .client import LLMClient

        out = LLMClient().chat(
            "Reply with the single word: ok", provider=provider, model=model
        )
        return bool(out and out.strip())
    except Exception as exc:
        logger.warning(
            "model_freshness smoke test failed for %s:%s — %s", provider, model, exc
        )
        return False


def _config_path() -> Path:
    return Path(
        os.environ.get("LLM_ROUTER_CONFIG", "~/.config/llm_router/config.toml")
    ).expanduser()


def _write_writing_route(provider: str, model: str) -> None:
    """Update ``[routing] writing`` in config.toml with minimal text surgery."""
    path = _config_path()
    line = f'writing = "{provider}:{model}"'
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*writing\s*=", text):
            text = re.sub(r"(?m)^\s*writing\s*=.*$", line, text, count=1)
        elif re.search(r"(?m)^\[routing\]", text):
            text = re.sub(r"(?m)^\[routing\]\s*$", f"[routing]\n{line}", text, count=1)
        else:
            text = text.rstrip() + f"\n\n[routing]\n{line}\n"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = f"[routing]\n{line}\n"
    path.write_text(text, encoding="utf-8")


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("model_freshness: state save failed", exc_info=True)


def refresh_writing_route(*, force: bool = False) -> dict[str, Any]:
    """Run the freshness check now. Returns a decision dict (also persisted)."""
    cfg = _freshness_config()
    decision: dict[str, Any] = {"checked_at": time.time(), "action": "none"}

    if cfg.get("enabled") is False or cfg.get("pin"):
        decision["action"] = "disabled" if cfg.get("enabled") is False else "pinned"
        _save_state(decision)
        return decision

    current = _current_writing_route()
    if not current:
        decision["action"] = "no_current_route"
        _save_state(decision)
        return decision
    provider, model = current
    decision["current"] = f"{provider}:{model}"

    try:
        best = _best_available(provider)
    except Exception as exc:
        decision.update(action="api_error", error=str(exc)[:200])
        _save_state(decision)
        return decision

    if best is None or best.model_id == model:
        _save_state(decision)
        return decision

    families = _ANTHROPIC_FAMILIES if provider == "anthropic" else _OPENAI_FAMILIES
    cur_rank = _rank_model(model, families)
    if cur_rank is None:
        decision["action"] = "current_unranked"
        _save_state(decision)
        return decision

    if best.sort_key() <= cur_rank.sort_key():
        _save_state(decision)
        return decision

    same_family = best.family_rank == cur_rank.family_rank
    if not same_family and not cfg.get("auto_family_upgrade"):
        decision.update(
            action="notice_only",
            candidate=f"{provider}:{best.model_id}",
            note="stronger family available; set auto_family_upgrade=true to switch",
        )
        logger.warning(
            "model_freshness: %s available (current %s). Cross-family switch "
            "changes cost — enable [model_freshness].auto_family_upgrade to adopt.",
            best.model_id,
            model,
        )
        _save_state(decision)
        return decision

    if not _smoke_test(provider, best.model_id):
        decision.update(action="smoke_failed", candidate=f"{provider}:{best.model_id}")
        _save_state(decision)
        return decision

    _write_writing_route(provider, best.model_id)
    decision.update(action="updated", candidate=f"{provider}:{best.model_id}")
    logger.warning(
        "model_freshness: writing route updated %s -> %s", model, best.model_id
    )
    _save_state(decision)
    return decision


def maybe_refresh_writing_route() -> dict[str, Any] | None:
    """Daily gate: run the check at most once per 24h. Never raises."""
    try:
        state = _load_state()
        last = float(state.get("checked_at") or 0)
        if time.time() - last < CHECK_INTERVAL_S:
            return None
        return refresh_writing_route()
    except Exception:
        logger.debug("model_freshness: check skipped", exc_info=True)
        return None


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh the writing-tier model route")
    parser.add_argument("--force", action="store_true", help="ignore the 24h gate")
    parser.add_argument("--quiet", action="store_true", help="suppress stdout")
    args = parser.parse_args()

    result = (
        refresh_writing_route()
        if args.force
        else (maybe_refresh_writing_route() or {"action": "fresh"})
    )
    if not args.quiet:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
