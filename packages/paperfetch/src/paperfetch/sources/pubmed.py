# -*- coding: utf-8 -*-
"""
pubmed 模块
实现 PubMed 两阶段数据源适配器 (esearch 抓取 PMID，efetch 解析 XML 提取元数据、PMC_ID 与 MeSH 词表)。
"""

import os
import uuid
from paperfetch.observability import get_event_logger
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional, AsyncGenerator
import httpx

from paperfetch.sources.base import BaseMetadataSource
from paperfetch.core.models import (
    PaperRecord,
    AuthorRecord,
    SourceRef,
    OrganizationRecord,
    InstitutionSignal,
)
from paperfetch.utils.client import async_request_with_retry

logger = get_event_logger("paperfetch.sources.pubmed")


class PubMedSource(BaseMetadataSource):
    """
    PubMedSource 学术检索源适配器

    集成 NCBI E-utilities API，实现高并发两阶段文献检索与 MeSH 医学专业词汇解析。
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limit_semaphore: Optional[asyncio.Semaphore] = None,
    ):
        super().__init__(client, rate_limit_semaphore)
        self.esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        self.efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    @property
    def source_name(self) -> str:
        return "pubmed"

    async def search(
        self,
        query: str,
        limit: int = 50,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> AsyncGenerator[PaperRecord, None]:
        """
        第一阶段：调用 esearch 并行拉取符合检索式的所有 PMID。
        第二阶段：分包调用 efetch 获取 XML 元数据，并流式产生 PaperRecord。

        Args:
            query (str): 检索关键词。
            limit (int): 最大召回篇数。
            year_from (Optional[int]): 起始年份过滤（含）。
            year_to (Optional[int]): 截止年份过滤（含）。
        """
        logger.info(f"PubMed 第一阶段: 开始检索 PMID. Query: {query}")

        # 行内注释：将 Brief 中的时间窗口约束拼接为 PubMed 原生的 [dp] 日期过滤后缀
        effective_query = query
        if year_from and year_to:
            effective_query = f"{query} AND {year_from}:{year_to}[dp]"
        elif year_from:
            effective_query = f"{query} AND {year_from}:3000[dp]"
        elif year_to:
            effective_query = f"{query} AND 1900:{year_to}[dp]"

        # 组装 esearch 请求参数
        params = {
            "db": "pubmed",
            "term": effective_query,
            "retmax": limit,
            "retmode": "json",
        }
        api_key = os.getenv("NCBI_API_KEY")
        if api_key:
            params["api_key"] = api_key

        headers = {"User-Agent": "paperfetch/2.0"}

        pmid_list: List[str] = []
        try:
            if self.semaphore:
                async with self.semaphore:
                    response = await async_request_with_retry(
                        self.client,
                        "GET",
                        self.esearch_url,
                        params=params,
                        headers=headers,
                    )
            else:
                response = await async_request_with_retry(
                    self.client, "GET", self.esearch_url, params=params, headers=headers
                )

            pmid_list = response.json().get("esearchresult", {}).get("idlist", [])
            logger.info(f"PubMed 第一阶段检索完成，召回 {len(pmid_list)} 个 PMID。")
        except Exception:
            logger.exception("PubMed 第一阶段 esearch 失败")
            return

        if not pmid_list:
            return

        # 第二阶段：分包拉取元数据（NCBI 推荐单包最大 200 个，避免 POST body 过大）
        chunk_size = 200
        chunks = [
            pmid_list[i : i + chunk_size] for i in range(0, len(pmid_list), chunk_size)
        ]

        # 并发请求分包
        tasks = [self._fetch_chunk(chunk, query) for chunk in chunks]
        chunk_results = await asyncio.gather(*tasks)

        for paper_list in chunk_results:
            for paper in paper_list:
                yield paper

    async def _fetch_chunk(self, pmids: List[str], query: str) -> List[PaperRecord]:
        """
        分包抓取对应 PMID 的完整 XML 文献详情。
        """
        pmid_str = ",".join(pmids)
        params = {"db": "pubmed", "id": pmid_str, "retmode": "xml"}
        api_key = os.getenv("NCBI_API_KEY")
        if api_key:
            params["api_key"] = api_key

        headers = {"User-Agent": "paperfetch/2.0"}

        try:
            # 采用 POST 方式避免超长 URL 导致 414 Request-URI Too Large
            if self.semaphore:
                async with self.semaphore:
                    response = await async_request_with_retry(
                        self.client,
                        "POST",
                        self.efetch_url,
                        data=params,
                        headers=headers,
                    )
            else:
                response = await async_request_with_retry(
                    self.client, "POST", self.efetch_url, data=params, headers=headers
                )

            return self._parse_pubmed_xml(
                response.text, f"/efetch?db=pubmed&query={query}"
            )
        except Exception:
            logger.exception("PubMed efetch 分包抓取失败")
            return []

    async def lookup(
        self, identifier: str, id_type: str = "doi"
    ) -> Optional[PaperRecord]:
        """
        根据唯一标识符精准抓取文献并转换。
        """
        pmid = None
        if id_type.lower() == "pmid":
            pmid = identifier.strip()
        elif id_type.lower() == "doi":
            pmid = await self._search_pmid_by_doi(identifier)
        else:
            logger.warning(f"PubMed lookup 不支持的 id_type: {id_type}")
            return None

        if not pmid:
            return None

        logger.info(f"PubMed 正在根据 PMID [{pmid}] 抓取元数据...")
        params = {"db": "pubmed", "id": pmid, "retmode": "xml"}
        api_key = os.getenv("NCBI_API_KEY")
        if api_key:
            params["api_key"] = api_key

        headers = {"User-Agent": "paperfetch/2.0"}

        try:
            if self.semaphore:
                async with self.semaphore:
                    response = await async_request_with_retry(
                        self.client,
                        "GET",
                        self.efetch_url,
                        params=params,
                        headers=headers,
                    )
            else:
                response = await async_request_with_retry(
                    self.client, "GET", self.efetch_url, params=params, headers=headers
                )

            papers = self._parse_pubmed_xml(
                response.text, f"/efetch?db=pubmed&id={pmid}"
            )
            return papers[0] if papers else None
        except Exception:
            logger.exception("PubMed lookup efetch 失败")
            return None

    async def _search_pmid_by_doi(self, doi: str) -> Optional[str]:
        """
        利用 esearch 通过 DOI 反查 PMID。
        """
        clean_doi = (
            doi.replace("https://doi.org/", "")
            .replace("http://dx.doi.org/", "")
            .strip()
            .lower()
        )
        params = {
            "db": "pubmed",
            "term": f"{clean_doi}[Location ID]",
            "retmode": "json",
        }
        api_key = os.getenv("NCBI_API_KEY")
        if api_key:
            params["api_key"] = api_key

        headers = {"User-Agent": "paperfetch/2.0"}

        try:
            if self.semaphore:
                async with self.semaphore:
                    response = await async_request_with_retry(
                        self.client,
                        "GET",
                        self.esearch_url,
                        params=params,
                        headers=headers,
                    )
            else:
                response = await async_request_with_retry(
                    self.client, "GET", self.esearch_url, params=params, headers=headers
                )

            id_list = response.json().get("esearchresult", {}).get("idlist", [])
            return id_list[0] if id_list else None
        except Exception:
            logger.exception(f"PubMed esearch DOI [{doi}] 失败")
            return None

    async def get_references(self, paper: PaperRecord) -> List[PaperRecord]:
        # PubMed 原生引用图谱不完整，引用关系交给 OpenAlex/Semantic Scholar 补充。
        logger.info("PubMed get_references 默认跳过，由主源合并进行补充。")
        return []

    async def get_citations(self, paper: PaperRecord) -> List[PaperRecord]:
        logger.info("PubMed get_citations 默认跳过，由主源合并进行补充。")
        return []

    def _parse_pubmed_xml(self, xml_text: str, endpoint: str) -> List[PaperRecord]:
        """
        使用 ElementTree 解析返回的 XML 字节流。
        """
        papers: List[PaperRecord] = []
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            logger.exception("XML 语法解析失败")
            return []

        for article_node in root.findall(".//PubmedArticle"):
            try:
                paper = self._parse_single_article(article_node, endpoint)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.warning(f"解析 MedlineCitation 节点发生异常忽略: {str(e)}")

        return papers

    def _parse_single_article(
        self, node: ET.Element, endpoint: str
    ) -> Optional[PaperRecord]:
        """
        将 PubmedArticle Element 节点提取并构造成 PaperRecord。
        """
        citation = node.find(".//MedlineCitation")
        if citation is None:
            return None

        # 1. 抓取唯一标识符 PMID
        pmid_node = citation.find("PMID")
        pmid = pmid_node.text.strip() if pmid_node is not None else None
        if not pmid:
            return None

        article = citation.find("Article")
        if article is None:
            return None

        # 2. 抓取规范化 Title (递归获取所有子标签中的文本)
        title_node = article.find("ArticleTitle")
        title = (
            "".join(title_node.itertext()).strip()
            if title_node is not None
            else "Untitled Paper"
        )

        # 3. 递归拼接结构化 Abstract (组合 BACKGROUND / METHOD / RESULTS / CONCLUSION 标签)
        abstract_parts = []
        abstract_node = article.find("Abstract")
        if abstract_node is not None:
            for text_node in abstract_node.findall("AbstractText"):
                label = text_node.get("Label")
                text = "".join(text_node.itertext()).strip()
                if label and text:
                    abstract_parts.append(f"{label}: {text}")
                elif text:
                    abstract_parts.append(text)
        abstract = "\n".join(abstract_parts) if abstract_parts else None

        # 4. 发表年份解析 (兼容 Year 和 MedlineDate)
        year = None
        pub_date = article.find(".//JournalIssue/PubDate")
        if pub_date is not None:
            year_node = pub_date.find("Year")
            if year_node is not None:
                try:
                    year = int(year_node.text.strip())
                except (AttributeError, ValueError):
                    pass
            else:
                medline_date = pub_date.find("MedlineDate")
                if medline_date is not None and medline_date.text:
                    try:
                        year = int(medline_date.text.strip()[:4])
                    except (AttributeError, ValueError):
                        pass

        # 5. 期刊名称
        journal_node = article.find(".//Journal/Title")
        journal = journal_node.text.strip() if journal_node is not None else None

        # 6. DOI 与 PMC 链接抓取
        doi = None
        pmc = None
        pub_id_list = node.find(".//PubmedData/ArticleIdList")
        if pub_id_list is not None:
            for pub_id in pub_id_list.findall("ArticleId"):
                id_type = pub_id.get("IdType")
                if id_type == "doi" and pub_id.text:
                    doi = pub_id.text.strip().lower()
                elif id_type == "pmc" and pub_id.text:
                    pmc = pub_id.text.strip()

        # 7. 提取作者及机构 Affiliation 信息
        authors: List[AuthorRecord] = []
        orgs: List[OrganizationRecord] = []
        has_uni = False
        has_corp = False
        has_res = False
        has_gov = False
        has_hosp = False

        author_list = article.find("AuthorList")
        if author_list is not None:
            for auth_node in author_list.findall("Author"):
                last = auth_node.find("LastName")
                fore = auth_node.find("ForeName")
                last_str = last.text.strip() if last is not None else ""
                fore_str = fore.text.strip() if fore is not None else ""
                auth_name = f"{fore_str} {last_str}".strip()

                # 兼容机构/团体作者名称 (CollectiveName)
                if not auth_name:
                    coll_node = auth_node.find("CollectiveName")
                    if coll_node is not None and coll_node.text:
                        auth_name = coll_node.text.strip()

                if not auth_name:
                    continue

                affiliations = []
                # 提取机构
                aff_info = auth_node.find("AffiliationInfo")
                if aff_info is not None:
                    aff_text_node = aff_info.find("Affiliation")
                    if aff_text_node is not None and aff_text_node.text:
                        aff_raw = aff_text_node.text.strip()
                        affiliations.append(aff_raw)

                        # 机构类别软判定
                        aff_lower = aff_raw.lower()
                        if (
                            "univ" in aff_lower
                            or "college" in aff_lower
                            or "school" in aff_lower
                        ):
                            has_uni = True
                            inst_type = "education"
                        elif (
                            "corp" in aff_lower
                            or "inc" in aff_lower
                            or "ltd" in aff_lower
                            or "pharma" in aff_lower
                        ):
                            has_corp = True
                            inst_type = "company"
                        elif (
                            "hosp" in aff_lower
                            or "clinic" in aff_lower
                            or "medical center" in aff_lower
                            or "infirmary" in aff_lower
                        ):
                            has_hosp = True
                            inst_type = "hospital"
                        elif (
                            "inst" in aff_lower
                            or "lab" in aff_lower
                            or "acad" in aff_lower
                        ):
                            has_res = True
                            inst_type = "research_institute"
                        elif "gov" in aff_lower or "ministry" in aff_lower:
                            has_gov = True
                            inst_type = "government"
                        else:
                            inst_type = "unknown"

                        orgs.append(
                            OrganizationRecord(
                                raw=aff_raw,
                                normalized_name=None,
                                type=inst_type,
                                source="pubmed",
                            )
                        )

                authors.append(
                    AuthorRecord(
                        name=auth_name,
                        orcid=None,
                        affiliations=affiliations,
                        source="pubmed",
                    )
                )

        # 8. 提取 MeSH (Medical Subject Headings) 核心主题词
        mesh_terms: List[str] = []
        mesh_list = citation.find("MeshHeadingList")
        if mesh_list is not None:
            for heading in mesh_list.findall("MeshHeading"):
                desc = heading.find("DescriptorName")
                if desc is not None and desc.text:
                    mesh_terms.append(desc.text.strip())

        # 构造内部唯一 ID
        paper_id = f"spc:{uuid.uuid4()}"

        # 字段级源溯源记录
        retrieved_at = datetime.now()
        source_refs = [
            SourceRef(
                source="pubmed",
                source_record_id=pmid,
                field="title",
                value=str(title),
                retrieved_at=retrieved_at,
                query_or_endpoint=endpoint,
                confidence=1.0,
            ),
            SourceRef(
                source="pubmed",
                source_record_id=pmid,
                field="year",
                value=str(year) if year else "",
                retrieved_at=retrieved_at,
                query_or_endpoint=endpoint,
                confidence=1.0,
            ),
        ]
        if doi:
            source_refs.append(
                SourceRef(
                    source="pubmed",
                    source_record_id=pmid,
                    field="doi",
                    value=str(doi),
                    retrieved_at=retrieved_at,
                    query_or_endpoint=endpoint,
                    confidence=1.0,
                )
            )

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

        return PaperRecord(
            paper_id=paper_id,
            doi=doi,
            pubmed_id=pmid,
            pmc_id=pmc,
            title=title,
            year=year,
            journal=journal,
            authors=authors,
            abstract=abstract,
            mesh_terms=mesh_terms,
            source_refs=source_refs,
            institution_signals=inst_signals,
        )
