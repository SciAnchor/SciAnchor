from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from research_harness.storage.db import Database


def _suite_preflight():
    import sys

    root = Path(__file__).resolve().parents[3]
    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import suite_preflight

    return suite_preflight, root


def pytest_configure(config):
    """E1 (2026-09-28): refuse a suite whose cwd, fixtures or db path would waste the run.

    RH suites run from the package directory (cwd import precedence), not the repo root.
    The check runs before the worker copy: a worker rewrites RESEARCH_HARNESS_DB_PATH,
    and a check that runs after that sees the copy and lets the live pool through.
    """
    suite_preflight, _root = _suite_preflight()
    suite_preflight.refuse_bad_suite_run(Path(__file__).resolve().parents[1])
    suite_preflight.copy_worker_db()


@pytest.fixture(autouse=True)
def _isolate_process_environment(monkeypatch):
    """Keep full-suite runs from reading a developer's local RH/API state."""
    for name in (
        "RESEARCH_HARNESS_DB_PATH",
        "RESEARCH_HUB_DB_PATH",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CURSOR_AGENT_ENABLED",
        "CODEX_ENABLED",
        "LLM_PROVIDER",
        "RESEARCH_HARNESS_ADVERSARIAL_BACKEND",
        "GOOGLE_SCHOLAR_API_URL",
        "OPENALEX_API_KEY",
        "OPENREVIEW_ENABLE",
        "SEMANTIC_SCHOLAR_API_KEY",
        "PUBMED_API_KEY",
        "PUBMED_EMAIL",
        "PUBMED_ENABLE",
        "PUBMED_TOOL",
        "PASA_ENABLE",
        # CLI invocations inside tests run load_env_files, which imports the
        # developer's ~/.config/research-harness/private.env into os.environ
        # for the rest of the process; clear the illustration-backend surface
        # so later tests never inherit a machine-local provider config
        # (figure_image_generation_ready() treats any of these keys as ready).
        "GOOGLE_API_KEY",
        "GROK_API_KEY",
        "GROK_BASE_URL",
        "GPT_IMAGE_API_KEY",
        "GPT_IMAGE_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    # Readiness probes now self-load default env files (env_bootstrap), so
    # tests must disable the autoload or a developer's private.env/Keychain
    # would leak back in right after the delenv above.
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    # Agentic trace hunt defaults ON in production; tests enable it
    # explicitly with an injected fake chat.
    monkeypatch.setenv("RESEARCH_HARNESS_DREAM_TRACE_HUNT", "0")
    from research_harness import env_bootstrap

    env_bootstrap.reset_ensure_cache_for_tests()


@pytest.fixture(autouse=True)
def _no_external_providers(monkeypatch):
    """Prevent real HTTP calls to search providers in all tests."""
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [],
    )


@pytest.fixture(autouse=True)
def _keyless_sources_offline(monkeypatch):
    """Keyless public sources are real provider objects in tests, but they never
    reach the network unless a test hands them its own fetcher."""
    from research_harness import paper_source_clients

    build = paper_source_clients._keyless_provider

    def offline(url, headers):
        raise ConnectionError(f"network disabled in tests: {url.split('?')[0]}")

    def keyless_provider(name, fetcher):
        provider = build(name, fetcher)
        if fetcher is None:
            provider._fetcher = offline
        return provider

    monkeypatch.setattr(paper_source_clients, "_keyless_provider", keyless_provider)
    # Refused requests would otherwise open a shared breaker for later tests.
    from research_harness._core.core.circuit_breaker import reset_all_breakers

    reset_all_breakers()
    yield
    reset_all_breakers()


@pytest.fixture
def spc_no_results(monkeypatch):
    """SPC answers but finds nothing, without spawning the ``spc`` CLI.

    Paper search and ingest fail closed when SPC is unavailable (AGENTS.md:
    no silent fallback to direct APIs). Tests of local-pool behavior opt in to
    this fixture so they neither need SPC installed nor query the real service.
    """
    from research_harness.acquisition import spc_bridge

    def no_results(operation):
        def answer(*_args, errors=None, **_kwargs):
            if errors is not None:
                errors.append("spc: no_results")
            raise spc_bridge.SPCAcquisitionError(
                operation, {"error": {"code": "no_results"}}
            )

        return answer

    monkeypatch.setattr(spc_bridge, "spc_search", no_results("search"))
    monkeypatch.setattr(spc_bridge, "spc_lookup", no_results("lookup"))


@pytest.fixture(autouse=True)
def _no_external_adversarial_review(monkeypatch):
    """Make missing reviewer mocks fail closed instead of spawning an agent."""
    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch._run_automated_adversarial",
        lambda proposal: {
            "verdict": "revise",
            "issues": [
                {
                    "category": "review_unavailable",
                    "severity": "critical",
                    "description": "external adversarial review disabled in tests",
                }
            ],
            "summary": "external adversarial review disabled in tests",
        },
    )


@pytest.fixture(autouse=True)
def _disable_topic_workspace_materialization(monkeypatch):
    """Keep CLI topic tests from writing to a user's real rh-workspace by default."""
    monkeypatch.setenv("RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION", "1")


@pytest.fixture(autouse=True)
def _stub_paperindex_llm_chat(monkeypatch):
    """Short-circuit paperindex's LLM chat calls in tests without a real
    provider. Returns deterministic JSON so the card-extraction path
    (``build_card`` → ``LLMClient.chat`` → ``PaperCard.from_dict``) runs
    end-to-end without network/LLM, keeping CLI tests exercising the real
    assembler and adapter code.

    Tests that patch ``LLMClient.chat`` themselves override this stub
    (monkeypatch order: test-local patch wins). Live-provider integration tests
    must opt into their own isolated test process; the default suite never
    inherits developer credentials or agent-mode configuration.
    """
    import json as _json
    from llm_router.client import LLMClient

    def _fake_chat(self, prompt, model=None, temperature=0.0):
        del self, prompt, model, temperature
        return _json.dumps(
            {
                "title": "Stubbed paper",
                "core_idea": "Stubbed core idea for test runs without an LLM provider.",
                "method_summary": "Stubbed method summary.",
                "key_results": ["stubbed result"],
                "evidence": [
                    {
                        "section": "summary",
                        "confidence": 0.9,
                        "snippet": "stubbed evidence",
                    }
                ],
            }
        )

    monkeypatch.setattr(LLMClient, "chat", _fake_chat)


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    return db


@pytest.fixture
def conn(db):
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    return CliRunner()
