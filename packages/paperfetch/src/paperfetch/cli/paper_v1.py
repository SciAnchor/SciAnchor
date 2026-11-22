"""SPC 2.0 `paper` 命令；领域内核继续复用稳定内部契约。"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from paperfetch.core.contracts_v1 import (
    BusinessStatus,
    CommandItem,
    CommandResult,
    CommandSummary,
    EntityRef,
    ErrorInfo,
)
from paperfetch.cli.projections import paper_command_data
from paperfetch.observability import current_run_id, write_output
from paperfetch.seedpacks.repository import SeedPackError, SeedPackRepository
from paperfetch.papers.lookup import LookupRequest, PaperLookupError, PaperLookupService
from paperfetch.utils.client import (
    create_metadata_client,
    metadata_fallback_proxy_configured,
    hosts_use_tun_fake_ip,
)


def request_from_args(args) -> LookupRequest:
    selected = [
        ("doi", getattr(args, "doi", None)),
        ("pubmed_id", getattr(args, "pubmed_id", None)),
        ("pmc_id", getattr(args, "pmc_id", None)),
        ("arxiv_id", getattr(args, "arxiv_id", None)),
    ]
    [(identifier_type, value)] = [(kind, value) for kind, value in selected if value]
    return LookupRequest.normalize(identifier_type, value)


def _lookup_error_result(
    command: str, request: LookupRequest | None, exc: PaperLookupError, started: float
) -> CommandResult:
    error = ErrorInfo(
        code=exc.code,
        error_class=exc.error_class,
        stage="metadata_lookup",
        retryable=exc.retryable,
        message=str(exc),
        remediation="核对标识后重试；网络错误可稍后重试"
        if exc.retryable
        else "核对论文标识与来源",
    )
    item = None
    if request is not None:
        item = CommandItem(
            entity=EntityRef(type="paper_identifier", id=request.display_id),
            status=BusinessStatus.FAILED,
            error=error,
        )
    return CommandResult(
        command=command,
        run_id=current_run_id() or uuid.uuid4().hex,
        status=BusinessStatus.FAILED,
        summary=CommandSummary(
            selected=1,
            failed=1,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        items=[item] if item else [],
        error=error,
    )


async def build_paper_lookup_result(args) -> CommandResult:
    started = time.perf_counter()
    request: LookupRequest | None = None
    try:
        request = request_from_args(args)
        record, _metadata_transport = await _lookup_with_transport_fallback(request)
    except PaperLookupError as exc:
        return _lookup_error_result("paper.lookup", request, exc, started)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return CommandResult(
        command="paper.lookup",
        run_id=current_run_id() or uuid.uuid4().hex,
        status=BusinessStatus.COMPLETED,
        summary=CommandSummary(selected=1, succeeded=1, elapsed_ms=elapsed_ms),
        items=[
            CommandItem(
                entity=EntityRef(type="paper", id=record.paper_id),
                status=BusinessStatus.COMPLETED,
                data=paper_command_data(record, include_download=False),
            )
        ],
        metrics={"metadata_source_count": len(record.provenance.sources)},
    )


async def _lookup_with_transport_fallback(request: LookupRequest):
    direct_error: PaperLookupError | None = None
    hosts = (
        ("export.arxiv.org", "api.crossref.org")
        if request.identifier_type == "arxiv_id"
        else ("www.ebi.ac.uk", "api.crossref.org")
    )
    skip_direct = metadata_fallback_proxy_configured() and hosts_use_tun_fake_ip(hosts)
    if not skip_direct:
        async with create_metadata_client() as client:
            try:
                return await PaperLookupService(client).lookup(request), getattr(
                    client, "_spc_transport", "direct"
                )
            except PaperLookupError as exc:
                if exc.code != "metadata_transport_failed":
                    raise
                direct_error = exc
    async with create_metadata_client(metadata_proxy_fallback=True) as client:
        if getattr(client, "_spc_transport", "direct") != "metadata-proxy-fallback":
            if direct_error is not None:
                raise direct_error
            raise PaperLookupError(
                "metadata_transport_failed",
                "network_error",
                "官方元数据服务本轮不可用，无法确认论文身份",
                retryable=True,
            )
        return await PaperLookupService(client).lookup(
            request
        ), "metadata-proxy-fallback"


def _skip_parse(args) -> bool:
    return bool(getattr(args, "no_parse", False))


async def build_paper_download_result(args) -> CommandResult:
    from paperfetch.fulltext.workflow import PaperFileWorkflow
    from paperfetch.cli.projections import file_item_projection
    from paperfetch.cli.seed_pack_v1 import _record_from_file_outcome

    started = time.perf_counter()
    request: LookupRequest | None = None
    repository: SeedPackRepository | None = None
    try:
        request = request_from_args(args)
        record, _metadata_transport = await _lookup_with_transport_fallback(request)
        repository = SeedPackRepository.initialize(args.output_dir, name="单篇论文")
        repository.add([record])
        outcome = await PaperFileWorkflow().run(
            paper=record,
            seed_pack=repository.root,
            no_cache=bool(getattr(args, "no_cache", False)),
            download_only=_skip_parse(args),
            route_mode=getattr(args, "route", "auto"),
        )
        persisted = _record_from_file_outcome(record, outcome)
        snapshot = repository.replace([persisted])
        reloaded = next(
            item for item in snapshot.papers if item.paper_id == record.paper_id
        )
    except PaperLookupError as exc:
        return _lookup_error_result("paper.download", request, exc, started)
    except SeedPackError as exc:
        error = ErrorInfo(
            code=exc.code,
            error_class="state_error",
            stage=exc.stage,
            retryable=False,
            message=str(exc),
            remediation="使用新的空输出目录后重试",
        )
        return CommandResult(
            command="paper.download",
            run_id=current_run_id() or uuid.uuid4().hex,
            status=BusinessStatus.REJECTED,
            summary=CommandSummary(
                selected=1,
                failed=1,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            ),
            error=error,
        )
    refs, data = file_item_projection(reloaded, outcome, repository.root)
    item_status = (
        BusinessStatus.COMPLETED
        if outcome.error is None
        else BusinessStatus.PARTIAL
        if outcome.partial
        else BusinessStatus.FAILED
    )
    result_status = item_status
    return CommandResult(
        command="paper.download",
        run_id=current_run_id() or uuid.uuid4().hex,
        status=result_status,
        summary=CommandSummary(
            selected=1,
            succeeded=1 if item_status == BusinessStatus.COMPLETED.value else 0,
            partial=1 if item_status == BusinessStatus.PARTIAL.value else 0,
            failed=1 if item_status == BusinessStatus.FAILED.value else 0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        items=[
            CommandItem(
                entity=EntityRef(type="paper", id=reloaded.paper_id),
                status=item_status,
                artifacts=refs,
                data=data,
                error=outcome.error,
                audit_ref=outcome.audit_refs[-1] if outcome.audit_refs else None,
            )
        ],
        error=outcome.error,
        audit_ref=outcome.error.audit_ref if outcome.error else None,
    )


async def build_paper_parse_result(args) -> CommandResult:
    from paperfetch.fulltext.file_parse import FileParseService
    from paperfetch.cli.projections import parse_item_projection

    started = time.perf_counter()
    outcome = await FileParseService().parse(
        pdf=Path(args.pdf),
        output_dir=Path(args.output_dir),
        no_cache=bool(getattr(args, "no_cache", False)),
    )
    refs, data = parse_item_projection(outcome)
    item_status = (
        BusinessStatus.COMPLETED if outcome.succeeded else BusinessStatus.FAILED
    )
    entity_id = outcome.input_sha256 or Path(args.pdf).name
    return CommandResult(
        command="paper.parse",
        run_id=current_run_id() or uuid.uuid4().hex,
        status=item_status,
        summary=CommandSummary(
            selected=1,
            succeeded=1 if outcome.succeeded else 0,
            failed=0 if outcome.succeeded else 1,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        items=[
            CommandItem(
                entity=EntityRef(type="pdf_file", id=entity_id),
                status=item_status,
                artifacts=refs,
                data=data,
                error=outcome.error,
                audit_ref=outcome.audit_ref,
            )
        ],
        error=outcome.error,
        audit_ref=outcome.error.audit_ref if outcome.error else outcome.audit_ref,
    )


def _candidate_page_result(
    command: str, page, *, started: float, item_type: str
) -> CommandResult:
    candidates = page.candidates
    source_errors = page.source_errors
    items = [
        CommandItem(
            entity=EntityRef(type=item_type, id=candidate.doi or candidate.title),
            status=BusinessStatus.COMPLETED,
            data=candidate.to_dict(),
        )
        for candidate in candidates
    ]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if not candidates and source_errors:
        error = ErrorInfo(
            code="metadata_sources_failed",
            error_class="network_error",
            stage="paper_search" if command == "paper.search" else "paper_graph",
            retryable=True,
            message="；".join(
                f"{name}: {detail}" for name, detail in source_errors.items()
            ),
            remediation="稍后重试；并行检索请 --detach 后使用 job wait 收取终局",
        )
        return CommandResult(
            command=command,
            run_id=current_run_id() or uuid.uuid4().hex,
            status=BusinessStatus.FAILED,
            summary=CommandSummary(selected=0, failed=0, elapsed_ms=elapsed_ms),
            items=[],
            error=error,
            metrics={"result_count": 0, "source_error_count": len(source_errors)},
        )
    metrics: dict[str, int | float] = {"result_count": len(candidates)}
    if command == "paper.graph":
        metrics["connected_count"] = len(candidates)
    if source_errors:
        metrics["source_error_count"] = len(source_errors)
    return CommandResult(
        command=command,
        run_id=current_run_id() or uuid.uuid4().hex,
        status=BusinessStatus.COMPLETED,
        summary=CommandSummary(
            selected=len(candidates),
            succeeded=len(candidates),
            elapsed_ms=elapsed_ms,
        ),
        items=items,
        metrics=metrics,
    )


async def build_paper_search_result(args) -> CommandResult:
    """构建 `paper search` 命令的标准业务结果。"""
    from paperfetch.papers.search import PaperSearchEngine

    started = time.perf_counter()
    ccf_ranks = [
        r.strip() for r in (args.ccf_rank or "").split(",") if r.strip()
    ] or None
    cas_zones = [
        int(z.strip()) for z in (args.cas_zone or "").split(",") if z.strip().isdigit()
    ] or None
    if cas_zones:
        from paperfetch.core.metadata_signals import journal_master_status

        cas_status = journal_master_status()
        if not cas_status["ready"]:
            # 中科院分区为受限数据，公开版不内置；未配置时拒绝过滤，而不是静默返回空结果。
            return CommandResult(
                command="paper.search",
                run_id=current_run_id() or uuid.uuid4().hex,
                status=BusinessStatus.REJECTED,
                summary=CommandSummary(
                    elapsed_ms=int((time.perf_counter() - started) * 1000)
                ),
                error=ErrorInfo(
                    code="cas_zone_not_configured"
                    if cas_status["error_class"] == "not_configured"
                    else "cas_zone_unavailable",
                    error_class=str(cas_status["error_class"]),
                    stage="input_validation",
                    message=f"--cas-zone 需要用户自备的期刊主库，{cas_status['env']} 未配置或不可用",
                    remediation=f"设置 {cas_status['env']} 指向 journal_master.db，或去掉 --cas-zone",
                ),
            )

    engine = PaperSearchEngine()
    page = await engine.search(
        query=args.query,
        limit=args.limit,
        min_year=args.min_year,
        ccf_ranks=ccf_ranks,
        cas_zones=cas_zones,
        min_citations=args.min_citations,
    )
    return _candidate_page_result(
        "paper.search", page, started=started, item_type="paper_candidate"
    )


async def build_paper_graph_result(args) -> CommandResult:
    """构建 `paper graph` 命令的标准业务结果。"""
    from paperfetch.papers.search import PaperGraphEngine

    started = time.perf_counter()
    engine = PaperGraphEngine()
    page = await engine.explore(
        doi=args.doi,
        direction=args.direction,
        limit=args.limit,
        min_year=args.min_year,
    )
    return _candidate_page_result(
        "paper.graph", page, started=started, item_type="paper_graph_node"
    )


def run_paper(args) -> int:
    import asyncio

    action = getattr(args, "paper_action", None)
    if action == "sciverse":
        from paperfetch.cli.lookup import run_sciverse_search

        return run_sciverse_search(args)
    if action == "lookup":
        coro = build_paper_lookup_result(args)
    elif action == "download":
        coro = build_paper_download_result(args)
    elif action == "parse":
        coro = build_paper_parse_result(args)
    elif action == "search":
        coro = build_paper_search_result(args)
    elif action == "graph":
        coro = build_paper_graph_result(args)
    else:
        raise ValueError(f"未知的 paper 操作: {action}")

    result = asyncio.run(coro)
    write_output(result.model_dump(mode="json"), pretty=True)
    return (
        0
        if result.status == BusinessStatus.COMPLETED.value
        else 2
        if result.status == BusinessStatus.PARTIAL.value
        else 1
    )


def register_paper_commands(subparsers):
    """注册 paper lookup/download/parse/search/graph。"""
    paper_parser = subparsers.add_parser(
        "paper", help="按标识检索、反查、下载，或对本地 PDF 做物理解析"
    )
    paper_subparsers = paper_parser.add_subparsers(dest="paper_action", required=True)
    paper_lookup_parser = paper_subparsers.add_parser(
        "lookup", help="按 DOI、PMID、PMCID 或 arXiv 精确查询元数据"
    )
    paper_lookup_identifiers = paper_lookup_parser.add_mutually_exclusive_group(
        required=True
    )
    paper_lookup_identifiers.add_argument("--doi")
    paper_lookup_identifiers.add_argument("--pubmed-id", dest="pubmed_id")
    paper_lookup_identifiers.add_argument("--pmc-id", dest="pmc_id")
    paper_lookup_identifiers.add_argument("--arxiv-id", dest="arxiv_id")
    paper_lookup_parser.add_argument(
        "--detach", action="store_true", help="后台可靠等待元数据终局并立即返回 job_id"
    )
    paper_lookup_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    paper_download_parser = paper_subparsers.add_parser(
        "download",
        help="反查元数据，在输出目录建单篇包，下载并校验 PDF，默认再解析正文",
    )
    paper_download_identifiers = paper_download_parser.add_mutually_exclusive_group(
        required=True
    )
    paper_download_identifiers.add_argument("--doi")
    paper_download_identifiers.add_argument("--pubmed-id", dest="pubmed_id")
    paper_download_identifiers.add_argument("--pmc-id", dest="pmc_id")
    paper_download_identifiers.add_argument("--arxiv-id", dest="arxiv_id")
    paper_download_parser.add_argument("--output-dir", required=True)
    paper_download_parser.add_argument(
        "--no-parse", action="store_true", help="只保存已验证 PDF，不解析正文"
    )
    paper_download_parser.add_argument(
        "--no-cache", action="store_true", help="禁用缓存，强制重新下载"
    )
    paper_download_parser.add_argument(
        "--route",
        choices=["auto", "public"],
        default="auto",
        help="下载路线；公开版仅含开放获取与官方 API 路线，auto 与 public 等价",
    )
    paper_download_parser.add_argument(
        "--detach", action="store_true", help="后台运行并立即返回 job_id"
    )
    paper_download_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )

    paper_parse_parser = paper_subparsers.add_parser(
        "parse",
        help="对本地 PDF 做 MinerU 物理解析；不校验论文身份，也不写入 papers.jsonl",
        description="对本地 PDF 做 MinerU 物理解析。不校验论文身份，不写入 papers.jsonl。解析成功不是论文正文事实。",
    )
    paper_parse_parser.add_argument("--pdf", required=True, help="本地 PDF 路径")
    paper_parse_parser.add_argument(
        "--output-dir", required=True, help="解析产物目录，不是 Seed Pack"
    )
    paper_parse_parser.add_argument(
        "--no-cache", action="store_true", help="禁用解析缓存，强制重新解析"
    )
    paper_parse_parser.add_argument(
        "--detach", action="store_true", help="后台可靠等待解析终局并立即返回 job_id"
    )
    paper_parse_parser.add_argument("--output-format", choices=["json"], default="json")

    paper_search_parser = paper_subparsers.add_parser(
        "search", help="根据关键词多源并发检索学术文献并富化 CCF/CAS 评价指标"
    )
    paper_search_parser.add_argument(
        "--query", required=True, help="检索关键词或研究主题设想"
    )
    paper_search_parser.add_argument(
        "--limit", type=int, default=10, help="返回文献条数，默认 10"
    )
    paper_search_parser.add_argument(
        "--min-year", type=int, default=None, help="最低发表年份 (如 2024)"
    )
    paper_search_parser.add_argument(
        "--ccf-rank", default=None, help="期望的 CCF 分区 (逗号分隔，如 A,B)"
    )
    paper_search_parser.add_argument(
        "--cas-zone",
        default=None,
        help="期望的中科院分区 (逗号分隔，如 1,2)；需设置 SPC_JOURNAL_MASTER_DB 指向自备期刊主库",
    )
    paper_search_parser.add_argument(
        "--min-citations", type=int, default=0, help="最小被引次数"
    )
    paper_search_parser.add_argument(
        "--detach", action="store_true", help="后台可靠等待检索终局并立即返回 job_id"
    )
    paper_search_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )

    paper_graph_parser = paper_subparsers.add_parser(
        "graph", help="基于种子论文 DOI 展开参考文献溯源、施引文献追踪或相似文献探索"
    )
    paper_graph_parser.add_argument("--doi", required=True, help="种子论文 DOI")
    paper_graph_parser.add_argument(
        "--direction",
        choices=["references", "citations", "similar"],
        default="references",
        help="拓扑探索方向：references (查参考文献), citations (查施引文献), similar (查相似文献)",
    )
    paper_graph_parser.add_argument(
        "--limit", type=int, default=15, help="返回文献条数，默认 15"
    )
    paper_graph_parser.add_argument(
        "--min-year", type=int, default=None, help="最低发表年份"
    )
    paper_graph_parser.add_argument(
        "--detach", action="store_true", help="后台可靠等待拓扑终局并立即返回 job_id"
    )
    paper_graph_parser.add_argument("--output-format", choices=["json"], default="json")
    sciverse_parser = paper_subparsers.add_parser(
        "sciverse", help="使用 Sciverse 语义检索或分段读取正文"
    )
    sciverse_parser.add_argument("--query", default=None, help="语义检索词")
    sciverse_parser.add_argument("--doc-id", default=None, help="文献唯一 ID")
    sciverse_parser.add_argument("--top-k", type=int, default=3)
    sciverse_parser.add_argument("--limit", type=int, default=2000)
    sciverse_parser.add_argument("--offset", type=int, default=0)
    sciverse_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    return [
        paper_lookup_parser,
        paper_download_parser,
        paper_parse_parser,
        paper_search_parser,
        paper_graph_parser,
        sciverse_parser,
    ]
