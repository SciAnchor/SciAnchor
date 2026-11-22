"""Preview helpers for Zotero seed paper search actions."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable


def zotero_seed_search_timeout_seconds() -> float:
    try:
        value = float(
            os.getenv("RESEARCH_HARNESS_ZOTERO_SEED_SEARCH_TIMEOUT_SECONDS", "18")
        )
    except ValueError:
        value = 18.0
    return max(3.0, min(value, 60.0))


def zotero_seed_candidate_preview(
    candidate: dict[str, Any], *, source: str
) -> dict[str, Any]:
    authors = candidate.get("authors") or []
    if not isinstance(authors, list):
        authors = [str(authors)]
    return {
        "title": str(candidate.get("title") or "Untitled"),
        "authors": [str(author) for author in authors[:8] if str(author).strip()],
        "year": candidate.get("year"),
        "venue": str(candidate.get("venue") or ""),
        "doi": str(candidate.get("doi") or ""),
        "arxiv_id": str(candidate.get("arxiv_id") or ""),
        "url": str(candidate.get("url") or ""),
        "source": source,
        "snippet": str(candidate.get("snippet") or candidate.get("abstract") or "")[
            :800
        ],
        "citation_count": candidate.get("citation_count"),
    }


def prepare_zotero_seed_papers_action(
    body: Any,
    matched: dict[str, Any],
    *,
    looks_like_zotero_seed_search_request: Callable[[str], bool],
    zotero_explicit_seed_topic_name: Callable[[str], str],
    build_zotero_seed_papers_preview: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    if not looks_like_zotero_seed_search_request(body.message):
        return None
    return build_zotero_seed_papers_preview(
        body=body,
        matched=matched,
        topic_name=zotero_explicit_seed_topic_name(body.message),
        query=None,
        requested_count=None,
        request_flags=None,
    )


def build_zotero_seed_papers_preview(
    *,
    body: Any,
    matched: dict[str, Any],
    topic_name: str = "",
    query: str | None = None,
    requested_count: int | None = None,
    request_flags: dict[str, bool] | None = None,
    get_db: Callable[[], Any],
    find_zotero_topic_by_name: Callable[[Any, str], dict[str, Any] | None],
    infer_zotero_import_topic: Callable[
        [Any, Any, dict[str, Any]], dict[str, Any] | None
    ],
    last_zotero_path_segment: Callable[[str], str],
    zotero_seed_search_query: Callable[..., str],
    extract_zotero_import_count: Callable[[str], int | None],
    zotero_names_equal: Callable[[str, str], bool],
    research_api_factory: Callable[[], Any],
    search_papers_impl: Callable[..., dict[str, Any]],
    seed_search_timeout_seconds: Callable[[], float],
    pick_candidate_source: Callable[[dict[str, Any]], str],
    seed_candidate_preview: Callable[..., dict[str, Any]],
    zotero_api_library_id: Callable[[Any, str], str],
    zotero_seed_request_flags: Callable[[str], dict[str, bool]],
    finalize_zotero_action_preview: Callable[..., dict[str, Any]],
    thread_pool_executor_cls: type[ThreadPoolExecutor] = ThreadPoolExecutor,
) -> dict[str, Any]:
    """Build a seed-paper preview from typed inputs plus current Zotero context."""

    directory_name = (
        body.item.current_directory_path or body.item.current_directory_name or ""
    ).strip()
    if not directory_name or not str(body.item.current_directory_key or "").strip():
        return {
            "kind": "assistant_message",
            "message": "要让 RH 为新目录找种子论文，请先在左侧选中一个具体 Zotero 目录。",
        }

    explicit_topic_name = str(topic_name or "").strip()
    with get_db() as conn:
        topic = (
            find_zotero_topic_by_name(conn, explicit_topic_name)
            if explicit_topic_name
            else infer_zotero_import_topic(conn, body, matched)
        )

    topic_id = int(topic["id"]) if topic and topic.get("id") is not None else None
    topic_name = explicit_topic_name or (
        str(topic.get("name") or "").strip()
        if topic
        else last_zotero_path_segment(directory_name)
        or body.item.current_directory_name
    )
    search_query = (
        zotero_seed_search_query(body, topic_name=topic_name)
        if query is None
        else str(query or "").strip()
        or topic_name
        or last_zotero_path_segment(directory_name)
        or body.item.current_directory_name
        or "research seed papers"
    )
    requested = (
        max(1, int(requested_count))
        if requested_count is not None
        else extract_zotero_import_count(body.message) or 5
    )
    max_results = max(1, min(requested, 12))
    target_is_current_collection = zotero_names_equal(
        last_zotero_path_segment(directory_name), topic_name
    )

    api = research_api_factory()
    search_timeout = seed_search_timeout_seconds()
    executor = thread_pool_executor_cls(max_workers=1)
    future = executor.submit(
        search_papers_impl,
        api,
        query=search_query,
        topic_id=topic_id,
        max_results=max_results,
    )
    try:
        search_out = future.result(timeout=search_timeout)
    except TimeoutError:
        future.cancel()
        return {
            "kind": "assistant_message",
            "message": (
                f"我开始用“{search_query}”为当前目录检索候选论文，但 "
                f"{search_timeout:g} 秒内没有返回结果。可以稍后重试，"
                "或换一个更具体的英文/论文关键词。"
            ),
        }
    except Exception as exc:
        return {
            "kind": "assistant_message",
            "message": f"我尝试为当前目录检索种子论文，但 paper_search 失败：{exc}",
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    raw_candidates = search_out.get("papers") or []
    records: list[dict[str, Any]] = []
    candidate_sources: list[str] = []
    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            continue
        source = pick_candidate_source(candidate)
        if not source or source in candidate_sources:
            continue
        candidate_sources.append(source)
        records.append(seed_candidate_preview(candidate, source=source))
        if len(records) >= max_results:
            break

    if not records:
        errors = search_out.get("provider_errors") or []
        suffix = f"\n\n检索错误：{'; '.join(map(str, errors))}" if errors else ""
        return {
            "kind": "assistant_message",
            "message": f"我还没有为“{directory_name}”找到可用的种子论文。你可以换一个更具体的关键词。{suffix}",
        }

    library_type = str(body.item.library_type or "user").strip() or "user"
    library_id = zotero_api_library_id(body.item.library_id, library_type)
    target_name = topic_name
    target_path = (
        directory_name
        if target_is_current_collection
        else f"{directory_name} / {topic_name}"
        if topic_name
        else directory_name
    )
    parent_collection_key = (
        "" if target_is_current_collection else body.item.current_directory_key
    )
    request_flags = (
        dict(request_flags)
        if request_flags is not None
        else zotero_seed_request_flags(body.message)
    )
    return {
        "kind": "action_preview",
        "preview": finalize_zotero_action_preview(
            {
                "action_type": "zotero_seed_paper_search",
                "title": "为当前目录找种子论文",
                "message": (
                    f"我用“{search_query}”为当前 Zotero 目录“{directory_name}”找到了 "
                    f"{len(records)} 篇候选种子论文。确认后会创建/复用 RH 主题，"
                    "在当前目录下创建/复用 topic 子目录，把这些论文入库并同步过去。"
                ),
                "query": search_query,
                "topic_id": topic_id,
                "topic_name": topic_name,
                "source_label": f"RH paper_search · {search_query}",
                "target_collection_key": body.item.current_directory_key,
                "parent_collection_key": parent_collection_key,
                "target_collection_name": target_name,
                "target_collection_path": target_path,
                "target_label": target_path,
                "library_id": library_id,
                "library_type": library_type,
                "target_is_topic_collection": target_is_current_collection,
                "planned_count": len(records),
                "candidate_sources": candidate_sources,
                **request_flags,
                "records": records,
                "notice": "这是空目录/新主题的启动流：先预览候选论文，再由确认动作写入 RH 与 Zotero。",
                "confirm_label": "入库并导入",
                "cancel_label": "取消",
                "list_label": "查看候选",
                "apply": {
                    "type": "zotero_local",
                    "handler": "zotero_seed_papers_apply",
                    "method": "POST",
                    "path": "/api/zotero/seed-papers/apply",
                    "label": "入库并导入",
                    "payload": {
                        "http_path": "/api/zotero/seed-papers/apply",
                        "query": search_query,
                        "topic_id": topic_id,
                        "topic_name": topic_name,
                        "topic_description": (
                            "Created from Zotero collection bootstrap.\n\n"
                            f"Initial query: {search_query}\n"
                            f"Collection: {directory_name}"
                        ),
                        "candidate_sources": candidate_sources,
                        "target_collection_key": body.item.current_directory_key,
                        "parent_collection_key": parent_collection_key,
                        "target_collection_name": target_name,
                        "target_collection_path": target_path,
                        "library_id": library_id,
                        "library_type": library_type,
                        "target_is_topic_collection": target_is_current_collection,
                        **request_flags,
                        "dry_run": False,
                    },
                },
            },
            capability="rh.zotero.prepare_seed_import",
            target_source="current_collection",
            target_record_count=len(records),
            writable_count=len(records),
            undo_supported=False,
        ),
    }
