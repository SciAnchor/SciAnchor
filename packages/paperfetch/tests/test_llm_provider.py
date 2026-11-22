from paperfetch.llm_provider import activate_llm_provider, llm_provider_status


def _clear(monkeypatch):
    for prefix in ("LLM", "GPT", "OPENROUTER", "QWEN"):
        for suffix in ("API_KEY", "API_URL", "BASE_URL", "MODEL", "PROVIDER"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


def test_provider_alias_requires_explicit_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("QWEN_API_KEY", "secret")
    monkeypatch.setenv("QWEN_API_URL", "https://example.invalid/v1")

    status = llm_provider_status()

    assert status["ready"] is False
    assert status["selection_error"] == "model_missing"
    assert status["providers"][3]["model_configured"] is False


def test_unique_complete_provider_projects_to_legacy_contract(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_API_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "verified-model")

    status = activate_llm_provider()

    assert status["selected_provider"] == "openrouter"
    assert status["ready"] is True
    assert __import__("os").environ["LLM_MODEL"] == "verified-model"


def test_multiple_ready_providers_require_explicit_selection(monkeypatch):
    _clear(monkeypatch)
    for provider in ("GPT", "QWEN"):
        monkeypatch.setenv(f"{provider}_API_KEY", "secret")
        monkeypatch.setenv(f"{provider}_API_URL", "https://example.invalid/v1")
        monkeypatch.setenv(f"{provider}_MODEL", "verified-model")

    status = llm_provider_status()

    assert status["ready"] is False
    assert status["selection_error"] == "provider_ambiguous"
