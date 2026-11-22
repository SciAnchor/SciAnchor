# -*- coding: utf-8 -*-
"""从 MinerU 正文提取代码仓并做客观可用性审计。"""

import os
import asyncio
from paperfetch.observability import get_event_logger
from typing import List

from paperfetch.core.action import BaseAction
from paperfetch.core.context import CuratorContext
from paperfetch.core.models import PaperRecord

logger = get_event_logger("paperfetch.core.code_audit")


def _audit_timeout_seconds() -> float:
    raw = str(os.getenv("SPC_CODE_AUDIT_TIMEOUT_SECONDS") or "30").strip()
    try:
        return max(0.1, float(raw))
    except ValueError:
        return 30.0


class CodeAuditAction(BaseAction):
    """读取 MinerU 解析后的 Markdown 提取论文代码库，并调用 GitHubAuditor 审计可用性。"""

    def __init__(self, enrich_top_k: int = 10, no_cache: bool = False):
        self.enrich_top_k = max(0, enrich_top_k)
        self.no_cache = no_cache

    async def execute(self, ctx: CuratorContext) -> None:
        logger.info(f"[代码审计] 启动代码库提取与审计，目标数={self.enrich_top_k}")
        audited_count = await self.audit_papers(ctx.top_seeds[: self.enrich_top_k])
        ctx.add_provenance(
            "CodeAuditAction",
            f"代码复现性核验完成。已审计 {audited_count} 篇论文的代码链接。",
        )

    async def audit_papers(self, papers: List[PaperRecord]) -> int:
        token = os.getenv("GITHUB_TOKEN")

        from paperfetch.core.repro_auditor import GitHubAuditor, extract_code_urls

        auditor = GitHubAuditor(github_token=token)
        sem = asyncio.Semaphore(3)

        audited_count_box = [0]
        count_lock = asyncio.Lock()

        async def audit_single_paper(paper: PaperRecord) -> None:
            async with sem:
                status = paper.fulltext_status

                if self.no_cache:
                    status.reproducibility_status = None
                    status.extracted_code_url = None
                    status.repo_metadata = {}
                    paper.curation_signals.pop("reproducibility_status", None)
                    paper.curation_signals.pop("extracted_code_url", None)
                    paper.curation_signals.pop("repo_metadata", None)

                if status.reproducibility_status not in (None, "unchecked", ""):
                    return

                status.reproducibility_status = "auditing"

                markdown_content = ""
                if status.mineru_status == "parsed" and status.mineru_markdown_path:
                    if os.path.exists(status.mineru_markdown_path):
                        try:

                            def _read():
                                with open(
                                    status.mineru_markdown_path, "r", encoding="utf-8"
                                ) as f:
                                    return f.read()

                            markdown_content = await asyncio.to_thread(_read)
                        except Exception as exc:
                            logger.warning(
                                f"[代码审计] Markdown 读取失败，路径={status.mineru_markdown_path}，原因={exc}"
                            )

                extracted_urls = extract_code_urls(
                    markdown_content, mineru_dir=status.mineru_extracted_dir
                )

                if not extracted_urls and paper.curation_signals.get("code_url"):
                    extracted_urls.append(paper.curation_signals.get("code_url"))

                if not extracted_urls and (paper.doi or paper.arxiv_id):
                    identifier = paper.doi or paper.arxiv_id
                    id_type = "doi" if paper.doi else "arxiv"
                    logger.info(
                        f"[代码审计] 本地正文无代码链接，改用在线元数据，标识符={identifier}"
                    )
                    try:
                        from paperfetch.utils.client import create_async_client
                        from paperfetch.sources.openalex import OpenAlexSource
                        from paperfetch.sources.semantic_scholar import (
                            SemanticScholarSource,
                        )

                        async def fetch_meta():
                            async with create_async_client() as client:
                                inner_sem = asyncio.Semaphore(1)
                                oa = OpenAlexSource(client, inner_sem)
                                rec = await oa.lookup(identifier, id_type)
                                if not rec:
                                    s2 = SemanticScholarSource(client, inner_sem)
                                    rec = await s2.lookup(identifier, id_type)
                                return rec

                        record = await fetch_meta()
                        if record:
                            target_code = record.curation_signals.get("code_url")
                            if not target_code:
                                extracted = extract_code_urls(record.abstract or "")
                                if extracted:
                                    target_code = extracted[0]
                            if target_code:
                                extracted_urls.append(target_code)
                                logger.info(
                                    f"[代码审计] 从元数据发现代码地址，URL={target_code}"
                                )
                    except Exception as lookup_err:
                        logger.warning(
                            f"[代码审计] 元数据反查失败，标识符={identifier}，原因={lookup_err}"
                        )

                if not extracted_urls:
                    status.reproducibility_status = "no_code_link"
                    status.repo_metadata = {}
                    logger.info(
                        f"[代码审计] 未匹配到代码地址，标题={paper.title[:20]!r}"
                    )
                    return

                try:
                    audit_tasks = [auditor.audit_url(url) for url in extracted_urls]
                    audit_results = await asyncio.gather(
                        *audit_tasks, return_exceptions=True
                    )

                    all_audits = {}
                    primary_url = None
                    primary_status = None
                    primary_meta = {}

                    for url, res in zip(extracted_urls, audit_results):
                        if isinstance(res, Exception):
                            logger.warning(
                                f"[代码审计] 链接审计失败，URL={url}，原因={res}"
                            )
                            url_status, url_meta = (
                                "unchecked",
                                {"error": str(res), "url": url},
                            )
                        else:
                            url_status, url_meta = res

                        all_audits[url] = {"status": url_status, "metadata": url_meta}

                        category = url_meta.get("category", "code_repository")
                        if primary_url is None:
                            primary_url = url
                            primary_status = url_status
                            primary_meta = url_meta
                        elif (
                            category == "code_repository"
                            and primary_meta.get("category") != "code_repository"
                        ):
                            primary_url = url
                            primary_status = url_status
                            primary_meta = url_meta

                    status.extracted_code_url = primary_url
                    status.reproducibility_status = primary_status

                    repo_meta = {
                        "primary_url": primary_url,
                        "platform": primary_meta.get("platform", "github"),
                        "category": primary_meta.get("category", "code_repository"),
                        "all_extracted_urls": extracted_urls,
                        "repo_audits": all_audits,
                    }
                    if primary_meta.get("platform") == "github":
                        repo_meta.update(
                            {
                                "owner": primary_meta.get("owner"),
                                "repo": primary_meta.get("repo"),
                                "stars": primary_meta.get("stars", 0),
                                "is_fork": primary_meta.get("is_fork", False),
                                "last_pushed": primary_meta.get("last_pushed"),
                                "detected_configs": primary_meta.get(
                                    "detected_configs", []
                                ),
                                "has_entry_script": primary_meta.get(
                                    "has_entry_script", False
                                ),
                                "inventory_file_count": primary_meta.get(
                                    "inventory_file_count", 0
                                ),
                                "code_file_count": primary_meta.get(
                                    "code_file_count", 0
                                ),
                                "notebook_count": primary_meta.get("notebook_count", 0),
                                "entrypoint_count": primary_meta.get(
                                    "entrypoint_count", 0
                                ),
                                "inventory_digest": primary_meta.get(
                                    "inventory_digest"
                                ),
                                "inventory_source": primary_meta.get(
                                    "inventory_source"
                                ),
                                "inventory_complete": primary_meta.get(
                                    "inventory_complete", False
                                ),
                            }
                        )

                    status.repo_metadata = repo_meta

                    paper.curation_signals["reproducibility_status"] = primary_status
                    paper.curation_signals["extracted_code_url"] = primary_url
                    paper.curation_signals["repo_metadata"] = repo_meta

                    logger.info(
                        f"[代码审计] 完成，标题={paper.title[:20]!r}，状态={primary_status}，链接数={len(extracted_urls)}"
                    )
                    async with count_lock:
                        audited_count_box[0] += 1
                except Exception as exc:
                    logger.warning(
                        f"[代码审计] 执行失败，标题={paper.title[:20]!r}，原因={exc}"
                    )
                    status.reproducibility_status = "unchecked"
                    target_url = extracted_urls[0] if extracted_urls else "unknown"
                    status.repo_metadata = {"error": str(exc), "url": target_url}

        timeout_seconds = _audit_timeout_seconds()

        async def audit_with_deadline(paper: PaperRecord) -> None:
            task = asyncio.create_task(audit_single_paper(paper))
            done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
            if task in done:
                await task
                return

            task.cancel()
            cancelled, _ = await asyncio.wait({task}, timeout=1.0)
            if task not in cancelled:
                task.add_done_callback(
                    lambda completed: (
                        completed.exception() if not completed.cancelled() else None
                    )
                )

            status = paper.fulltext_status
            status.reproducibility_status = "unchecked"
            status.repo_metadata = {
                "error_class": "audit_timeout",
                "stage": "code_audit",
                "timeout_seconds": timeout_seconds,
            }
            paper.curation_signals["reproducibility_status"] = "unchecked"
            paper.curation_signals["repo_metadata"] = status.repo_metadata
            logger.warning(
                "[代码审计] 超过单篇有界预算，保留全文成功并结束可选审计，标题=%r，预算=%ss",
                paper.title[:20],
                timeout_seconds,
            )

        await asyncio.gather(*[audit_with_deadline(paper) for paper in papers])
        return audited_count_box[0]
