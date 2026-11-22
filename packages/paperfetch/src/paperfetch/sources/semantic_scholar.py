# -*- coding: utf-8 -*-
"""
semantic_scholar 模块
实现 Semantic Scholar (S2) 学术数据源适配器。支持多 Key 自动冷却轮换、字段按需请求与精准反查。
"""

import uuid
from paperfetch.observability import get_event_logger
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from paperfetch.sources.base import BaseMetadataSource
from paperfetch.sources.rotator import KeyRotator
from paperfetch.sources.s2_pool import (
    PersistentS2KeyPool,
    S2KeyLease,
    S2KeyPoolUnavailableError,
)
from paperfetch.core.models import (
    PaperRecord,
    AuthorRecord,
    SourceRef,
    InstitutionSignal,
    FulltextStatus,
)
from paperfetch.utils.client import global_rate_limiter
from paperfetch.utils.cache import (
    CACHE_SCHEMA_VERSION,
    global_cache,
    metadata_cache_key,
)
from paperfetch.sources.s2_config import get_semantic_scholar_config

logger = get_event_logger("paperfetch.sources.semantic_scholar")

S2_CACHE_SCHEMA = f"{CACHE_SCHEMA_VERSION}:s2-graph-v1:paper-core-v1"
S2_LOOKUP_TTL_SECONDS = 7 * 24 * 3600
S2_SEARCH_TTL_SECONDS = 24 * 3600
S2_GRAPH_TTL_SECONDS = 24 * 3600
S2_NOT_FOUND_TTL_SECONDS = 6 * 3600


class SemanticScholarRateLimitError(Exception):
    """兼容旧调用的显式限流异常；可靠调度不会把 429 暴露给业务层。"""

    def __init__(
        self, message: str, retry_after: Optional[float] = None, status_code: int = 429
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code


class SemanticScholarAuthenticationError(Exception):
    """Semantic Scholar rejected every configured API key with HTTP 403."""


class SemanticScholarSource(BaseMetadataSource):
    """
    SemanticScholarSource 学术检索源适配器

    对接 Semantic Scholar Graph API，支持基于多 Key 轮转的高可用数据抓取。
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limit_semaphore: Optional[asyncio.Semaphore] = None,
        rotator: Optional[KeyRotator] = None,
        key_pool: Optional[PersistentS2KeyPool] = None,
    ):
        super().__init__(client, rate_limit_semaphore)
        self.base_url = "https://api.semanticscholar.org/graph/v1"
        self.config = get_semantic_scholar_config()
        self.rotator = rotator
        self.key_pool = key_pool
        self.min_interval_with_key = self.config.min_interval_with_key
        self.min_interval_without_key = self.config.min_interval_without_key
        self.rate_limit_cooldown = self.config.rate_limit_cooldown

        if self.key_pool is None and self.rotator is None and self.config.api_keys:
            self.key_pool = PersistentS2KeyPool(
                self.config.api_keys,
                min_interval_seconds=self.min_interval_with_key,
            )

        # 默认请求的核心论文元数据字段，避免全量请求导致接口限流或效率低下
        self.default_fields = "title,abstract,authors,year,venue,journal,externalIds,citationCount,referenceCount,openAccessPdf,isOpenAccess"

    @property
    def source_name(self) -> str:
        return "semantic_scholar"

    async def _send_request_with_key_rotator(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """可靠执行请求；临时限流/网络/5xx 在内部排队，不伪装成空结果。"""

        url = f"{self.base_url}{path}"
        temporary_failures = 0
        rejected_rotator_keys = 0

        while True:
            lease: S2KeyLease | None = None
            current_key: str | None = None
            try:
                if self.key_pool is not None:
                    lease = await self.key_pool.acquire()
                    current_key = lease.key
                elif self.rotator is not None:
                    current_key = await self.rotator.get_key()
            except S2KeyPoolUnavailableError as exc:
                raise SemanticScholarAuthenticationError(
                    "Semantic Scholar API 拒绝全部已配置 key"
                ) from exc

            headers = {"User-Agent": "paperfetch/2.0"}
            if current_key:
                headers["x-api-key"] = current_key
            try:
                if not current_key:
                    await global_rate_limiter.wait(
                        "semantic_scholar", self.min_interval_without_key
                    )
                if self.semaphore:
                    async with self.semaphore:
                        response = await self.client.request(
                            method, url, params=params, headers=headers, **kwargs
                        )
                else:
                    response = await self.client.request(
                        method, url, params=params, headers=headers, **kwargs
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
                logger.warning("S2 临时网络错误，%.1f 秒后继续等待", delay)
                await asyncio.sleep(delay)
                continue

            status_code = response.status_code
            if status_code == 429 or (
                status_code == 403 and self._is_quota_response(response)
            ):
                cooldown = (
                    self._retry_after_seconds(response) or self.rate_limit_cooldown
                )
                if lease is not None:
                    await self.key_pool.report_rate_limit(lease, cooldown)
                elif self.rotator is not None and current_key:
                    await self.rotator.report_failure(
                        current_key, cooldown_duration=cooldown
                    )
                else:
                    await asyncio.sleep(cooldown)
                logger.info("S2 当前请求受限，已进入内部冷却队列")
                continue
            if status_code in {401, 403} and current_key:
                if lease is not None:
                    await self.key_pool.report_auth_rejected(
                        lease, f"http_{status_code}"
                    )
                elif self.rotator is not None:
                    rejected_rotator_keys += 1
                    await self.rotator.report_failure(
                        current_key, cooldown_duration=86400.0
                    )
                    if rejected_rotator_keys >= self.rotator.get_total_keys_count():
                        raise SemanticScholarAuthenticationError(
                            "Semantic Scholar API 拒绝全部已配置 key"
                        )
                logger.warning("S2 单个 API key 被拒绝，已从当前调度周期停用")
                continue
            if status_code in {500, 502, 503, 504}:
                temporary_failures += 1
                if lease is not None:
                    delay = await self.key_pool.report_temporary_failure(
                        lease, f"http_{status_code}"
                    )
                else:
                    delay = min(60.0, float(2 ** min(6, temporary_failures - 1)))
                logger.warning(
                    "S2 上游临时错误 HTTP %d，%.1f 秒后继续等待", status_code, delay
                )
                await asyncio.sleep(delay)
                continue
            if lease is not None:
                await self.key_pool.report_success(lease, f"http_{status_code}")
            if status_code >= 400 and status_code != 404:
                response.raise_for_status()
            return response

    async def _cached_json(
        self,
        *,
        cache_key: str,
        path: str,
        params: Dict[str, Any],
        ttl_seconds: float,
        negative_ttl_seconds: float | None = None,
    ) -> tuple[int, Any | None]:
        entry = await global_cache.get_entry(cache_key, expected_schema=S2_CACHE_SCHEMA)
        if entry.state == "hit":
            return 200, entry.data
        if entry.state == "negative":
            return 404, None
        async with global_cache.request_lease(cache_key):
            entry = await global_cache.get_entry(
                cache_key, expected_schema=S2_CACHE_SCHEMA
            )
            if entry.state == "hit":
                return 200, entry.data
            if entry.state == "negative":
                return 404, None
            response = await self._send_request_with_key_rotator(
                "GET", path, params=params
            )
            if response.status_code == 404:
                if negative_ttl_seconds is not None:
                    await global_cache.set_not_found(
                        cache_key,
                        "semantic_scholar",
                        ttl_seconds=negative_ttl_seconds,
                        schema_version=S2_CACHE_SCHEMA,
                    )
                return 404, None
            data = response.json()
            await global_cache.set(
                cache_key,
                data,
                "semantic_scholar",
                ttl_seconds=ttl_seconds,
                schema_version=S2_CACHE_SCHEMA,
            )
            return response.status_code, data
            response.raise_for_status()
        return response

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, IndexError, OverflowError):
                return None

    @staticmethod
    def _is_quota_response(response: httpx.Response) -> bool:
        text = response.text.casefold()
        return any(
            marker in text
            for marker in ("rate limit", "rate-limit", "too many requests", "quota")
        )

    async def search(
        self,
        query: str,
        limit: int = 50,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> AsyncGenerator[PaperRecord, None]:
        """
        检索学术文献。

        Args:
            query (str): 搜索 query。
            limit (int): 最大召回篇数。
            year_from (Optional[int]): 起始年份过滤（含）。
            year_to (Optional[int]): 截止年份过滤（含）。
        """
        path = "/paper/search"
        params = {
            "query": query,
            "limit": min(limit, 100),  # 单次分页最大限制 100
            "fields": self.default_fields,
        }

        # 行内注释：将 Brief 中的时间窗口约束翻译为 S2 原生的 year=YYYY-YYYY 过滤参数
        if year_from and year_to:
            params["year"] = f"{year_from}-{year_to}"
        elif year_from:
            params["year"] = f"{year_from}-"
        elif year_to:
            params["year"] = f"-{year_to}"

        retrieved_count = 0
        offset = 0

        while retrieved_count < limit:
            params["offset"] = offset
            logger.info(f"S2 正在检索分页: offset={offset}")

            cache_key = metadata_cache_key(
                "semantic_scholar",
                "search",
                f"{query}|{year_from}|{year_to}|{offset}|{params['limit']}",
                api_version="graph-v1",
                fields_version="paper-core-v1",
            )
            _status, data = await self._cached_json(
                cache_key=cache_key,
                path=path,
                params=params,
                ttl_seconds=S2_SEARCH_TTL_SECONDS,
            )

            results = data.get("data", [])
            if not results:
                break

            for item in results:
                if retrieved_count >= limit:
                    break
                yield self._to_paper_record(item, f"/paper/search?query={query}")
                retrieved_count += 1

            total = data.get("total", 0)
            offset += len(results)

            if offset >= total or len(results) == 0:
                break

    async def lookup(
        self, identifier: str, id_type: str = "doi"
    ) -> Optional[PaperRecord]:
        """
        精准查询单篇论文。
        """
        # 转换标识符为 S2 匹配的前缀格式
        if id_type.lower() == "doi":
            clean_doi = (
                identifier.replace("https://doi.org/", "")
                .replace("http://dx.doi.org/", "")
                .strip()
                .lower()
            )
            path = f"/paper/DOI:{clean_doi}"
        elif id_type.lower() == "arxiv":
            path = f"/paper/ARXIV:{identifier.strip()}"
        elif id_type.lower() == "pmid":
            path = f"/paper/PMID:{identifier.strip()}"
        elif id_type.lower() == "s2_id":
            path = f"/paper/{identifier.strip()}"
        else:
            logger.warning(f"S2 不支持的 lookup 类型: {id_type}")
            return None

        params = {"fields": self.default_fields}

        clean_path = path.strip().lower()
        cache_key = metadata_cache_key(
            "semantic_scholar",
            "lookup",
            clean_path,
            api_version="graph-v1",
            fields_version="paper-core-v1",
        )
        logger.info(f"S2 正在执行 lookup: {path}")
        status, data = await self._cached_json(
            cache_key=cache_key,
            path=path,
            params=params,
            ttl_seconds=S2_LOOKUP_TTL_SECONDS,
            negative_ttl_seconds=S2_NOT_FOUND_TTL_SECONDS,
        )
        return self._to_paper_record(data, path) if status == 200 else None

    async def get_references(self, paper: PaperRecord) -> List[PaperRecord]:
        if not paper.semantic_scholar_id:
            logger.warning("get_references 失败: 论文缺少 semantic_scholar_id")
            return []

        path = f"/paper/{paper.semantic_scholar_id}/references"
        # 显式获取 S2 关联的被引用 Paper 对象字段
        params = {
            "limit": 100,
            "fields": f"contexts,intents,isInfluential,citedPaper.{self.default_fields}",
        }

        cache_key = metadata_cache_key(
            "semantic_scholar",
            "references",
            paper.semantic_scholar_id,
            api_version="graph-v1",
            fields_version="paper-core-v1",
        )
        _status, data = await self._cached_json(
            cache_key=cache_key,
            path=path,
            params=params,
            ttl_seconds=S2_GRAPH_TTL_SECONDS,
        )
        papers = []
        for item in data.get("data", []):
            cited_paper = item.get("citedPaper")
            if cited_paper:
                papers.append(self._to_paper_record(cited_paper, path))
        return papers

    async def get_citations(self, paper: PaperRecord) -> List[PaperRecord]:
        if not paper.semantic_scholar_id:
            logger.warning("get_citations 失败: 论文缺少 semantic_scholar_id")
            return []

        path = f"/paper/{paper.semantic_scholar_id}/citations"
        params = {
            "limit": 100,
            "fields": f"contexts,intents,isInfluential,citingPaper.{self.default_fields}",
        }

        cache_key = metadata_cache_key(
            "semantic_scholar",
            "citations",
            paper.semantic_scholar_id,
            api_version="graph-v1",
            fields_version="paper-core-v1",
        )
        _status, data = await self._cached_json(
            cache_key=cache_key,
            path=path,
            params=params,
            ttl_seconds=S2_GRAPH_TTL_SECONDS,
        )
        papers = []
        for item in data.get("data", []):
            citing_paper = item.get("citingPaper")
            if citing_paper:
                papers.append(self._to_paper_record(citing_paper, path))
        return papers

    def _to_paper_record(
        self, item: Dict[str, Any], query_or_endpoint: str
    ) -> PaperRecord:
        """
        转换 S2 原始 JSON 数据为统一的 PaperRecord。
        """
        s2_id = item.get("paperId")
        title = item.get("title") or "Untitled Paper"
        year = item.get("year")
        abstract = item.get("abstract")

        # 提取期刊与会议
        venue = item.get("venue")
        journal_info = item.get("journal") or {}
        journal = journal_info.get("name") or venue

        # S2 的外部标识符字典
        ext_ids = item.get("externalIds") or {}
        doi = ext_ids.get("DOI")
        if doi:
            doi = doi.strip().lower()

        arxiv_id = ext_ids.get("ArXiv")
        if arxiv_id:
            arxiv_id = arxiv_id.split("v")[0].strip()  # 剔除版本号

        pmid = ext_ids.get("PubMed")
        pmcid = ext_ids.get("PubMedCentral")
        corpus_id = item.get("corpusId")

        # 引用数据量
        citation_count = item.get("citationCount")
        reference_count = item.get("referenceCount")
        open_access_pdf = item.get("openAccessPdf") or {}
        s2_pdf_url = (
            open_access_pdf.get("url") if isinstance(open_access_pdf, dict) else None
        )
        pdf_candidates = (
            [
                {
                    "url": str(s2_pdf_url).strip(),
                    "source": "semantic_scholar_openAccessPdf",
                    "priority": 10,
                }
            ]
            if s2_pdf_url
            else []
        )
        fulltext_status = FulltextStatus(
            oa_status="open" if item.get("isOpenAccess") else "unknown",
            pdf_url=str(s2_pdf_url).strip() if s2_pdf_url else None,
            pdf_source="semantic_scholar_openAccessPdf" if s2_pdf_url else None,
            pdf_candidates=pdf_candidates,
        )

        # 作者信息转换
        authors: List[AuthorRecord] = []
        for auth in item.get("authors", []):
            auth_name = auth.get("name")
            if not auth_name:
                continue
            authors.append(
                AuthorRecord(
                    name=auth_name,
                    orcid=None,  # S2 默认接口不提供
                    affiliations=[],
                    source="semantic_scholar",
                )
            )

        # 组装内部唯一 ID
        paper_id = f"spc:{uuid.uuid4()}"

        # 字段级数据源溯源
        retrieved_at = datetime.now()
        source_refs = [
            SourceRef(
                source="semantic_scholar",
                source_record_id=s2_id,
                field="title",
                value=str(title),
                retrieved_at=retrieved_at,
                query_or_endpoint=query_or_endpoint,
                confidence=0.99,
            ),
            SourceRef(
                source="semantic_scholar",
                source_record_id=s2_id,
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
                    source="semantic_scholar",
                    source_record_id=s2_id,
                    field="doi",
                    value=str(doi),
                    retrieved_at=retrieved_at,
                    query_or_endpoint=query_or_endpoint,
                    confidence=1.0,
                )
            )

        # 机构信息判定（由于 S2 默认不提供机构明细，信号设为空，待与其他源合并时补充）
        inst_signals = InstitutionSignal(
            has_university_affiliation=False,
            has_company_affiliation=False,
            org_signal_confidence="low",
        )

        return PaperRecord(
            paper_id=paper_id,
            doi=doi,
            semantic_scholar_id=s2_id,
            corpus_id=corpus_id,
            pubmed_id=pmid,
            pmc_id=pmcid,
            arxiv_id=arxiv_id,
            title=title,
            year=year,
            venue=venue,
            journal=journal,
            authors=authors,
            abstract=abstract,
            citation_count=citation_count,
            reference_count=reference_count,
            source_refs=source_refs,
            institution_signals=inst_signals,
            fulltext_status=fulltext_status,
        )
