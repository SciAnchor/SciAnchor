"""Image generation client for academic figure generation.

The default provider uses OpenAI GPT Image. fal.ai remains available for legacy
``recraft`` and ``flux`` model names.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENAI_IMAGE_MODEL = "gpt-image-2"
RECRAFT_MODEL = "fal-ai/recraft/v3/text-to-image"
FLUX_MODEL = "fal-ai/flux-pro/v1.1"
NANO_BANANA_FAST_MODEL = "fal-ai/nano-banana-2"
NANO_BANANA_PRO_MODEL = "fal-ai/nano-banana-pro"
SESSION_IMAGEGEN_MODEL = "codex_session_imagegen"
ILLUSTRATION_MODEL = "illustration"

OPENAI_IMAGE_MODEL_ALIASES: dict[str, str] = {
    "codex": OPENAI_IMAGE_MODEL,
    "openai": OPENAI_IMAGE_MODEL,
    "gpt image2": OPENAI_IMAGE_MODEL,
    "gpt-image2": OPENAI_IMAGE_MODEL,
    "gpt_image2": OPENAI_IMAGE_MODEL,
    "gpt image 2": OPENAI_IMAGE_MODEL,
    "gpt-image-2": OPENAI_IMAGE_MODEL,
    "gpt_image_2": OPENAI_IMAGE_MODEL,
}

FAL_MODEL_NAMES = {"recraft", "flux"}
FAL_IMAGE_MODEL_ALIASES: dict[str, str] = {
    "recraft": RECRAFT_MODEL,
    "flux": FLUX_MODEL,
    "nano-banana": NANO_BANANA_FAST_MODEL,
    "nano_banana": NANO_BANANA_FAST_MODEL,
    "nano-banana-2": NANO_BANANA_FAST_MODEL,
    "nano_banana_2": NANO_BANANA_FAST_MODEL,
    "gemini-nano-banana": NANO_BANANA_FAST_MODEL,
    "gemini_nano_banana": NANO_BANANA_FAST_MODEL,
    "nano-banana-pro": NANO_BANANA_PRO_MODEL,
    "nano_banana_pro": NANO_BANANA_PRO_MODEL,
}
SESSION_IMAGEGEN_MODEL_ALIASES = {
    "codex-session",
    "codex_session",
    "codex-session-imagegen",
    "codex_session_imagegen",
    "session-imagegen",
    "session_imagegen",
}
ILLUSTRATION_MODEL_ALIASES = {
    "illustration",
    "figure-illustration",
    "figure_illustration",
}
ILLUSTRATION_FAKE_MODEL_ALIASES = {
    "illustration-fake",
    "illustration_fake",
}
OPENAI_IMAGE_SIZES: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "wide": (1536, 1024),
    "tall": (1024, 1536),
}

RECRAFT_STYLES: dict[str, str] = {
    "pipeline": "vector_illustration/infographical",
    "flowchart": "vector_illustration/infographical",
    "architecture": "digital_illustration",
    "system": "digital_illustration",
    "comparison": "digital_illustration",
    "default": "digital_illustration",
}

DIMENSION_PRESETS: dict[str, dict[str, int]] = {
    "wide": {"width": 1920, "height": 960},
    "square": {"width": 1024, "height": 1024},
    "tall": {"width": 960, "height": 1920},
    "standard": {"width": 1440, "height": 960},
}


@dataclass(frozen=True)
class GenerationResult:
    success: bool
    image_url: str = ""
    local_path: str = ""
    error: str = ""
    model_id: str = ""
    width: int = 0
    height: int = 0
    provenance: dict[str, Any] | None = None


def _get_fal_key() -> str:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        raise EnvironmentError(
            "FAL_KEY environment variable not set. "
            "Get your key at https://fal.ai/dashboard/keys"
        )
    return key


def _get_openai_key() -> str:
    # An OpenAI-compatible image gateway may serve gpt-image under its own key
    # and base URL separately from OPENAI_API_KEY.
    key = os.environ.get("GPT_IMAGE_API_KEY", "") or os.environ.get(
        "OPENAI_API_KEY", ""
    )
    if not key:
        raise EnvironmentError(
            "Neither GPT_IMAGE_API_KEY nor OPENAI_API_KEY is set. "
            "Set one before generating OpenAI GPT Image figures."
        )
    return key


def _normalize_image_model(model: str) -> str:
    raw = (model or "").strip()
    if not raw:
        return OPENAI_IMAGE_MODEL
    return OPENAI_IMAGE_MODEL_ALIASES.get(raw.lower(), raw)


def _is_fal_model(model: str) -> bool:
    raw = model.strip().lower()
    return raw in FAL_MODEL_NAMES or raw in FAL_IMAGE_MODEL_ALIASES


def _is_session_imagegen_model(model: str) -> bool:
    return model.strip().lower() in SESSION_IMAGEGEN_MODEL_ALIASES


def _is_illustration_model(model: str) -> bool:
    raw = model.strip().lower()
    return raw in ILLUSTRATION_MODEL_ALIASES or raw in ILLUSTRATION_FAKE_MODEL_ALIASES


def _is_fake_illustration_model(model: str) -> bool:
    return model.strip().lower() in ILLUSTRATION_FAKE_MODEL_ALIASES


def _dimensions_to_openai_size(dimensions: dict[str, int]) -> str:
    width = int(dimensions.get("width") or DIMENSION_PRESETS["standard"]["width"])
    height = int(dimensions.get("height") or DIMENSION_PRESETS["standard"]["height"])
    aspect_ratio = width / max(height, 1)
    if aspect_ratio > 1.15:
        target = OPENAI_IMAGE_SIZES["wide"]
    elif aspect_ratio < 0.85:
        target = OPENAI_IMAGE_SIZES["tall"]
    else:
        target = OPENAI_IMAGE_SIZES["square"]
    return f"{target[0]}x{target[1]}"


def _size_to_dimensions(size: str) -> tuple[int, int]:
    width, height = size.split("x", 1)
    return int(width), int(height)


def classify_figure_style(purpose: str, suggested_layout: str, title: str) -> str:
    combined = f"{purpose} {suggested_layout} {title}".lower()
    if any(w in combined for w in ("pipeline", "flow", "process", "step", "sequence")):
        return RECRAFT_STYLES["pipeline"]
    if any(
        w in combined
        for w in ("architecture", "system", "framework", "overview", "module")
    ):
        return RECRAFT_STYLES["architecture"]
    if any(w in combined for w in ("comparison", "ablation", "matrix", "grid")):
        return RECRAFT_STYLES["comparison"]
    return RECRAFT_STYLES["default"]


def choose_dimensions(suggested_layout: str, purpose: str) -> dict[str, int]:
    combined = f"{suggested_layout} {purpose}".lower()
    if any(
        w in combined
        for w in ("wide", "horizontal", "architecture", "pipeline", "overview")
    ):
        return DIMENSION_PRESETS["wide"]
    if any(w in combined for w in ("vertical", "tall", "stack")):
        return DIMENSION_PRESETS["tall"]
    if any(w in combined for w in ("square", "matrix", "grid")):
        return DIMENSION_PRESETS["square"]
    return DIMENSION_PRESETS["standard"]


def figure_id_to_filename(figure_id: str) -> str:
    name = re.sub(r"^fig:", "", figure_id).strip()
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    if not name:
        name = "figure"
    return f"{name}.png"


def build_image_prompt(
    *,
    title: str,
    purpose: str,
    caption: str = "",
    data_source: str = "",
    suggested_layout: str = "",
    section: str = "",
    figure_contract: dict[str, Any] | None = None,
) -> str:
    combined = f"{purpose} {suggested_layout} {title}".lower()
    if "pipeline" in combined or "flow" in combined:
        figure_type = "academic pipeline flowchart"
    elif "comparison" in combined or "ablation" in combined:
        figure_type = "academic comparison diagram"
    elif "overview" in combined or "system" in combined:
        figure_type = "system architecture overview diagram"
    else:
        figure_type = "academic architecture diagram"

    parts = [
        f"A clean, professional {figure_type} for an academic research paper.",
    ]
    if title:
        parts.append(f"Title: {title}.")
    if purpose:
        parts.append(f"The diagram shows: {purpose}.")
    if suggested_layout:
        parts.append(f"Layout: {suggested_layout}.")
    contract_prompt = _figure_contract_prompt(figure_contract)
    if contract_prompt:
        parts.append(contract_prompt)
    parts.append(
        "Style: publication-ready vector-like academic diagram with crisp "
        "labeled components, connecting arrows, white background, and clear "
        "hierarchy. Avoid tiny text, screenshots, blurry raster effects, "
        "decorative clip art, and photorealism. Use short 2-4 word labels, "
        "consistent line weights, generous spacing, and a restrained palette "
        "with blues, grays, and one accent color."
    )
    return " ".join(parts)


def _figure_contract_prompt(figure_contract: dict[str, Any] | None) -> str:
    if not isinstance(figure_contract, dict):
        return ""
    parts: list[str] = []
    allowed = _clean_contract_list(figure_contract.get("allowed_labels"))
    if allowed:
        parts.append(
            "Use only these exact in-image labels: " + "; ".join(allowed) + "."
        )
    forbidden = _clean_contract_list(figure_contract.get("forbidden_labels"))
    if forbidden:
        parts.append("Do not use these labels or claims: " + "; ".join(forbidden) + ".")
    evidence_boundary = str(figure_contract.get("evidence_boundary") or "").strip()
    if evidence_boundary:
        parts.append(f"Evidence boundary: {evidence_boundary}.")
    style_ref = _style_reference_prompt(figure_contract.get("style_reference"))
    if style_ref:
        parts.append(style_ref)
    return " ".join(parts)


def _style_reference_prompt(style_anchor: Any) -> str:
    """Render an exemplar-derived VISUAL STYLE ANCHOR into prompt guidance.

    Transfers visual FORM (layout/palette/geometry) chosen by analogy to
    well-composed published architecture figures — never their method content.
    """
    if not isinstance(style_anchor, dict):
        return ""
    fields = [
        ("layout_archetype", "layout"),
        ("palette_strategy", "palette"),
        ("geometry_language", "geometry"),
        ("depth_model", "depth"),
        ("composition", "composition"),
        ("typography_mood", "typography"),
    ]
    picked = [
        f"{label} = {str(style_anchor[key]).strip()}"
        for key, label in fields
        if str(style_anchor.get(key) or "").strip()
    ]
    if not picked:
        return ""
    return (
        "Visual style (transferred from well-composed published figures, form only, "
        "not their content): " + "; ".join(picked) + "."
    )


def _clean_contract_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def generate_image(
    *,
    prompt: str,
    model: str = OPENAI_IMAGE_MODEL,
    style: str = "digital_illustration",
    dimensions: dict[str, int] | None = None,
    output_dir: str,
    filename: str,
    figure_id: str = "",
    figure_contract: dict[str, Any] | None = None,
    evidence_boundary: str = "conceptual",
    quality: str = "high",
    timeout: float = 60.0,
    reference_images: tuple[bytes, ...] = (),
) -> GenerationResult:
    dims = dimensions or DIMENSION_PRESETS["standard"]
    if _is_session_imagegen_model(model):
        return GenerationResult(
            success=False,
            error=(
                "Codex session ImageGen is a session-only agent capability, not "
                "a programmatic figure_generate provider. Use the figure-quality "
                "skill interactively and record the generated asset provenance, "
                "or choose an explicit API provider such as gpt-image-2."
            ),
            model_id=SESSION_IMAGEGEN_MODEL,
        )
    if _is_illustration_model(model):
        return _generate_illustration_image(
            prompt=prompt,
            model=model,
            dimensions=dims,
            output_dir=output_dir,
            filename=filename,
            figure_id=figure_id,
            figure_contract=figure_contract,
            evidence_boundary=evidence_boundary,
            timeout=timeout,
            reference_images=reference_images,
        )
    if _is_fal_model(model):
        return _generate_fal_image(
            prompt=prompt,
            model=model,
            style=style,
            dimensions=dims,
            output_dir=output_dir,
            filename=filename,
            timeout=timeout,
        )

    return _generate_openai_image(
        prompt=prompt,
        model=model,
        dimensions=dims,
        output_dir=output_dir,
        filename=filename,
        quality=quality,
    )


def _generate_illustration_image(
    *,
    prompt: str,
    model: str,
    dimensions: dict[str, int],
    output_dir: str,
    filename: str,
    figure_id: str,
    figure_contract: dict[str, Any] | None,
    evidence_boundary: str,
    timeout: float,
    reference_images: tuple[bytes, ...] = (),
) -> GenerationResult:
    from research_harness.integrations.figure_image_provider import (
        DEFAULT_MODEL,
        GOOGLE_API_KEY_ENV,
        GPT_IMAGE_API_KEY_ENV,
        GROK_API_KEY_ENV,
        FakeFigureImageProvider,
        FigureImageConfigurationError,
        FigureImageRequest,
        GeminiImageProvider,
        GeminiImageProviderConfig,
        GptImageProvider,
        GptImageProviderConfig,
        GrokImageProvider,
        GrokImageProviderConfig,
    )

    frozen = (figure_contract or {}).get("generation")
    providers = {
        "grok": (GrokImageProvider, GrokImageProviderConfig),
        "gpt_image": (GptImageProvider, GptImageProviderConfig),
        "gemini": (GeminiImageProvider, GeminiImageProviderConfig),
    }
    if frozen is not None:
        if (
            not isinstance(frozen, dict)
            or set(frozen)
            != {
                "provider",
                "model",
                "candidate_count",
                "max_refinement_rounds",
                "dimensions",
            }
            or frozen.get("provider") not in providers
            or not isinstance(frozen.get("model"), str)
            or not frozen["model"].strip()
            or type(frozen.get("candidate_count")) is not int
            or frozen["candidate_count"] != 1
            or type(frozen.get("max_refinement_rounds")) is not int
            or frozen["max_refinement_rounds"] != 0
            or _is_fake_illustration_model(model)
        ):
            raise FigureImageConfigurationError(
                "invalid frozen single-candidate generation contract"
            )
        dimensions = frozen["dimensions"]
        if (
            not isinstance(dimensions, dict)
            or set(dimensions) != {"width", "height"}
            or any(
                type(v) is not int or not 1 <= v <= 8192 for v in dimensions.values()
            )
        ):
            raise FigureImageConfigurationError("invalid frozen generation dimensions")
    request = FigureImageRequest(
        prompt=prompt,
        figure_id=figure_id,
        figure_contract=figure_contract or {},
        evidence_boundary=evidence_boundary,
        dimensions=dimensions,
        reference_images=tuple(reference_images or ()),
        model=frozen["model"] if frozen is not None else DEFAULT_MODEL,
        max_refinement_rounds=0 if frozen is not None else 1,
    )
    if frozen is not None:
        provider, config = providers[frozen["provider"]]
        result = provider(replace(config.from_env(), model=frozen["model"])).generate(
            request
        )
    elif _is_fake_illustration_model(model):
        result = FakeFigureImageProvider().generate(request)
    else:
        attempts: list[Any] = []
        if os.environ.get(GROK_API_KEY_ENV, "").strip():
            attempts.append(
                lambda: GrokImageProvider(GrokImageProviderConfig.from_env()).generate(
                    request
                )
            )
        if os.environ.get(GPT_IMAGE_API_KEY_ENV, "").strip():
            attempts.append(
                lambda: GptImageProvider(GptImageProviderConfig.from_env()).generate(
                    request
                )
            )
        if os.environ.get(GOOGLE_API_KEY_ENV, "").strip():
            attempts.append(
                lambda: GeminiImageProvider(
                    GeminiImageProviderConfig.from_env()
                ).generate(request)
            )
        if not attempts:
            raise FigureImageConfigurationError(
                "Missing illustration provider configuration. Configure "
                f"{GROK_API_KEY_ENV} for Grok Imagine, "
                f"{GPT_IMAGE_API_KEY_ENV} for GPT Image, or "
                f"{GOOGLE_API_KEY_ENV} for Gemini native."
            )
        result = attempts[0]()
        for attempt in attempts[1:]:
            if result.success:
                break
            result = attempt()

    if not result.success:
        return GenerationResult(
            success=False,
            error=result.error,
            image_url=result.image_url,
            model_id=result.model,
            width=int(dimensions.get("width") or 0),
            height=int(dimensions.get("height") or 0),
            provenance=dict(result.provenance),
        )

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    local_path = out_path / filename
    if result.image_bytes:
        content = result.image_bytes
    elif result.image_url:
        try:
            with httpx.Client(timeout=timeout) as client_http:
                response = client_http.get(result.image_url)
                response.raise_for_status()
                content = response.content
        except httpx.HTTPError as exc:
            return GenerationResult(
                success=False,
                error=(
                    f"Illustration image_url download failed: {exc.__class__.__name__}."
                ),
                image_url=result.image_url,
                model_id=result.model,
                provenance=dict(result.provenance),
            )
    else:
        return GenerationResult(
            success=False,
            error="Illustration result did not include image bytes or image_url.",
            model_id=result.model,
            provenance=dict(result.provenance),
        )
    local_path.write_bytes(content)

    provenance = dict(result.provenance)
    asset_record = dict(provenance.get("asset_record") or {})
    provenance["asset_record"] = {
        **asset_record,
        "byte_count": len(content),
        "local_path": str(local_path),
        "recorded": True,
    }

    return GenerationResult(
        success=True,
        image_url=result.image_url,
        local_path=str(local_path),
        model_id=result.model,
        width=int(dimensions.get("width") or 0),
        height=int(dimensions.get("height") or 0),
        provenance=provenance,
    )


def _generate_openai_image(
    *,
    prompt: str,
    model: str,
    dimensions: dict[str, int],
    output_dir: str,
    filename: str,
    quality: str,
) -> GenerationResult:
    model_id = _normalize_image_model(model)
    _get_openai_key()

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=_get_openai_key(),
            base_url=os.environ.get("GPT_IMAGE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or None,
        )
        image_size = _dimensions_to_openai_size(dimensions)
        response = client.images.generate(
            model=model_id,
            prompt=prompt,
            size=image_size,
            quality=quality,
            output_format="png",
            response_format="b64_json",
            n=1,
        )

        image = response.data[0]
        image_b64 = getattr(image, "b64_json", "") or ""
        image_url = getattr(image, "url", "") or ""

        if image_b64:
            content = base64.b64decode(image_b64)
        elif image_url:
            with httpx.Client(timeout=30.0) as client_http:
                resp = client_http.get(image_url)
                resp.raise_for_status()
                content = resp.content
        else:
            return GenerationResult(
                success=False,
                error="OpenAI image response did not contain b64_json or url.",
                model_id=model_id,
            )

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        local_path = out_path / filename
        local_path.write_bytes(content)

        width, height = _size_to_dimensions(image_size)
        return GenerationResult(
            success=True,
            image_url=image_url,
            local_path=str(local_path),
            model_id=model_id,
            width=width,
            height=height,
        )
    except Exception as exc:
        return GenerationResult(
            success=False,
            error=f"OpenAI image generation failed: {exc}",
            model_id=model_id,
        )


def _generate_fal_image(
    *,
    prompt: str,
    model: str,
    style: str,
    dimensions: dict[str, int],
    output_dir: str,
    filename: str,
    timeout: float,
) -> GenerationResult:
    dims = dimensions
    fal_key = _get_fal_key()
    normalized_model = FAL_IMAGE_MODEL_ALIASES.get(model.strip().lower(), model)

    if normalized_model == FLUX_MODEL:
        model_id = normalized_model
        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_size": dims,
            "output_format": "png",
            "num_images": 1,
            "enhance_prompt": False,
        }
    elif normalized_model in {NANO_BANANA_FAST_MODEL, NANO_BANANA_PRO_MODEL}:
        model_id = normalized_model
        payload = {
            "prompt": prompt,
            "image_size": _dimensions_to_fal_named_size(dims),
            "num_images": 1,
        }
    else:
        model_id = normalized_model if normalized_model != model else RECRAFT_MODEL
        payload = {"prompt": prompt, "style": style, "image_size": dims}

    try:
        import fal_client

        result = fal_client.subscribe(model_id, arguments=payload)
        image_url: str = result["images"][0]["url"]
    except ImportError:
        logger.info("fal_client not installed, using httpx fallback")
        image_url = _fal_http_generate(model_id, payload, fal_key, timeout)
    except Exception as exc:
        return GenerationResult(
            success=False, error=f"fal.ai generation failed: {exc}", model_id=model_id
        )

    try:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        local_path = out_path / filename

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(image_url)
            resp.raise_for_status()
            local_path.write_bytes(resp.content)

        return GenerationResult(
            success=True,
            image_url=image_url,
            local_path=str(local_path),
            model_id=model_id,
            width=dims["width"],
            height=dims["height"],
        )
    except Exception as exc:
        return GenerationResult(
            success=False,
            error=f"Image download failed: {exc}",
            image_url=image_url,
            model_id=model_id,
        )


def _dimensions_to_fal_named_size(dimensions: dict[str, int]) -> str:
    width = int(dimensions.get("width") or DIMENSION_PRESETS["standard"]["width"])
    height = int(dimensions.get("height") or DIMENSION_PRESETS["standard"]["height"])
    aspect_ratio = width / max(height, 1)
    if aspect_ratio > 1.55:
        return "landscape_16_9"
    if aspect_ratio > 1.15:
        return "landscape_4_3"
    if aspect_ratio < 0.65:
        return "portrait_16_9"
    if aspect_ratio < 0.9:
        return "portrait_4_3"
    return "square"


def _fal_http_generate(
    model_id: str,
    payload: dict[str, Any],
    fal_key: str,
    timeout: float,
) -> str:

    headers = {"Authorization": f"Key {fal_key}", "Content-Type": "application/json"}
    base_url = f"https://queue.fal.run/{model_id}"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(base_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "images" in data:
            return data["images"][0]["url"]

        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError(f"No request_id in fal response: {data}")

        status_url = f"{base_url}/requests/{request_id}/status"
        result_url = f"{base_url}/requests/{request_id}"

        for _ in range(int(timeout)):
            time.sleep(1.0)
            status_resp = client.get(status_url, headers=headers)
            status_data = status_resp.json()
            if status_data.get("status") == "COMPLETED":
                result_resp = client.get(result_url, headers=headers)
                return result_resp.json()["images"][0]["url"]
            if status_data.get("status") in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"fal.ai job failed: {status_data}")

        raise TimeoutError(f"fal.ai job timed out after {timeout}s")
