"""Reliability controls for OpenAI-compatible providers: bounded HTTP
timeout/retries (fast-fail instead of the SDK's ~600s x 2 default stall) and
opt-in cross-process serialization for a shared local tunnel."""

from __future__ import annotations

import sys
import types

import pytest

from llm_router import client as C


# --- timeout / retries env plumbing ---------------------------------------


def test_http_timeout_default(monkeypatch):
    monkeypatch.delenv("LLM_HTTP_TIMEOUT_SECONDS", raising=False)
    assert C._http_timeout() == C._DEFAULT_HTTP_TIMEOUT_SECONDS


def test_http_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_HTTP_TIMEOUT_SECONDS", "45")
    assert C._http_timeout() == 45.0


def test_http_timeout_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_HTTP_TIMEOUT_SECONDS", "not-a-number")
    assert C._http_timeout() == C._DEFAULT_HTTP_TIMEOUT_SECONDS
    monkeypatch.setenv("LLM_HTTP_TIMEOUT_SECONDS", "-5")
    assert C._http_timeout() == C._DEFAULT_HTTP_TIMEOUT_SECONDS


def test_http_max_retries_default_and_env(monkeypatch):
    monkeypatch.delenv("LLM_HTTP_MAX_RETRIES", raising=False)
    assert C._http_max_retries() == C._DEFAULT_HTTP_MAX_RETRIES
    monkeypatch.setenv("LLM_HTTP_MAX_RETRIES", "0")
    assert C._http_max_retries() == 0


# --- serialization guard ---------------------------------------------------


def test_serialize_disabled_returns_no_lock(monkeypatch):
    monkeypatch.delenv("LLM_TUNNEL_SERIALIZE", raising=False)
    assert C._serialize_lock_path("http://127.0.0.1:18443/v1") is None


def test_serialize_skips_remote_endpoints(monkeypatch):
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    assert C._serialize_lock_path("https://api.openai.com/v1") is None


def test_serialize_skips_local_text_endpoint(monkeypatch, tmp_path):
    # Text/chat endpoint is load-balanced and scales: must NOT serialize.
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    monkeypatch.delenv("LLM_TUNNEL_SERIALIZE_ALL", raising=False)
    monkeypatch.setenv("LLM_TUNNEL_LOCK_PATH", str(tmp_path / "tunnel.lock"))
    assert C._serialize_lock_path("http://localhost:18443/v1") is None


def test_serialize_engages_for_image_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    lock = tmp_path / "tunnel.lock"
    monkeypatch.setenv("LLM_TUNNEL_LOCK_PATH", str(lock))
    # The image endpoint is the scarce resource: serialize it.
    assert C._serialize_lock_path("http://localhost:18443/v1/images") == str(lock)
    # Or via the explicit is_image flag on the text endpoint.
    assert C._serialize_lock_path("http://localhost:18443/v1", is_image=True) == str(
        lock
    )


def test_serialize_all_restores_text_locking(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE_ALL", "1")
    lock = tmp_path / "tunnel.lock"
    monkeypatch.setenv("LLM_TUNNEL_LOCK_PATH", str(lock))
    assert C._serialize_lock_path("http://localhost:18443/v1") == str(lock)


def test_guard_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("LLM_TUNNEL_SERIALIZE", raising=False)
    with C._endpoint_serialize_guard("http://127.0.0.1:18443/v1"):
        pass  # must not raise or block


def test_guard_acquires_lock_file_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    lock = tmp_path / "t.lock"
    monkeypatch.setenv("LLM_TUNNEL_LOCK_PATH", str(lock))
    with C._endpoint_serialize_guard("http://127.0.0.1:1/v1", is_image=True):
        assert lock.exists()


# --- _chat_openai wiring ---------------------------------------------------


def _install_fake_openai(monkeypatch, captured):
    class FakeMsg:
        content = "ok"

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        choices = [FakeChoice()]
        usage = None

    class FakeCompletions:
        def create(self, **kwargs):
            captured["create"] = kwargs
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        chat = FakeChat()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))


def test_chat_openai_bounds_timeout_and_retries(monkeypatch):
    monkeypatch.setenv("LLM_HTTP_TIMEOUT_SECONDS", "77")
    monkeypatch.setenv("LLM_HTTP_MAX_RETRIES", "3")
    monkeypatch.delenv("LLM_TUNNEL_SERIALIZE", raising=False)
    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)
    out = C._chat_openai(
        "hello", "gpt-x", api_key="k", base_url="http://127.0.0.1:18443/v1"
    )
    assert out == "ok"
    assert captured["init"]["timeout"] == 77.0
    # The SDK retries nothing; _create_with_transport_retries re-sends fast failures only.
    assert captured["init"]["max_retries"] == 0
    assert C._http_max_retries() == 3
    assert captured["init"]["base_url"] == "http://127.0.0.1:18443/v1"


def test_chat_openai_text_call_is_not_serialized(monkeypatch, tmp_path):
    # Text/chat runs concurrently on the load-balanced tunnel: no shared lock.
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    monkeypatch.delenv("LLM_TUNNEL_SERIALIZE_ALL", raising=False)
    lock = tmp_path / "s.lock"
    monkeypatch.setenv("LLM_TUNNEL_LOCK_PATH", str(lock))
    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)
    out = C._chat_openai(
        "hi", "gpt-x", api_key="k", base_url="http://localhost:18443/v1"
    )
    assert out == "ok"
    assert not lock.exists()  # text call did not acquire the image lock


def test_chat_openai_serializes_when_all_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE", "1")
    monkeypatch.setenv("LLM_TUNNEL_SERIALIZE_ALL", "1")
    lock = tmp_path / "s.lock"
    monkeypatch.setenv("LLM_TUNNEL_LOCK_PATH", str(lock))
    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)
    out = C._chat_openai(
        "hi", "gpt-x", api_key="k", base_url="http://localhost:18443/v1"
    )
    assert out == "ok"
    assert lock.exists()  # legacy safety valve still serializes text


# --- gateway compatibility: max_tokens + temperature-rejecting models -------


class _FakeCompletions:
    """Records每次 create 的参数; 可选地对带 temperature 的首次调用报 400。"""

    def __init__(self, reject_temperature: bool):
        self.reject_temperature = reject_temperature
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_temperature and "temperature" in kwargs:
            raise RuntimeError(
                "Error code: 400 - `temperature` is deprecated for this model."
            )
        msg = types.SimpleNamespace(content="ok")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg)], usage=None
        )


def _install_kwargs_recording_openai(monkeypatch, reject_temperature=False):
    completions = _FakeCompletions(reject_temperature)
    client_obj = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=completions)
    )
    module = types.ModuleType("openai")
    module.OpenAI = lambda **_: client_obj
    monkeypatch.setitem(sys.modules, "openai", module)
    return completions


def test_openai_sends_max_tokens_from_env(monkeypatch):
    # Gateways默认 8192 会截断长 JSON 输出, 所以必须显式带 max_tokens。
    calls = _install_kwargs_recording_openai(monkeypatch)
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "12345")
    C._chat_openai("hi", "some-model", api_key="k", base_url="http://x/v1")
    assert calls.calls[0]["max_tokens"] == 12345


def test_openai_retries_without_temperature_and_remembers(monkeypatch):
    calls = _install_kwargs_recording_openai(monkeypatch, reject_temperature=True)
    monkeypatch.setattr(C, "_NO_TEMPERATURE_MODELS", set())
    assert (
        C._chat_openai("hi", "claude-x-5", api_key="k", base_url="http://x/v1") == "ok"
    )
    # 首次带 temperature 被拒 -> 去掉重试成功
    assert "temperature" in calls.calls[0] and "temperature" not in calls.calls[1]
    # 该模型被记住, 第二次调用不再浪费一次上游请求
    C._chat_openai("hi", "claude-x-5", api_key="k", base_url="http://x/v1")
    assert "temperature" not in calls.calls[2]
    assert len(calls.calls) == 3


def _stub_client(errors):
    import httpx
    import openai

    calls = []
    request = httpx.Request("POST", "http://127.0.0.1:18444/v1/chat/completions")

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if errors:
                kind = errors.pop(0)
                if kind == "timeout":
                    raise openai.APITimeoutError(request=request)
                raise openai.APIConnectionError(request=request)
            return "reply"

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client(), calls


def test_a_timed_out_generation_is_not_resent(monkeypatch):
    """a0113 (2026-09-26): 180 s + an SDK retry of 180 s ended in 'Request timed out.' at 360 s,
    and a reply that finished on the retry had been bought twice."""
    import openai

    client, calls = _stub_client(["timeout"])
    with pytest.raises(openai.APITimeoutError):
        C._create_with_transport_retries(client, {"model": "m"})
    assert len(calls) == 1


def test_a_fast_transport_failure_is_retried(monkeypatch):
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    client, calls = _stub_client(["connect"])
    assert C._create_with_transport_retries(client, {"model": "m"}) == "reply"
    assert len(calls) == 2


def test_the_default_timeout_fits_a_long_generation(monkeypatch):
    monkeypatch.delenv("LLM_HTTP_TIMEOUT_SECONDS", raising=False)
    assert C._http_timeout() >= 450  # a ~9k-token reply at ~22 tokens/s
