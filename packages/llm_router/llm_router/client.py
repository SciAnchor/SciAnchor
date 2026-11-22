"""Multi-provider LLM client with task-tier routing.

Architecture:
  - Provider Registry: pluggable provider functions (cursor_agent, codex, openai, anthropic, kimi)
  - Task Tier Routing: light/medium/heavy → provider:model mapping via env vars
  - LLMClient: unified interface, backwards-compatible

Adding a new provider:
  1. Write a function: (prompt: str, model: str, **kwargs) -> str
  2. Call register_provider("name", fn)
  3. Set env: LLM_ROUTE_LIGHT=name:model-id
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib import error, request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token usage accounting
#
# Providers call ``_record_usage`` after a successful request so LLMClient can
# surface it via ``get_last_usage``. Stored in thread-local storage so
# concurrent calls from different threads do not cross-contaminate. Providers
# that cannot observe token counts (e.g. CLI agents) simply skip recording.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMUsage:
    """Token usage reported by a provider for a single request."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BudgetAuthorization:
    """Durable caller authority for one bounded provider purchase."""

    attempt_id: str
    request_sha256: str
    max_cost_usd: float
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.idempotency_key:
            raise ValueError("budget authorization identity is required")
        if not _SHA256_RE.fullmatch(self.request_sha256):
            raise ValueError("budget authorization request_sha256 is invalid")
        if not math.isfinite(self.max_cost_usd) or self.max_cost_usd <= 0:
            raise ValueError("budget authorization max_cost_usd must be positive")


@dataclass(frozen=True)
class ProviderUsageReceipt:
    """Provider outcome returned atomically with its text."""

    attempt_id: str
    request_sha256: str
    provider: str
    model: str
    provider_request_id: str | None
    provider_started: bool
    completion_known: bool
    prompt_tokens: int | None
    completion_tokens: int | None
    cache_read_tokens: int | None
    cost_usd: float | None
    cost_source: str
    transport: str
    evidence_class: str
    output_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.provider or not self.model:
            raise ValueError("provider receipt identity is required")
        if not _SHA256_RE.fullmatch(self.request_sha256):
            raise ValueError("provider receipt request_sha256 is invalid")
        if self.provider_request_id is not None and not self.provider_request_id:
            raise ValueError("provider_request_id must be non-empty when present")
        if (
            type(self.provider_started) is not bool
            or type(self.completion_known) is not bool
        ):
            raise TypeError("provider receipt state must be boolean")
        for name in ("prompt_tokens", "completion_tokens", "cache_read_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.cost_usd is not None and (
            not isinstance(self.cost_usd, (int, float))
            or isinstance(self.cost_usd, bool)
            or not math.isfinite(float(self.cost_usd))
            or self.cost_usd < 0
        ):
            raise ValueError("provider receipt cost_usd is invalid")
        if not self.cost_source or not self.evidence_class:
            raise ValueError("provider receipt cost evidence is required")
        if self.transport not in {"provider", "synthetic", "cache", "replay"}:
            raise ValueError("provider receipt transport is invalid")
        if not _SHA256_RE.fullmatch(self.output_sha256):
            raise ValueError("provider receipt output_sha256 is invalid")
        payload = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "receipt_sha256"
        }
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.receipt_sha256 != expected:
            raise ValueError("provider receipt hash is invalid")


_usage_local = threading.local()


def _record_usage(prompt_tokens: int | None, completion_tokens: int | None) -> None:
    """Record usage for the current thread's most recent LLM call."""
    _usage_local.value = LLMUsage(
        prompt_tokens=prompt_tokens if prompt_tokens is not None else None,
        completion_tokens=completion_tokens if completion_tokens is not None else None,
    )


def _clear_usage() -> None:
    _usage_local.value = None


def get_last_usage() -> LLMUsage | None:
    """Return usage recorded by the most recent provider call on this thread."""
    return getattr(_usage_local, "value", None)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_from_openai_dict(payload: Any) -> tuple[int | None, int | None]:
    """Extract (prompt_tokens, completion_tokens) from an OpenAI-style dict."""
    if not isinstance(payload, dict):
        return (None, None)
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return (None, None)
    prompt = _coerce_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _coerce_int(
        usage.get("completion_tokens") or usage.get("output_tokens")
    )
    return (prompt, completion)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Provider = str  # open-ended: built-in + litellm + plugin providers
TaskTier = Literal["light", "medium", "heavy", "writing"]
ProviderFn = Callable[..., str]  # (prompt, model, **kwargs) -> response
AccountedProviderFn = Callable[..., tuple[str, ProviderUsageReceipt]]

# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, ProviderFn] = {}
_ACCOUNTED_PROVIDER_REGISTRY: dict[str, AccountedProviderFn] = {}


class AccountedProviderNotStarted(ValueError):
    """Preflight-only proof that an accounted provider transport did not start."""


class AccountedProviderUnsupported(AccountedProviderNotStarted):
    """Raised before transport when a provider lacks the accounted contract."""


def register_provider(
    name: str,
    fn: ProviderFn,
    *,
    accounted_fn: AccountedProviderFn | None = None,
) -> None:
    """Register a provider function. Overwrites existing registration."""
    _PROVIDER_REGISTRY[name] = fn
    if accounted_fn is None:
        _ACCOUNTED_PROVIDER_REGISTRY.pop(name, None)
    else:
        _ACCOUNTED_PROVIDER_REGISTRY[name] = accounted_fn


def get_provider(name: str) -> ProviderFn:
    """Get a registered provider by name."""
    fn = _PROVIDER_REGISTRY.get(name)
    if fn is None:
        available = ", ".join(sorted(_PROVIDER_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return fn


def list_providers() -> list[str]:
    """List all registered provider names."""
    return sorted(_PROVIDER_REGISTRY)


# ---------------------------------------------------------------------------
# Task Tier Routing
# ---------------------------------------------------------------------------

_DEFAULT_ROUTES: dict[TaskTier, tuple[str, str]] = {
    "light": ("openai", "gpt-4o-mini"),
    "medium": ("openai", "gpt-4o"),
    "heavy": ("anthropic", "claude-opus-4-8"),
    "writing": ("anthropic", "claude-opus-4-8"),
}

# ---------------------------------------------------------------------------
# Provider Blocklist — RED LINE: never use these providers for paper-reading
# tasks (light/medium tiers). Anthropic API is too expensive for bulk
# summarization, card extraction, and deep-reading work that basic models
# handle well. Heavy tier (review/approval) is exempt.
# ---------------------------------------------------------------------------

_BLOCKED_PROVIDERS_BY_TIER: dict[TaskTier, frozenset[str]] = {
    "light": frozenset({"anthropic"}),
    "medium": frozenset({"anthropic"}),
    "heavy": frozenset(),  # heavy tier may use any provider
    "writing": frozenset(),
}

# WRITING LINE — the inverse of the RED LINE above. Manuscript prose work
# (section drafting/revision/review, whole-manuscript unification, exemplar
# generation) must run on a frontier writing model. Only these providers
# qualify; when none is usable the call FAILS LOUDLY instead of silently
# degrading to a cheaper provider, because degraded prose is worse than no
# prose (it gets submitted).
_ALLOWED_PROVIDERS_BY_TIER: dict[TaskTier, frozenset[str]] = {
    "writing": frozenset({"anthropic", "openai"}),
}

_TIER_FALLBACKS: dict[TaskTier, tuple[str, str]] = {
    "light": ("openai", "gpt-4o-mini"),
    "medium": ("openai", "gpt-4o"),
}


class WritingTierUnavailableError(RuntimeError):
    """The writing tier has no allowed frontier provider configured."""


def _apply_blocklist(tier: TaskTier, provider_name: str, model: str) -> tuple[str, str]:
    """Replace ``provider_name`` with a safe default when blocked for this tier."""
    # Escape hatch for local dev / users with proxied Anthropic access.
    if os.environ.get("LLM_ROUTE_ALLOW_ANYTHING", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return provider_name, model
    allowed = _ALLOWED_PROVIDERS_BY_TIER.get(tier)
    if allowed is not None and provider_name not in allowed:
        raise WritingTierUnavailableError(
            f"Tier '{tier}' accepts only providers {sorted(allowed)}, got "
            f"'{provider_name}'. Writing-quality tasks never degrade to cheaper "
            f"models — set LLM_ROUTE_{tier.upper()}=anthropic:claude-opus-4-8 "
            "(or openai:<frontier model>) with the matching API key, or export "
            "LLM_ROUTE_ALLOW_ANYTHING=1 to explicitly opt out."
        )
    blocked = _BLOCKED_PROVIDERS_BY_TIER.get(tier, frozenset())
    if provider_name in blocked:
        fallback = _TIER_FALLBACKS.get(tier, _DEFAULT_ROUTES["medium"])
        logger.warning(
            "RED LINE: provider '%s' is blocked for tier '%s' "
            "(paper-reading tasks must not use expensive APIs). "
            "Falling back to %s:%s",
            provider_name,
            tier,
            fallback[0],
            fallback[1],
        )
        return fallback
    return (provider_name, model)


def resolve_route(tier: TaskTier) -> tuple[str, str]:
    """Resolve a task tier to (provider_name, model).

    Priority: LLM_ROUTE_{TIER} env > config file [routing] tier entry >
    _DEFAULT_ROUTES.

    RED LINE: if the resolved provider is in the blocklist for this tier,
    logs a warning and falls back to the safe default.
    """
    env_key = f"LLM_ROUTE_{tier.upper()}"
    env_val = os.environ.get(env_key, "").strip()
    if env_val and ":" in env_val:
        provider_name, model = env_val.split(":", 1)
        return _apply_blocklist(tier, provider_name.strip(), model.strip())

    from .config import get_tier_route

    config_route = get_tier_route(tier)
    if config_route is not None:
        return _apply_blocklist(tier, config_route[0], config_route[1])

    default = _DEFAULT_ROUTES.get(tier, _DEFAULT_ROUTES["medium"])
    if default[0] in _PROVIDER_REGISTRY:
        return default

    # Allowlisted tiers (writing) never auto-map to cheap litellm providers.
    if tier in _ALLOWED_PROVIDERS_BY_TIER:
        raise WritingTierUnavailableError(
            f"No provider available for tier '{tier}' "
            f"(allowed: {sorted(_ALLOWED_PROVIDERS_BY_TIER[tier])}). "
            f"Set LLM_ROUTE_{tier.upper()} or configure an allowed provider."
        )

    # Default provider not registered — try auto-mapping from litellm providers.
    try:
        from .litellm_backend import suggest_tier_mapping
        from .config import detect_available_providers

        available = detect_available_providers()
        suggested = suggest_tier_mapping(available)
        if tier in suggested:
            return _apply_blocklist(tier, suggested[tier][0], suggested[tier][1])
    except ImportError:
        pass
    return default


def set_default_route(tier: TaskTier, provider: str, model: str) -> None:
    """Override default route for a tier (programmatic, not env-based)."""
    _DEFAULT_ROUTES[tier] = (provider, model)


# ---------------------------------------------------------------------------
# CLI Provider Implementations
# ---------------------------------------------------------------------------

_CLI_TIMEOUT = 300  # 5-minute hard ceiling


def _chat_cursor_agent(prompt: str, model: str, **_: Any) -> str:
    """Call Cursor Agent CLI in headless print mode."""
    # PDF/text extraction can occasionally contain embedded NUL bytes. Python's
    # subprocess layer rejects argv entries with NULs, so strip them before
    # passing the prompt as a CLI argument.
    prompt = prompt.replace("\x00", "")
    cmd = ["agent", "--print", "--trust", "--model", model, prompt]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_CLI_TIMEOUT
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Cursor Agent CLI not found. Install from https://docs.cursor.com/agent"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Cursor Agent timed out after {_CLI_TIMEOUT}s")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Cursor Agent failed (exit {result.returncode}): {stderr}")
    return (result.stdout or "").strip()


def _chat_codex(prompt: str, model: str, **_: Any) -> str:
    """Call Codex CLI in non-interactive mode."""
    # Pin an isolated, ephemeral working directory. Codex otherwise inherits
    # the parent process cwd — for RH primitives that is the project/repo tree,
    # frequently outside Codex's project-trust list. A throwaway dir keeps a
    # pure JSON chat call from reading or mutating project files.
    workdir = tempfile.mkdtemp(prefix="rh-codex-")
    cmd = ["codex", "exec", "--cd", workdir, "--full-auto", "--ephemeral", "--json"]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_CLI_TIMEOUT
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Codex CLI not found. Install with: npm install -g @openai/codex"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Codex timed out after {_CLI_TIMEOUT}s")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Codex failed (exit {result.returncode}): {stderr}")
    # Parse JSONL output: find last agent_message item AND scan for usage events.
    text_parts: list[str] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    for line in (result.stdout or "").strip().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message" and item.get("text"):
                text_parts.append(item["text"])
        # Codex emits token usage in a variety of event shapes; probe the most
        # common places conservatively and let the last seen value win.
        usage_like: dict[str, Any] | None = None
        if isinstance(event.get("usage"), dict):
            usage_like = event["usage"]
        elif isinstance(event.get("token_usage"), dict):
            usage_like = event["token_usage"]
        elif isinstance(event.get("info"), dict) and isinstance(
            event["info"].get("usage"), dict
        ):
            usage_like = event["info"]["usage"]
        if usage_like is not None:
            p = _coerce_int(
                usage_like.get("prompt_tokens") or usage_like.get("input_tokens")
            )
            c = _coerce_int(
                usage_like.get("completion_tokens") or usage_like.get("output_tokens")
            )
            if p is not None:
                prompt_tokens = p
            if c is not None:
                completion_tokens = c
    if prompt_tokens is not None or completion_tokens is not None:
        _record_usage(prompt_tokens, completion_tokens)
    return (
        "\n".join(text_parts).strip() if text_parts else (result.stdout or "").strip()
    )


# ---------------------------------------------------------------------------
# API Provider Implementations
# ---------------------------------------------------------------------------

_LLM_TIMEOUT_SECONDS = 300.0

# Fast-fail + contention control for OpenAI-compatible endpoints.
#
# The OpenAI SDK's built-in defaults are a 600s per-attempt timeout and 2
# retries, so a single stalled request against a saturated *local tunnel* can
# block silently for ~30 minutes. That is exactly what makes a heavy RH job
# (e.g. the polish gate) appear to "hang" when it is really queued behind
# another job on the same one-pipe SSH tunnel. We instead bound the wait so a
# contended call surfaces an error in minutes, and optionally serialize calls
# to a shared local tunnel across processes.
#
# 180 s cut long generations (RH candidate design, 6-9k output tokens at ~22 tokens/s on the
# grok route) and the SDK then re-sent them: 180 + 180 = 360 s "Request timed out." (a0113,
# 2026-09-26), and a generation that finished on the retry was bought twice. 480 s fits a
# ~9k-token reply; a timeout is not retried, only fast transport failures are.
_DEFAULT_HTTP_TIMEOUT_SECONDS = 480.0
_DEFAULT_HTTP_MAX_RETRIES = 1


def _http_timeout() -> float:
    """Per-request timeout for OpenAI-compatible providers (env override:
    ``LLM_HTTP_TIMEOUT_SECONDS``). Bounds a stalled call instead of inheriting
    the SDK's 600s default."""
    raw = os.environ.get("LLM_HTTP_TIMEOUT_SECONDS", "").strip()
    try:
        value = float(raw)
        if value > 0:
            return value
    except ValueError:
        pass
    return _DEFAULT_HTTP_TIMEOUT_SECONDS


def _http_max_retries() -> int:
    """Retry budget for OpenAI-compatible providers (env override:
    ``LLM_HTTP_MAX_RETRIES``). Kept small so worst-case latency stays bounded."""
    raw = os.environ.get("LLM_HTTP_MAX_RETRIES", "").strip()
    try:
        value = int(raw)
        if value >= 0:
            return value
    except ValueError:
        pass
    return _DEFAULT_HTTP_MAX_RETRIES


def _create_with_transport_retries(client: Any, kwargs: dict[str, Any]) -> Any:
    """One chat completion, re-sent only after a failure that bought nothing.

    A timeout is not re-sent: the gateway may still be generating (and billing) the first
    reply, and re-sending a long generation doubles its cost and its wait. A refused
    connection, a 429 or a 5xx fails fast and is retried up to ``_http_max_retries()``.
    """
    import openai

    timeout_error = getattr(openai, "APITimeoutError", ())
    transient = tuple(
        getattr(openai, name)
        for name in ("APIConnectionError", "RateLimitError", "InternalServerError")
        if hasattr(openai, name)
    )
    retries = _http_max_retries()
    for attempt in range(retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except timeout_error:
            raise
        except transient:
            if attempt >= retries:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")  # pragma: no cover


def _serialize_lock_path(base_url: str, *, is_image: bool = False) -> str | None:
    """Return an flock path when concurrent calls to a shared *local* tunnel
    should be serialized, else None.

    Opt-in via ``LLM_TUNNEL_SERIALIZE=1`` and only for loopback base URLs.
    Scope matters: the tunnel's text/chat endpoint is load-balanced across
    several upstream accounts and scales with concurrency, so text calls are
    **not** serialized — serializing them needlessly starves parallel jobs
    (e.g. exemplar/EAG planning contending with figure generation). Only the
    scarce image-generation endpoint is serialized, detected by ``is_image``
    or an ``/image`` path segment. Set
    ``LLM_TUNNEL_SERIALIZE_ALL=1`` to restore serialization of every loopback
    call (legacy single-pipe behaviour / safety valve). Lock path is
    ``LLM_TUNNEL_LOCK_PATH`` or ``~/.config/research-harness/tunnel.lock``, so a
    cooperating external tool (the figure generator) can share the same lock.
    """
    if os.environ.get("LLM_TUNNEL_SERIALIZE", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return None
    if not any(h in (base_url or "") for h in ("127.0.0.1", "localhost", "::1")):
        return None
    serialize_all = os.environ.get("LLM_TUNNEL_SERIALIZE_ALL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    bl = (base_url or "").lower()
    is_image_endpoint = is_image or ("/image" in bl)
    if not (serialize_all or is_image_endpoint):
        # Text/chat call on the load-balanced tunnel: run concurrently.
        return None
    path = os.environ.get("LLM_TUNNEL_LOCK_PATH", "").strip()
    if not path:
        path = os.path.join(
            os.path.expanduser("~"), ".config", "research-harness", "tunnel.lock"
        )
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return None
    return path


def _endpoint_serialize_guard(base_url: str, *, is_image: bool = False):
    """Context manager that (optionally) holds a cross-process lock while a
    request runs, so concurrent processes take turns on a shared local tunnel.
    Degrades to a no-op when disabled or when ``fcntl`` is unavailable."""
    import contextlib

    @contextlib.contextmanager
    def _guard():
        path = _serialize_lock_path(base_url, is_image=is_image)
        if not path:
            yield
            return
        try:
            import fcntl
        except ImportError:  # non-POSIX; skip locking
            yield
            return
        handle = open(path, "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()

    return _guard()


def _build_anthropic_client(
    api_key: str, base_url: str, timeout: float = _LLM_TIMEOUT_SECONDS
):
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package is required. Install with: pip install anthropic"
        ) from exc
    kwargs: dict[str, Any] = {"api_key": api_key or None, "timeout": timeout}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


_ANTHROPIC_MAX_TOKENS = 8192


def _chat_anthropic(
    prompt: str,
    model: str,
    *,
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.0,
    **_: Any,
) -> str:
    if not api_key:
        raise ValueError("Anthropic provider requires api_key")
    client = _build_anthropic_client(api_key, base_url)
    response = client.messages.create(
        model=model,
        # Bumped from 2048 → 4096 to fix silent mid-string JSON truncation on
        # deep_read pass1 (see docs/TROUBLESHOOTING.md — long structured
        # outputs used to hit the cap mid-string and return {}).
        max_tokens=_ANTHROPIC_MAX_TOKENS,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(response, "usage", None)
    if usage is not None:
        _record_usage(
            _coerce_int(getattr(usage, "input_tokens", None)),
            _coerce_int(getattr(usage, "output_tokens", None)),
        )
    content_blocks = response.content
    if content_blocks is None:
        err = None
        try:
            err = response.model_dump().get("error")
        except Exception:
            pass
        raise RuntimeError(
            f"Anthropic returned empty content (model={model}). "
            f"The proxy may have rejected the model name. error={err}"
        )
    return "\n".join(b.text for b in content_blocks if hasattr(b, "text"))


_KIMI_DEFAULT_BASE_URL = "https://api.kimi.com/coding/"
_KIMI_MAX_TOKENS = 20480


def _resolve_kimi_base_url(base_url: str) -> str:
    normalized = (base_url or _KIMI_DEFAULT_BASE_URL).strip().rstrip("/")
    if normalized.endswith("/messages"):
        normalized = normalized[: -len("/messages")]
    if normalized.endswith("/v1"):
        normalized = normalized[: -len("/v1")]
    return normalized + "/"


def _chat_kimi(
    prompt: str,
    model: str,
    *,
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.0,
    **_: Any,
) -> str:
    if not api_key:
        raise ValueError("Kimi provider requires api_key")
    resolved_url = _resolve_kimi_base_url(base_url)
    client = _build_anthropic_client(api_key, resolved_url)
    with client.messages.stream(
        model=model,
        max_tokens=_KIMI_MAX_TOKENS,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        text = stream.get_final_text()
        try:
            final_message = stream.get_final_message()
            usage = getattr(final_message, "usage", None)
            if usage is not None:
                _record_usage(
                    _coerce_int(getattr(usage, "input_tokens", None)),
                    _coerce_int(getattr(usage, "output_tokens", None)),
                )
        except Exception:  # pragma: no cover - best-effort usage capture
            pass
        return text


# Backward-compat aliases for tests
_resolve_kimi_anthropic_base_url = _resolve_kimi_base_url


def _resolve_kimi_messages_url(base_url: str) -> str:
    normalized = (
        (base_url or "https://api.kimi.com/coding/v1/messages").strip().rstrip("/")
    )
    if normalized.endswith("/messages"):
        return normalized
    if normalized.endswith("/coding"):
        return f"{normalized}/v1/messages"
    return f"{normalized}/messages"


# Models whose API rejects `temperature` (learned on first 400, per process).
_NO_TEMPERATURE_MODELS: set[str] = set()

# OpenAI-compatible gateways (sub2api -> Anthropic) default to 8192 output
# tokens, which truncates long structured JSON (deep_read pass 2). Ask for
# more explicitly; override with LLM_MAX_OUTPUT_TOKENS.
_OPENAI_MAX_TOKENS_ENV = "LLM_MAX_OUTPUT_TOKENS"
_OPENAI_MAX_TOKENS_DEFAULT = 32000


def _openai_max_tokens() -> int:
    raw = os.environ.get(_OPENAI_MAX_TOKENS_ENV, "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _OPENAI_MAX_TOKENS_DEFAULT


def _chat_openai(
    prompt: str,
    model: str,
    *,
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.0,
    **_: Any,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is required. Install with: pip install openai"
        ) from exc
    client = OpenAI(
        api_key=api_key,
        base_url=base_url or None,
        timeout=_http_timeout(),
        # Retried below, where a timeout is told apart from a fast transport failure.
        max_retries=0,
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": _openai_max_tokens(),
    }
    if model not in _NO_TEMPERATURE_MODELS:
        kwargs["temperature"] = temperature
    with _endpoint_serialize_guard(base_url):
        try:
            response = _create_with_transport_retries(client, kwargs)
        except Exception as exc:
            # Newer models (claude-*-5, gpt-5.x reasoning) reject sampling params.
            if "temperature" not in str(exc) or "temperature" not in kwargs:
                raise
            _NO_TEMPERATURE_MODELS.add(model)
            kwargs.pop("temperature", None)
            response = _create_with_transport_retries(client, kwargs)
    usage = getattr(response, "usage", None)
    if usage is not None:
        _record_usage(
            _coerce_int(getattr(usage, "prompt_tokens", None)),
            _coerce_int(getattr(usage, "completion_tokens", None)),
        )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Evolink Provider — OpenAI-compatible gateway
# ---------------------------------------------------------------------------

_EVOLINK_DEFAULT_BASE_URL = "https://direct.evolink.ai/v1"


def _chat_evolink(
    prompt: str,
    model: str,
    *,
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.0,
    **kwargs: Any,
) -> str:
    """Evolink AI gateway — OpenAI-compatible endpoint.

    Uses ``EVOLINK_API_KEY`` and defaults to ``https://direct.evolink.ai/v1``.
    Falls back to the generic ``_chat_openai`` implementation since the API
    is fully OpenAI-compatible.
    """
    import os

    resolved_key = api_key or os.environ.get("EVOLINK_API_KEY", "")
    if not resolved_key:
        raise ValueError("Evolink provider requires EVOLINK_API_KEY")
    resolved_url = (
        base_url or os.environ.get("EVOLINK_BASE_URL") or _EVOLINK_DEFAULT_BASE_URL
    )
    return _chat_openai(
        prompt,
        model,
        api_key=resolved_key,
        base_url=resolved_url,
        temperature=temperature,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Register Built-in Providers
# ---------------------------------------------------------------------------

register_provider("cursor_agent", _chat_cursor_agent)
register_provider("codex", _chat_codex)
register_provider("anthropic", _chat_anthropic)
register_provider("openai", _chat_openai)
register_provider("kimi", _chat_kimi)
register_provider("evolink", _chat_evolink)


_BUILTIN_PROVIDERS = {"anthropic", "openai", "kimi", "cursor_agent", "codex", "evolink"}
_CLI_PROVIDERS = frozenset({"cursor_agent", "codex"})

# Register LiteLLM-backed providers (optional: graceful no-op if litellm is absent).
try:
    from .litellm_backend import register_litellm_providers

    register_litellm_providers()
except ImportError:
    pass


def available_providers() -> list[str]:
    """Return the list of currently-usable LLM providers, ordered by preference.

    Used by parallel workers (e.g. the deep-read expansion pool) to fan out
    work across every available agent rather than hammering a single
    tier-routed default.

    Order (rough throughput / cost preference for background batch work):
      1. Plugin-registered providers (`list_providers()` minus built-ins) —
         these are almost always local corporate gateways the user explicitly
         installed, so we trust registration as an availability signal.
         Example: plugin-registered providers from
         ``~/.config/llm_router/plugins/``.
      2. ``cursor_agent`` — local CLI, no API quota (auto-detected via
         ``which agent`` even if ``CURSOR_AGENT_ENABLED`` is not set).
      3. ``anthropic`` — proxy or direct API key.
      4. ``openai`` — direct API key.
      5. ``kimi`` — direct API key.

    ``codex`` is intentionally excluded — it targets code generation, not
    paper reading. Use ``RESEARCH_HARNESS_DEEP_READ_PROVIDERS`` (a
    comma-separated list) if you want to override the default pool
    (e.g. to drop a provider that's temporarily broken upstream).
    """
    out: list[str] = []

    # Plugin providers first: if the user installed a plugin, they want it used.
    try:
        registered = list_providers()
    except Exception:
        registered = []
    for name in registered:
        if name in _BUILTIN_PROVIDERS:
            continue
        # Skip plugin-tagged aliases so the pool doesn't run the same
        # backend twice under two names. Convention: plugins mark aliased
        # chat fns with ``fn.__llm_router_alias__ = "<canonical-name>"``.
        try:
            fn = get_provider(name)
        except Exception:
            fn = None
        if fn is not None and getattr(fn, "__llm_router_alias__", None):
            continue
        out.append(name)

    # Delegate built-in detection to the richer config-layer probe, which
    # also handles CLI-on-PATH for cursor_agent / codex.
    try:
        from .config import detect_available_providers

        builtin = detect_available_providers()
    except Exception:
        builtin = []
    for name in builtin:
        if name == "codex":
            continue  # code-gen CLI, wrong shape for paper reading
        if name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Config Resolution (backwards-compatible)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedLLMConfig:
    provider: str = "openai"
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "provider": self.provider,
                "model": self.model,
                "api_key": self.api_key,
                "base_url": self.base_url,
            }.items()
            if v
        }


def resolve_llm_config(overrides: dict[str, Any] | None = None) -> ResolvedLLMConfig:
    """Resolve LLM config from overrides -> config file -> env vars.

    Priority for picking the provider:
      1. ``overrides['provider']`` — explicit caller override
      2. ``$LLM_PROVIDER`` — explicit environment override
      3. ``[routing] provider_order`` in config file — walk list, pick first
         with satisfied credentials (or any registered plugin provider)
      4. Built-in auto-detect: cursor_agent > anthropic > openai > kimi >
         evolink > codex (codex last: it is a code-gen CLI, unsuitable as a
         structured-JSON chat backend for primitives)
    """
    overrides = overrides or {}
    provider_override = str(overrides.get("provider", "")).strip().lower()
    env_provider_override = os.environ.get("LLM_PROVIDER", "").strip().lower()

    # Env/CLI detection. Cursor Agent is authenticated out-of-band by the
    # local CLI, so the CLI being on PATH is a sufficient availability signal
    # even when CURSOR_AGENT_ENABLED is not explicitly exported. This keeps
    # resolve_llm_config consistent with detect_available_providers().
    cursor_enabled = (
        os.environ.get("CURSOR_AGENT_ENABLED", "").strip().lower()
        in (
            "1",
            "true",
            "yes",
        )
        or shutil.which("agent") is not None
    )
    codex_enabled = (
        os.environ.get("CODEX_ENABLED", "").strip().lower()
        in (
            "1",
            "true",
            "yes",
        )
        or shutil.which("codex") is not None
    )
    anthropic_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or ""
    )
    openai_key = (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("CHATGPT_API_KEY") or ""
    )
    kimi_key = os.environ.get("KIMI_API_KEY", "")
    evolink_key = os.environ.get("EVOLINK_API_KEY", "")

    available_builtin: dict[str, bool] = {
        "anthropic": bool(anthropic_key),
        "openai": bool(openai_key),
        "kimi": bool(kimi_key),
        "evolink": bool(evolink_key),
        "cursor_agent": cursor_enabled,
        "codex": codex_enabled,
    }

    valid_providers = set(_PROVIDER_REGISTRY)
    provider: str | None = None

    if provider_override in valid_providers:
        provider = provider_override
    elif env_provider_override in valid_providers:
        provider = env_provider_override
    elif overrides.get("api_key"):
        provider = "openai"
    else:
        # Try config-file provider_order first.
        from .config import get_provider_order

        order = get_provider_order()
        if order:
            for candidate in order:
                if candidate in available_builtin:
                    if available_builtin[candidate]:
                        provider = candidate
                        break
                elif candidate in valid_providers:
                    # Plugin-registered provider: trust the user's choice.
                    provider = candidate
                    break

        if provider is None:
            if cursor_enabled:
                provider = "cursor_agent"
            elif anthropic_key and (
                not openai_key or os.environ.get("ANTHROPIC_MODEL")
            ):
                provider = "anthropic"
            elif openai_key:
                provider = "openai"
            elif kimi_key:
                provider = "kimi"
            elif evolink_key:
                provider = "evolink"
            elif codex_enabled:
                # codex is an agentic code-gen CLI, not a structured-JSON chat
                # backend: primitives that require strict JSON (claim_extract,
                # etc.) break when routed to it. Only fall back to codex when no
                # API provider is configured.
                provider = "codex"
            else:
                provider = "cursor_agent" if cursor_enabled else "openai"

    # Resolve model/key/url per provider
    model: str
    api_key: str
    base_url: str

    if provider == "cursor_agent":
        model = str(
            overrides.get("model")
            or os.environ.get("CURSOR_AGENT_MODEL")
            or "composer-2.5-fast"
        )
        api_key = ""
        base_url = ""
    elif provider == "codex":
        model = str(overrides.get("model") or os.environ.get("CODEX_MODEL") or "")
        api_key = ""
        base_url = ""
    elif provider == "kimi":
        model = str(
            overrides.get("model") or os.environ.get("KIMI_MODEL") or "kimi-for-coding"
        )
        api_key = str(overrides.get("api_key") or kimi_key)
        base_url = _resolve_kimi_base_url(
            str(
                overrides.get("base_url")
                or os.environ.get("KIMI_BASE_URL")
                or _KIMI_DEFAULT_BASE_URL
            )
        )
    elif provider == "evolink":
        model = str(
            overrides.get("model") or os.environ.get("EVOLINK_MODEL") or "gpt-5.2"
        )
        api_key = str(overrides.get("api_key") or evolink_key)
        base_url = str(
            overrides.get("base_url")
            or os.environ.get("EVOLINK_BASE_URL")
            or _EVOLINK_DEFAULT_BASE_URL
        )
    elif provider == "anthropic":
        model = str(
            overrides.get("model")
            or os.environ.get("ANTHROPIC_MODEL")
            or "claude-sonnet-4-6"
        )
        api_key = str(overrides.get("api_key") or anthropic_key)
        base_url = str(
            overrides.get("base_url") or os.environ.get("ANTHROPIC_BASE_URL") or ""
        )
    elif provider == "openai":
        model = str(
            overrides.get("model")
            or os.environ.get("PAPERINDEX_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("CHATGPT_MODEL")
            or ""
        )
        api_key = str(overrides.get("api_key") or openai_key)
        base_url = str(
            overrides.get("base_url")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("CHATGPT_BASE_URL")
            or ""
        )
    else:
        # Check if this is a LiteLLM-backed provider first.
        _litellm_meta = None
        try:
            from .litellm_backend import (
                get_litellm_provider_meta,
                resolve_provider_api_key,
            )

            _litellm_meta = get_litellm_provider_meta(provider)
        except ImportError:
            pass

        if _litellm_meta is not None:
            upper = provider.upper()
            model = str(
                overrides.get("model")
                or os.environ.get(f"{upper}_MODEL")
                or _litellm_meta.tier_suggestions.get("medium", "")
            )
            api_key = str(
                overrides.get("api_key") or resolve_provider_api_key(_litellm_meta)
            )
            base_url = str(overrides.get("base_url") or _litellm_meta.base_url)
        else:
            # Custom plugin provider: convention is {PROVIDER}_MODEL / {PROVIDER}_API_KEY /
            # {PROVIDER}_BASE_URL env vars. Plugin authors are free to ignore these.
            upper = provider.upper()
            model = str(
                overrides.get("model") or os.environ.get(f"{upper}_MODEL") or ""
            )
            api_key = str(
                overrides.get("api_key") or os.environ.get(f"{upper}_API_KEY") or ""
            )
            base_url = str(
                overrides.get("base_url") or os.environ.get(f"{upper}_BASE_URL") or ""
            )

    return ResolvedLLMConfig(
        provider=provider, model=model, api_key=api_key, base_url=base_url
    )


def llm_route_transport(config: ResolvedLLMConfig) -> str:
    """Describe how a resolved provider is reached."""
    if config.provider in _CLI_PROVIDERS:
        return "host-cli"
    if config.provider == "openai" and config.base_url:
        return "openai-compatible"
    if config.provider == "anthropic" and config.base_url:
        return "anthropic-compatible"
    return "direct-api"


def llm_route_can_attempt(config: ResolvedLLMConfig) -> bool:
    """Return whether the current config is sufficient for a live probe."""
    if config.provider in _CLI_PROVIDERS:
        return True
    return bool(config.api_key and config.model)


# ---------------------------------------------------------------------------
# LLMClient — unified interface
# ---------------------------------------------------------------------------


class LLMClient:
    """Unified LLM client with provider registry and task-tier routing.

    Usage:
        # Default provider from config
        client = LLMClient()
        client.chat("summarize this")

        # Tier-based routing (ignores default provider)
        client.chat("extract claims", tier="medium")

        # Explicit provider + model
        client.chat("review this", provider="codex", model="gpt-5.4-high")
    """

    def __init__(self, config: ResolvedLLMConfig | None = None, **kwargs: Any) -> None:
        self._config = config or resolve_llm_config(kwargs if kwargs else None)

    @property
    def provider(self) -> str:
        return self._config.provider

    @property
    def model(self) -> str:
        return self._config.model

    def chat(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        *,
        tier: TaskTier | None = None,
        provider: str | None = None,
    ) -> str:
        """Send a prompt and get a response.

        Args:
            prompt: The input text.
            model: Override model (optional).
            temperature: Sampling temperature (ignored by CLI providers).
            tier: Task tier for automatic routing (light/medium/heavy).
                  When set, overrides the default provider/model.
            provider: Explicit provider name override.
        """
        _clear_usage()
        # Tier-based routing takes priority
        if tier and not (provider or model):
            prov_name, route_model = resolve_route(tier)
            logger.debug("tier=%s → provider=%s model=%s", tier, prov_name, route_model)
            fn = get_provider(prov_name)
            return fn(
                prompt,
                route_model,
                api_key=self._config.api_key,
                base_url=self._config.base_url,
                temperature=temperature,
            )

        # Explicit provider override
        prov_name = provider or self._config.provider
        use_model = model or self._config.model
        if not use_model:
            raise ValueError("No model specified in config or call")

        fn = get_provider(prov_name)
        return fn(
            prompt,
            use_model,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            temperature=temperature,
        )

    def chat_with_usage(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        *,
        tier: TaskTier | None = None,
        provider: str | None = None,
    ) -> tuple[str, LLMUsage | None]:
        """Send a prompt and return (text, usage). ``usage`` may be None for
        providers that cannot observe token counts (e.g. cursor_agent)."""
        text = self.chat(
            prompt, model=model, temperature=temperature, tier=tier, provider=provider
        )
        return text, get_last_usage()

    def preflight_accounted(
        self,
        model: str | None = None,
        *,
        tier: TaskTier | None = None,
        provider: str | None = None,
    ) -> ResolvedLLMConfig:
        """Resolve and validate one side-effect-free accounted call binding."""
        try:
            if tier and not (provider or model):
                provider_name, selected_model = resolve_route(tier)
            else:
                provider_name = provider or self._config.provider
                selected_model = model or self._config.model
        except Exception as exc:
            raise AccountedProviderNotStarted(
                f"accounted route rejected before transport: {exc}"
            ) from exc
        if not provider_name or not provider_name.strip():
            raise AccountedProviderNotStarted("No provider specified in config or call")
        if not selected_model or not selected_model.strip():
            raise AccountedProviderNotStarted("No model specified in config or call")
        accounted = _ACCOUNTED_PROVIDER_REGISTRY.get(provider_name)
        if accounted is None:
            raise AccountedProviderUnsupported(
                f"Provider '{provider_name}' does not support hard-cap accounted calls"
            )
        if provider_name == self._config.provider:
            resolved = self._config
        else:
            try:
                resolved = resolve_llm_config(
                    {"provider": provider_name, "model": selected_model}
                )
            except Exception as exc:
                raise AccountedProviderNotStarted(
                    f"accounted provider config rejected before transport: {exc}"
                ) from exc
        if not resolved.api_key:
            raise AccountedProviderNotStarted(
                f"Provider '{provider_name}' requires an accounted credential"
            )
        return ResolvedLLMConfig(
            provider=provider_name,
            model=selected_model,
            api_key=resolved.api_key,
            base_url=resolved.base_url,
        )

    def chat_accounted(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        *,
        authorization: BudgetAuthorization,
        tier: TaskTier | None = None,
        provider: str | None = None,
    ) -> tuple[str, ProviderUsageReceipt]:
        """Make one provider call only when it supports the typed budget contract.

        Once the adapter is invoked, its outcome is never represented as the
        preflight-only ``AccountedProviderNotStarted`` signal.
        """
        if not isinstance(authorization, BudgetAuthorization):
            raise TypeError("authorization must be a BudgetAuthorization")
        call_config = self.preflight_accounted(
            model=model,
            tier=tier,
            provider=provider,
        )
        provider_name, selected_model = call_config.provider, call_config.model
        accounted = _ACCOUNTED_PROVIDER_REGISTRY[provider_name]
        try:
            result = accounted(
                prompt,
                selected_model,
                authorization=authorization,
                api_key=call_config.api_key,
                base_url=call_config.base_url,
                temperature=temperature,
            )
        except AccountedProviderNotStarted as exc:
            raise RuntimeError(
                "accounted provider outcome is unknown after adapter invocation"
            ) from exc
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], str)
            or not isinstance(result[1], ProviderUsageReceipt)
        ):
            raise TypeError(
                "accounted provider must return (text, ProviderUsageReceipt)"
            )
        text, receipt = result
        if (
            receipt.attempt_id != authorization.attempt_id
            or receipt.request_sha256 != authorization.request_sha256
            or receipt.provider != provider_name
            or receipt.model != selected_model
            or receipt.output_sha256 != hashlib.sha256(text.encode()).hexdigest()
        ):
            raise ValueError(
                "accounted provider receipt differs from the authorized call"
            )
        return text, receipt

    def get_last_usage(self) -> LLMUsage | None:
        """Return token usage recorded by the most recent call on this thread."""
        return get_last_usage()


# Backwards compatibility alias
OpenAICompatibleClient = LLMClient


# ---------------------------------------------------------------------------
# Utility helpers (kept for backward compat, used by paperindex internals)
# ---------------------------------------------------------------------------


def _post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 60.0
) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise
            last_error = exc
        except (error.URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == 2:
                raise
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


def _extract_kimi_text(response_payload: Any) -> str:
    if not isinstance(response_payload, dict):
        return ""
    content = response_payload.get("content")
    if isinstance(content, list):
        parts = [
            str(b.get("text", "")).strip()
            for b in content
            if isinstance(b, dict) and b.get("text")
        ]
        if parts:
            return "\n".join(parts)
    if isinstance(content, str):
        return content
    messages = response_payload.get("messages")
    if isinstance(messages, list):
        parts = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mc = msg.get("content")
            if isinstance(mc, str) and mc.strip():
                parts.append(mc.strip())
            elif isinstance(mc, list):
                parts.extend(
                    str(b.get("text", "")).strip()
                    for b in mc
                    if isinstance(b, dict) and b.get("text")
                )
        if parts:
            return "\n".join(p for p in parts if p)
    return json.dumps(response_payload, ensure_ascii=False)
