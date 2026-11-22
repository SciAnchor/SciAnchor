# -*- coding: utf-8 -*-
"""路由候选生成提供者。

基于学术库分类命中的证据，为单篇论文规划出各种可用于实际下载的
物理路由候选 (PDFRouteCandidate)。
"""

from __future__ import annotations

from paperfetch.observability import get_event_logger
from typing import Any, List, Optional, Protocol, Sequence

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.base import PDFRouteCandidate
from paperfetch.downloaders.routing.classifier import PDFDatabaseMatch
from paperfetch.downloaders.registry import BackendRegistry
from paperfetch.downloaders.backends.publisher_api.base import PublisherAPIBackend

logger = get_event_logger("paperfetch.downloaders.routing.providers")


class PDFRouteBuildContext:
    """路由候选构建上下文。"""

    def __init__(
        self,
        paper: PaperRecord,
        doi_cache_key: str,
        run_context: Any,
        publisher_text: str = "",
    ) -> None:
        self.paper = paper
        self.doi_cache_key = doi_cache_key
        self.run_context = run_context
        self.publisher_text = publisher_text


class PDFRouteProvider(Protocol):
    """所有路由候选生成器的接口契约。"""

    key: str

    def build_candidates(
        self, context: PDFRouteBuildContext, matches: Sequence[PDFDatabaseMatch]
    ) -> List[PDFRouteCandidate]: ...


def _best_database_match(
    matches: Sequence[PDFDatabaseMatch], key: str
) -> Optional[PDFDatabaseMatch]:
    relevant = [match for match in matches if match.key == key]
    if not relevant:
        return None
    return sorted(relevant, key=lambda item: item.confidence, reverse=True)[0]


class PublisherAPIProvider:
    """聚合所有已注册出版商官方 API 的候选提供者。"""

    key = "publisher_api"

    def build_candidates(
        self, context: PDFRouteBuildContext, matches: Sequence[PDFDatabaseMatch]
    ) -> List[PDFRouteCandidate]:
        if not context.paper.doi:
            return []

        candidates: List[PDFRouteCandidate] = []

        # 1. 自动发现所有继承自 PublisherAPIBackend 的已配置且支持的后端类
        backends = BackendRegistry.get_backends_by_type(PublisherAPIBackend)
        for backend in backends:
            # 必须保证支持处理该 DOI
            if backend.can_handle(context.paper.doi):
                is_cfg = backend.is_configured()
                match = next(
                    (
                        m
                        for m in matches
                        if getattr(backend, "database_key", None) == m.key
                    ),
                    None,
                )
                meta = match.metadata() if match else {}
                meta.update(
                    {
                        "doi": context.paper.doi,
                        "doi_resolve_key": context.doi_cache_key,
                        "decision_reason": f"publisher_api_configured_for_{backend.publisher_name.lower()}"
                        if is_cfg
                        else f"publisher_api_missing_credentials_for_{backend.publisher_name.lower()}",
                        "route_provider": backend.route_key,
                    }
                )
                if not is_cfg:
                    meta["error_class"] = "missing_credentials"
                    meta["missing_credentials"] = True

                from urllib.parse import quote

                doi_val = context.paper.doi.strip()
                for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
                    if doi_val.lower().startswith(prefix):
                        doi_val = doi_val[len(prefix) :]
                        break
                doi_val = doi_val.lstrip("/")

                url_candidate = None
                if backend.route_key == "elsevier_api":
                    url_candidate = f"https://api.elsevier.com/content/article/doi/{quote(doi_val, safe='')}"
                elif backend.route_key == "publisher_api_springer":
                    url_candidate = f"https://api.springernature.com/openaccess/json?q=doi:{doi_val}"

                candidates.append(
                    PDFRouteCandidate(
                        route=backend.route_key,
                        url=url_candidate,
                        priority=15,
                        source=backend.route_key,
                        metadata=meta,
                    )
                )

        return candidates
