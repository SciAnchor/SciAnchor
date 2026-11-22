"""LLM provider 配置归一化；不包含网络调用或模型默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProvider:
    name: str
    api_key: str
    base_url: str
    model: str

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


_PROVIDERS = {
    "generic": ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"),
    "gpt": ("GPT_API_KEY", "GPT_API_URL", "GPT_MODEL"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_API_URL", "OPENROUTER_MODEL"),
    "qwen": ("QWEN_API_KEY", "QWEN_API_URL", "QWEN_MODEL"),
}


def configured_llm_providers() -> list[LLMProvider]:
    return [
        LLMProvider(
            name=name,
            api_key=(os.getenv(key_var) or "").strip(),
            base_url=(os.getenv(url_var) or "").strip(),
            model=(os.getenv(model_var) or "").strip(),
        )
        for name, (key_var, url_var, model_var) in _PROVIDERS.items()
    ]


def llm_provider_status() -> dict:
    providers = configured_llm_providers()
    preferred = (os.getenv("LLM_PROVIDER") or "").strip().lower() or None
    ready = [provider for provider in providers if provider.ready]
    selected = next(
        (provider for provider in ready if provider.name == preferred), None
    )
    if selected is None and preferred is None and len(ready) == 1:
        selected = ready[0]
    return {
        "preferred_provider": preferred,
        "selected_provider": selected.name if selected else None,
        "ready": selected is not None,
        "selection_error": (
            None
            if selected is not None
            else "preferred_provider_not_ready"
            if preferred
            else "provider_ambiguous"
            if not preferred and len(ready) > 1
            else "model_missing"
            if any(p.api_key and p.base_url and not p.model for p in providers)
            else "provider_not_configured"
            if not ready
            else None
        ),
        "providers": [
            {
                "name": provider.name,
                "api_key_configured": bool(provider.api_key),
                "base_url_configured": bool(provider.base_url),
                "model_configured": bool(provider.model),
                "ready": provider.ready,
            }
            for provider in providers
        ],
    }


def activate_llm_provider() -> dict:
    """仅在 provider 完整且选择唯一时投影到旧 LLM_* 消费接口。"""
    status = llm_provider_status()
    selected_name = status["selected_provider"]
    if not selected_name:
        return status
    provider = next(
        item for item in configured_llm_providers() if item.name == selected_name
    )
    os.environ["LLM_API_KEY"] = provider.api_key
    os.environ["LLM_BASE_URL"] = provider.base_url
    os.environ["LLM_MODEL"] = provider.model
    return status
