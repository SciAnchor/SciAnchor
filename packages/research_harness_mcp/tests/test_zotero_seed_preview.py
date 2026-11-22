"""Focused tests for Zotero seed preview helper extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


class _DbContext:
    def __init__(self, conn: object = "conn") -> None:
        self.conn = conn

    def __enter__(self) -> object:
        return self.conn

    def __exit__(self, *_args: object) -> None:
        return None


def _body(message: str) -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": message,
            "item": {
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Seeds",
                "current_directory_path": "Root / Agent Seeds",
            },
        }
    )


def test_zotero_seed_preview_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_seed_preview

    assert (
        http_api._zotero_seed_search_timeout_seconds
        is zotero_seed_preview.zotero_seed_search_timeout_seconds
    )
    assert (
        http_api._zotero_seed_candidate_preview
        is zotero_seed_preview.zotero_seed_candidate_preview
    )
    assert callable(zotero_seed_preview.prepare_zotero_seed_papers_action)
    assert callable(http_api._prepare_zotero_seed_papers_action)
    assert callable(zotero_seed_preview.build_zotero_seed_papers_preview)
    assert callable(http_api._build_zotero_seed_papers_preview)


def test_zotero_seed_search_timeout_uses_default_invalid_and_clamped_values(
    monkeypatch,
):
    from research_harness_mcp import zotero_seed_preview

    env_name = "RESEARCH_HARNESS_ZOTERO_SEED_SEARCH_TIMEOUT_SECONDS"
    monkeypatch.delenv(env_name, raising=False)
    assert zotero_seed_preview.zotero_seed_search_timeout_seconds() == 18.0

    monkeypatch.setenv(env_name, "bad")
    assert zotero_seed_preview.zotero_seed_search_timeout_seconds() == 18.0

    monkeypatch.setenv(env_name, "1")
    assert zotero_seed_preview.zotero_seed_search_timeout_seconds() == 3.0

    monkeypatch.setenv(env_name, "120")
    assert zotero_seed_preview.zotero_seed_search_timeout_seconds() == 60.0

    monkeypatch.setenv(env_name, "12.5")
    assert zotero_seed_preview.zotero_seed_search_timeout_seconds() == 12.5


def test_zotero_seed_candidate_preview_formats_and_truncates_fields():
    from research_harness_mcp import zotero_seed_preview

    candidate = {
        "title": "",
        "authors": ["A", " ", "B", "C", "D", "E", "F", "G", "H", "I"],
        "year": 2026,
        "venue": None,
        "doi": 123,
        "arxiv_id": "2401.00001",
        "url": "https://example.invalid/paper",
        "snippet": "x" * 900,
        "abstract": "abstract should be ignored when snippet exists",
        "citation_count": 42,
    }

    preview = zotero_seed_preview.zotero_seed_candidate_preview(
        candidate,
        source="doi:10.1234/demo",
    )

    assert preview == {
        "title": "Untitled",
        "authors": ["A", "B", "C", "D", "E", "F", "G"],
        "year": 2026,
        "venue": "",
        "doi": "123",
        "arxiv_id": "2401.00001",
        "url": "https://example.invalid/paper",
        "source": "doi:10.1234/demo",
        "snippet": "x" * 800,
        "citation_count": 42,
    }


def test_zotero_seed_candidate_preview_coerces_scalar_authors_and_abstract():
    from research_harness_mcp import zotero_seed_preview

    preview = zotero_seed_preview.zotero_seed_candidate_preview(
        {
            "title": "Demo",
            "authors": "Single Author",
            "abstract": "abstract text",
        },
        source="arxiv:2401.00001",
    )

    assert preview["authors"] == ["Single Author"]
    assert preview["snippet"] == "abstract text"
    assert preview["source"] == "arxiv:2401.00001"


def test_prepare_zotero_seed_papers_action_ignores_non_seed_messages():
    from research_harness_mcp import zotero_seed_preview

    calls: list[dict[str, Any]] = []

    result = zotero_seed_preview.prepare_zotero_seed_papers_action(
        _body("请总结当前论文"),
        {"topic": {"id": 3}},
        looks_like_zotero_seed_search_request=lambda _message: False,
        zotero_explicit_seed_topic_name=lambda _message: "should-not-run",
        build_zotero_seed_papers_preview=lambda **kwargs: (
            calls.append(kwargs) or {"kind": "action_preview"}
        ),
    )

    assert result is None
    assert calls == []


def test_prepare_zotero_seed_papers_action_forwards_preview_arguments():
    from research_harness_mcp import zotero_seed_preview

    calls: list[dict[str, Any]] = []
    body = _body("为“agentic discovery”找 5 篇种子论文")
    matched = {"topic": {"id": 3, "name": "agentic discovery"}}

    result = zotero_seed_preview.prepare_zotero_seed_papers_action(
        body,
        matched,
        looks_like_zotero_seed_search_request=lambda _message: True,
        zotero_explicit_seed_topic_name=lambda _message: "agentic discovery",
        build_zotero_seed_papers_preview=lambda **kwargs: (
            calls.append(kwargs)
            or {
                "kind": "action_preview",
                "preview": {"topic_name": kwargs["topic_name"]},
            }
        ),
    )

    assert result == {
        "kind": "action_preview",
        "preview": {"topic_name": "agentic discovery"},
    }
    assert calls == [
        {
            "body": body,
            "matched": matched,
            "topic_name": "agentic discovery",
            "query": None,
            "requested_count": None,
            "request_flags": None,
        }
    ]


def test_build_zotero_seed_papers_preview_requires_concrete_directory():
    from research_harness_mcp import zotero_seed_preview

    body = ZoteroChatRequest.model_validate(
        {
            "message": "找种子论文",
            "item": {"current_directory_name": "Missing key"},
        }
    )
    calls: list[str] = []

    result = zotero_seed_preview.build_zotero_seed_papers_preview(
        body=body,
        matched={},
        get_db=lambda: calls.append("db") or _DbContext(),
        find_zotero_topic_by_name=lambda *_args: None,
        infer_zotero_import_topic=lambda *_args: None,
        last_zotero_path_segment=lambda value: str(value).split("/")[-1].strip(),
        zotero_seed_search_query=lambda _body, *, topic_name: topic_name,
        extract_zotero_import_count=lambda _message: None,
        zotero_names_equal=lambda left, right: left == right,
        research_api_factory=lambda: calls.append("api") or object(),
        search_papers_impl=lambda *_args, **_kwargs: {"papers": []},
        seed_search_timeout_seconds=lambda: 3.0,
        pick_candidate_source=lambda candidate: str(candidate.get("doi") or ""),
        seed_candidate_preview=lambda candidate, *, source: {"source": source},
        zotero_api_library_id=lambda value, library_type: str(value or ""),
        zotero_seed_request_flags=lambda _message: {},
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result == {
        "kind": "assistant_message",
        "message": "要让 RH 为新目录找种子论文，请先在左侧选中一个具体 Zotero 目录。",
    }
    assert calls == []


def test_build_zotero_seed_papers_preview_reports_no_records_with_errors():
    from research_harness_mcp import zotero_seed_preview

    result = zotero_seed_preview.build_zotero_seed_papers_preview(
        body=_body("找 2 篇种子论文"),
        matched={},
        get_db=lambda: _DbContext(),
        find_zotero_topic_by_name=lambda *_args: None,
        infer_zotero_import_topic=lambda *_args: None,
        last_zotero_path_segment=lambda value: str(value).split("/")[-1].strip(),
        zotero_seed_search_query=lambda _body, *, topic_name: f"query:{topic_name}",
        extract_zotero_import_count=lambda _message: 2,
        zotero_names_equal=lambda left, right: left == right,
        research_api_factory=lambda: object(),
        search_papers_impl=lambda *_args, **_kwargs: {
            "papers": [{"title": "No source"}],
            "provider_errors": ["rate limited"],
        },
        seed_search_timeout_seconds=lambda: 3.0,
        pick_candidate_source=lambda _candidate: "",
        seed_candidate_preview=lambda candidate, *, source: {"source": source},
        zotero_api_library_id=lambda value, library_type: str(value or ""),
        zotero_seed_request_flags=lambda _message: {},
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result == {
        "kind": "assistant_message",
        "message": (
            "我还没有为“Root / Agent Seeds”找到可用的种子论文。你可以换一个更具体的关键词。"
            "\n\n检索错误：rate limited"
        ),
    }


def test_build_zotero_seed_papers_preview_builds_preview_payload():
    from research_harness_mcp import zotero_seed_preview

    search_calls: list[dict[str, Any]] = []
    finalize_calls: list[dict[str, Any]] = []
    body = _body("找 9 篇种子论文")

    def fake_search(api: object, **kwargs: Any) -> dict[str, Any]:
        search_calls.append({"api": api, **kwargs})
        return {
            "papers": [
                {"title": "One", "doi": "10.1/one"},
                {"title": "Duplicate", "doi": "10.1/one"},
                {"title": "Two", "arxiv_id": "2401.00002"},
                {"title": "No source"},
            ]
        }

    def finalize(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        finalize_calls.append({"payload": payload, "kwargs": kwargs})
        return {**payload, "finalized": kwargs}

    result = zotero_seed_preview.build_zotero_seed_papers_preview(
        body=body,
        matched={"source": "directory"},
        topic_name="agentic discovery",
        query="",
        requested_count=9,
        request_flags={"include_pdf": True, "deep_read": False},
        get_db=lambda: _DbContext("db-conn"),
        find_zotero_topic_by_name=lambda conn, name: {
            "id": 7,
            "name": f"{name}:{conn}",
        },
        infer_zotero_import_topic=lambda *_args: None,
        last_zotero_path_segment=lambda value: str(value).split("/")[-1].strip(),
        zotero_seed_search_query=lambda _body, *, topic_name: f"query:{topic_name}",
        extract_zotero_import_count=lambda _message: 5,
        zotero_names_equal=lambda left, right: left == right,
        research_api_factory=lambda: "research-api",
        search_papers_impl=fake_search,
        seed_search_timeout_seconds=lambda: 3.0,
        pick_candidate_source=lambda candidate: str(
            candidate.get("doi") or candidate.get("arxiv_id") or ""
        ),
        seed_candidate_preview=lambda candidate, *, source: {
            "title": candidate["title"],
            "source": source,
        },
        zotero_api_library_id=lambda value, library_type: f"api-{library_type}-{value}",
        zotero_seed_request_flags=lambda _message: {"unused": True},
        finalize_zotero_action_preview=finalize,
    )

    assert result is not None
    assert result["kind"] == "action_preview"
    preview = result["preview"]
    assert preview["action_type"] == "zotero_seed_paper_search"
    assert preview["query"] == "agentic discovery"
    assert preview["topic_id"] == 7
    assert preview["topic_name"] == "agentic discovery"
    assert preview["target_collection_key"] == "COLL1"
    assert preview["parent_collection_key"] == "COLL1"
    assert preview["target_collection_path"] == "Root / Agent Seeds / agentic discovery"
    assert preview["target_label"] == "Root / Agent Seeds / agentic discovery"
    assert preview["library_id"] == "api-user-None"
    assert preview["library_type"] == "user"
    assert preview["target_is_topic_collection"] is False
    assert preview["planned_count"] == 2
    assert preview["candidate_sources"] == ["10.1/one", "2401.00002"]
    assert preview["include_pdf"] is True
    assert preview["deep_read"] is False
    assert preview["records"] == [
        {"title": "One", "source": "10.1/one"},
        {"title": "Two", "source": "2401.00002"},
    ]
    assert preview["apply"]["payload"]["candidate_sources"] == [
        "10.1/one",
        "2401.00002",
    ]
    assert preview["apply"]["payload"]["target_is_topic_collection"] is False
    assert preview["apply"]["payload"]["dry_run"] is False
    assert search_calls == [
        {
            "api": "research-api",
            "query": "agentic discovery",
            "topic_id": 7,
            "max_results": 9,
        }
    ]
    assert finalize_calls[0]["kwargs"] == {
        "capability": "rh.zotero.prepare_seed_import",
        "target_source": "current_collection",
        "target_record_count": 2,
        "writable_count": 2,
        "undo_supported": False,
    }
