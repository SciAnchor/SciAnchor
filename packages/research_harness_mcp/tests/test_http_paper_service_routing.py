from __future__ import annotations

from pathlib import Path


def test_http_paper_search_wrapper_uses_service_backed_python_facade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.api import ResearchAPI
    from research_harness.service import ServiceResult
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={"papers": [{"title": "Service Search"}]},
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = ResearchAPI(db_path=tmp_path / "http-paper-search.db")

    assert http_api._search_papers_impl(
        api,
        query="graph agents",
        topic_id=7,
        max_results=12,
    ) == {"papers": [{"title": "Service Search"}]}
    assert calls == [
        ("paper_search", {"query": "graph agents", "topic_id": 7, "max_results": 12})
    ]


def test_http_paper_ingest_wrapper_uses_service_backed_python_facade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.api import ResearchAPI
    from research_harness.service import ServiceResult
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={"paper_id": 99, "title": "Service Ingest"},
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = ResearchAPI(db_path=tmp_path / "http-paper-ingest.db")

    assert http_api._ingest_paper_impl(
        api,
        source="10.1000/http",
        topic_id=7,
        relevance="high",
    ) == {"paper_id": 99, "title": "Service Ingest"}
    assert calls == [
        (
            "paper_ingest",
            {"source": "10.1000/http", "relevance": "high", "topic_id": 7},
        )
    ]
