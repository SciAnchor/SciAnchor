"""SPC 2.0 `seed-pack` 命令；durable Seed Pack 格式保持兼容。"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from paperfetch.fulltext.workflow import PaperFileOutcome, PaperFileWorkflow
from paperfetch.cli.paper_v1 import _lookup_with_transport_fallback
from paperfetch.cli.projections import file_item_projection, paper_command_data
from paperfetch.core.contracts_v1 import (
    ArtifactRef,
    BusinessStatus,
    CommandItem,
    CommandResult,
    CommandSummary,
    EntityRef,
    ErrorInfo,
)
from paperfetch.observability import current_run_id, write_output
from paperfetch.papers.lookup import LookupRequest, PaperLookupError
from paperfetch.papers.models import (
    FulltextState,
    PaperRecord,
    ParseTerminal,
    PdfTerminal,
)
from paperfetch.seedpacks.repository import SeedPackError, SeedPackRepository


def _seed_pack_error(
    code: str, message: str, *, stage: str, retryable: bool = False
) -> ErrorInfo:
    error_class = {
        "unsupported_legacy_seed_pack": "format_unsupported",
        "seed_pack_not_found": "resource_not_found",
        "seed_pack_lock_timeout": "state_conflict",
        "duplicate_strong_identifier": "identity_conflict",
    }.get(code, "state_error")
    return ErrorInfo(
        code=code,
        error_class=error_class,
        stage=stage,
        retryable=retryable,
        message=message,
        remediation=(
            "使用新的空目录初始化 SPC 1.0 Seed Pack；不要直接混写 0.x 文件"
            if code == "unsupported_legacy_seed_pack"
            else "核对 Seed Pack 路径和当前记录后重试"
        ),
    )


def _result_for_seed_pack_error(
    command: str, root: str, exc: SeedPackError, started: float
) -> CommandResult:
    error = _seed_pack_error(
        exc.code,
        str(exc),
        stage=exc.stage,
        retryable=exc.code == "seed_pack_lock_timeout",
    )
    return CommandResult(
        command=command,
        run_id=current_run_id() or uuid.uuid4().hex,
        status=BusinessStatus.REJECTED,
        summary=CommandSummary(
            selected=1, failed=1, elapsed_ms=int((time.perf_counter() - started) * 1000)
        ),
        items=[
            CommandItem(
                entity=EntityRef(type="seed_pack", id=str(Path(root).resolve())),
                status=BusinessStatus.REJECTED,
                error=error,
            )
        ],
        error=error,
    )


def _seed_pack_status_data(snapshot, root: Path) -> dict:
    papers = snapshot.papers
    return {
        "seed_pack_id": snapshot.manifest.seed_pack_id,
        "name": snapshot.manifest.name,
        "path": str(root),
        "paper_count": len(papers),
        "verified_pdf_count": sum(
            item.fulltext.pdf.status == "available" for item in papers
        ),
        "mineru_markdown_count": sum(
            item.fulltext.parse.status == "available" for item in papers
        ),
        "pdf_failure_count": sum(
            item.fulltext.pdf.status == "failed" for item in papers
        ),
        "parse_failure_count": sum(
            item.fulltext.parse.status == "failed" for item in papers
        ),
        "file_manifest_count": snapshot.artifact_count,
        "pdf_routes": {
            route: sum(1 for item in papers if item.fulltext.pdf.route == route)
            for route in sorted(
                {item.fulltext.pdf.route for item in papers if item.fulltext.pdf.route}
            )
        },
    }


def _requests_from_args(args) -> list[LookupRequest]:
    values = [
        *(LookupRequest.normalize("doi", value) for value in args.doi),
        *(LookupRequest.normalize("pubmed_id", value) for value in args.pubmed_id),
        *(LookupRequest.normalize("pmc_id", value) for value in args.pmc_id),
        *(LookupRequest.normalize("arxiv_id", value) for value in args.arxiv_id),
    ]
    if not values:
        raise PaperLookupError(
            "identifier_required",
            "invalid_input",
            "至少提供一个 DOI、PMID、PMCID 或 arXiv 标识",
            retryable=False,
        )
    seen: set[tuple[str, str]] = set()
    result: list[LookupRequest] = []
    for item in values:
        key = (item.identifier_type, item.value.casefold())
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


async def _build_add_result(args) -> CommandResult:
    started = time.perf_counter()
    command = "seed-pack.add"
    try:
        requests = _requests_from_args(args)
    except PaperLookupError as exc:
        error = ErrorInfo(
            code=exc.code,
            error_class=exc.error_class,
            stage="input",
            retryable=False,
            message=str(exc),
            remediation="提供至少一个受支持的论文标识",
        )
        return CommandResult(
            command=command,
            run_id=current_run_id() or uuid.uuid4().hex,
            status=BusinessStatus.REJECTED,
            summary=CommandSummary(
                selected=1,
                failed=1,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            ),
            error=error,
        )
    try:
        repository = SeedPackRepository(args.seed_pack)
        # 在联网前拒绝旧包或错误目录，避免无意义请求。
        repository.load(probe_artifacts=True)
    except SeedPackError as exc:
        return _result_for_seed_pack_error(command, args.seed_pack, exc, started)
    outcomes = []
    for request in requests:
        try:
            record, _transport = await _lookup_with_transport_fallback(request)
            outcomes.append(record)
        except PaperLookupError as exc:
            outcomes.append(exc)
    failures = [
        outcome for outcome in outcomes if isinstance(outcome, PaperLookupError)
    ]
    if failures:
        items: list[CommandItem] = []
        first_error: ErrorInfo | None = None
        for request, outcome in zip(requests, outcomes, strict=True):
            if isinstance(outcome, PaperLookupError):
                error = ErrorInfo(
                    code=outcome.code,
                    error_class=outcome.error_class,
                    stage="metadata_lookup",
                    retryable=outcome.retryable,
                    message=str(outcome),
                )
                first_error = first_error or error
            else:
                error = ErrorInfo(
                    code="atomic_batch_aborted",
                    error_class="atomicity_guard",
                    stage="metadata_persist",
                    retryable=True,
                    message="同批次其他标识解析失败，本篇元数据未写入 Seed Pack",
                    remediation="修正失败标识后原样重试整个批次",
                )
            items.append(
                CommandItem(
                    entity=EntityRef(type="paper_identifier", id=request.display_id),
                    status=BusinessStatus.REJECTED,
                    data={"persisted": False},
                    error=error,
                )
            )
        top_error = ErrorInfo(
            code="atomic_metadata_batch_failed",
            error_class="atomicity_guard",
            stage="metadata_lookup",
            retryable=any(item.retryable for item in failures),
            message=f"{len(failures)} 个论文标识未能解析；Seed Pack 保持不变",
            remediation="处理 items 中的具体错误后重试",
        )
        return CommandResult(
            command=command,
            run_id=current_run_id() or uuid.uuid4().hex,
            status=BusinessStatus.FAILED,
            summary=CommandSummary(
                selected=len(requests),
                failed=len(requests),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            ),
            items=items,
            error=top_error,
        )
    records = list(outcomes)
    try:
        snapshot = repository.add(
            records, lock_timeout_seconds=args.lock_timeout_seconds
        )
    except SeedPackError as exc:
        error_result = _result_for_seed_pack_error(
            command, args.seed_pack, exc, started
        )
        error_result.summary = CommandSummary(
            selected=len(requests),
            failed=len(requests),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        error_result.items = [
            CommandItem(
                entity=EntityRef(type="paper_identifier", id=request.display_id),
                status=BusinessStatus.REJECTED,
                data={"persisted": False},
                error=error_result.error,
            )
            for request in requests
        ]
        return error_result
    reloaded_by_id = {item.paper_id: item for item in snapshot.papers}
    return CommandResult(
        command=command,
        run_id=current_run_id() or uuid.uuid4().hex,
        status=BusinessStatus.COMPLETED,
        summary=CommandSummary(
            selected=len(records),
            succeeded=len(records),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        items=[
            CommandItem(
                entity=EntityRef(type="paper", id=record.paper_id),
                status=BusinessStatus.COMPLETED,
                data=paper_command_data(
                    reloaded_by_id[record.paper_id], persisted=True
                ),
            )
            for record in records
        ],
        artifacts=[
            ArtifactRef(kind="seed_pack_papers", path=str(repository.papers_path))
        ],
        metrics={"seed_pack_paper_count": len(snapshot.papers)},
    )


def _matches_request(record: PaperRecord, request: LookupRequest) -> bool:
    value = getattr(record.identifiers, request.identifier_type)
    return value is not None and value.casefold() == request.value.casefold()


def _select_enrich_records(args, records: tuple[PaperRecord, ...]) -> list[PaperRecord]:
    requests = (
        _requests_from_args(args)
        if any((args.doi, args.pubmed_id, args.pmc_id, args.arxiv_id))
        else []
    )
    if not requests:
        selected = list(records)
    else:
        selected = [
            record
            for record in records
            if any(_matches_request(record, request) for request in requests)
        ]
        unmatched = [
            request.display_id
            for request in requests
            if not any(_matches_request(record, request) for record in records)
        ]
        if unmatched:
            raise SeedPackError(
                "paper_not_found", "Seed Pack 中未找到请求的论文标识", stage="select"
            )
    if args.failed_only:
        selected = [
            record
            for record in selected
            if record.fulltext.pdf.status == "failed"
            or record.fulltext.parse.status == "failed"
        ]
    elif args.parse_only:
        selected = [
            record for record in selected if record.fulltext.parse.status != "available"
        ]
    elif args.download_only:
        selected = [
            record for record in selected if record.fulltext.pdf.status != "available"
        ]
    else:
        selected = [
            record for record in selected if record.fulltext.parse.status != "available"
        ]
    return selected


def _record_from_file_outcome(
    record: PaperRecord, outcome: PaperFileOutcome
) -> PaperRecord:
    pdf = record.fulltext.pdf
    parse = record.fulltext.parse
    if outcome.pdf is not None:
        pdf = PdfTerminal(
            status="available",
            artifact=outcome.pdf,
            identity=outcome.identity,
            route=outcome.successful_route or record.fulltext.pdf.route,
        )
    elif outcome.pdf_error is not None:
        pdf = PdfTerminal(status="failed", error=outcome.pdf_error)
    if outcome.fulltext is not None:
        parse = ParseTerminal(status="available", artifact=outcome.fulltext)
    elif outcome.parse_error is not None:
        parse = ParseTerminal(status="failed", error=outcome.parse_error)
    return PaperRecord.model_validate(
        record.model_copy(
            update={
                "revision": record.revision + 1,
                "updated_at": datetime.now(timezone.utc),
                "fulltext": FulltextState(pdf=pdf, parse=parse),
            }
        ).model_dump(mode="python")
    )


def _file_item_data(
    record: PaperRecord,
    outcome: PaperFileOutcome,
    seed_pack: Path,
) -> tuple[list[ArtifactRef], dict]:
    return file_item_projection(record, outcome, seed_pack)


async def _build_enrich_result(args) -> CommandResult:
    started = time.perf_counter()
    command = "seed-pack.enrich"
    repository = SeedPackRepository(args.seed_pack)
    try:
        snapshot = repository.load(probe_artifacts=True)
        selected = _select_enrich_records(args, snapshot.papers)
    except (SeedPackError, PaperLookupError) as exc:
        if isinstance(exc, PaperLookupError):
            error = ErrorInfo(
                code=exc.code,
                error_class=exc.error_class,
                stage="select",
                retryable=False,
                message=str(exc),
            )
            return CommandResult(
                command=command,
                run_id=current_run_id() or uuid.uuid4().hex,
                status=BusinessStatus.REJECTED,
                summary=CommandSummary(selected=1, failed=1),
                error=error,
            )
        return _result_for_seed_pack_error(command, args.seed_pack, exc, started)
    if not selected:
        return CommandResult(
            command=command,
            run_id=current_run_id() or uuid.uuid4().hex,
            status=BusinessStatus.COMPLETED,
            summary=CommandSummary(
                selected=0,
                skipped=0,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            ),
            metrics={"seed_pack_paper_count": len(snapshot.papers)},
        )
    if args.parse_only:
        missing_pdf = [
            record for record in selected if record.fulltext.pdf.status != "available"
        ]
        if missing_pdf:
            error = ErrorInfo(
                code="verified_pdf_required",
                error_class="precondition_failed",
                stage="parse_input",
                retryable=False,
                message="只解析模式所选论文中存在尚无已验证 PDF 的记录；Seed Pack 保持不变",
                remediation="先运行默认 enrich 或 download-only 获取 PDF",
            )
            return CommandResult(
                command=command,
                run_id=current_run_id() or uuid.uuid4().hex,
                status=BusinessStatus.REJECTED,
                summary=CommandSummary(
                    selected=len(selected),
                    failed=len(selected),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                ),
                items=[
                    CommandItem(
                        entity=EntityRef(type="paper", id=record.paper_id),
                        status=BusinessStatus.REJECTED,
                        data={"persisted": False},
                        error=error,
                    )
                    for record in selected
                ],
                error=error,
            )
    workflow = PaperFileWorkflow()
    outcomes = []
    for record in selected:
        outcomes.append(
            await workflow.run(
                paper=record,
                seed_pack=repository.root,
                no_cache=bool(getattr(args, "no_cache", False)),
                download_only=bool(getattr(args, "download_only", False)),
                parse_only=bool(getattr(args, "parse_only", False)),
            )
        )
    updated = [
        _record_from_file_outcome(record, outcome)
        for record, outcome in zip(selected, outcomes, strict=True)
    ]
    try:
        reloaded = repository.replace(
            updated, lock_timeout_seconds=args.lock_timeout_seconds
        )
    except SeedPackError as exc:
        return _result_for_seed_pack_error(command, args.seed_pack, exc, started)
    by_id = {record.paper_id: record for record in reloaded.papers}
    items: list[CommandItem] = []
    succeeded = partial = failed = 0
    first_error: ErrorInfo | None = None
    for original, outcome in zip(selected, outcomes, strict=True):
        persisted = by_id[original.paper_id]
        refs, data = _file_item_data(persisted, outcome, repository.root)
        if outcome.error is None:
            item_status = BusinessStatus.COMPLETED
            succeeded += 1
        elif outcome.partial:
            item_status = BusinessStatus.PARTIAL
            partial += 1
            first_error = first_error or outcome.error
        else:
            item_status = BusinessStatus.FAILED
            failed += 1
            first_error = first_error or outcome.error
        items.append(
            CommandItem(
                entity=EntityRef(type="paper", id=persisted.paper_id),
                status=item_status,
                artifacts=refs,
                data=data,
                error=outcome.error,
                audit_ref=outcome.audit_refs[-1] if outcome.audit_refs else None,
            )
        )
    result_status = (
        BusinessStatus.COMPLETED
        if failed == 0 and partial == 0
        else BusinessStatus.FAILED
        if failed == len(selected)
        else BusinessStatus.PARTIAL
    )
    return CommandResult(
        command=command,
        run_id=current_run_id() or uuid.uuid4().hex,
        status=result_status,
        summary=CommandSummary(
            selected=len(selected),
            succeeded=succeeded,
            partial=partial,
            failed=failed,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        items=items,
        metrics={
            "verified_pdf_count": sum(
                item.fulltext.pdf.status == "available" for item in reloaded.papers
            ),
            "mineru_markdown_count": sum(
                item.fulltext.parse.status == "available" for item in reloaded.papers
            ),
        },
        error=first_error if result_status != BusinessStatus.COMPLETED.value else None,
        audit_ref=first_error.audit_ref if first_error else None,
    )


def run_seed_pack(args) -> int:
    started = time.perf_counter()
    command = f"seed-pack.{args.seed_pack_action}"
    if args.seed_pack_action == "add":
        result = asyncio.run(_build_add_result(args))
    elif args.seed_pack_action == "enrich":
        result = asyncio.run(_build_enrich_result(args))
    else:
        try:
            if args.seed_pack_action == "init":
                repository = SeedPackRepository.initialize(
                    args.seed_pack, name=args.name
                )
            else:
                repository = SeedPackRepository(args.seed_pack)
            snapshot = repository.load(probe_artifacts=True)
            data = _seed_pack_status_data(snapshot, repository.root)
            result = CommandResult(
                command=command,
                run_id=current_run_id() or uuid.uuid4().hex,
                status=BusinessStatus.COMPLETED,
                summary=CommandSummary(
                    selected=1,
                    succeeded=1,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                ),
                items=[
                    CommandItem(
                        entity=EntityRef(
                            type="seed_pack", id=snapshot.manifest.seed_pack_id
                        ),
                        status=BusinessStatus.COMPLETED,
                        data=data,
                    )
                ],
                artifacts=[
                    ArtifactRef(
                        kind="seed_pack_manifest", path=str(repository.manifest_path)
                    ),
                    ArtifactRef(
                        kind="seed_pack_papers", path=str(repository.papers_path)
                    ),
                ],
                metrics={
                    "paper_count": data["paper_count"],
                    "verified_pdf_count": data["verified_pdf_count"],
                    "mineru_markdown_count": data["mineru_markdown_count"],
                },
            )
        except SeedPackError as exc:
            result = _result_for_seed_pack_error(command, args.seed_pack, exc, started)
    write_output(result.model_dump(mode="json"), pretty=True)
    return (
        0
        if result.status == BusinessStatus.COMPLETED.value
        else 2
        if result.status == BusinessStatus.PARTIAL.value
        else 1
    )


def register_seed_pack_commands(subparsers):
    """注册 seed-pack init/status/add/enrich。"""
    seed_pack_parser = subparsers.add_parser(
        "seed-pack", help="初始化、检查和原子更新 Seed Pack"
    )
    seed_pack_subparsers = seed_pack_parser.add_subparsers(
        dest="seed_pack_action", required=True
    )
    seed_pack_init_parser = seed_pack_subparsers.add_parser(
        "init", help="在空目录创建 Seed Pack"
    )
    seed_pack_init_parser.add_argument("--seed-pack", required=True)
    seed_pack_init_parser.add_argument("--name", default=None)
    seed_pack_init_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    seed_pack_status_parser = seed_pack_subparsers.add_parser(
        "show", help="重载记录并检查实际 PDF 与正文文件"
    )
    seed_pack_status_parser.add_argument("--seed-pack", required=True)
    seed_pack_status_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    seed_pack_add_parser = seed_pack_subparsers.add_parser(
        "add", help="按强标识原子新增论文元数据"
    )
    seed_pack_add_parser.add_argument("--seed-pack", required=True)
    seed_pack_add_parser.add_argument("--doi", action="append", default=[])
    seed_pack_add_parser.add_argument(
        "--pubmed-id", dest="pubmed_id", action="append", default=[]
    )
    seed_pack_add_parser.add_argument(
        "--pmc-id", dest="pmc_id", action="append", default=[]
    )
    seed_pack_add_parser.add_argument(
        "--arxiv-id", dest="arxiv_id", action="append", default=[]
    )
    seed_pack_add_parser.add_argument(
        "--lock-timeout-seconds", type=float, default=30.0
    )
    seed_pack_add_parser.add_argument(
        "--detach", action="store_true", help="后台运行并立即返回 job_id"
    )
    seed_pack_add_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    seed_pack_enrich_parser = seed_pack_subparsers.add_parser(
        "enrich", help="原子补齐已验证 PDF 与 MinerU 正文"
    )
    seed_pack_enrich_parser.add_argument("--seed-pack", required=True)
    seed_pack_enrich_parser.add_argument("--doi", action="append", default=[])
    seed_pack_enrich_parser.add_argument(
        "--pubmed-id", dest="pubmed_id", action="append", default=[]
    )
    seed_pack_enrich_parser.add_argument(
        "--pmc-id", dest="pmc_id", action="append", default=[]
    )
    seed_pack_enrich_parser.add_argument(
        "--arxiv-id", dest="arxiv_id", action="append", default=[]
    )
    seed_pack_enrich_parser.add_argument("--failed-only", action="store_true")
    seed_pack_enrich_parser.add_argument("--download-only", action="store_true")
    seed_pack_enrich_parser.add_argument("--parse-only", action="store_true")
    seed_pack_enrich_parser.add_argument("--no-cache", action="store_true")
    seed_pack_enrich_parser.add_argument(
        "--lock-timeout-seconds", type=float, default=30.0
    )
    seed_pack_enrich_parser.add_argument(
        "--detach", action="store_true", help="后台运行并立即返回 job_id"
    )
    seed_pack_enrich_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    return [
        seed_pack_init_parser,
        seed_pack_status_parser,
        seed_pack_add_parser,
        seed_pack_enrich_parser,
    ]
