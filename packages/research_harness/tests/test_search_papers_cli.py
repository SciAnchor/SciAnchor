from __future__ import annotations

import json

from research_harness.cli import main
from research_harness.paper_source_clients import ProviderSpec
from research_harness.paper_sources import PDFCandidate, PaperRecord


class StubProvider:
    def __init__(self, name: str, records: list[PaperRecord]):
        self.name = name
        self._records = records

    def search(self, query):
        return list(self._records)


def test_search_sciverse_cli_routes_through_spc(runner, monkeypatch):
    """Sciverse semantic retrieval is an SPC lane, not a direct client call."""
    import shutil
    import subprocess
    from types import SimpleNamespace

    calls = []
    payload = {"status": "completed", "data": {"hits": [{"title": "rag", "score": 4}]}}

    def run(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(payload), returncode=0)

    monkeypatch.setattr(shutil, "which", lambda name: "/trusted/spc")
    monkeypatch.setattr(subprocess, "run", run)

    result = runner.invoke(
        main, ["--json", "search", "sciverse", "--query", "rag", "--top-k", "4"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload
    assert calls == [
        [
            "/trusted/spc",
            "paper",
            "sciverse",
            "--output-format",
            "json",
            "--query",
            "rag",
            "--top-k",
            "4",
        ]
    ]


def test_search_sciverse_cli_fails_closed_without_spc(runner, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = runner.invoke(main, ["--json", "search", "sciverse", "--query", "rag"])
    assert result.exit_code != 0
    assert "SPC production unavailable" in result.output


def test_search_papers_returns_ranked_download_plan(runner, monkeypatch):
    def fake_build_provider_suite(fetcher=None):
        del fetcher
        return [
            StubProvider(
                "google_scholar",
                [
                    PaperRecord(
                        title="Attention Is All You Need",
                        provider="google_scholar",
                        year=2017,
                        pdf_candidates=[
                            PDFCandidate(
                                url="https://mirror.example/attention.pdf",
                                source_type="open_access_pdf",
                                provider="google_scholar",
                                confidence=0.8,
                            )
                        ],
                    )
                ],
            )
        ]

    monkeypatch.setattr(
        "research_harness.paper_source_clients.build_provider_suite",
        fake_build_provider_suite,
    )
    monkeypatch.setattr(
        "research_harness.paper_source_clients.available_provider_specs",
        lambda: [
            ProviderSpec(name="google_scholar", enabled=True, reason="configured")
        ],
    )

    result = runner.invoke(main, ["--json", "search", "papers", "--query", "attention"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["result_count"] == 1
    assert payload["provider_errors"] == []
    assert payload["results"][0]["title"] == "Attention Is All You Need"
    assert (
        payload["results"][0]["pdf_candidates"][0]["source_type"] == "open_access_pdf"
    )


def test_search_papers_can_log_run(runner, monkeypatch):
    runner.invoke(main, ["topic", "init", "demo"])

    monkeypatch.setattr(
        "research_harness.paper_source_clients.build_provider_suite",
        lambda fetcher=None: [
            StubProvider(
                "openalex", [PaperRecord(title="Paper A", provider="openalex")]
            )
        ],
    )
    monkeypatch.setattr(
        "research_harness.paper_source_clients.available_provider_specs",
        lambda: [ProviderSpec(name="openalex", enabled=True, reason="official api")],
    )

    query = "budget-test-search-log-run"
    result = runner.invoke(
        main, ["search", "papers", "--query", query, "--topic", "demo", "--log-run"]
    )

    assert result.exit_code == 0

    listed = runner.invoke(
        main, ["--json", "search", "list", "--provider", "multi-source", "--limit", "5"]
    )
    payload = json.loads(listed.output)
    assert payload[0]["query"] == query
    assert payload[0]["provider"] == "multi-source"


def test_search_papers_reports_provider_errors_but_returns_success(runner, monkeypatch):
    class FailingProvider:
        name = "openalex"

        def search(self, query):
            del query
            raise RuntimeError("upstream timeout")

    monkeypatch.setattr(
        "research_harness.paper_source_clients.build_provider_suite",
        lambda fetcher=None: [
            FailingProvider(),
            StubProvider(
                "semantic_scholar",
                [PaperRecord(title="Recovered Result", provider="semantic_scholar")],
            ),
        ],
    )
    monkeypatch.setattr(
        "research_harness.paper_source_clients.available_provider_specs",
        lambda: [
            ProviderSpec(name="openalex", enabled=True, reason="configured"),
            ProviderSpec(name="semantic_scholar", enabled=True, reason="configured"),
        ],
    )

    result = runner.invoke(main, ["--json", "search", "papers", "--query", "attention"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["result_count"] == 1
    assert payload["results"][0]["title"] == "Recovered Result"
    assert payload["provider_errors"][0]["provider"] == "openalex"
    assert payload["provider_errors"][0]["error_type"] == "RuntimeError"
