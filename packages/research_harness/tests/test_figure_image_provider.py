from __future__ import annotations

import base64
import json
from dataclasses import replace

import httpx
import pytest

from research_harness.integrations import figure_image_provider as api
from research_harness.integrations.figure_image_provider import (
    FIGURE_GEMINI_MODEL_ENV,
    FIGURE_IMAGE_TIMEOUT_SECONDS_ENV,
    GEMINI_ROUTE,
    GOOGLE_API_KEY_ENV,
    GPT_IMAGE_API_KEY_ENV,
    GPT_IMAGE_ROUTE,
    GROK_API_KEY_ENV,
    FakeFigureImageProvider,
    FigureImageConfigurationError,
    FigureImageRequest,
    FigureImageRequestError,
    GeminiImageProvider,
    GeminiImageProviderConfig,
    GptImageProvider,
    GptImageProviderConfig,
)


def _test_auth_value() -> str:
    return "illustration" + "-test" + "-auth"


def _request() -> FigureImageRequest:
    return FigureImageRequest(
        prompt="Create a clean academic workflow diagram.",
        figure_id="fig:workflow",
        figure_contract={
            "claim": "The workflow separates planning, rendering, and review.",
            "panel_map": ["Plan", "Render", "Review"],
        },
        evidence_boundary="conceptual",
        dimensions={"width": 1536, "height": 1024},
        output_format="png",
        model="illustration-v1",
    )


def test_gemini_config_from_env_reads_google_key_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GOOGLE_API_KEY_ENV, "google-secret")
    monkeypatch.setenv(FIGURE_GEMINI_MODEL_ENV, "gemini-2.5-flash-image")
    monkeypatch.setenv(FIGURE_IMAGE_TIMEOUT_SECONDS_ENV, "123")

    config = GeminiImageProviderConfig.from_env()

    assert config.api_key == "google-secret"
    assert config.model == "gemini-2.5-flash-image"
    assert config.timeout_seconds == 123.0
    assert config.safe_config() == {
        "api_key_configured": True,
        "provider_backend": "gemini_native",
        "route": GEMINI_ROUTE,
        "model": "gemini-2.5-flash-image",
        "timeout_seconds": 123.0,
    }
    assert "google-secret" not in repr(config)
    assert "google-secret" not in repr(config.safe_config())


def test_gemini_config_from_env_fails_closed_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(GOOGLE_API_KEY_ENV, raising=False)

    with pytest.raises(FigureImageConfigurationError) as exc_info:
        GeminiImageProviderConfig.from_env()

    assert GOOGLE_API_KEY_ENV in str(exc_info.value)


def test_config_from_env_rejects_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GOOGLE_API_KEY_ENV, "google-secret")
    monkeypatch.setenv(FIGURE_IMAGE_TIMEOUT_SECONDS_ENV, "0")

    with pytest.raises(FigureImageConfigurationError):
        GeminiImageProviderConfig.from_env()


def test_generation_ready_tracks_public_backend_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "research_harness.env_bootstrap.ensure_default_env_loaded", lambda: None
    )
    for name in (GOOGLE_API_KEY_ENV, GROK_API_KEY_ENV, GPT_IMAGE_API_KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    assert api.figure_image_generation_ready() is False
    monkeypatch.setenv(GOOGLE_API_KEY_ENV, "google-secret")
    assert api.figure_image_generation_ready() is True


def test_gpt_image_provider_posts_compat_payload_and_decodes_b64() -> None:
    image_bytes = b"\x89PNG\r\n\x1a\ngpt-image"
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(image_bytes).decode()}]},
        )

    config = GptImageProviderConfig(
        api_key=_test_auth_value(),
        base_url="https://images.example.invalid",
        model="gpt-image-test",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GptImageProvider(config=config, client=client).generate(_request())

    assert result.success is True
    assert result.route == GPT_IMAGE_ROUTE
    assert result.image_bytes == image_bytes
    assert str(calls[0].url) == "https://images.example.invalid/v1/images/generations"
    body = json.loads(calls[0].content)
    assert body["model"] == "gpt-image-test"
    assert body["size"] == "1536x1024"
    assert _test_auth_value() not in repr(result.to_dict())


def test_gpt_image_provider_fails_closed_for_missing_data() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []}))
    config = GptImageProviderConfig(
        api_key=_test_auth_value(), base_url="https://images.example.invalid"
    )
    with httpx.Client(transport=transport) as client:
        result = GptImageProvider(config=config, client=client).generate(_request())

    assert result.success is False
    assert result.provenance["route"] == GPT_IMAGE_ROUTE
    assert result.provenance["limitations"] == ["provider_missing_image_output"]
    assert _test_auth_value() not in repr(result.to_dict())


def test_frozen_dimensions_reach_actual_provider_payload() -> None:
    frozen = {
        "provider": "gpt_image",
        "model": "explicit",
        "candidate_count": 1,
        "max_refinement_rounds": 0,
        "dimensions": {"width": 2400, "height": 1800},
    }
    request = replace(
        _request(),
        dimensions=frozen["dimensions"],
        figure_contract={"generation": frozen},
    )
    payload = api._gpt_image_payload(
        request=request,
        config=GptImageProviderConfig(
            api_key=_test_auth_value(),
            base_url="https://invalid.test",
            model="explicit",
        ),
    )
    assert payload["size"] == "2400x1800"
    assert payload["n"] == 1


def test_gemini_native_provider_generates_inline_image_without_secret_leak() -> None:
    image_bytes = b"\x89PNG\r\n\x1a\ngemini-native"
    calls: list[dict[str, object]] = []

    class _InlineData:
        data = image_bytes

    class _Part:
        inline_data = _InlineData()

    class _Response:
        parts = [_Part()]

    class _Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return _Response()

    class _Client:
        models = _Models()

    provider = GeminiImageProvider(
        config=GeminiImageProviderConfig(
            api_key="google-secret",
            model="gemini-2.5-flash-image",
        ),
        client=_Client(),
    )

    result = provider.generate(_request())

    assert result.success is True
    assert result.route == GEMINI_ROUTE
    assert result.model == "illustration-v1"
    assert result.model_version == "gemini-2.5-flash-image"
    assert result.image_bytes == image_bytes
    assert result.provenance["provider_config"]["provider_backend"] == "gemini_native"
    assert result.provenance["quality_loop"]["status"] == "provider_completed"
    assert result.provenance["asset_record"]["byte_count"] == len(image_bytes)
    assert calls[0]["model"] == "gemini-2.5-flash-image"
    assert calls[0]["contents"] == "Create a clean academic workflow diagram."
    assert "google-secret" not in repr(result.to_dict())
    assert "Create a clean academic workflow diagram." not in repr(
        result.provenance["request_shape"]
    )


def test_request_shape_excludes_prompt_text() -> None:
    request = _request()

    payload = request.to_provider_payload()
    shape = request.sanitized_request_shape()

    assert payload["prompt"] == "Create a clean academic workflow diagram."
    assert payload["dimensions"] == {"width": 1536, "height": 1024}
    assert shape["provider"] == "illustration"
    assert shape["prompt_length"] == 41
    assert shape["figure_contract_keys"] == ["claim", "panel_map"]
    assert shape["reference_image_count"] == 0
    assert "Create a clean academic workflow diagram." not in repr(shape)


def test_fake_provider_returns_deterministic_result_without_network() -> None:
    provider = FakeFigureImageProvider(image_bytes=b"\x89PNG\r\n\x1a\nfake-image")

    result = provider.generate(_request())

    assert result.success is True
    assert result.provider == "illustration"
    assert result.route == "illustration_fake"
    assert result.model_version == "fake-illustration-v1"
    assert result.image_bytes == b"\x89PNG\r\n\x1a\nfake-image"
    assert result.provenance["quality_loop"]["status"] == "fake_completed"
    assert result.provenance["limitations"] == [
        "fake_provider_no_network",
        "quality_not_independently_evaluated",
    ]


def test_request_rejects_unknown_evidence_boundary() -> None:
    request = FigureImageRequest(
        prompt="Draw observed accuracy gains without data.",
        figure_id="fig:unsafe",
        figure_contract={"claim": "Unsupported observed result."},
        evidence_boundary="observed_without_evidence",
    )
    with pytest.raises(FigureImageRequestError, match="evidence_boundary"):
        request.to_provider_payload()


def test_request_rejects_missing_figure_contract() -> None:
    request = FigureImageRequest(
        prompt="Create a clean academic workflow diagram.",
        figure_id="fig:workflow",
        figure_contract={},
        evidence_boundary="conceptual",
    )
    with pytest.raises(FigureImageRequestError, match="figure_contract"):
        request.to_provider_payload()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("style_guide", "README"),
        ("style_guide", "/etc/passwd"),
        ("anchor", "../private.png"),
        ("anchor", "/tmp/private.png"),
    ],
)
def test_request_rejects_file_backed_style_contract_values(field, value) -> None:
    request = FigureImageRequest(
        prompt="Create a clean academic workflow diagram.",
        figure_id="fig:workflow",
        figure_contract={"title": "Workflow", field: value},
        evidence_boundary="conceptual",
    )
    with pytest.raises(FigureImageRequestError, match=field):
        request.to_provider_payload()


def test_request_rejects_unbounded_quality_loop() -> None:
    request = FigureImageRequest(
        prompt="Create a clean academic workflow diagram.",
        figure_id="fig:workflow",
        figure_contract={"claim": "bounded"},
        evidence_boundary="conceptual",
        max_refinement_rounds=4,
    )
    with pytest.raises(FigureImageRequestError, match="max_refinement_rounds"):
        request.to_provider_payload()
