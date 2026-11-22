"""Tests for figure_generate primitive and fal_image_client."""

from __future__ import annotations

import os
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from research_harness.execution.fal_image_client import (
    _dimensions_to_openai_size,
    build_image_prompt,
    choose_dimensions,
    classify_figure_style,
    figure_id_to_filename,
    generate_image,
    DIMENSION_PRESETS,
    OPENAI_IMAGE_MODEL,
    NANO_BANANA_FAST_MODEL,
)
from research_harness.integrations.figure_image_provider import (
    GEMINI_ROUTE,
    GOOGLE_API_KEY_ENV,
    GPT_IMAGE_API_KEY_ENV,
    GPT_IMAGE_ROUTE,
    GROK_API_KEY_ENV,
    GROK_ROUTE,
    FigureImageConfigurationError,
    FigureImageResult,
)


class TestBuildImagePrompt:
    def test_architecture_prompt(self):
        prompt = build_image_prompt(
            title="ModalGate Architecture",
            purpose="Show the overall system architecture with modal gating mechanism",
            suggested_layout="wide horizontal flow diagram",
            section="method",
        )
        assert "architecture" in prompt.lower()
        assert "ModalGate" in prompt
        assert "white background" in prompt
        assert "labeled" in prompt.lower()

    def test_pipeline_prompt(self):
        prompt = build_image_prompt(
            title="Training Pipeline",
            purpose="Step-by-step data processing flow",
            suggested_layout="left-to-right flow",
            section="method",
        )
        assert "pipeline" in prompt.lower() or "flowchart" in prompt.lower()

    def test_comparison_prompt(self):
        prompt = build_image_prompt(
            title="Model Comparison",
            purpose="Ablation study showing component contributions",
            suggested_layout="grid layout",
            section="experiments",
        )
        assert "comparison" in prompt.lower()

    def test_empty_fields(self):
        prompt = build_image_prompt(title="", purpose="", section="")
        assert "academic" in prompt.lower()
        assert len(prompt) > 50

    def test_prompt_includes_figure_contract_label_constraints(self):
        prompt = build_image_prompt(
            title="Publication-State Gates",
            purpose="show readiness-state adjudication",
            section="method",
            figure_contract={
                "allowed_labels": ["Generated", "Review-ready", "Submission-ready"],
                "forbidden_labels": ["Positive", "Errors"],
                "evidence_boundary": "conceptual",
            },
        )

        assert "Use only these exact in-image labels" in prompt
        assert "Generated; Review-ready; Submission-ready" in prompt
        assert "Do not use these labels or claims: Positive; Errors." in prompt
        assert "Evidence boundary: conceptual." in prompt


class TestFigureIdToFilename:
    def test_basic(self):
        assert figure_id_to_filename("fig:arch") == "arch.png"

    def test_no_prefix(self):
        assert figure_id_to_filename("overview") == "overview.png"

    def test_special_chars(self):
        assert figure_id_to_filename("fig:my figure!@#") == "my_figure___.png"

    def test_empty(self):
        assert figure_id_to_filename("") == "figure.png"

    def test_only_prefix(self):
        assert figure_id_to_filename("fig:") == "figure.png"

    def test_underscores_preserved(self):
        assert figure_id_to_filename("fig:arch_overview") == "arch_overview.png"

    def test_hyphens_preserved(self):
        assert figure_id_to_filename("fig:my-figure") == "my-figure.png"


class TestClassifyFigureStyle:
    def test_pipeline(self):
        style = classify_figure_style("data processing flow", "", "Pipeline")
        assert "infographical" in style

    def test_architecture(self):
        style = classify_figure_style("system architecture", "", "Framework")
        assert "digital_illustration" in style

    def test_comparison(self):
        style = classify_figure_style("ablation comparison", "", "Results")
        assert "digital_illustration" in style

    def test_default(self):
        style = classify_figure_style("some random purpose", "", "Figure")
        assert "digital_illustration" in style


class TestChooseDimensions:
    def test_wide_for_architecture(self):
        dims = choose_dimensions("wide horizontal", "architecture overview")
        assert dims == DIMENSION_PRESETS["wide"]

    def test_square_for_grid(self):
        dims = choose_dimensions("grid layout", "matrix comparison")
        assert dims == DIMENSION_PRESETS["square"]

    def test_default(self):
        dims = choose_dimensions("", "some purpose")
        assert dims == DIMENSION_PRESETS["standard"]


class TestGenerateImageMocked:
    def test_success_with_openai_image_default(self, tmp_path: Path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        encoded = base64.b64encode(image_bytes).decode("ascii")

        mock_image = MagicMock()
        mock_image.b64_json = encoded
        mock_image.url = None

        mock_response = MagicMock()
        mock_response.data = [mock_image]

        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            result = generate_image(
                prompt="test academic diagram",
                output_dir=str(tmp_path),
                filename="test.png",
            )

        assert result.success
        assert result.model_id == OPENAI_IMAGE_MODEL
        assert result.width == 1536
        assert result.height == 1024
        assert (tmp_path / "test.png").read_bytes() == image_bytes
        mock_client.images.generate.assert_called_once()
        kwargs = mock_client.images.generate.call_args.kwargs
        assert kwargs["model"] == OPENAI_IMAGE_MODEL
        assert kwargs["size"] == "1536x1024"
        assert kwargs["quality"] == "high"
        assert kwargs["output_format"] == "png"

    def test_openai_dimensions_use_supported_sizes(self):
        assert _dimensions_to_openai_size(DIMENSION_PRESETS["wide"]) == "1536x1024"
        assert _dimensions_to_openai_size(DIMENSION_PRESETS["standard"]) == "1536x1024"
        assert _dimensions_to_openai_size(DIMENSION_PRESETS["square"]) == "1024x1024"
        assert _dimensions_to_openai_size(DIMENSION_PRESETS["tall"]) == "1024x1536"

    def test_openai_image_model_alias(self, tmp_path: Path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        encoded = base64.b64encode(image_bytes).decode("ascii")

        mock_image = MagicMock()
        mock_image.b64_json = encoded
        mock_image.url = None
        mock_response = MagicMock(data=[mock_image])
        mock_client = MagicMock()
        mock_client.images.generate.return_value = mock_response

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch("openai.OpenAI", return_value=mock_client),
        ):
            result = generate_image(
                prompt="test academic diagram",
                model="gpt image2",
                output_dir=str(tmp_path),
                filename="test.png",
            )

        assert result.success
        assert result.model_id == OPENAI_IMAGE_MODEL
        assert (
            mock_client.images.generate.call_args.kwargs["model"] == OPENAI_IMAGE_MODEL
        )

    def test_missing_openai_key_for_default_provider(self, tmp_path: Path):
        old_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
                generate_image(
                    prompt="test",
                    output_dir=str(tmp_path),
                    filename="test.png",
                )
        finally:
            if old_key:
                os.environ["OPENAI_API_KEY"] = old_key

    def test_success_with_fal_client(self, tmp_path: Path):
        mock_result = {"images": [{"url": "https://example.com/image.png"}]}
        mock_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = mock_result

        mock_resp = MagicMock()
        mock_resp.content = mock_content
        mock_resp.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch.dict(os.environ, {"FAL_KEY": "test-key"}),
            patch.dict("sys.modules", {"fal_client": mock_fal}),
            patch("httpx.Client", return_value=mock_client_instance),
        ):
            result = generate_image(
                prompt="test diagram",
                model="recraft",
                output_dir=str(tmp_path),
                filename="test.png",
            )
            assert result.success
            assert result.image_url == "https://example.com/image.png"
            assert result.model_id == "fal-ai/recraft/v3/text-to-image"

    def test_missing_fal_key(self, tmp_path: Path):
        old_key = os.environ.pop("FAL_KEY", None)
        try:
            with pytest.raises(EnvironmentError, match="FAL_KEY"):
                generate_image(
                    prompt="test",
                    model="recraft",
                    output_dir=str(tmp_path),
                    filename="test.png",
                )
        finally:
            if old_key:
                os.environ["FAL_KEY"] = old_key

    def test_nano_banana_alias_uses_fal_fast_path(self, tmp_path: Path):
        mock_result = {"images": [{"url": "https://example.com/nano.png"}]}
        mock_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = mock_result

        mock_resp = MagicMock()
        mock_resp.content = mock_content
        mock_resp.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch.dict(os.environ, {"FAL_KEY": "test-key"}),
            patch.dict("sys.modules", {"fal_client": mock_fal}),
            patch("httpx.Client", return_value=mock_client_instance),
        ):
            result = generate_image(
                prompt="test diagram",
                model="nano-banana",
                output_dir=str(tmp_path),
                filename="test.png",
            )

        assert result.success
        assert result.model_id == NANO_BANANA_FAST_MODEL
        mock_fal.subscribe.assert_called_once()
        assert mock_fal.subscribe.call_args.args[0] == NANO_BANANA_FAST_MODEL
        assert mock_fal.subscribe.call_args.kwargs["arguments"]["image_size"] == (
            "landscape_4_3"
        )

    def test_session_imagegen_is_not_programmatic_primitive_provider(
        self, tmp_path: Path
    ):
        result = generate_image(
            prompt="test diagram",
            model="codex-session",
            output_dir=str(tmp_path),
            filename="test.png",
        )

        assert not result.success
        assert result.model_id == "codex_session_imagegen"
        assert "session-only" in result.error

    def test_illustration_fake_alias_generates_without_network(self, tmp_path: Path):
        with patch("httpx.Client", side_effect=AssertionError("network disabled")):
            result = generate_image(
                prompt="Create a clean academic workflow diagram.",
                model="illustration-fake",
                output_dir=str(tmp_path),
                filename="illustration.png",
                figure_id="fig:illustration",
                figure_contract={
                    "title": "Illustration route",
                    "purpose": "show explicit provider routing",
                },
                evidence_boundary="conceptual",
            )

        assert result.success
        assert result.model_id == "illustration"
        assert result.width == 1440
        assert result.height == 960
        assert (tmp_path / "illustration.png").read_bytes().startswith(b"\x89PNG")
        assert result.provenance["provider"] == "illustration"
        assert result.provenance["route"] == "illustration_fake"
        assert result.provenance["request_shape"]["has_prompt"] is True
        assert result.provenance["asset_record"]["local_path"] == str(
            tmp_path / "illustration.png"
        )
        assert result.provenance["asset_record"]["recorded"] is True
        assert result.provenance["quality_loop"]["status"] == "fake_completed"
        assert "quality_not_independently_evaluated" in result.provenance["limitations"]
        assert "Create a clean academic workflow diagram." not in repr(
            result.provenance["request_shape"]
        )

    def test_illustration_route_fails_closed_when_env_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
        for name in (
            GOOGLE_API_KEY_ENV,
            GROK_API_KEY_ENV,
            GPT_IMAGE_API_KEY_ENV,
        ):
            monkeypatch.delenv(name, raising=False)

        with pytest.raises(FigureImageConfigurationError) as exc_info:
            generate_image(
                prompt="Create a clean academic workflow diagram.",
                model="illustration",
                output_dir=str(tmp_path),
                filename="illustration.png",
                figure_id="fig:illustration",
                figure_contract={"title": "Illustration route"},
                evidence_boundary="conceptual",
            )

        message = str(exc_info.value)
        assert GOOGLE_API_KEY_ENV in message
        assert GROK_API_KEY_ENV in message
        assert GPT_IMAGE_API_KEY_ENV in message
        assert not (tmp_path / "illustration.png").exists()

    def test_illustration_route_uses_gemini_native_when_google_key_is_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        image_bytes = b"\x89PNG\r\n\x1a\nillustration-gemini"
        calls: list[object] = []

        def fake_generate(provider, request):
            calls.append(provider.config)
            return FigureImageResult(
                success=True,
                provider="illustration",
                route=GEMINI_ROUTE,
                model=request.model,
                model_version=provider.config.model,
                image_bytes=image_bytes,
                provenance={
                    "provider": "illustration",
                    "route": GEMINI_ROUTE,
                    "model": request.model,
                    "model_version": provider.config.model,
                    "request_shape": request.sanitized_request_shape(),
                    "provider_config": provider.config.safe_config(),
                    "quality_loop": {
                        "status": "provider_completed",
                    },
                    "asset_record": {
                        "byte_count": len(image_bytes),
                        "recorded": False,
                    },
                    "limitations": [
                        "provider_output_not_human_reviewed",
                        "quality_not_independently_evaluated",
                    ],
                },
            )

        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
        for name in ():
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(GOOGLE_API_KEY_ENV, "google-secret")

        with patch(
            "research_harness.integrations.figure_image_provider."
            "GeminiImageProvider.generate",
            fake_generate,
        ):
            result = generate_image(
                prompt="Create a clean academic workflow diagram.",
                model="illustration",
                output_dir=str(tmp_path),
                filename="illustration.png",
                figure_id="fig:illustration",
                figure_contract={"title": "Illustration route"},
                evidence_boundary="conceptual",
            )

        assert result.success
        assert result.model_id == "illustration"
        assert (tmp_path / "illustration.png").read_bytes() == image_bytes
        assert result.provenance["route"] == GEMINI_ROUTE
        assert result.provenance["provider_config"]["provider_backend"] == (
            "gemini_native"
        )
        assert calls
        assert "google-secret" not in repr(result.provenance)

    def test_illustration_grok_payload_uses_resolution_not_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        image_bytes = b"\x89PNG\r\n\x1a\nillustration-grok"
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["payload"] = request.read()
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    ]
                },
            )

        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
        for name in (
            GOOGLE_API_KEY_ENV,
            GPT_IMAGE_API_KEY_ENV,
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(GROK_API_KEY_ENV, "grok-secret")
        monkeypatch.setenv("GROK_BASE_URL", "https://example.invalid/v1")

        with patch(
            "httpx.Client",
            return_value=httpx.Client(transport=httpx.MockTransport(handler)),
        ):
            result = generate_image(
                prompt="Create a clean academic workflow diagram.",
                model="illustration",
                output_dir=str(tmp_path),
                filename="illustration.png",
                figure_id="fig:illustration",
                figure_contract={"title": "Illustration route"},
                evidence_boundary="conceptual",
            )

        import json

        payload = json.loads(captured["payload"])
        assert result.success
        assert result.provenance["route"] == GROK_ROUTE
        assert payload["resolution"] == "2k"
        assert payload["aspect_ratio"]
        assert "size" not in payload
        assert "grok-secret" not in repr(result.provenance)
        assert (tmp_path / "illustration.png").read_bytes() == image_bytes

    def test_illustration_falls_back_from_grok_to_gpt_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        image_bytes = b"\x89PNG\r\n\x1a\nillustration-gpt"
        grok_calls = {"n": 0}

        def grok_fail(self, request):
            grok_calls["n"] += 1
            return FigureImageResult(
                success=False,
                provider="illustration",
                route=GROK_ROUTE,
                model=request.model,
                model_version="grok-imagine-image-2.0",
                error="quota",
                provenance={"route": GROK_ROUTE},
            )

        def gpt_ok(self, request):
            return FigureImageResult(
                success=True,
                provider="illustration",
                route=GPT_IMAGE_ROUTE,
                model=request.model,
                model_version="gpt-image-2.5",
                image_bytes=image_bytes,
                provenance={
                    "provider": "illustration",
                    "route": GPT_IMAGE_ROUTE,
                    "model": request.model,
                    "model_version": "gpt-image-2.5",
                    "provider_config": {"provider_backend": "gpt_image"},
                    "quality_loop": {"status": "provider_completed"},
                    "asset_record": {"byte_count": len(image_bytes), "recorded": False},
                    "limitations": [],
                },
            )

        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
        for name in (GOOGLE_API_KEY_ENV,):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(GROK_API_KEY_ENV, "grok-secret")
        monkeypatch.setenv(GPT_IMAGE_API_KEY_ENV, "gpt-secret")

        with (
            patch(
                "research_harness.integrations.figure_image_provider."
                "GrokImageProvider.generate",
                grok_fail,
            ),
            patch(
                "research_harness.integrations.figure_image_provider."
                "GptImageProvider.generate",
                gpt_ok,
            ),
        ):
            result = generate_image(
                prompt="Create a clean academic workflow diagram.",
                model="illustration",
                output_dir=str(tmp_path),
                filename="illustration.png",
                figure_id="fig:illustration",
                figure_contract={"title": "Illustration route"},
                evidence_boundary="conceptual",
            )

        assert grok_calls["n"] == 1
        assert result.success
        assert result.provenance["route"] == GPT_IMAGE_ROUTE
        assert "gpt-secret" not in repr(result.provenance)
        assert "grok-secret" not in repr(result.provenance)
        assert (tmp_path / "illustration.png").read_bytes() == image_bytes

    def test_illustration_route_downloads_url_only_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        image_bytes = b"\x89PNG\r\n\x1a\nillustration-url"

        def provider_handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://example.invalid/v1/images/generations"
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(
                200,
                json={"data": [{"url": "https://assets.example.invalid/fig.png"}]},
            )

        def download_handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://assets.example.invalid/fig.png"
            assert "authorization" not in request.headers
            return httpx.Response(200, content=image_bytes)

        provider_client = httpx.Client(transport=httpx.MockTransport(provider_handler))
        download_client = httpx.Client(transport=httpx.MockTransport(download_handler))

        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
        monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
        for name in (GOOGLE_API_KEY_ENV, GROK_API_KEY_ENV):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(GPT_IMAGE_API_KEY_ENV, "test-token")
        monkeypatch.setenv("GPT_IMAGE_BASE_URL", "https://example.invalid")

        with patch("httpx.Client", side_effect=[provider_client, download_client]):
            result = generate_image(
                prompt="Create a clean academic workflow diagram.",
                model="illustration",
                output_dir=str(tmp_path),
                filename="illustration.png",
                figure_id="fig:illustration",
                figure_contract={"title": "Illustration route"},
                evidence_boundary="conceptual",
            )

        assert result.success
        assert result.image_url == "https://assets.example.invalid/fig.png"
        assert (tmp_path / "illustration.png").read_bytes() == image_bytes
        assert result.provenance["asset_record"]["recorded"] is True
        assert result.provenance["asset_record"]["byte_count"] == len(image_bytes)
        assert result.provenance["asset_record"]["image_url_present"] is True
        assert result.provenance["asset_record"]["local_path"] == str(
            tmp_path / "illustration.png"
        )
        assert "test-token" not in repr(result.provenance)


def test_figure_generate_schema_exposes_illustration_contract_fields() -> None:
    from research_harness.primitives.registry import get_primitive_spec

    spec = get_primitive_spec("figure_generate")
    assert spec is not None

    schema = spec.input_schema
    properties = schema["properties"]
    model_schema = properties["model"]

    assert "illustration" in model_schema["description"]
    assert "illustration-fake" in model_schema["description"]
    assert properties["evidence_boundary"] == {
        "type": "string",
        "enum": ["conceptual", "planned_protocol", "evidence_backed", "mixed"],
        "default": "conceptual",
        "description": "Evidence boundary for illustration figure requests.",
    }
    assert properties["figure_contract"] == {
        "type": "object",
        "description": (
            "Optional explicit figure contract for the illustration route. When "
            "omitted, figure_generate derives it from each item."
        ),
    }
    assert properties["illustration_fake"] == {
        "type": "boolean",
        "default": False,
        "description": (
            "Use the deterministic no-network illustration fake provider "
            "for local tests instead of a configured backend."
        ),
    }


class TestFigureGeneratePrimitive:
    def test_filters_tables(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from research_harness.execution.llm_primitives import figure_generate
        from research_harness.execution.llm_primitives import FIGURE_MODEL_ENV
        from research_harness.storage.db import Database

        monkeypatch.delenv(FIGURE_MODEL_ENV, raising=False)
        items = [
            {
                "figure_id": "fig:arch",
                "kind": "figure",
                "title": "Arch",
                "purpose": "overview",
            },
            {"figure_id": "tab:main", "kind": "table", "title": "Main Results"},
        ]

        mock_gen = MagicMock()
        mock_gen.return_value = MagicMock(
            success=True,
            local_path=str(tmp_path / "arch.png"),
            model_id="recraft",
            width=1920,
            height=960,
            error="",
        )

        db = Database(":memory:")
        with patch(
            "research_harness.execution.fal_image_client.generate_image", mock_gen
        ):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
            )

        assert result.total_requested == 1
        assert len(result.items) == 1
        assert result.items[0].figure_id == "fig:arch"
        assert mock_gen.call_args.kwargs["model"] == OPENAI_IMAGE_MODEL

    def test_default_model_can_be_selected_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from research_harness.execution.llm_primitives import (
            FIGURE_MODEL_ENV,
            figure_generate,
        )
        from research_harness.storage.db import Database

        monkeypatch.setenv(FIGURE_MODEL_ENV, "illustration")
        items = [
            {
                "figure_id": "fig:arch",
                "kind": "figure",
                "title": "Arch",
                "purpose": "overview",
            },
        ]
        mock_gen = MagicMock()
        mock_gen.return_value = MagicMock(
            success=True,
            local_path=str(tmp_path / "arch.png"),
            model_id="illustration",
            width=1920,
            height=960,
            error="",
            provenance={},
        )

        db = Database(":memory:")
        with patch(
            "research_harness.execution.fal_image_client.generate_image", mock_gen
        ):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
            )

        assert result.model_used == "illustration"
        assert mock_gen.call_args.kwargs["model"] == "illustration"

    def test_handles_generation_failure(self, tmp_path: Path):
        from research_harness.execution.llm_primitives import figure_generate
        from research_harness.storage.db import Database

        items = [
            {
                "figure_id": "fig:fail",
                "kind": "figure",
                "title": "Failing",
                "purpose": "test",
            },
        ]

        mock_gen = MagicMock(side_effect=RuntimeError("API down"))

        db = Database(":memory:")
        with patch(
            "research_harness.execution.fal_image_client.generate_image", mock_gen
        ):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
                model="recraft",
            )

        assert result.total_requested == 1
        assert result.total_generated == 0
        assert result.total_failed == 1
        assert "API down" in result.items[0].error

    def test_illustration_fake_route_from_figure_generate(self, tmp_path: Path):
        from research_harness.execution.llm_primitives import figure_generate
        from research_harness.storage.db import Database

        items = [
            {
                "figure_id": "fig:illustration",
                "kind": "figure",
                "title": "Illustration Route",
                "purpose": "show explicit Illustration provider routing",
                "caption": "A provider-routing workflow.",
                "suggested_layout": "wide horizontal workflow",
                "evidence_boundary": "conceptual",
            },
        ]

        db = Database(":memory:")
        with patch("httpx.Client", side_effect=AssertionError("network disabled")):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
                model="illustration-fake",
            )

        assert result.total_requested == 1
        assert result.total_generated == 1
        assert result.total_failed == 0
        assert result.model_used == "illustration"
        assert result.items[0].success is True
        assert result.items[0].model_used == "illustration"
        assert Path(result.items[0].path).read_bytes().startswith(b"\x89PNG")
        assert result.items[0].provenance["asset_record"]["recorded"] is True
        assert result.items[0].provenance["quality_loop"]["status"] == "fake_completed"
        assert (
            "quality_not_independently_evaluated"
            in result.items[0].provenance["limitations"]
        )

    def test_illustration_fake_flag_passes_contract_fields(self, tmp_path: Path):
        from research_harness.execution.llm_primitives import figure_generate
        from research_harness.storage.db import Database

        items = [
            {
                "figure_id": "fig:illustration",
                "kind": "figure",
                "title": "Illustration Route",
                "purpose": "show explicit Illustration provider routing",
            },
        ]

        mock_gen = MagicMock()
        mock_gen.return_value = MagicMock(
            success=True,
            local_path=str(tmp_path / "illustration.png"),
            model_id="illustration",
            width=1440,
            height=960,
            error="",
        )

        db = Database(":memory:")
        with patch(
            "research_harness.execution.fal_image_client.generate_image", mock_gen
        ):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
                model="illustration",
                illustration_fake=True,
                figure_contract={"title": "Explicit contract"},
                evidence_boundary="planned_protocol",
            )

        assert result.total_generated == 1
        assert mock_gen.call_args.kwargs["model"] == "illustration-fake"
        assert mock_gen.call_args.kwargs["figure_contract"] == {
            "title": "Explicit contract"
        }
        assert mock_gen.call_args.kwargs["evidence_boundary"] == "planned_protocol"


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skip real OpenAI image API test",
)
class TestRealGeneration:
    def test_generate_real_image(self, tmp_path: Path):
        result = generate_image(
            prompt=(
                "A clean academic architecture diagram showing an encoder-decoder model. "
                "White background, labeled boxes, connecting arrows. Minimalist style."
            ),
            output_dir=str(tmp_path),
            filename="test_real.png",
        )
        assert result.success, f"Generation failed: {result.error}"
        assert Path(result.local_path).exists()
        assert Path(result.local_path).stat().st_size > 1000
