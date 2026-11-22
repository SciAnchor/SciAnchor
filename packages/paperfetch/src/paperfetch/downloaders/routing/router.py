# -*- coding: utf-8 -*-
"""路由选择路线规划总控。

聚合数据库分类与所有的路由生成提供者，对每一篇学术论文产出完整的
路由规划图 (PDFDatabaseRoutingPlan)。
"""

from __future__ import annotations

from paperfetch.observability import get_event_logger
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.base import PDFRouteCandidate
from paperfetch.downloaders.routing.classifier import (
    PDFDatabaseClassifier,
    PDFDatabaseMatch,
    _publisher_text,
)
from paperfetch.downloaders.routing.providers import (
    PDFRouteBuildContext,
    PDFRouteProvider,
    PublisherAPIProvider,
)

logger = get_event_logger("paperfetch.downloaders.routing.router")


@dataclass
class PDFDatabaseRoutingPlan:
    """包含了某篇文献所分类命中的数据库以及其所有生成路由候选项。"""

    matches: List[PDFDatabaseMatch]
    candidates: List[PDFRouteCandidate]


class PDFDatabaseRouter:
    """PDF 路由决策总控类。"""

    def __init__(
        self,
        run_context: Any,
        doi_cache_key_factory: Callable[[Optional[str]], str],
        providers: Optional[Sequence[PDFRouteProvider]] = None,
        classifier: Optional[PDFDatabaseClassifier] = None,
    ) -> None:
        self.run_context = run_context
        self.doi_cache_key_factory = doi_cache_key_factory
        self.classifier = classifier or PDFDatabaseClassifier()
        self.providers: Sequence[PDFRouteProvider] = providers or (
            PublisherAPIProvider(),
        )

    def plan(self, paper: PaperRecord) -> PDFDatabaseRoutingPlan:
        """为单篇文献生成其专属的路由规划方案。"""
        matches = self.classifier.classify(paper)
        context = PDFRouteBuildContext(
            paper=paper,
            doi_cache_key=self.doi_cache_key_factory(paper.doi),
            run_context=self.run_context,
            publisher_text=_publisher_text(paper),
        )
        candidates: List[PDFRouteCandidate] = []
        for provider in self.providers:
            candidates.extend(provider.build_candidates(context, matches))
        return PDFDatabaseRoutingPlan(matches=matches, candidates=candidates)
