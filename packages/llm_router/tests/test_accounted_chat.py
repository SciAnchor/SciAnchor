"""Fail-closed contract for a budget-authorized provider call."""

from __future__ import annotations

import hashlib
import json

import pytest

from llm_router import client as client_module


def _contract_types():
    authorization_type = getattr(client_module, "BudgetAuthorization", None)
    receipt_type = getattr(client_module, "ProviderUsageReceipt", None)
    assert authorization_type is not None, "BudgetAuthorization is required"
    assert receipt_type is not None, "ProviderUsageReceipt is required"
    return authorization_type, receipt_type


def test_accounted_contract_types_are_exported_from_public_package():
    from llm_router import (
        AccountedProviderFn,
        AccountedProviderNotStarted,
        AccountedProviderUnsupported,
        BudgetAuthorization,
        ProviderUsageReceipt,
    )

    assert BudgetAuthorization is client_module.BudgetAuthorization
    assert ProviderUsageReceipt is client_module.ProviderUsageReceipt
    assert AccountedProviderFn is client_module.AccountedProviderFn
    assert AccountedProviderNotStarted is client_module.AccountedProviderNotStarted
    assert AccountedProviderUnsupported is client_module.AccountedProviderUnsupported


def _authorization():
    authorization_type, _ = _contract_types()
    return authorization_type(
        attempt_id="attempt-1",
        request_sha256="a" * 64,
        max_cost_usd=0.75,
        idempotency_key="repair-attempt-1",
    )


def _receipt(text: str):
    _, receipt_type = _contract_types()
    payload = {
        "attempt_id": "attempt-1",
        "request_sha256": "a" * 64,
        "provider": "accounted-test",
        "model": "test-model",
        "provider_request_id": "provider-request-1",
        "provider_started": True,
        "completion_known": True,
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "cache_read_tokens": 0,
        "cost_usd": 0.37,
        "cost_source": "reported",
        "transport": "provider",
        "evidence_class": "provider_reported",
        "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return receipt_type(**payload, receipt_sha256=digest)


def _receipt_kwargs(text: str, **overrides):
    receipt = _receipt(text)
    values = {name: getattr(receipt, name) for name in receipt.__dataclass_fields__}
    values.update(overrides)
    if "receipt_sha256" not in overrides:
        payload = {
            name: value for name, value in values.items() if name != "receipt_sha256"
        }
        values["receipt_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    return values


def _client(provider: str):
    return client_module.LLMClient(
        client_module.ResolvedLLMConfig(
            provider=provider,
            model="test-model",
            api_key="test-only",
        )
    )


def test_legacy_provider_is_refused_before_any_side_effect(monkeypatch):
    calls: list[str] = []

    def legacy_provider(prompt, model, **kwargs):
        calls.append(prompt)
        return "must not run"

    monkeypatch.setitem(
        client_module._PROVIDER_REGISTRY, "legacy-test", legacy_provider
    )
    authorization = _authorization()
    client = _client("legacy-test")

    accounted_chat = getattr(client, "chat_accounted", None)
    assert callable(accounted_chat), "LLMClient.chat_accounted is required"
    with pytest.raises(Exception, match=r"(?i)(hard.?cap|account|receipt|unsupported)"):
        accounted_chat("repair this manuscript", authorization=authorization)

    assert calls == []


def test_accounted_provider_returns_text_and_bound_receipt_atomically(monkeypatch):
    legacy_calls: list[str] = []
    authorizations = []

    def legacy_provider(prompt, model, **kwargs):
        legacy_calls.append(prompt)
        raise AssertionError("the legacy call surface must not be used")

    def accounted_provider(prompt, model, *, authorization, **kwargs):
        authorizations.append(authorization)
        text = '{"revised_content":"bounded"}'
        return text, _receipt(text)

    monkeypatch.setitem(
        client_module._PROVIDER_REGISTRY, "accounted-test", legacy_provider
    )
    register_provider = client_module.register_provider
    register_provider(
        "accounted-test", legacy_provider, accounted_fn=accounted_provider
    )
    try:
        authorization = _authorization()
        client = _client("accounted-test")

        accounted_chat = getattr(client, "chat_accounted", None)
        assert callable(accounted_chat), "LLMClient.chat_accounted is required"
        result = accounted_chat("repair this manuscript", authorization=authorization)
        if isinstance(result, tuple):
            text, receipt = result
        else:
            text, receipt = result.text, result.receipt

        assert text == '{"revised_content":"bounded"}'
        assert receipt.attempt_id == authorization.attempt_id
        assert receipt.request_sha256 == authorization.request_sha256
        assert receipt.cost_usd == 0.37
        assert receipt.cost_source == "reported"
        assert receipt.transport == "provider"
        assert receipt.output_sha256 == hashlib.sha256(text.encode()).hexdigest()
        assert authorizations == [authorization]
        assert legacy_calls == []
    finally:
        register_provider("accounted-test", legacy_provider)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"attempt_id": ""}, "identity"),
        ({"idempotency_key": ""}, "identity"),
        ({"request_sha256": "invalid"}, "request_sha256"),
        ({"max_cost_usd": 0}, "positive"),
        ({"max_cost_usd": float("inf")}, "positive"),
    ],
)
def test_budget_authorization_rejects_invalid_boundary_values(overrides, message):
    authorization_type, _ = _contract_types()
    values = {
        "attempt_id": "attempt-1",
        "request_sha256": "a" * 64,
        "max_cost_usd": 0.75,
        "idempotency_key": "repair-attempt-1",
        **overrides,
    }

    with pytest.raises(ValueError, match=message):
        authorization_type(**values)


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        ({"attempt_id": ""}, ValueError, "identity"),
        ({"provider": ""}, ValueError, "identity"),
        ({"model": ""}, ValueError, "identity"),
        ({"request_sha256": "invalid"}, ValueError, "request_sha256"),
        ({"provider_request_id": ""}, ValueError, "provider_request_id"),
        ({"provider_started": 1}, TypeError, "boolean"),
        ({"completion_known": 1}, TypeError, "boolean"),
        ({"prompt_tokens": -1}, ValueError, "prompt_tokens"),
        ({"completion_tokens": True}, ValueError, "completion_tokens"),
        ({"cache_read_tokens": -1}, ValueError, "cache_read_tokens"),
        ({"cost_usd": True}, ValueError, "cost_usd"),
        ({"cost_usd": -0.01}, ValueError, "cost_usd"),
        ({"cost_usd": float("nan")}, ValueError, "cost_usd"),
        ({"cost_source": ""}, ValueError, "cost evidence"),
        ({"evidence_class": ""}, ValueError, "cost evidence"),
        ({"transport": "unknown"}, ValueError, "transport"),
        ({"output_sha256": "invalid"}, ValueError, "output_sha256"),
        ({"receipt_sha256": "0" * 64}, ValueError, "receipt hash"),
    ],
)
def test_provider_receipt_rejects_invalid_boundary_values(
    overrides, error_type, message
):
    _, receipt_type = _contract_types()

    with pytest.raises(error_type, match=message):
        receipt_type(**_receipt_kwargs("bounded", **overrides))


def test_chat_accounted_rejects_untyped_authorization_before_transport(monkeypatch):
    calls = []
    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(TypeError, match="BudgetAuthorization"):
        _client("accounted-test").chat_accounted("repair", authorization=object())

    assert calls == []


def test_chat_accounted_uses_the_tier_route(monkeypatch):
    calls = []

    def accounted_provider(prompt, model, *, authorization, **kwargs):
        calls.append((prompt, model, authorization))
        text = "routed"
        _, receipt_type = _contract_types()
        return text, receipt_type(
            **_receipt_kwargs(text, provider="routed-provider", model="routed-model")
        )

    monkeypatch.setattr(
        client_module, "resolve_route", lambda tier: ("routed-provider", "routed-model")
    )
    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "routed-provider",
        accounted_provider,
    )
    monkeypatch.setitem(
        client_module._PROVIDER_REGISTRY,
        "routed-provider",
        lambda *args, **kwargs: pytest.fail("legacy transport must not run"),
    )
    monkeypatch.setenv("ROUTED-PROVIDER_API_KEY", "route-key")
    authorization = _authorization()

    text, receipt = _client("unused-provider").chat_accounted(
        "repair", tier="writing", authorization=authorization
    )

    assert (text, receipt.model) == ("routed", "routed-model")
    assert calls == [("repair", "routed-model", authorization)]


def test_chat_accounted_tier_uses_routed_provider_credentials(monkeypatch):
    calls = []

    def accounted_provider(prompt, model, *, authorization, **kwargs):
        calls.append((prompt, model, kwargs["api_key"], kwargs["base_url"]))
        text = "routed"
        _, receipt_type = _contract_types()
        return text, receipt_type(
            **_receipt_kwargs(text, provider="anthropic", model="writing-model")
        )

    monkeypatch.setattr(
        client_module, "resolve_route", lambda tier: ("anthropic", "writing-model")
    )
    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "anthropic",
        accounted_provider,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "writing-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://writing.example/v1")
    client = client_module.LLMClient(
        client_module.ResolvedLLMConfig(
            provider="openai",
            model="default-model",
            api_key="default-key",
            base_url="https://default.example/v1",
        )
    )

    client.chat_accounted("repair", tier="writing", authorization=_authorization())

    assert calls == [
        (
            "repair",
            "writing-model",
            "writing-key",
            "https://writing.example/v1",
        )
    ]


def test_chat_accounted_rejects_an_empty_model_before_transport(monkeypatch):
    calls = []
    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    client = client_module.LLMClient(
        client_module.ResolvedLLMConfig(provider="accounted-test", model="")
    )

    with pytest.raises(ValueError, match="No model"):
        client.chat_accounted("repair", authorization=_authorization())

    assert calls == []


@pytest.mark.parametrize(
    "config",
    [
        client_module.ResolvedLLMConfig(
            provider="missing-accounted-provider",
            model="test-model",
            api_key="test-only",
        ),
        client_module.ResolvedLLMConfig(
            provider="",
            model="test-model",
            api_key="test-only",
        ),
        client_module.ResolvedLLMConfig(
            provider="accounted-test",
            model="",
            api_key="test-only",
        ),
        client_module.ResolvedLLMConfig(
            provider="accounted-test",
            model="test-model",
            api_key="",
        ),
    ],
    ids=(
        "invalid-provider",
        "empty-provider",
        "empty-model",
        "missing-credential",
    ),
)
def test_accounted_preflight_rejects_invalid_binding_before_transport(
    monkeypatch, config
):
    calls = []
    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    client = client_module.LLMClient(config)
    preflight = getattr(client, "preflight_accounted", None)

    assert callable(preflight), "accounted calls require a read-only preflight"
    not_started = getattr(client_module, "AccountedProviderNotStarted", None)
    assert not_started is not None, "typed pre-transport rejection is required"
    with pytest.raises(not_started):
        preflight()

    assert calls == []


def test_accounted_preflight_freezes_route_credentials_and_endpoint(monkeypatch):
    seen = []

    def accounted_provider(prompt, model, *, authorization, **kwargs):
        seen.append((model, kwargs["api_key"], kwargs["base_url"]))
        text = "bounded"
        return text, client_module.ProviderUsageReceipt(
            **_receipt_kwargs(text, provider="accounted-test", model=model)
        )

    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        accounted_provider,
    )
    client = _client("accounted-test")
    client._config.base_url = "https://configured.example/v1"
    prepared_config = client.preflight_accounted()

    client._config.api_key = "changed-after-preflight"
    client._config.base_url = "https://changed.example/v1"
    client_module.LLMClient(prepared_config).chat_accounted(
        "repair", authorization=_authorization()
    )

    assert seen == [("test-model", "test-only", "https://configured.example/v1")]


def test_adapter_not_started_error_after_invocation_becomes_unknown_outcome(
    monkeypatch,
):
    not_started = getattr(client_module, "AccountedProviderNotStarted", None)
    assert not_started is not None, "typed pre-transport rejection is required"
    secret = "secret-adapter-detail"

    def raise_misleading_not_started(*args, **kwargs):
        raise not_started(secret)

    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        raise_misleading_not_started,
    )

    with pytest.raises(RuntimeError, match="outcome is unknown") as raised:
        _client("accounted-test").chat_accounted(
            "repair", authorization=_authorization()
        )

    assert not isinstance(raised.value, not_started)
    assert isinstance(raised.value.__cause__, not_started)
    assert secret not in str(raised.value)


@pytest.mark.parametrize(
    "result",
    [
        "not-a-tuple",
        ("text-only",),
        ("text", object()),
    ],
)
def test_chat_accounted_rejects_invalid_provider_return_shape(monkeypatch, result):
    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        lambda *args, **kwargs: result,
    )

    with pytest.raises(TypeError, match="ProviderUsageReceipt"):
        _client("accounted-test").chat_accounted(
            "repair", authorization=_authorization()
        )


@pytest.mark.parametrize(
    "receipt_override",
    [
        {"attempt_id": "other-attempt"},
        {"request_sha256": "b" * 64},
        {"provider": "other-provider"},
        {"model": "other-model"},
        {"output_sha256": hashlib.sha256(b"other-output").hexdigest()},
    ],
)
def test_chat_accounted_rejects_receipt_outside_authorized_call(
    monkeypatch, receipt_override
):
    def accounted_provider(prompt, model, **kwargs):
        _, receipt_type = _contract_types()
        return "bounded", receipt_type(**_receipt_kwargs("bounded", **receipt_override))

    monkeypatch.setitem(
        client_module._ACCOUNTED_PROVIDER_REGISTRY,
        "accounted-test",
        accounted_provider,
    )

    with pytest.raises(ValueError, match="authorized call"):
        _client("accounted-test").chat_accounted(
            "repair", authorization=_authorization()
        )
