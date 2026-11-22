"""Contract-driven illustration providers for academic figure generation.

The ``illustration`` route sends a figure contract (prompt, evidence boundary,
dimensions, optional reference images) to one of the public image backends:

- Grok Imagine via an OpenAI-compatible endpoint (``GROK_API_KEY``)
- GPT Image via an OpenAI-compatible endpoint (``GPT_IMAGE_API_KEY``)
- Google Gemini native image generation (``GOOGLE_API_KEY``)

A deterministic no-network fake provider is available for tests.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

import httpx


GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
FIGURE_IMAGE_TIMEOUT_SECONDS_ENV = "RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS"
FIGURE_GEMINI_MODEL_ENV = "RESEARCH_HARNESS_FIGURE_GEMINI_MODEL"
GROK_API_KEY_ENV = "GROK_API_KEY"
GROK_BASE_URL_ENV = "GROK_BASE_URL"
GROK_IMAGE_MODEL_ENV = "GROK_IMAGE_MODEL"
GPT_IMAGE_API_KEY_ENV = "GPT_IMAGE_API_KEY"
GPT_IMAGE_BASE_URL_ENV = "GPT_IMAGE_BASE_URL"
GPT_IMAGE_MODEL_ENV = "GPT_IMAGE_MODEL"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"

FIGURE_IMAGE_PROVIDER = "illustration"
FIGURE_IMAGE_ROUTE = "illustration"
FAKE_ROUTE = "illustration_fake"
GEMINI_ROUTE = "gemini_native"
GROK_ROUTE = "grok_imagine"
GPT_IMAGE_ROUTE = "gpt_image"

DEFAULT_GROK_IMAGE_MODEL = "grok-imagine-image-2.0"
DEFAULT_GPT_IMAGE_MODEL = "gpt-image-2.5"
DEFAULT_OPENAI_COMPAT_BASE_URL = "https://api.openai.com/v1"
SAFE_STYLE_GUIDE_IDS = frozenset({"none", "rh_house", "cs_topvenue", "neurips2025"})
SAFE_ANCHOR_MODES = frozenset({"auto", "none"})
DEFAULT_OPERATION = "generate_figure"
DEFAULT_MODEL = "illustration"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_OUTPUT_FORMAT = "png"
DEFAULT_TIMEOUT_SECONDS = 60.0
QUALITY_LOOP_STEPS = (
    "figure_contract",
    "reference_style_selection",
    "render",
    "critic_review",
    "bounded_refinement",
    "caption_and_provenance_record",
)
DEFAULT_MAX_REFINEMENT_ROUNDS = 1
DEFAULT_MAX_CRITIQUE_FINDINGS = 5


def _env_configured(*names: str) -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in names)


def figure_image_generation_ready() -> bool:
    """True when at least one real illustration backend is configured.

    Gate checks use this to decide whether an ILLUSTRATION_PENDING figure
    fallback is still an acceptable degraded state: once a real backend is
    ready, pending fallbacks must block instead of shipping silently.

    Service/MCP entrypoints do not pass through the CLI's env autoload, so
    the probe pulls in the same default env files itself; otherwise the
    answer would depend on which surface asked.
    """
    try:
        from ..env_bootstrap import ensure_default_env_loaded

        ensure_default_env_loaded()
    except Exception:  # noqa: BLE001 - readiness probe must never raise
        pass
    return _env_configured(GROK_API_KEY_ENV, GPT_IMAGE_API_KEY_ENV, GOOGLE_API_KEY_ENV)


ALLOWED_EVIDENCE_BOUNDARIES = {
    "conceptual",
    "planned_protocol",
    "evidence_backed",
    "mixed",
}


class FigureImageError(RuntimeError):
    """Base exception for illustration provider contract errors."""


class FigureImageConfigurationError(FigureImageError):
    """Raised when required illustration provider configuration is missing."""


class FigureImageRequestError(FigureImageError):
    """Raised when an illustration request violates the local contract."""


@dataclass(frozen=True)
class GeminiImageProviderConfig:
    api_key: str = field(repr=False)
    model: str = DEFAULT_GEMINI_IMAGE_MODEL
    route: str = GEMINI_ROUTE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "GeminiImageProviderConfig":
        api_key = os.environ.get(GOOGLE_API_KEY_ENV, "").strip()
        model = (
            os.environ.get(FIGURE_GEMINI_MODEL_ENV, "").strip()
            or DEFAULT_GEMINI_IMAGE_MODEL
        )
        timeout_seconds = _coerce_positive_float_env(
            FIGURE_IMAGE_TIMEOUT_SECONDS_ENV,
            default=DEFAULT_TIMEOUT_SECONDS,
        )
        if not api_key:
            raise FigureImageConfigurationError(
                f"Missing Gemini native environment variable: {GOOGLE_API_KEY_ENV}"
            )
        return cls(api_key=api_key, model=model, timeout_seconds=timeout_seconds)

    def safe_config(self) -> dict[str, Any]:
        return {
            "api_key_configured": bool(self.api_key),
            "provider_backend": "gemini_native",
            "route": self.route,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class GrokImageProviderConfig:
    api_key: str = field(repr=False)
    base_url: str = field(repr=False)
    model: str = DEFAULT_GROK_IMAGE_MODEL
    route: str = GROK_ROUTE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "GrokImageProviderConfig":
        api_key = os.environ.get(GROK_API_KEY_ENV, "").strip()
        base_url = (
            os.environ.get(GROK_BASE_URL_ENV, "").strip()
            or os.environ.get(OPENAI_BASE_URL_ENV, "").strip()
            or DEFAULT_OPENAI_COMPAT_BASE_URL
        )
        model = (
            os.environ.get(GROK_IMAGE_MODEL_ENV, "").strip() or DEFAULT_GROK_IMAGE_MODEL
        )
        timeout_seconds = _coerce_positive_float_env(
            FIGURE_IMAGE_TIMEOUT_SECONDS_ENV,
            default=DEFAULT_TIMEOUT_SECONDS,
        )
        if not api_key:
            raise FigureImageConfigurationError(
                f"Missing Grok environment variable: {GROK_API_KEY_ENV}"
            )
        return cls(
            api_key=api_key,
            base_url=_normalize_base_url(base_url),
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def safe_config(self) -> dict[str, Any]:
        return {
            "api_key_configured": bool(self.api_key),
            "base_url_configured": bool(self.base_url),
            "provider_backend": "grok_imagine",
            "route": self.route,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class GptImageProviderConfig:
    api_key: str = field(repr=False)
    base_url: str = field(repr=False)
    model: str = DEFAULT_GPT_IMAGE_MODEL
    route: str = GPT_IMAGE_ROUTE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "GptImageProviderConfig":
        api_key = os.environ.get(GPT_IMAGE_API_KEY_ENV, "").strip()
        base_url = (
            os.environ.get(GPT_IMAGE_BASE_URL_ENV, "").strip()
            or os.environ.get(OPENAI_BASE_URL_ENV, "").strip()
            or DEFAULT_OPENAI_COMPAT_BASE_URL
        )
        model = (
            os.environ.get(GPT_IMAGE_MODEL_ENV, "").strip() or DEFAULT_GPT_IMAGE_MODEL
        )
        timeout_seconds = _coerce_positive_float_env(
            FIGURE_IMAGE_TIMEOUT_SECONDS_ENV,
            default=DEFAULT_TIMEOUT_SECONDS,
        )
        if not api_key:
            raise FigureImageConfigurationError(
                f"Missing GPT Image environment variable: {GPT_IMAGE_API_KEY_ENV}"
            )
        return cls(
            api_key=api_key,
            base_url=_normalize_base_url(base_url),
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def safe_config(self) -> dict[str, Any]:
        return {
            "api_key_configured": bool(self.api_key),
            "base_url_configured": bool(self.base_url),
            "provider_backend": "gpt_image",
            "route": self.route,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class FigureImageRequest:
    prompt: str
    figure_id: str
    figure_contract: Mapping[str, Any]
    evidence_boundary: str
    dimensions: Mapping[str, int] = field(
        default_factory=lambda: {"width": 1536, "height": 1024}
    )
    max_refinement_rounds: int = DEFAULT_MAX_REFINEMENT_ROUNDS
    max_critique_findings: int = DEFAULT_MAX_CRITIQUE_FINDINGS
    output_format: str = DEFAULT_OUTPUT_FORMAT
    model: str = DEFAULT_MODEL
    operation: str = DEFAULT_OPERATION
    # Optional reference figures (PNG bytes) for multimodal image-conditioning.
    reference_images: tuple[bytes, ...] = ()

    def to_provider_payload(self) -> dict[str, Any]:
        self._validate()
        return {
            "prompt": self.prompt,
            "figure_id": self.figure_id,
            "figure_contract": dict(self.figure_contract),
            "evidence_boundary": self.evidence_boundary,
            "dimensions": {
                "width": int(self.dimensions.get("width") or 1536),
                "height": int(self.dimensions.get("height") or 1024),
            },
            "quality_loop": self.quality_loop_contract(),
            "output_format": self.output_format,
            "model": self.model,
            "operation": self.operation,
        }

    def quality_loop_contract(self) -> dict[str, Any]:
        self._validate()
        return {
            "steps": list(QUALITY_LOOP_STEPS),
            "max_refinement_rounds": int(self.max_refinement_rounds),
            "max_critique_findings": int(self.max_critique_findings),
            "requires_asset_record": True,
            "requires_provenance_record": True,
        }

    def sanitized_request_shape(self) -> dict[str, Any]:
        self._validate()
        dimensions = {
            "width": int(self.dimensions.get("width") or 1536),
            "height": int(self.dimensions.get("height") or 1024),
        }
        return {
            "provider": FIGURE_IMAGE_PROVIDER,
            "route": FIGURE_IMAGE_ROUTE,
            "model": self.model,
            "operation": self.operation,
            "output_format": self.output_format,
            "evidence_boundary": self.evidence_boundary,
            "dimensions": dimensions,
            "has_prompt": bool(self.prompt),
            "prompt_length": len(self.prompt),
            "figure_contract_keys": sorted(str(key) for key in self.figure_contract),
            "quality_loop_steps": list(QUALITY_LOOP_STEPS),
            "max_refinement_rounds": int(self.max_refinement_rounds),
            "max_critique_findings": int(self.max_critique_findings),
            "reference_image_count": len(self.reference_images),
        }

    def _validate(self) -> None:
        if not self.prompt.strip():
            raise FigureImageRequestError("Illustration prompt is required.")
        if not self.figure_id.strip():
            raise FigureImageRequestError("Illustration figure_id is required.")
        if not self.figure_contract:
            raise FigureImageRequestError("Illustration figure_contract is required.")
        if self.evidence_boundary not in ALLOWED_EVIDENCE_BOUNDARIES:
            raise FigureImageRequestError(
                f"Unsupported illustration evidence_boundary: {self.evidence_boundary}"
            )
        if self.max_refinement_rounds < 0 or self.max_refinement_rounds > 1:
            raise FigureImageRequestError(
                "Illustration max_refinement_rounds must be between 0 and 1."
            )
        if self.max_critique_findings < 0 or self.max_critique_findings > 5:
            raise FigureImageRequestError(
                "Illustration max_critique_findings must be between 0 and 5."
            )
        style_guide = self.figure_contract.get("style_guide")
        if style_guide is not None and (
            not isinstance(style_guide, str) or style_guide not in SAFE_STYLE_GUIDE_IDS
        ):
            raise FigureImageRequestError(
                "Illustration style_guide must be a registered style-guide ID."
            )
        anchor = self.figure_contract.get("anchor")
        if anchor is not None and (
            not isinstance(anchor, str) or anchor not in SAFE_ANCHOR_MODES
        ):
            raise FigureImageRequestError(
                "Illustration anchor must be one of the registered modes: auto or none."
            )


@dataclass(frozen=True)
class FigureImageResult:
    success: bool
    provider: str
    route: str
    model: str
    model_version: str
    image_bytes: bytes = b""
    image_url: str = ""
    error: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["image_bytes"] = (
            f"<{len(self.image_bytes)} bytes>" if self.image_bytes else ""
        )
        payload["provenance"] = dict(self.provenance)
        return payload


@dataclass(frozen=True)
class FakeFigureImageProvider:
    image_bytes: bytes = b"\x89PNG\r\n\x1a\nillustration-fake"
    model_version: str = "fake-illustration-v1"
    route: str = FAKE_ROUTE

    def generate(self, request: FigureImageRequest) -> FigureImageResult:
        request.to_provider_payload()
        request_shape = request.sanitized_request_shape()
        return FigureImageResult(
            success=True,
            provider=FIGURE_IMAGE_PROVIDER,
            route=self.route,
            model=request.model,
            model_version=self.model_version,
            image_bytes=self.image_bytes,
            provenance={
                "provider": FIGURE_IMAGE_PROVIDER,
                "route": self.route,
                "model": request.model,
                "model_version": self.model_version,
                "request_shape": request_shape,
                "evidence_boundary": request.evidence_boundary,
                "quality_loop": _quality_loop_provenance(
                    request=request,
                    status="fake_completed",
                    executed_refinement_rounds=0,
                    critique_findings_count=0,
                ),
                "asset_record": _asset_record(
                    request=request,
                    image_bytes=self.image_bytes,
                    image_url="",
                    recorded=False,
                ),
                "limitations": [
                    "fake_provider_no_network",
                    "quality_not_independently_evaluated",
                ],
            },
        )


@dataclass(frozen=True)
class GeminiImageProvider:
    """Native Google Gemini image adapter."""

    config: GeminiImageProviderConfig
    client: Any | None = field(default=None, repr=False, compare=False)

    def generate(self, request: FigureImageRequest) -> FigureImageResult:
        request.to_provider_payload()
        request_shape = {
            **request.sanitized_request_shape(),
            "route": self.config.route,
        }
        try:
            client = self.client or _build_gemini_client(self.config)
            generate_config = (
                _gemini_generate_content_config(request)
                if self.client is None
                else {
                    "response_modalities": ["IMAGE"],
                    "image_config": {
                        "aspect_ratio": _dimensions_to_gemini_aspect_ratio(
                            request.dimensions
                        )
                    },
                }
            )
            response = client.models.generate_content(
                model=self.config.model,
                contents=request.prompt,
                config=generate_config,
            )
        except ImportError:
            return _failure_result(
                request=request,
                request_shape=request_shape,
                error="Gemini native provider requires the google-genai package.",
                limitation="provider_dependency_missing",
                route=self.config.route,
                provider_config=self.config.safe_config(),
            )
        except Exception as exc:
            return _failure_result(
                request=request,
                request_shape=request_shape,
                error=(
                    f"Gemini native provider request failed: {exc.__class__.__name__}."
                ),
                limitation="provider_request_failed",
                route=self.config.route,
                provider_config=self.config.safe_config(),
            )

        return _gemini_response_to_result(
            response=response,
            request=request,
            request_shape=request_shape,
            config=self.config,
        )


@dataclass(frozen=True)
class GrokImageProvider:
    """Grok Imagine via an OpenAI-compatible image endpoint."""

    config: GrokImageProviderConfig
    client: httpx.Client | None = field(default=None, repr=False, compare=False)

    def generate(self, request: FigureImageRequest) -> FigureImageResult:
        request.to_provider_payload()
        request_shape = {
            **request.sanitized_request_shape(),
            "route": self.config.route,
        }
        payload = _grok_image_payload(request=request, config=self.config)
        return _compat_image_generate(
            request=request,
            request_shape=request_shape,
            config=self.config,
            payload=payload,
            client=self.client,
            label="Grok Imagine",
        )


@dataclass(frozen=True)
class GptImageProvider:
    """GPT Image via an OpenAI-compatible image endpoint."""

    config: GptImageProviderConfig
    client: httpx.Client | None = field(default=None, repr=False, compare=False)

    def generate(self, request: FigureImageRequest) -> FigureImageResult:
        request.to_provider_payload()
        request_shape = {
            **request.sanitized_request_shape(),
            "route": self.config.route,
        }
        payload = _gpt_image_payload(request=request, config=self.config)
        return _compat_image_generate(
            request=request,
            request_shape=request_shape,
            config=self.config,
            payload=payload,
            client=self.client,
            label="GPT Image",
        )


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _openai_compatible_base_url(base_url: str) -> str:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return ""
    return normalized if normalized.endswith("/v1") else f"{normalized}/v1"


def _compat_endpoint(base_url: str, path: str) -> str:
    return f"{_openai_compatible_base_url(base_url)}{path}"


def _dimensions_to_aspect_ratio(dimensions: Mapping[str, int]) -> str:
    width = int(dimensions.get("width") or 1536)
    height = int(dimensions.get("height") or 1024)
    ratio = width / max(height, 1)
    if ratio >= 1.45:
        return "16:9"
    return _dimensions_to_gemini_aspect_ratio(dimensions)


def _grok_image_payload(
    *,
    request: FigureImageRequest,
    config: GrokImageProviderConfig,
) -> dict[str, Any]:
    return {
        "model": config.model,
        "prompt": request.prompt,
        "n": 1,
        "response_format": "b64_json",
        "resolution": "2k",
        "aspect_ratio": _dimensions_to_aspect_ratio(request.dimensions),
    }


def _gpt_image_payload(
    *,
    request: FigureImageRequest,
    config: GptImageProviderConfig,
) -> dict[str, Any]:
    return {
        "model": config.model,
        "prompt": request.prompt,
        "n": 1,
        "response_format": "b64_json",
        "size": (
            f"{request.dimensions['width']}x{request.dimensions['height']}"
            if "generation" in request.figure_contract
            else _dimensions_to_openai_wxh(request.dimensions)
        ),
    }


def _dimensions_to_openai_wxh(dimensions: Mapping[str, int]) -> str:
    width = int(dimensions.get("width") or 1536)
    height = int(dimensions.get("height") or 1024)
    ratio = width / max(height, 1)
    if ratio > 1.15:
        return "1536x1024"
    if ratio < 0.85:
        return "1024x1536"
    return "1024x1024"


def _compat_image_generate(
    *,
    request: FigureImageRequest,
    request_shape: Mapping[str, Any],
    config: Any,
    payload: Mapping[str, Any],
    client: httpx.Client | None,
    label: str,
) -> FigureImageResult:
    def fail(error: str, limitation: str) -> FigureImageResult:
        return _failure_result(
            request=request,
            request_shape=request_shape,
            error=error,
            limitation=limitation,
            route=config.route,
            provider_config=config.safe_config(),
        )

    try:
        response = _compat_post(config=config, payload=payload, client=client)
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        return fail(f"{label} provider request timed out.", "provider_timeout")
    except httpx.HTTPStatusError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
        return fail(
            f"{label} provider returned HTTP {status_code}.", "provider_http_error"
        )
    except httpx.HTTPError as exc:
        return fail(
            f"{label} provider request failed: {exc.__class__.__name__}.",
            "provider_request_failed",
        )
    except ValueError:
        return fail(
            f"{label} provider returned a non-JSON response.",
            "provider_non_json_response",
        )
    if not isinstance(data, Mapping):
        return fail(
            f"{label} provider returned an unsupported response shape.",
            "provider_unsupported_response_shape",
        )

    image_b64, image_url, output_field = _extract_compat_image_fields(data)
    if not image_b64 and not image_url:
        return fail(
            f"{label} provider returned an unsupported response shape: "
            "expected data[0].b64_json or data[0].url.",
            "provider_missing_image_output",
        )
    image_bytes = b""
    if image_b64:
        try:
            image_bytes = base64.b64decode(str(image_b64), validate=True)
        except (binascii.Error, ValueError):
            return fail(
                f"{label} provider returned invalid base64 image data.",
                "provider_invalid_image_base64",
            )
    return _success_result(
        request=request,
        request_shape=request_shape,
        route=config.route,
        model_version=config.model,
        image_bytes=image_bytes,
        image_url=image_url,
        output_fields=[output_field],
        provider_config=config.safe_config(),
    )


def _compat_post(
    *,
    config: Any,
    payload: Mapping[str, Any],
    client: httpx.Client | None,
) -> httpx.Response:
    headers = _bearer_headers(config.api_key)
    endpoint = _compat_endpoint(config.base_url, "/images/generations")
    if client is not None:
        return client.post(endpoint, headers=headers, json=payload)
    with httpx.Client(timeout=config.timeout_seconds) as http_client:
        return http_client.post(endpoint, headers=headers, json=payload)


def _extract_compat_image_fields(data: Mapping[str, Any]) -> tuple[str, str, str]:
    items = data.get("data")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, Mapping):
            b64_json = str(first.get("b64_json") or "").strip()
            if b64_json:
                return _extract_b64_from_data_url(b64_json), "", "data[0].b64_json"
            url = str(first.get("url") or "").strip()
            if url.startswith("data:image"):
                return _extract_b64_from_data_url(url), "", "data[0].url"
            if url.startswith(("http://", "https://")):
                return "", url, "data[0].url"
    return "", "", ""


def _extract_b64_from_data_url(value: str) -> str:
    return value.split(",", 1)[1] if "," in value else value


def _success_result(
    *,
    request: FigureImageRequest,
    request_shape: Mapping[str, Any],
    route: str,
    model_version: str,
    image_bytes: bytes,
    image_url: str,
    output_fields: list[str],
    provider_config: Mapping[str, Any],
) -> FigureImageResult:
    return FigureImageResult(
        success=True,
        provider=FIGURE_IMAGE_PROVIDER,
        route=route,
        model=request.model,
        model_version=model_version,
        image_bytes=image_bytes,
        image_url=image_url,
        provenance={
            "provider": FIGURE_IMAGE_PROVIDER,
            "route": route,
            "model": request.model,
            "model_version": model_version,
            "request_shape": dict(request_shape),
            "evidence_boundary": request.evidence_boundary,
            "output_fields": output_fields,
            "provider_config": dict(provider_config),
            "quality_loop": _quality_loop_provenance(
                request=request,
                status="provider_completed",
                executed_refinement_rounds=0,
                critique_findings_count=0,
            ),
            "asset_record": _asset_record(
                request=request,
                image_bytes=image_bytes,
                image_url=image_url,
                recorded=False,
            ),
            "limitations": [
                "provider_output_not_human_reviewed",
                "quality_not_independently_evaluated",
            ],
        },
    )


def _failure_result(
    *,
    request: FigureImageRequest,
    request_shape: Mapping[str, Any],
    error: str,
    limitation: str,
    route: str = FIGURE_IMAGE_ROUTE,
    provider_config: Mapping[str, Any] | None = None,
) -> FigureImageResult:
    provenance: dict[str, Any] = {
        "provider": FIGURE_IMAGE_PROVIDER,
        "route": route,
        "model": request.model,
        "request_shape": dict(request_shape),
        "evidence_boundary": request.evidence_boundary,
        "quality_loop": _quality_loop_provenance(
            request=request,
            status="failed",
            executed_refinement_rounds=0,
            critique_findings_count=0,
        ),
        "asset_record": _asset_record(
            request=request,
            image_bytes=b"",
            image_url="",
            recorded=False,
        ),
        "limitations": [limitation],
    }
    if provider_config is not None:
        provenance["provider_config"] = dict(provider_config)
    return FigureImageResult(
        success=False,
        provider=FIGURE_IMAGE_PROVIDER,
        route=route,
        model=request.model,
        model_version="",
        error=error,
        provenance=provenance,
    )


def _build_gemini_client(config: GeminiImageProviderConfig) -> Any:
    from google import genai

    return genai.Client(api_key=config.api_key)


def _gemini_generate_content_config(request: FigureImageRequest) -> Any:
    aspect_ratio = _dimensions_to_gemini_aspect_ratio(request.dimensions)
    try:
        from google.genai import types
    except ImportError:
        return {
            "response_modalities": ["IMAGE"],
            "image_config": {"aspect_ratio": aspect_ratio},
        }
    return types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
    )


def _dimensions_to_gemini_aspect_ratio(dimensions: Mapping[str, int]) -> str:
    width = int(dimensions.get("width") or 1536)
    height = int(dimensions.get("height") or 1024)
    ratio = width / max(height, 1)
    candidates = {
        "1:1": 1.0,
        "3:4": 0.75,
        "4:3": 4 / 3,
        "9:16": 9 / 16,
        "16:9": 16 / 9,
    }
    return min(candidates, key=lambda key: abs(candidates[key] - ratio))


def _gemini_response_to_result(
    *,
    response: Any,
    request: FigureImageRequest,
    request_shape: Mapping[str, Any],
    config: GeminiImageProviderConfig,
) -> FigureImageResult:
    image_bytes = _extract_gemini_image_bytes(response)
    if image_bytes is None:
        return _failure_result(
            request=request,
            request_shape=request_shape,
            error="Gemini native provider returned no inline image data.",
            limitation="provider_missing_image_output",
            route=config.route,
            provider_config=config.safe_config(),
        )
    return _success_result(
        request=request,
        request_shape=request_shape,
        route=config.route,
        model_version=config.model,
        image_bytes=image_bytes,
        image_url="",
        output_fields=["inline_data"],
        provider_config=config.safe_config(),
    )


def _extract_gemini_image_bytes(response: Any) -> bytes | None:
    for part in _gemini_response_parts(response):
        image_bytes = _part_inline_data_bytes(part)
        if image_bytes:
            return image_bytes
        image_bytes = _part_as_image_bytes(part)
        if image_bytes:
            return image_bytes
    return None


def _gemini_response_parts(response: Any) -> list[Any]:
    parts = getattr(response, "parts", None)
    if isinstance(parts, list):
        return parts
    candidates = getattr(response, "candidates", None)
    collected: list[Any] = []
    if isinstance(candidates, list):
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            candidate_parts = getattr(content, "parts", None)
            if isinstance(candidate_parts, list):
                collected.extend(candidate_parts)
    return collected


def _part_inline_data_bytes(part: Any) -> bytes | None:
    inline_data = getattr(part, "inline_data", None)
    data = getattr(inline_data, "data", None)
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        try:
            return base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return None
    return None


def _part_as_image_bytes(part: Any) -> bytes | None:
    as_image = getattr(part, "as_image", None)
    if not callable(as_image):
        return None
    image = as_image()
    output = io.BytesIO()
    save = getattr(image, "save", None)
    if not callable(save):
        return None
    save(output, format="PNG")
    return output.getvalue()


def _quality_loop_provenance(
    *,
    request: FigureImageRequest,
    status: str,
    executed_refinement_rounds: int,
    critique_findings_count: int,
) -> dict[str, Any]:
    return {
        "steps": list(QUALITY_LOOP_STEPS),
        "max_refinement_rounds": int(request.max_refinement_rounds),
        "max_critique_findings": int(request.max_critique_findings),
        "executed_refinement_rounds": executed_refinement_rounds,
        "critique_findings_count": critique_findings_count,
        "status": status,
    }


def _asset_record(
    *,
    request: FigureImageRequest,
    image_bytes: bytes,
    image_url: str,
    recorded: bool,
) -> dict[str, Any]:
    dimensions = {
        "width": int(request.dimensions.get("width") or 1536),
        "height": int(request.dimensions.get("height") or 1024),
    }
    return {
        "figure_id": request.figure_id,
        "output_format": request.output_format,
        "dimensions": dimensions,
        "byte_count": len(image_bytes),
        "image_url_present": bool(image_url),
        "recorded": recorded,
    }


def _coerce_positive_float_env(name: str, *, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        coerced = float(value)
    except ValueError as exc:
        raise FigureImageConfigurationError(
            f"{name} must be a positive number."
        ) from exc
    if coerced <= 0:
        raise FigureImageConfigurationError(f"{name} must be a positive number.")
    return coerced
