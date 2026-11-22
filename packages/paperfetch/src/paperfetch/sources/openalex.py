# -*- coding: utf-8 -*-
"""
openalex 模块
实现 OpenAlex 学术数据源适配器，支持游标分页检索、精确 DOI Lookup、倒排索引摘要重建与机构属性分析。
"""

import os
import re
import time
import uuid
import weakref
from paperfetch.observability import get_event_logger
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from paperfetch.sources.base import BaseMetadataSource
from paperfetch.sources.key_pool import (
    ApiKeyLease,
    ApiKeyPoolUnavailableError,
    PersistentApiKeyPool,
)
from paperfetch.core.models import (
    PaperRecord,
    AuthorRecord,
    SourceRef,
    OrganizationRecord,
    InstitutionSignal,
    FulltextStatus,
)
from paperfetch.utils.client import (
    _retry_after_seconds,
    global_rate_limiter,
)
from paperfetch.utils.cache import (
    CACHE_SCHEMA_VERSION,
    global_cache,
    metadata_cache_key,
)
from paperfetch.utils.normalizer import extract_pmcid_from_url, normalize_pmid

logger = get_event_logger("paperfetch.sources.openalex")

OPENALEX_CACHE_SCHEMA = f"{CACHE_SCHEMA_VERSION}:openalex-v1:work-core-v1"
OPENALEX_LOOKUP_TTL_SECONDS = 7 * 24 * 3600
OPENALEX_SEARCH_TTL_SECONDS = 24 * 3600
OPENALEX_NOT_FOUND_TTL_SECONDS = 6 * 3600
OPENALEX_RATE_LIMIT_COOLDOWN_SECONDS = 300.0


class OpenAlexAuthenticationError(RuntimeError):
    """OpenAlex 拒绝全部已配置 API Key。"""


def _openalex_api_keys() -> tuple[str, ...]:
    keys = []
    seen = set()
    for raw in (
        os.getenv("OPENALEX_API_KEYS") or "",
        os.getenv("OPENALEX_API_KEY") or "",
    ):
        for value in raw.replace(";", ",").split(","):
            key = value.strip().strip("'\"").strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return tuple(keys)


class OpenAlexTopicClassificationError(RuntimeError):
    """Sanitized topic-neighborhood failure without manuscript text."""


_TOPIC_REQUEST_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_TOPIC_FAILURE_UNTIL = 0.0
_TOPIC_CLASSIFIER_VERSION = "openalex-work-neighborhood-topics-v2"


def _topic_request_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _TOPIC_REQUEST_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _TOPIC_REQUEST_LOCKS[loop] = lock
    return lock


def _clean_env_value(name: str) -> str:
    """Normalize values inherited from legacy dotenv/shell quoting."""
    return str(os.getenv(name) or "").strip().strip("'\"").strip()


def _openalex_mailto() -> str:
    value = _clean_env_value("OPENALEX_MAILTO") or _clean_env_value("CROSSREF_MAILTO")
    return value if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else ""


def _location_pdf_url(location: Optional[Dict[str, Any]]) -> Optional[str]:
    if not location:
        return None
    pdf_url = location.get("pdf_url")
    return str(pdf_url).strip() if pdf_url else None


def _openalex_pdf_candidates(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按 OpenAlex 字段可靠性排序，返回去重后的 PDF/落地页候选。"""
    raw_candidates = [
        (
            "openalex_primary_location",
            _location_pdf_url(item.get("primary_location") or {}),
            10,
        ),
        (
            "openalex_best_oa_location",
            _location_pdf_url(item.get("best_oa_location") or {}),
            20,
        ),
    ]
    for loc in item.get("locations", []) or []:
        raw_candidates.append(("openalex_location", _location_pdf_url(loc), 30))
    oa_url = (item.get("open_access") or {}).get("oa_url")
    if oa_url:
        raw_candidates.append(("openalex_oa_url", str(oa_url).strip(), 40))

    candidates: List[Dict[str, Any]] = []
    seen = set()
    for source, url, priority in raw_candidates:
        if not url:
            continue
        key = str(url).strip()
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"url": key, "source": source, "priority": priority})
    return candidates


def _best_openalex_pdf_url(item: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """选择 OpenAlex 暴露的最高价值 PDF 直链。"""
    candidates = _openalex_pdf_candidates(item)
    if not candidates:
        return None, None
    return candidates[0]["url"], candidates[0]["source"]


def reconstruct_abstract(
    inverted_index: Optional[Dict[str, List[int]]],
) -> Optional[str]:
    """
    根据 OpenAlex 的倒排索引重建摘要文本。

    Args:
        inverted_index (Optional[Dict[str, List[int]]]): OpenAlex 的倒排索引字典。

    Returns:
        Optional[str]: 重建后的完整摘要文本，无输入或解析失败则返回 None。
    """
    if not inverted_index:
        return None
    try:
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        # 按位置升序排列
        word_positions.sort(key=lambda x: x[0])
        return " ".join([word for _, word in word_positions])
    except Exception as e:
        logger.warning(f"重建摘要时发生异常: {str(e)}")
        return None


def _normalized_title(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _topic_payload(raw: object) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    topic = raw.get("topic") if isinstance(raw.get("topic"), dict) else raw
    display_name = str(
        topic.get("display_name") or raw.get("display_name") or ""
    ).strip()
    topic_id = str(topic.get("id") or raw.get("id") or "").strip()
    if not display_name or not topic_id:
        return None
    try:
        score = float(raw.get("score") or topic.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "id": topic_id,
        "display_name": display_name,
        "score": max(0.0, min(1.0, score)),
        "subfield": topic.get("subfield") or raw.get("subfield") or {},
        "field": topic.get("field") or raw.get("field") or {},
        "domain": topic.get("domain") or raw.get("domain") or {},
    }


def _aggregate_work_neighborhood_topics(
    raw_works: List[Dict[str, Any]],
    *,
    manuscript_title: str,
    limit: int = 8,
    minimum_support: int = 2,
) -> List[Dict[str, Any]]:
    """Aggregate official Topics while retaining public-neighbor provenance."""
    manuscript_key = _normalized_title(manuscript_title)
    unique_works: List[Dict[str, Any]] = []
    seen_work_ids = set()
    for raw in raw_works:
        if not isinstance(raw, dict):
            continue
        work_id = str(raw.get("id") or "").strip()
        work_title = str(raw.get("title") or raw.get("display_name") or "").strip()
        if not work_id or work_id in seen_work_ids:
            continue
        # A previously indexed version of the submitted manuscript is not independent
        # evidence and must not become its own domain-classification neighbor.
        if manuscript_key and _normalized_title(work_title) == manuscript_key:
            continue
        seen_work_ids.add(work_id)
        unique_works.append(raw)

    grouped: Dict[str, Dict[str, Any]] = {}
    neighbor_count = len(unique_works)
    for rank, work in enumerate(unique_works, start=1):
        work_id = str(work.get("id") or "").strip()
        work_title = str(work.get("title") or work.get("display_name") or "").strip()
        try:
            relevance = float(work.get("relevance_score") or 0.0)
        except (TypeError, ValueError):
            relevance = 0.0
        raw_topics = list(work.get("topics") or [])
        if not raw_topics and work.get("primary_topic"):
            raw_topics = [work["primary_topic"]]
        per_work: Dict[str, Dict[str, Any]] = {}
        for topic_rank, raw_topic in enumerate(raw_topics, start=1):
            topic = _topic_payload(raw_topic)
            if not topic:
                continue
            if topic["score"] <= 0:
                topic["score"] = 1.0 if topic_rank == 1 else 1.0 / topic_rank
            current = per_work.get(topic["id"])
            if current is None or topic["score"] > current["score"]:
                per_work[topic["id"]] = topic
        for topic in per_work.values():
            bucket = grouped.setdefault(
                topic["id"],
                {
                    **topic,
                    "weighted_score": 0.0,
                    "topic_score_sum": 0.0,
                    "supporting_works": [],
                },
            )
            rank_weight = 1.0 / (1.0 + 0.20 * (rank - 1))
            bucket["weighted_score"] += rank_weight * topic["score"]
            bucket["topic_score_sum"] += topic["score"]
            bucket["supporting_works"].append(
                {
                    "work_id": work_id,
                    "title": work_title,
                    "rank": rank,
                    "relevance_score": relevance,
                    "topic_score": topic["score"],
                }
            )

    aggregated: List[Dict[str, Any]] = []
    for bucket in grouped.values():
        support_count = len(bucket["supporting_works"])
        if support_count < max(2, int(minimum_support)):
            continue
        support_ratio = support_count / max(1, neighbor_count)
        mean_topic_score = bucket["topic_score_sum"] / support_count
        confidence = min(1.0, 0.65 * support_ratio + 0.35 * mean_topic_score)
        aggregated.append(
            {
                "id": bucket["id"],
                "display_name": bucket["display_name"],
                "score": confidence,
                "subfield": bucket["subfield"],
                "field": bucket["field"],
                "domain": bucket["domain"],
                "support_count": support_count,
                "neighbor_count": neighbor_count,
                "supporting_works": bucket["supporting_works"],
                "classification_method": "work_neighborhood_consensus",
                "classifier_version": _TOPIC_CLASSIFIER_VERSION,
                "_weighted_score": bucket["weighted_score"],
            }
        )
    aggregated.sort(
        key=lambda item: (
            item["support_count"],
            item["_weighted_score"],
            item["score"],
        ),
        reverse=True,
    )
    for item in aggregated:
        item.pop("_weighted_score", None)
    return aggregated[: max(1, int(limit))]


class OpenAlexSource(BaseMetadataSource):
    """
    OpenAlexSource 学术检索源适配器

    对接 OpenAlex 官方 REST API 接口，实现大规模游标式文献召回、DOI 精准反查与相关引用数据抓取。
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limit_semaphore: Optional[asyncio.Semaphore] = None,
        key_pool: PersistentApiKeyPool | None = None,
    ):
        super().__init__(client, rate_limit_semaphore)
        self.base_url = "https://api.openalex.org"
        self.api_keys = _openalex_api_keys()
        self.key_pool = key_pool or (
            PersistentApiKeyPool(
                "openalex",
                self.api_keys,
                min_interval_seconds=float(
                    os.getenv("OPENALEX_MIN_INTERVAL_SECONDS") or 0.2
                ),
            )
            if self.api_keys
            else None
        )
        if not self.api_keys:
            logger.warning(
                "OpenAlex: 未配置 OPENALEX_API_KEYS/OPENALEX_API_KEY，正式查询将按匿名能力降级。"
            )

    @property
    def source_name(self) -> str:
        return "openalex"

    async def _request_reliably(
        self,
        method: str,
        url: str,
        *,
        params: Dict[str, Any] | None = None,
        headers: Dict[str, str] | None = None,
        max_attempts: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        temporary_failures = 0
        attempts = 0
        while True:
            attempts += 1
            lease: ApiKeyLease | None = None
            request_params = dict(params or {})
            try:
                if self.key_pool is not None:
                    lease = await self.key_pool.acquire()
                    request_params["api_key"] = lease.key
            except ApiKeyPoolUnavailableError as exc:
                raise OpenAlexAuthenticationError(
                    "OpenAlex 拒绝全部已配置 API Key"
                ) from exc

            try:
                if lease is None:
                    await global_rate_limiter.wait("openalex", 0.2)
                response = await self.client.request(
                    method, url, params=request_params, headers=headers, **kwargs
                )
            except asyncio.CancelledError:
                if lease is not None:
                    await self.key_pool.release(lease, "cancelled")
                raise
            except httpx.RequestError as exc:
                temporary_failures += 1
                if lease is not None:
                    delay = await self.key_pool.report_temporary_failure(
                        lease, type(exc).__name__
                    )
                else:
                    delay = min(60.0, float(2 ** min(6, temporary_failures - 1)))
                if max_attempts is not None and attempts >= max_attempts:
                    raise
                logger.warning("OpenAlex 临时网络错误，%.1f 秒后继续等待", delay)
                await asyncio.sleep(delay)
                continue

            status_code = response.status_code
            quota_limited = status_code == 429 or (
                status_code == 403
                and any(
                    marker in response.text.casefold()
                    for marker in (
                        "rate limit",
                        "rate-limit",
                        "too many requests",
                        "quota",
                    )
                )
            )
            if quota_limited:
                cooldown = _retry_after_seconds(response) or float(
                    os.getenv("OPENALEX_RATE_LIMIT_COOLDOWN_SECONDS")
                    or OPENALEX_RATE_LIMIT_COOLDOWN_SECONDS
                )
                if lease is not None:
                    await self.key_pool.report_rate_limit(lease, cooldown)
                if max_attempts is not None and attempts >= max_attempts:
                    return response
                if lease is None:
                    await asyncio.sleep(cooldown)
                logger.info("OpenAlex 当前请求受限，已进入内部冷却队列")
                continue
            if status_code in {401, 403} and lease is not None:
                await self.key_pool.report_auth_rejected(lease, f"http_{status_code}")
                if max_attempts is not None and attempts >= max_attempts:
                    return response
                logger.warning("OpenAlex 单个 API Key 被拒绝，已从当前调度周期停用")
                continue
            if status_code in {408, 500, 502, 503, 504}:
                temporary_failures += 1
                if lease is not None:
                    delay = await self.key_pool.report_temporary_failure(
                        lease, f"http_{status_code}"
                    )
                else:
                    delay = min(60.0, float(2 ** min(6, temporary_failures - 1)))
                if max_attempts is not None and attempts >= max_attempts:
                    return response
                await asyncio.sleep(delay)
                continue
            if lease is not None:
                await self.key_pool.report_success(lease, f"http_{status_code}")
            return response

    async def _cached_json(
        self,
        *,
        cache_key: str,
        url: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
        ttl_seconds: float,
        negative_ttl_seconds: float | None = None,
    ) -> tuple[int, Any | None]:
        entry = await global_cache.get_entry(
            cache_key, expected_schema=OPENALEX_CACHE_SCHEMA
        )
        if entry.state == "hit":
            return 200, entry.data
        if entry.state == "negative":
            return 404, None
        async with global_cache.request_lease(cache_key):
            entry = await global_cache.get_entry(
                cache_key, expected_schema=OPENALEX_CACHE_SCHEMA
            )
            if entry.state == "hit":
                return 200, entry.data
            if entry.state == "negative":
                return 404, None
            if self.semaphore:
                async with self.semaphore:
                    response = await self._request_reliably(
                        "GET", url, params=params, headers=headers
                    )
            else:
                response = await self._request_reliably(
                    "GET", url, params=params, headers=headers
                )
            if response.status_code == 404:
                if negative_ttl_seconds is not None:
                    await global_cache.set_not_found(
                        cache_key,
                        "openalex",
                        ttl_seconds=negative_ttl_seconds,
                        schema_version=OPENALEX_CACHE_SCHEMA,
                    )
                return 404, None
            response.raise_for_status()
            data = response.json()
            await global_cache.set(
                cache_key,
                data,
                "openalex",
                ttl_seconds=ttl_seconds,
                schema_version=OPENALEX_CACHE_SCHEMA,
            )
            return response.status_code, data

    def _get_headers_and_params(
        self, params: Optional[Dict[str, Any]] = None
    ) -> tuple[Dict[str, str], Dict[str, Any]]:
        """
        组装 OpenAlex 专有请求头与 Polite 请求参数。

        Args:
            params (Optional[Dict[str, Any]]): 原始请求参数。

        Returns:
            tuple[Dict[str, str], Dict[str, Any]]: 请求头与请求参数字典。
        """
        headers = {"User-Agent": "paperfetch/2.0"}
        res_params = params.copy() if params else {}

        return headers, res_params

    async def search(
        self,
        query: str,
        limit: int = 50,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> AsyncGenerator[PaperRecord, None]:
        """
        游标分页流式检索文献。

        Args:
            query (str): 检索关键词或检索式。
            limit (int): 最大返回文献数。
            year_from (Optional[int]): 起始年份过滤（含）。
            year_to (Optional[int]): 截止年份过滤（含）。

        Yields:
            PaperRecord: 统一规范化后的论文实体。
        """
        url = f"{self.base_url}/works"

        # 组装基础过滤器字符串，支持年份过滤注入
        # A comma separates OpenAlex filters; one inside the query splits it into a malformed
        # filter and the request fails with HTTP 400.
        filter_parts = [
            f"title_and_abstract.search:{' '.join(query.replace(',', ' ').split())}"
        ]
        if year_from:
            filter_parts.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filter_parts.append(f"to_publication_date:{year_to}-12-31")

        params = {
            "filter": ",".join(filter_parts),
            "per_page": min(limit, 50),
            "cursor": "*",  # 使用游标分页
        }

        headers, params = self._get_headers_and_params(params)
        retrieved_count = 0

        while retrieved_count < limit:
            cursor_val = params.get("cursor")
            logger.info(f"OpenAlex 正在检索分页: cursor={cursor_val}")

            cache_key = metadata_cache_key(
                "openalex",
                "search",
                f"{query}|{year_from}|{year_to}|{cursor_val}|{params['per_page']}",
                api_version="v1",
                fields_version="work-core-v1",
            )
            _status, data = await self._cached_json(
                cache_key=cache_key,
                url=url,
                params=params,
                headers=headers,
                ttl_seconds=OPENALEX_SEARCH_TTL_SECONDS,
            )

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                if retrieved_count >= limit:
                    break
                yield self._to_paper_record(
                    item, f"/works?filter=title_and_abstract.search:{query}"
                )
                retrieved_count += 1

            next_cursor = data.get("meta", {}).get("next_cursor")
            if not next_cursor or next_cursor == params.get("cursor"):
                break
            params["cursor"] = next_cursor

    async def classify_topics_from_work_neighborhood(
        self, title: str, abstract: str = "", *, limit: int = 8
    ) -> List[Dict[str, Any]]:
        """Infer Topics from independently indexed, semantically related OpenAlex works.

        The deprecated paid ``/text`` endpoint is deliberately not used. A hierarchy is
        returned only when at least two distinct neighboring works support the same
        official OpenAlex topic. Manuscript text is represented in cache/logs only by a
        SHA-256 digest and is never copied into exceptions or events.
        """
        clean_title = re.sub(r"\s+", " ", str(title or "")).strip()
        clean_abstract = re.sub(r"\s+", " ", str(abstract or "")).strip()
        normalized = f"{clean_title}\n{clean_abstract}".strip()
        if len(normalized) < 20:
            return []
        import hashlib

        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        strategy_limit = min(max(2, int(limit)), 20)
        neighbor_limit = min(25, max(8, strategy_limit * 2))
        cache_key = (
            f"openalex:work-neighborhood-topics:{content_hash}:"
            f"{_TOPIC_CLASSIFIER_VERSION}:{neighbor_limit}"
        )
        cached = await global_cache.get(cache_key)
        if cached is not None:
            return list(cached)[:limit]
        semantic_query = " ".join(
            value for value in (clean_title[:500], clean_abstract[:3_500]) if value
        )
        headers, params = self._get_headers_and_params(
            {
                "search.semantic": semantic_query,
                "per_page": neighbor_limit,
                "select": "id,title,display_name,primary_topic,topics,relevance_score",
            }
        )
        global _TOPIC_FAILURE_UNTIL
        request_lock = _topic_request_lock()
        await request_lock.acquire()
        try:
            if time.monotonic() < _TOPIC_FAILURE_UNTIL:
                raise OpenAlexTopicClassificationError(
                    "OpenAlex topic classification circuit is open"
                )
            topic_max_attempts = max(
                1, int(os.getenv("OPENALEX_TOPIC_MAX_ATTEMPTS", "2"))
            )
            response = await self._request_reliably(
                "GET",
                f"{self.base_url}/works",
                params=params,
                headers=headers,
                max_attempts=topic_max_attempts,
            )
            if response.is_error:
                raise OpenAlexTopicClassificationError(
                    f"OpenAlex work-neighborhood endpoint returned HTTP {response.status_code}"
                )
            data = response.json()
            topics = _aggregate_work_neighborhood_topics(
                data.get("results") or [],
                manuscript_title=clean_title,
                limit=strategy_limit,
            )
            await global_cache.set(cache_key, topics, "openalex")
            return topics
        except Exception as exc:
            status_code = (
                response.status_code
                if "response" in locals() and response is not None
                else None
            )
            _TOPIC_FAILURE_UNTIL = time.monotonic() + max(
                1.0, float(os.getenv("OPENALEX_TOPIC_FAILURE_COOLDOWN", "300"))
            )
            logger.warning(
                "OpenAlex 近邻主题分类降级，error_class=%s，status_code=%s",
                type(exc).__name__,
                status_code,
            )
            if isinstance(exc, OpenAlexTopicClassificationError):
                raise
            raise OpenAlexTopicClassificationError(
                f"OpenAlex topic classification failed: {type(exc).__name__}"
            ) from exc
        finally:
            request_lock.release()

    async def classify_text_topics(
        self, title: str, abstract: str = "", *, limit: int = 8
    ) -> List[Dict[str, Any]]:
        """Compatibility alias for the work-neighborhood classifier (never calls /text)."""
        return await self.classify_topics_from_work_neighborhood(
            title, abstract, limit=limit
        )

    async def search_in_journal(
        self,
        query: str,
        issn: str,
        *,
        limit: int = 5,
        year_from: Optional[int] = None,
    ) -> List[PaperRecord]:
        """Retrieve recent topic-matched works from one ISSN-identified journal."""
        clean_issn = re.sub(r"[^0-9Xx-]", "", str(issn or ""))
        if not clean_issn:
            return []
        filters = [
            f"primary_location.source.issn:{clean_issn}",
            f"title_and_abstract.search:{query}",
        ]
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        params = {
            "filter": ",".join(filters),
            "per_page": min(max(1, int(limit)), 25),
        }
        headers, params = self._get_headers_and_params(params)
        if self.semaphore:
            async with self.semaphore:
                response = await self._request_reliably(
                    "GET",
                    f"{self.base_url}/works",
                    params=params,
                    headers=headers,
                )
        else:
            response = await self._request_reliably(
                "GET",
                f"{self.base_url}/works",
                params=params,
                headers=headers,
            )
        return [
            self._to_paper_record(item, f"/works?filter=journal-issn:{clean_issn}")
            for item in response.json().get("results", [])[:limit]
        ]

    async def lookup(
        self, identifier: str, id_type: str = "doi"
    ) -> Optional[PaperRecord]:
        """
        根据唯一标识符精准反查论文。

        Args:
            identifier (str): 标识符值。
            id_type (str): 标识符类型 (doi, pmid, arxiv 等)。

        Returns:
            Optional[PaperRecord]: 补全后的论文实体，若未找到返回 None。
        """
        headers, params = self._get_headers_and_params()

        # 根据标识符类型拼装查询端点并规范化
        if id_type.lower() == "doi":
            clean_id = (
                identifier.replace("https://doi.org/", "")
                .replace("http://dx.doi.org/", "")
                .strip()
                .lower()
            )
            url = f"{self.base_url}/works/https://doi.org/{clean_id}"
        elif id_type.lower() == "pmid":
            clean_id = identifier.strip().lower()
            url = f"{self.base_url}/works/pmid:{clean_id}"
        elif id_type.lower() == "arxiv":
            clean_id = identifier.strip().lower()
            url = f"{self.base_url}/works/arxiv:{clean_id}"
        else:
            logger.warning(f"OpenAlex 不支持的 lookup 类型: {id_type}")
            return None

        cache_key = metadata_cache_key(
            "openalex",
            "lookup",
            f"{id_type.casefold()}:{clean_id}",
            api_version="v1",
            fields_version="work-core-v1",
        )
        logger.info(f"OpenAlex 正在根据 [{id_type}] 反查: {identifier}")
        status, data = await self._cached_json(
            cache_key=cache_key,
            url=url,
            params=params,
            headers=headers,
            ttl_seconds=OPENALEX_LOOKUP_TTL_SECONDS,
            negative_ttl_seconds=OPENALEX_NOT_FOUND_TTL_SECONDS,
        )
        return (
            self._to_paper_record(data, f"/works/{id_type}:{identifier}")
            if status == 200
            else None
        )

    async def get_references(self, paper: PaperRecord) -> List[PaperRecord]:
        # OpenAlex 用 referenced_by 过滤器查询该论文的参考文献。
        if not paper.openalex_id:
            logger.warning("get_references 失败: 论文缺少 openalex_id。")
            return []

        work_id = paper.openalex_id.split("/")[-1]
        url = f"{self.base_url}/works"
        params = {"filter": f"referenced_by:{work_id}", "per_page": 100}
        headers, params = self._get_headers_and_params(params)

        if self.semaphore:
            async with self.semaphore:
                response = await self._request_reliably(
                    "GET", url, params=params, headers=headers
                )
        else:
            response = await self._request_reliably(
                "GET", url, params=params, headers=headers
            )
        results = response.json().get("results", [])
        return [
            self._to_paper_record(item, f"/works?filter=referenced_by:{work_id}")
            for item in results
        ]

    async def get_citations(self, paper: PaperRecord) -> List[PaperRecord]:
        # OpenAlex 用 cites 过滤器查询引用该论文的文献。
        if not paper.openalex_id:
            logger.warning("get_citations 失败: 论文缺少 openalex_id。")
            return []

        work_id = paper.openalex_id.split("/")[-1]
        url = f"{self.base_url}/works"
        params = {"filter": f"cites:{work_id}", "per_page": 100}
        headers, params = self._get_headers_and_params(params)

        if self.semaphore:
            async with self.semaphore:
                response = await self._request_reliably(
                    "GET", url, params=params, headers=headers
                )
        else:
            response = await self._request_reliably(
                "GET", url, params=params, headers=headers
            )
        results = response.json().get("results", [])
        return [
            self._to_paper_record(item, f"/works?filter=cites:{work_id}")
            for item in results
        ]

    def _to_paper_record(
        self, item: Dict[str, Any], query_or_endpoint: str
    ) -> PaperRecord:
        """
        将 OpenAlex API 返回的原始 work JSON 数据转换为 PaperRecord。

        Args:
            item (Dict[str, Any]): OpenAlex 原始 work JSON。
            query_or_endpoint (str): 数据来源终端信息。

        Returns:
            PaperRecord: 统一的学术文献格式记录。
        """
        openalex_id = item.get("id")
        doi_raw = item.get("doi")

        # DOI 规范化
        doi = None
        if doi_raw:
            doi = (
                doi_raw.replace("https://doi.org/", "")
                .replace("http://dx.doi.org/", "")
                .strip()
                .lower()
            )

        title = item.get("title") or "Untitled Paper"
        year = item.get("publication_year")

        # 区分会议 (Conference) 与期刊 (Journal)
        venue = None
        journal = None
        primary_loc = item.get("primary_location") or {}
        source_info = primary_loc.get("source") or {}
        source_type = source_info.get("type")
        source_name = source_info.get("display_name")

        if source_type == "conference":
            venue = source_name
        else:
            journal = source_name

        # 作者及机构抽取
        authors: List[AuthorRecord] = []
        orgs: List[OrganizationRecord] = []
        has_uni = False
        has_corp = False
        has_res = False
        has_gov = False
        has_hosp = False

        for auth_info in item.get("authorships", []):
            author = auth_info.get("author") or {}
            author_name = author.get("display_name")
            if not author_name:
                continue
            orcid = author.get("orcid")

            affiliations = []
            for inst in auth_info.get("institutions", []):
                inst_name = inst.get("display_name")
                if inst_name:
                    affiliations.append(inst_name)
                    inst_type = inst.get("type", "unknown")

                    if inst_type == "education":
                        has_uni = True
                    elif inst_type == "company":
                        has_corp = True
                    elif inst_type in ["facility", "nonprofit"]:
                        has_res = True
                    elif inst_type == "government":
                        has_gov = True
                    elif inst_type == "healthcare":
                        has_hosp = True

                    orgs.append(
                        OrganizationRecord(
                            raw=inst_name,
                            normalized_name=inst_name,
                            type=inst_type,
                            source="openalex",
                            ror_id=inst.get("ror"),
                            country=inst.get("country_code"),
                        )
                    )

            authors.append(
                AuthorRecord(
                    name=author_name,
                    orcid=orcid,
                    affiliations=affiliations,
                    source="openalex",
                )
            )

        # 重建摘要文本
        abstract = reconstruct_abstract(item.get("abstract_inverted_index"))

        citation_count = item.get("cited_by_count")
        referenced_works = item.get("referenced_works", [])
        reference_count = len(referenced_works)

        # 自动生成内部唯一 ID
        paper_id = f"spc:{uuid.uuid4()}"

        # 构造字段级溯源
        retrieved_at = datetime.now()
        source_refs = [
            SourceRef(
                source="openalex",
                source_record_id=openalex_id,
                field="title",
                value=str(title),
                retrieved_at=retrieved_at,
                query_or_endpoint=query_or_endpoint,
                confidence=0.99,
            ),
            SourceRef(
                source="openalex",
                source_record_id=openalex_id,
                field="year",
                value=str(year),
                retrieved_at=retrieved_at,
                query_or_endpoint=query_or_endpoint,
                confidence=0.99,
            ),
        ]
        if doi:
            source_refs.append(
                SourceRef(
                    source="openalex",
                    source_record_id=openalex_id,
                    field="doi",
                    value=str(doi),
                    retrieved_at=retrieved_at,
                    query_or_endpoint=query_or_endpoint,
                    confidence=1.0,
                )
            )

        # 封装机构分析信号
        inst_signals = InstitutionSignal(
            has_university_affiliation=has_uni,
            has_company_affiliation=has_corp,
            has_research_institute_affiliation=has_res,
            has_government_affiliation=has_gov,
            has_hospital_affiliation=has_hosp,
            has_industry_academic_collaboration=has_uni and has_corp,
            org_signal_confidence="medium",
            organizations=orgs,
        )

        # 尝试解析 arXiv ID
        arxiv_id = None
        for loc in item.get("locations", []):
            pdf_url = loc.get("pdf_url")
            if pdf_url and "arxiv.org" in pdf_url:
                parts = pdf_url.split("/pdf/")
                if len(parts) > 1:
                    arxiv_id = (
                        parts[1].replace(".pdf", "").split("v")[0].strip()
                    )  # 规范化去掉版本号
                    break

        # 提取 OA 状态信息，避免下游 FulltextStatus 永远为 unknown。
        # 优先使用结构化 PDF URL；OpenAlex open_access.oa_url 经常只是 landing page。
        oa_info = item.get("open_access") or {}
        is_oa = oa_info.get("is_oa", False)
        pdf_candidates = _openalex_pdf_candidates(item)
        pdf_url = pdf_candidates[0]["url"] if pdf_candidates else None
        pdf_source = pdf_candidates[0]["source"] if pdf_candidates else None
        pmcid_urls = [
            (item.get("open_access") or {}).get("oa_url"),
            *(
                value
                for location in [
                    item.get("primary_location") or {},
                    item.get("best_oa_location") or {},
                    *(item.get("locations") or []),
                ]
                for value in (
                    location.get("landing_page_url"),
                    location.get("pdf_url"),
                )
            ),
            *(candidate.get("url") for candidate in pdf_candidates),
        ]
        pmcid = next(
            (
                extracted
                for candidate_url in pmcid_urls
                if (extracted := extract_pmcid_from_url(candidate_url))
            ),
            None,
        )
        ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        pubmed_id = normalize_pmid(ids.get("pmid"))
        if pmcid:
            source_refs.append(
                SourceRef(
                    source="openalex",
                    source_record_id=openalex_id,
                    field="pmc_id",
                    value=pmcid,
                    retrieved_at=retrieved_at,
                    query_or_endpoint=query_or_endpoint,
                    confidence=0.99,
                )
            )
        if pubmed_id:
            source_refs.append(
                SourceRef(
                    source="openalex",
                    source_record_id=openalex_id,
                    field="pubmed_id",
                    value=pubmed_id,
                    retrieved_at=retrieved_at,
                    query_or_endpoint=query_or_endpoint,
                    confidence=0.99,
                )
            )
        fulltext_status = FulltextStatus(
            oa_status="open" if is_oa else "closed",
            pdf_url=pdf_url,
            pdf_source=pdf_source,
            pdf_candidates=pdf_candidates,
        )

        return PaperRecord(
            paper_id=paper_id,
            doi=doi,
            openalex_id=openalex_id,
            title=title,
            year=year,
            venue=venue,
            journal=journal,
            authors=authors,
            abstract=abstract,
            openalex_topics=[
                {
                    "id": topic.get("id"),
                    "display_name": topic.get("display_name") or "",
                    "score": float(topic.get("score") or 0.0),
                    "subfield": topic.get("subfield") or {},
                    "field": topic.get("field") or {},
                    "domain": topic.get("domain") or {},
                }
                for topic in item.get("topics", []) or []
            ],
            citation_count=citation_count,
            reference_count=reference_count,
            source_refs=source_refs,
            institution_signals=inst_signals,
            arxiv_id=arxiv_id,
            pubmed_id=pubmed_id,
            pmc_id=pmcid,
            fulltext_status=fulltext_status,
        )

    async def fetch_source_details(
        self, identifier: str, id_type: str = "issn"
    ) -> Optional[Dict[str, Any]]:
        """
        通过 ISSN 或 OpenAlex Source ID 精准拉取期刊/来源的权威元数据。

        调用 OpenAlex /sources 端点，获取如下关键字段：
        - h_index: 期刊 H 指数
        - two_year_mean_citedness: 即时影响因子（2年均引率）
        - apc_usd: 文章处理费（美元计价）
        - x_concepts: 官方学科概念标签列表（含权重）
        - works_count / cited_by_count: 总发文量与总被引量
        - publisher: 出版商名称
        - counts_by_year: 按年统计的发文量与被引量

        Args:
            identifier (str): ISSN (如 "1234-5678") 或 OpenAlex Source ID (如 "S12345678")。
            id_type (str): 标识符类型，可选 "issn" 或 "openalex_id"。

        Returns:
            Optional[Dict[str, Any]]: 标准化后的期刊元数据字典，失败时返回 None。
        """
        if not identifier or not identifier.strip():
            logger.warning("fetch_source_details: 传入的标识符为空。")
            return None

        identifier = identifier.strip()

        # 根据类型构造查询方式
        if id_type == "issn":
            # ISSN 精确过滤查询，确保实体对齐的唯一性
            cache_key = f"openalex:source_detail:issn:{identifier.upper()}"
            url = f"{self.base_url}/sources"
            headers, params = self._get_headers_and_params(
                {"filter": f"issn:{identifier}", "per_page": "1"}
            )
        elif id_type == "openalex_id":
            # OpenAlex ID 直接查询
            source_id = (
                identifier if identifier.startswith("S") else identifier.split("/")[-1]
            )
            cache_key = f"openalex:source_detail:id:{source_id}"
            url = f"{self.base_url}/sources/{source_id}"
            headers, params = self._get_headers_and_params()
        else:
            logger.warning(f"fetch_source_details: 不支持的 id_type: {id_type}")
            return None

        # 优先命中本地缓存
        cached = await global_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"OpenAlex Source 详情命中本地缓存: {id_type}={identifier}")
            return cached

        try:
            if self.semaphore:
                async with self.semaphore:
                    response = await self._request_reliably(
                        "GET", url, params=params, headers=headers
                    )
            else:
                response = await self._request_reliably(
                    "GET", url, params=params, headers=headers
                )

            if response.status_code != 200:
                logger.info(
                    f"OpenAlex Source 查询返回状态码 {response.status_code}: {id_type}={identifier}"
                )
                return None

            payload = response.json()

            # ISSN 过滤查询返回 results 数组，直接 ID 查询返回单个对象
            if id_type == "issn":
                results = payload.get("results", [])
                if not results:
                    logger.info(f"OpenAlex 未找到 ISSN={identifier} 对应的期刊记录。")
                    return None
                source_data = results[0]
            else:
                source_data = payload

            # 提取 APC 信息（文章处理费）
            apc_usd = None
            apc_list = source_data.get("apc_usd") or source_data.get("apc_prices", [])
            if isinstance(apc_list, (int, float)):
                apc_usd = int(apc_list)
            elif isinstance(apc_list, list) and apc_list:
                # 取 USD 价格，若无则取第一个
                for apc_entry in apc_list:
                    if (
                        isinstance(apc_entry, dict)
                        and apc_entry.get("currency") == "USD"
                    ):
                        apc_usd = apc_entry.get("price")
                        break
                if apc_usd is None and isinstance(apc_list[0], dict):
                    apc_usd = apc_list[0].get("price")

            # 提取学科分类信息
            # OpenAlex 新版 API 已弃用 x_concepts，改用 topics + topic_share
            # 兼容策略：优先使用 topics（层级更丰富），退化到 x_concepts 兜底
            x_concepts = []
            topics_raw = source_data.get("topics", []) or []
            if topics_raw:
                # 新版 topics 字段：包含 topic/subfield/field/domain 层级
                for topic in topics_raw:
                    if isinstance(topic, dict) and topic.get("display_name"):
                        x_concepts.append(
                            {
                                "name": topic["display_name"],
                                "score": topic.get(
                                    "count", 0
                                ),  # topics 用 count 代替 score
                                "level": 0,
                                "id": topic.get("id", ""),
                                "subfield": (topic.get("subfield") or {}).get(
                                    "display_name", ""
                                ),
                                "field": (topic.get("field") or {}).get(
                                    "display_name", ""
                                ),
                                "domain": (topic.get("domain") or {}).get(
                                    "display_name", ""
                                ),
                            }
                        )
            else:
                # 旧版 x_concepts 兜底
                for concept in source_data.get("x_concepts", []) or []:
                    if isinstance(concept, dict) and concept.get("display_name"):
                        x_concepts.append(
                            {
                                "name": concept["display_name"],
                                "score": concept.get("score", 0),
                                "level": concept.get("level", 0),
                                "id": concept.get("id", ""),
                            }
                        )

            # 提取 ISSN 列表
            issn_list = source_data.get("issn", []) or []

            # 构造标准化结果
            summary_stats = source_data.get("summary_stats", {}) or {}
            result = {
                "openalex_id": source_data.get("id"),
                "display_name": source_data.get("display_name", ""),
                "publisher": source_data.get("publisher")
                or source_data.get("host_organization_name", ""),
                "issn": issn_list,
                "type": source_data.get("type", ""),
                "homepage_url": source_data.get("homepage_url"),
                "h_index": summary_stats.get("h_index"),
                "two_year_mean_citedness": summary_stats.get("2yr_mean_citedness"),
                "i10_index": summary_stats.get("i10_index"),
                "works_count": source_data.get("works_count"),
                "cited_by_count": source_data.get("cited_by_count"),
                "apc_usd": apc_usd,
                "is_oa": source_data.get("is_oa", False),
                "x_concepts": x_concepts,
                "counts_by_year": source_data.get("counts_by_year", []),
                "country_code": source_data.get("country_code"),
            }

            # 写入本地缓存
            await global_cache.set(cache_key, result, "openalex")
            logger.info(
                f"OpenAlex Source 详情获取成功: {id_type}={identifier}, "
                f"Name={result['display_name']}, H-index={result['h_index']}, "
                f"2yr-IF={result['two_year_mean_citedness']}"
            )
            return result

        except OpenAlexAuthenticationError:
            raise
        except Exception as e:
            logger.error(f"OpenAlex Source 详情查询异常 ({id_type}={identifier}): {e}")
            return None
