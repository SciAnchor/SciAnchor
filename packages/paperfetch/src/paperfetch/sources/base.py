# -*- coding: utf-8 -*-
"""
BaseMetadataSource 模块
定义所有学术元数据拉取源的抽象基类 BaseMetadataSource。
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, AsyncGenerator
import httpx
from paperfetch.core.models import PaperRecord


class BaseMetadataSource(ABC):
    """
    BaseMetadataSource 学术元数据源基类

    规定了所有文献数据源必须实现的检索、详情精准查询、引用与被引关联拉取的统一异步接口。
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limit_semaphore: Optional[asyncio.Semaphore] = None,
    ):
        """
        初始化元数据源。

        Args:
            client (httpx.AsyncClient): 网络请求共享客户端。
            rate_limit_semaphore (Optional[asyncio.Semaphore]): 用于防止高并发请求击穿目标 API 的并发控制信号量。
        """
        self.client: httpx.AsyncClient = client
        self.semaphore: Optional[asyncio.Semaphore] = rate_limit_semaphore

    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        返回当前数据源的唯一名称标识 (例如 "openalex", "pubmed")。

        Returns:
            str: 数据源名称。
        """
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 50,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> AsyncGenerator[PaperRecord, None]:
        """
        异步流式搜索文献。

        Args:
            query (str): 检索关键词或检索式。
            limit (int): 期望返回的最大候选篇数。
            year_from (Optional[int]): 起始年份过滤（含），由 Brief scope.time_window.from 驱动。
            year_to (Optional[int]): 截止年份过滤（含），由 Brief scope.time_window.to 驱动。

        Yields:
            PaperRecord: 统一格式的学术论文实体。
        """
        pass

    @abstractmethod
    async def lookup(
        self, identifier: str, id_type: str = "doi"
    ) -> Optional[PaperRecord]:
        """
        根据唯一标识符（如 DOI、PMID、CorpusID 等）精准查询单篇论文详情。

        Args:
            identifier (str): 标识符内容值。
            id_type (str): 标识符类型 ("doi", "pmid", "arxiv", "s2_id")。

        Returns:
            Optional[PaperRecord]: 精准抓取补全后的论文实体，未找到则返回 None。
        """
        pass

    @abstractmethod
    async def get_references(self, paper: PaperRecord) -> List[PaperRecord]:
        """
        获取单篇论文的所有引用文献列表。

        Args:
            paper (PaperRecord): 输入的目标论文。

        Returns:
            List[PaperRecord]: 引用文献列表。
        """
        pass

    @abstractmethod
    async def get_citations(self, paper: PaperRecord) -> List[PaperRecord]:
        """
        获取单篇论文的所有被引文献列表。

        Args:
            paper (PaperRecord): 输入的目标论文。

        Returns:
            List[PaperRecord]: 被引文献列表。
        """
        pass
