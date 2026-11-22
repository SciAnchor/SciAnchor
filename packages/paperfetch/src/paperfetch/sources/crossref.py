# -*- coding: utf-8 -*-
"""
crossref 模块
实现 Crossref REST API 的 Polite 通道客户端，提供基于 ISSN 的期刊元数据检索能力。
作为 OpenAlex 的兜底数据源，用于补全 publisher、ISSN、期刊分类等基础元数据。
"""

import os
from paperfetch.observability import get_event_logger
from typing import Dict, Any, Optional

import httpx

from paperfetch.utils.client import async_request_with_retry, global_rate_limiter
from paperfetch.utils.cache import global_cache

logger = get_event_logger("paperfetch.sources.crossref")

# Crossref REST API 基础端点
CROSSREF_API_BASE = "https://api.crossref.org"


class CrossrefSource:
    """
    CrossrefSource — Crossref REST API Polite 通道客户端

    遵循 Crossref 开放科学礼貌协议（https://github.com/CrossRef/rest-api-doc#etiquette），
    在请求头中注入 mailto 邮箱以进入高吞吐的 Polite Pool，获得更稳定的并发限额。

    主要能力:
    - fetch_journal_by_issn: 根据 ISSN 查询期刊的出版商、ISSN、学科分类等基础元数据
    - fetch_work_by_doi: 根据 DOI 查询单篇文献的元数据
    """

    def __init__(self, client: httpx.AsyncClient):
        """
        初始化 Crossref Polite 客户端。

        Args:
            client (httpx.AsyncClient): 共享的 HTTP 异步客户端实例。
        """
        self.client = client
        self.base_url = CROSSREF_API_BASE

        # 从环境变量读取 Polite 邮箱，推荐在 .env 中配置 CROSSREF_MAILTO
        self.mailto = (
            os.getenv("CROSSREF_MAILTO")
            or os.getenv("CROSSREF_POLITE_MAILTO")
            or os.getenv("OPENALEX_MAILTO")
        )
        if not self.mailto:
            logger.warning(
                "Crossref: 未配置 CROSSREF_MAILTO 环境变量。"
                "请求将走非 Polite 通道，可能受到更严格的限流。"
                "建议在 .env 中设置 CROSSREF_MAILTO=your-email@example.com"
            )

    def _get_headers(self) -> Dict[str, str]:
        """
        组装 Crossref Polite 请求头。

        Crossref 的 Polite Pool 机制要求在 User-Agent 中包含 mailto 字段。
        进入 Polite Pool 后，限流上限从 50 req/s 提升至更高，且错误率更低。

        Returns:
            Dict[str, str]: 包含 User-Agent 和可选 mailto 的请求头。
        """
        headers = {}
        if self.mailto:
            # Crossref Polite Pool 识别格式: GroovyBib/1.1 (https://example.org/GroovyBib/; mailto:foo@bar.com)
            headers["User-Agent"] = (
                f"paperfetch/2.0 (https://github.com/paperfetch; mailto:{self.mailto})"
            )
        else:
            headers["User-Agent"] = "paperfetch/2.0"
        return headers

    async def fetch_journal_by_issn(self, issn: str) -> Optional[Dict[str, Any]]:
        """
        根据 ISSN 查询期刊的 Crossref 注册元数据。

        通过 /journals/{issn} 端点获取出版商名称、ISSN（print/electronic）、
        期刊标题、学科分类等信息，用于多源融合补全和实体对齐校验。

        Args:
            issn (str): 期刊的 ISSN（print 或 electronic 均可）。

        Returns:
            Optional[Dict[str, Any]]: 标准化后的期刊元数据字典，结构如下：
                - title: 期刊官方名称
                - publisher: 出版商名称
                - issn_print: 印刷版 ISSN
                - issn_electronic: 电子版 ISSN
                - subjects: 学科分类列表
                - total_dois: 该期刊在 Crossref 注册的 DOI 总数
                - last_status_check_time: 最后状态检查时间
                若查询失败或 ISSN 无效则返回 None。
        """
        if not issn or not issn.strip():
            logger.warning("Crossref: 传入的 ISSN 为空，跳过查询。")
            return None

        issn = issn.strip().upper()

        # 优先检查本地持久化缓存
        cache_key = f"crossref:journal:{issn}"
        cached = await global_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Crossref Journal 命中本地缓存: ISSN={issn}")
            return cached

        url = f"{self.base_url}/journals/{issn}"
        headers = self._get_headers()

        try:
            # Crossref Polite 通道最小间隔控速，避免 429
            await global_rate_limiter.wait("crossref", 0.15)

            response = await async_request_with_retry(
                self.client, "GET", url, headers=headers, timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                message = data.get("message", {})

                # 解析 ISSN 列表（Crossref 返回的是 issn-type 列表）
                issn_print = None
                issn_electronic = None
                for issn_entry in message.get("issn-type", []):
                    if issn_entry.get("type") == "print":
                        issn_print = issn_entry.get("value")
                    elif issn_entry.get("type") == "electronic":
                        issn_electronic = issn_entry.get("value")

                # 如果 issn-type 为空，退化到通用 ISSN 列表
                if not issn_print and not issn_electronic:
                    issn_list = message.get("ISSN", [])
                    if len(issn_list) >= 1:
                        issn_print = issn_list[0]
                    if len(issn_list) >= 2:
                        issn_electronic = issn_list[1]

                # 解析学科分类
                subjects = []
                for subj in message.get("subjects", []):
                    subj_name = (
                        subj.get("name") if isinstance(subj, dict) else str(subj)
                    )
                    if subj_name:
                        subjects.append(subj_name)

                result = {
                    "title": message.get("title", ""),
                    "publisher": message.get("publisher", ""),
                    "issn_print": issn_print,
                    "issn_electronic": issn_electronic,
                    "subjects": subjects,
                    "total_dois": message.get("total-dois", 0),
                    "last_status_check_time": message.get("last-status-check-time"),
                }

                # 写入本地缓存（长期有效，期刊基础信息几乎不变）
                await global_cache.set(cache_key, result, "crossref")
                logger.info(
                    f"Crossref 期刊元数据获取成功: ISSN={issn}, "
                    f"Title={result['title']}, Publisher={result['publisher']}"
                )
                return result

            elif response.status_code == 404:
                logger.info(f"Crossref 未找到 ISSN={issn} 对应的期刊记录。")
                return None
            else:
                logger.warning(
                    f"Crossref 查询返回非预期状态码 {response.status_code}: ISSN={issn}"
                )
                return None

        except Exception as e:
            logger.error(f"Crossref 期刊查询异常 (ISSN={issn}): {e}")
            return None

    async def fetch_work_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        根据 DOI 查询单篇文献在 Crossref 的注册元数据。

        用于校验 DOI 有效性、补全出版商信息、获取参考文献数量等。

        Args:
            doi (str): 文献的 DOI（不含 https://doi.org/ 前缀）。

        Returns:
            Optional[Dict[str, Any]]: Crossref 文献原始 message 字典，若查询失败则返回 None。
        """
        if not doi or not doi.strip():
            return None

        # 规范化 DOI
        doi = (
            doi.replace("https://doi.org/", "")
            .replace("http://dx.doi.org/", "")
            .strip()
            .lower()
        )

        cache_key = f"crossref:work:{doi}"
        cached = await global_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Crossref Work 命中本地缓存: DOI={doi}")
            return cached

        url = f"{self.base_url}/works/{doi}"
        headers = self._get_headers()

        try:
            await global_rate_limiter.wait("crossref", 0.15)

            response = await async_request_with_retry(
                self.client, "GET", url, headers=headers, timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                message = data.get("message", {})
                await global_cache.set(cache_key, message, "crossref")
                logger.info(f"Crossref Work 元数据获取成功: DOI={doi}")
                return message
            elif response.status_code == 404:
                logger.info(f"Crossref 未找到 DOI={doi} 对应的文献记录。")
                return None
            else:
                logger.warning(
                    f"Crossref 查询返回非预期状态码 {response.status_code}: DOI={doi}"
                )
                return None

        except Exception as e:
            logger.error(f"Crossref Work 查询异常 (DOI={doi}): {e}")
            return None
