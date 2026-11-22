# -*- coding: utf-8 -*-
"""SPC 单篇文献检索、反查、关联获取与学术元数据搜索子命令处理器。"""

import hashlib
import os
import re
from paperfetch.observability import get_event_logger, write_output
import asyncio

from paperfetch.utils.client import create_async_client, async_request_with_retry
from paperfetch.sources.openalex import OpenAlexSource
from paperfetch.sources.semantic_scholar import SemanticScholarSource
from paperfetch.sources.pubmed import PubMedSource
from paperfetch.utils.normalizer import (
    normalize_doi,
    normalize_arxiv_id,
    normalize_pmid,
    normalize_pmcid,
)
from paperfetch.utils.cleaner import MetadataCleanPipeline
from paperfetch.core.models import FulltextStatus, PaperRecord

logger = get_event_logger("paperfetch.cli.lookup")


def build_arxiv_identifier_record(arxiv_id: str) -> PaperRecord:
    """为聚合元数据尚未收录的新 arXiv 论文构造强标识实体。"""
    normalized = normalize_arxiv_id(arxiv_id)
    if not normalized or not re.fullmatch(
        r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})",
        normalized,
        re.IGNORECASE,
    ):
        raise ValueError(f"无效 arXiv ID: {arxiv_id}")
    digest = hashlib.sha256(f"arxiv:{normalized}".encode("utf-8")).hexdigest()[:16]
    return PaperRecord(
        paper_id=f"spc:arxiv:{digest}",
        doi=f"10.48550/arxiv.{normalized}",
        arxiv_id=normalized,
        title=f"arXiv {normalized}",
        publisher="arXiv",
        document_type="preprint",
        fulltext_status=FulltextStatus(
            oa_status="open",
            pdf_url=f"https://arxiv.org/pdf/{normalized}.pdf",
            pdf_source="arxiv",
        ),
    )


def run_lookup(parsed_args) -> int:
    """根据标识符精确反查单篇文献并支持下载与 MinerU 解析。"""
    doi = parsed_args.doi
    pmid = parsed_args.pmid
    arxiv = parsed_args.arxiv

    if not doi and not pmid and not arxiv:
        logger.error("[文献查询] 必须提供 --doi、--pmid 或 --arxiv 之一")
        return 1

    identifier = doi or pmid or arxiv
    id_type = "doi" if doi else ("pmid" if pmid else "arxiv")

    # 自动容错 arXiv DOI 前缀
    if doi and "10.48550/arxiv." in doi.lower():
        import re

        match_arxiv = re.search(r"10\.48550/arxiv\.([0-9\.\-_v]+)", doi, re.IGNORECASE)
        if match_arxiv:
            identifier = match_arxiv.group(1)
            id_type = "arxiv"
            logger.info(f"[文献查询] 识别为 arXiv 标识符，标识符={identifier}")

    async def _lookup():
        client = create_async_client()
        sem = asyncio.Semaphore(1)
        sources = ["openalex", "semantic_scholar"]
        instances = []
        for s in sources:
            if s == "openalex":
                instances.append(OpenAlexSource(client, sem))
            elif s == "semantic_scholar":
                instances.append(SemanticScholarSource(client, sem))

        found_record = None
        matched_source = None

        for src in instances:
            try:
                logger.info(
                    f"[文献查询] 反查元数据，数据源={src.source_name}，标识符={identifier}"
                )
                record = await src.lookup(identifier, id_type)
                if record:
                    found_record = record
                    matched_source = src.source_name
                    break
            except Exception as e:
                logger.warning(
                    f"[文献查询] 元数据反查失败，数据源={src.source_name}，原因={str(e)}"
                )

        await client.aclose()

        if found_record and id_type == "arxiv":
            # 用户输入的强标识优先于聚合元数据推断，防止上游 DOI 覆盖 arXiv 身份。
            found_record.arxiv_id = normalize_arxiv_id(identifier)

        if not found_record and id_type == "arxiv":
            normalized_arxiv = normalize_arxiv_id(identifier)
            if normalized_arxiv:
                found_record = build_arxiv_identifier_record(normalized_arxiv)
                matched_source = "arxiv_identifier_fallback"
                logger.info(
                    "[文献查询] 聚合元数据未命中，使用 arXiv 强标识继续下载，arXiv=%s",
                    normalized_arxiv,
                )

        if found_record:
            found_record.doi = normalize_doi(found_record.doi)
            found_record.arxiv_id = normalize_arxiv_id(found_record.arxiv_id)
            found_record.pubmed_id = normalize_pmid(found_record.pubmed_id)
            found_record.pmc_id = normalize_pmcid(found_record.pmc_id)
            found_record.title = MetadataCleanPipeline.clean(found_record.title)
            found_record.abstract = MetadataCleanPipeline.clean(found_record.abstract)

            if parsed_args.output_format == "json":
                dump_data = found_record.model_dump(mode="json")
                dump_data["_execution_summary"] = {"metadata_status": "success"}
                write_output(dump_data, pretty=True)
            else:
                write_output("=== 论文反查结果 ===")
                write_output(f"标题: {found_record.title}")
                write_output(f"年份: {found_record.year}")
                write_output(
                    f"发表源: {found_record.journal or found_record.venue or 'N/A'}"
                )
                write_output(f"DOI: {found_record.doi or 'N/A'}")
                write_output(f"arXiv: {found_record.arxiv_id or 'N/A'}")
                write_output(f"PMID: {found_record.pubmed_id or 'N/A'}")
                write_output(f"被引数: {found_record.citation_count}")
                write_output(f"数据源: {matched_source}")
                write_output(f"摘要: {found_record.abstract or 'N/A'}")
            return 0
        else:
            logger.error(
                f"[文献查询] 未找到文献，标识类型={id_type}，标识符={identifier}"
            )
            return 1

    return asyncio.run(_lookup())


def run_sciverse_search(parsed_args) -> int:
    """使用 Sciverse 进行语义片段检索或正文拉取。"""
    query = parsed_args.query
    doc_id = parsed_args.doc_id

    token = os.getenv("SCIVERSE_API_TOKEN")
    if not token:
        logger.error("[SciVerse] 缺少 SCIVERSE_API_TOKEN")
        return 1

    if not query and not doc_id:
        logger.error("[SciVerse] 必须提供 --query 或 --doc-id 之一")
        return 1

    async def _search():
        async with create_async_client() as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            if query:
                logger.info(f"[SciVerse] 语义检索，查询词={query!r}")
                payload = {"query": query, "top_k": parsed_args.top_k}
                url = "https://api.sciverse.space/agentic-search"
                resp = await async_request_with_retry(
                    client, "POST", url, json=payload, headers=headers
                )
                if resp.status_code != 200:
                    logger.error(
                        f"[SciVerse] 语义检索失败，HTTP 状态码={resp.status_code}"
                    )
                    return 1
                data = resp.json()
                if parsed_args.output_format == "json":
                    write_output(data, pretty=True)
                else:
                    hits = data.get("hits", [])
                    if not hits:
                        write_output("[-] 未在该主题下检索到相关的学术文献片段。")
                    else:
                        write_output(
                            f"--- 成功获取到 {len(hits)} 个最相关的学术片段 (Sciverse /agentic-search) ---"
                        )
                        for i, hit in enumerate(hits):
                            write_output(f"\n[{i + 1}] 标题: {hit.get('title')}")
                            write_output(
                                f"    文献ID: {hit.get('doc_id')} | 相似度分数: {hit.get('score', 0):.4f} | 发表年份: {hit.get('publication_published_year')}"
                            )
                            write_output(f"    正文片段预览:\n{hit.get('chunk')}")
                            write_output("-" * 80)
            elif doc_id:
                logger.info(f"[SciVerse] 流式获取全文，文档 ID={doc_id}")
                params = {
                    "doc_id": doc_id,
                    "offset": parsed_args.offset,
                    "limit": parsed_args.limit,
                }
                url = "https://api.sciverse.space/content"
                resp = await async_request_with_retry(
                    client,
                    "GET",
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code != 200:
                    logger.error(
                        f"[SciVerse] 全文获取失败，HTTP 状态码={resp.status_code}"
                    )
                    return 1
                data = resp.json()
                if parsed_args.output_format == "json":
                    write_output(data, pretty=True)
                else:
                    write_output(f"--- 成功拉取文献内容 (Doc ID: {doc_id}) ---")
                    write_output(
                        f"当前字符偏移起量: {parsed_args.offset} | 实际拉取字符长度: {data.get('chars_returned', 0)}"
                    )
                    write_output(
                        f"是否含有更多内容: {data.get('more', False)} (下一段起始偏移量建议: {data.get('next_offset')})"
                    )
                    write_output("\n[正文段落内容]:")
                    write_output(data.get("text", ""))
                    write_output("-" * 80)
        return 0

    return asyncio.run(_search())


def run_search_metadata(parsed_args) -> int:
    """多路学术源探测性检索。"""
    query = parsed_args.query
    source_opt = parsed_args.source
    limit = parsed_args.limit
    year_from = parsed_args.year_from
    year_to = parsed_args.year_to
    domain = parsed_args.domain

    async def _search():
        client = create_async_client()
        sem = asyncio.Semaphore(5)

        # 确定搜索数据源
        available_sources = ["openalex", "semantic_scholar", "pubmed"]
        selected_sources = [source_opt] if source_opt else available_sources

        # 针对不同领域定制默认源
        if not source_opt:
            if domain == "biomedical":
                selected_sources = ["pubmed", "openalex", "semantic_scholar"]
            else:
                selected_sources = ["openalex", "semantic_scholar"]

        instances = []
        for s in selected_sources:
            if s == "openalex":
                instances.append(OpenAlexSource(client, sem))
            elif s == "semantic_scholar":
                instances.append(SemanticScholarSource(client, sem))
            elif s == "pubmed":
                instances.append(PubMedSource(client, sem))

        logger.info(
            f"[文献查询] 探测检索，查询词={query!r}，数据源={selected_sources}，数量上限={limit}"
        )
        all_results = []

        for src in instances:
            try:
                logger.info(f"[文献查询] 检索数据源，数据源={src.source_name}")
                results = []
                async for paper in src.search(
                    query=query,
                    limit=limit,
                    year_from=year_from,
                    year_to=year_to,
                ):
                    results.append(paper)
                    if len(results) >= limit:
                        break
                logger.info(
                    f"[文献查询] 检索完成，数据源={src.source_name}，命中数={len(results)}"
                )
                for r in results:
                    all_results.append((src.source_name, r))
            except Exception as e:
                logger.warning(
                    f"[文献查询] 检索失败，数据源={src.source_name}，原因={str(e)}"
                )

        await client.aclose()

        # 规范化输出
        if parsed_args.output_format == "json":
            serialized = []
            for src_name, paper in all_results:
                d = paper.model_dump(mode="json")
                d["_source"] = src_name
                serialized.append(d)
            write_output(serialized, pretty=True)
        else:
            write_output(
                "========================================================================="
            )
            write_output(
                f"                          SPC 多路元数据搜索探测结果 (关键词: {query})"
            )
            write_output(
                "========================================================================="
            )
            if not all_results:
                write_output("未检索到匹配的文献数据。")
            else:
                for idx, (src_name, p) in enumerate(all_results, 1):
                    write_output(f"[{idx}] {p.title} ({p.year})")
                    write_output(
                        f"    DOI: {p.doi or 'N/A'} | PMID: {p.pubmed_id or 'N/A'} | arXiv: {p.arxiv_id or 'N/A'}"
                    )
                    write_output(
                        f"    来源数据源: {src_name} | 被引次数: {p.citation_count} | 数据库ID: {p.paper_id}"
                    )
                    write_output(
                        f"    发表源: {p.journal or p.venue or 'N/A'} | 出版商: {p.publisher or 'N/A'}"
                    )
                    write_output("-" * 73)
        return 0

    return asyncio.run(_search())


def run_get_relations(parsed_args, command_type: str) -> int:
    """拉取引用/被引关系文献列表。"""
    doi = parsed_args.doi
    pmid = parsed_args.pmid
    arxiv = parsed_args.arxiv
    limit = parsed_args.limit
    if not doi and not pmid and not arxiv:
        logger.error("[文献查询] 必须提供 --doi、--pmid 或 --arxiv 之一")
        return 1

    identifier = doi or pmid or arxiv
    id_type = "doi" if doi else ("pmid" if pmid else "arxiv")

    async def _fetch():
        client = create_async_client()
        sem = asyncio.Semaphore(1)

        # 默认只走 OpenAlex 和 Semantic Scholar，因为 PubMed 没有直接暴露引文接口
        sources = ["openalex", "semantic_scholar"]
        instances = []
        for s in sources:
            if s == "openalex":
                instances.append(OpenAlexSource(client, sem))
            elif s == "semantic_scholar":
                instances.append(SemanticScholarSource(client, sem))

        # 首先需要定位文献
        target_paper = None
        for src in instances:
            try:
                logger.info(
                    f"[文献查询] 定位核心文献，数据源={src.source_name}，标识符={identifier}"
                )
                record = await src.lookup(identifier, id_type)
                if record:
                    target_paper = record
                    logger.info(
                        f"[文献查询] 核心文献定位成功，标题={target_paper.title}"
                    )

                    if command_type == "get-references":
                        logger.info(
                            f"[文献查询] 获取参考文献，数据源={src.source_name}"
                        )
                        related_list = await src.get_references(target_paper)
                    else:
                        logger.info(
                            f"[文献查询] 获取施引文献，数据源={src.source_name}"
                        )
                        related_list = await src.get_citations(target_paper)

                    if related_list:
                        related_list = related_list[:limit]
                        for p in related_list:
                            p.doi = normalize_doi(p.doi)
                            p.arxiv_id = normalize_arxiv_id(p.arxiv_id)
                            p.pubmed_id = normalize_pmid(p.pubmed_id)
                            p.pmc_id = normalize_pmcid(p.pmc_id)
                            p.title = MetadataCleanPipeline.clean(p.title)
                            p.abstract = MetadataCleanPipeline.clean(p.abstract)

                        if parsed_args.output_format == "json":
                            serialized = [
                                p.model_dump(mode="json") for p in related_list
                            ]
                            write_output(serialized, pretty=True)
                        else:
                            rel_str = (
                                "引用参考文献"
                                if command_type == "get-references"
                                else "被引文献"
                            )
                            write_output(f"=== 目标论文: {target_paper.title} ===")
                            write_output(
                                f"=== 共获取到 {len(related_list)} 篇 {rel_str} (源: {src.source_name}) ==="
                            )
                            for i, p in enumerate(related_list, 1):
                                write_output(f"[{i}] {p.title} ({p.year})")
                                write_output(
                                    f"    DOI: {p.doi or 'N/A'} | PMID: {p.pubmed_id or 'N/A'}"
                                )
                                write_output(
                                    f"    发表源: {p.journal or p.venue or 'N/A'} | 被引次数: {p.citation_count}"
                                )
                                write_output("-" * 80)
                        await client.aclose()
                        return 0
            except Exception as e:
                logger.warning(
                    f"[文献查询] 引文关系获取失败，数据源={src.source_name}，原因={str(e)}"
                )

        await client.aclose()
        logger.error(f"[文献查询] 无法获取引文关系，标识符={identifier}")
        return 1

    return asyncio.run(_fetch())
