"""公共生物医学数据垂直切片 CLI。"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paperfetch.biomedical.geo import PARSER_VERSION, build_geo_dataset_record
from paperfetch.biomedical.gold import default_policy_path, run_gold_validation
from paperfetch.biomedical.handoff import build_analysis_handoff
from paperfetch.biomedical.models import (
    BiomedicalDatasetRecord,
    OperationInputReadiness,
)
from paperfetch.biomedical.policy import assess_operation_readiness
from paperfetch.datasets.geo import atomic_write_json
from paperfetch.observability import get_event_logger, write_output


logger = get_event_logger("paperfetch.cli.biomedical")

_HUMAN_STATUS_LABELS = {
    "allowed": "允许",
    "blocked": "阻断",
    "conditional": "有条件",
    "failed": "失败",
    "not_assessable": "无法评估",
    "passed": "通过",
    "satisfied": "满足",
}


def _human_status(value: Any) -> str:
    """将稳定英文状态值转换为文本模式的人读标签。"""

    raw = getattr(value, "value", value)
    return _HUMAN_STATUS_LABELS.get(str(raw), str(raw))


def _timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("时间戳必须包含 UTC 偏移")
    return parsed


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(path.parent.stat().st_mode | 0o2775)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            if value and not value.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            temporary.chmod(0o664)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_record(path: str | Path) -> BiomedicalDatasetRecord:
    source = Path(path).expanduser().resolve()
    lines = [
        line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(lines) != 1:
        raise ValueError("当前垂直切片要求 dataset_records.jsonl 恰好包含一个记录")
    return BiomedicalDatasetRecord.model_validate_json(lines[0])


def _load_readiness(path: str | Path) -> OperationInputReadiness:
    return OperationInputReadiness.model_validate_json(
        Path(path).expanduser().resolve().read_text(encoding="utf-8")
    )


def _resolve_geo_sources(parsed_args: Any) -> tuple[Path, Path | None]:
    accession = parsed_args.accession.upper()
    if parsed_args.soft_file:
        soft = Path(parsed_args.soft_file).expanduser().resolve()
        directory = soft.parent
    else:
        root = Path(parsed_args.geo_root).expanduser().resolve()
        directory = root / accession
        candidates = (
            directory / f"{accession}_family.soft.gz",
            directory / f"{accession}_family.soft",
            directory / f"{accession}.provisional.soft",
        )
        soft = next((item for item in candidates if item.is_file()), candidates[0])
    if not soft.is_file():
        raise ValueError(f"未找到本地 GEO SOFT 文件：{soft}")
    if parsed_args.filelist_file:
        filelist = Path(parsed_args.filelist_file).expanduser().resolve()
    else:
        candidates = (
            directory / "filelist.txt",
            directory / f"{accession}.filelist.txt",
        )
        filelist = next((item for item in candidates if item.is_file()), None)
    return soft, filelist


def run_dataset_inspect(parsed_args: Any) -> int:
    observed = _timestamp(parsed_args.observed_at)
    soft, filelist = _resolve_geo_sources(parsed_args)
    output_dir = (
        Path(parsed_args.output_dir).expanduser().resolve()
        if parsed_args.output_dir
        else Path(os.getenv("SPC_BIOMEDICAL_DATA_ROOT") or "~/.cache/spc/biomedical")
        .expanduser()
        .resolve()
        / parsed_args.accession.upper()
    )
    logger.event(
        "biomedical.dataset_inspection.started",
        phase="dataset_inspection",
        action="inspect_geo_dataset",
        outcome="started",
        source="ncbi_geo",
        message=f"开始检查公共生物医学数据集：{parsed_args.accession.upper()}",
        diagnostics={"accession": parsed_args.accession.upper()},
    )
    record = build_geo_dataset_record(
        soft,
        filelist_file=filelist,
        observed_at=observed,
    )
    request = {
        "schema_version": "spc.biomedical-dataset-request.v0.1",
        "accession": record.accession,
        "source": "NCBI_GEO",
        "soft_file": soft.name,
        "filelist_file": filelist.name if filelist else None,
        "requested_at": observed.isoformat(),
        "network_accessed": False,
    }
    graph = {
        "schema_version": "spc.experimental-entity-graph.v0.1",
        "dataset_ref": record.dataset_ref,
        "record_digest": record.content_digest,
        "entities": [item.model_dump(mode="json") for item in record.entities],
        "relations": [item.model_dump(mode="json") for item in record.relations],
    }
    report = {
        "schema_version": "spc.biomedical-inspection-run-report.v0.1",
        "status": "complete",
        "lifecycle_status": "provisional",
        "accession": record.accession,
        "record_digest": record.content_digest,
        "parser_version": PARSER_VERSION,
        "network_accessed": False,
        "coverage": {
            "field_assertions": len(record.field_assertions),
            "entities": len(record.entities),
            "relations": len(record.relations),
            "artifacts": len(record.artifacts),
            "unresolved_questions": len(record.unresolved_questions),
        },
        "completed_at": observed.isoformat(),
    }
    paths = {
        "dataset_request": output_dir / "dataset_request.json",
        "dataset_records": output_dir / "dataset_records.jsonl",
        "entity_graph": output_dir / "entity_graph.json",
        "run_report": output_dir / "run_report.json",
    }
    atomic_write_json(paths["dataset_request"], request)
    _atomic_write_text(
        paths["dataset_records"],
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
    )
    atomic_write_json(paths["entity_graph"], graph)
    atomic_write_json(paths["run_report"], report)
    logger.event(
        "biomedical.dataset_inspection.completed",
        phase="dataset_inspection",
        action="inspect_geo_dataset",
        outcome="success",
        source="ncbi_geo",
        message=f"公共生物医学数据集检查完成：{record.accession}",
        diagnostics={
            "accession": record.accession,
            "record_digest": record.content_digest,
        },
    )
    payload = {
        "schema_version": "spc.biomedical-inspection-result.v0.1",
        "status": "complete",
        "lifecycle_status": "provisional",
        "record": record.model_dump(mode="json"),
        "artifacts": {key: str(value) for key, value in paths.items()},
    }
    if parsed_args.output_format == "json":
        write_output(payload, pretty=True)
    else:
        write_output(
            f"{record.accession}：检查完成；实体={len(record.entities)}；"
            f"关系={len(record.relations)}；未决问题={len(record.unresolved_questions)}"
        )
        write_output(f"  事实源：{paths['dataset_records']}")
    return 0


def run_dataset_readiness(parsed_args: Any) -> int:
    record = _load_record(parsed_args.record_file)
    checked = _timestamp(parsed_args.checked_at)
    readiness = assess_operation_readiness(
        record,
        parsed_args.operation,
        parsed_args.policy_file or default_policy_path(),
        checked_at=checked,
    )
    if parsed_args.output_file:
        atomic_write_json(
            Path(parsed_args.output_file).expanduser().resolve(),
            readiness.model_dump(mode="json"),
        )
    if parsed_args.output_format == "json":
        write_output(readiness.model_dump(mode="json"), pretty=True)
    else:
        write_output(
            f"{record.accession}：操作={readiness.intended_operation}；"
            f"输入信号={_human_status(readiness.signal)}"
        )
        for item in readiness.requirements:
            write_output(f"- {item.code}：{_human_status(item.status)}；{item.message}")
    return 0 if readiness.signal.value == "allowed" else 2


def run_dataset_handoff(parsed_args: Any) -> int:
    record = _load_record(parsed_args.record_file)
    readiness = _load_readiness(parsed_args.readiness_file)
    handoff = build_analysis_handoff(
        record,
        readiness,
        generated_at=_timestamp(parsed_args.generated_at),
    )
    if parsed_args.output_file:
        atomic_write_json(
            Path(parsed_args.output_file).expanduser().resolve(),
            handoff.model_dump(mode="json"),
        )
    if parsed_args.output_format == "json":
        write_output(handoff.model_dump(mode="json"), pretty=True)
    else:
        write_output(
            f"{record.accession}：交接包已生成；操作={handoff.intended_operation}；"
            f"输入信号={_human_status(handoff.signal)}"
        )
    return 0 if handoff.signal.value == "allowed" else 2


def run_dataset_gold_validate(parsed_args: Any) -> int:
    report = run_gold_validation(
        parsed_args.gold_file,
        policy_path=parsed_args.policy_file,
    )
    if parsed_args.report_file:
        atomic_write_json(
            Path(parsed_args.report_file).expanduser().resolve(),
            report,
        )
    if parsed_args.output_format == "json":
        write_output(report, pretty=True)
    else:
        summary = report["summary"]
        write_output(
            f"医学金标回放：{_human_status(report['status'])}；"
            f"通过={summary['passed']}/{summary['total']}"
        )
        for case in report["cases"]:
            write_output(f"- {case['case_id']}：{_human_status(case['status'])}")
    return 0 if report["status"] == "passed" else 2


def run_biomedical_dataset(parsed_args: Any) -> int:
    if parsed_args.dataset_action == "inspect":
        return run_dataset_inspect(parsed_args)
    if parsed_args.dataset_action == "readiness":
        return run_dataset_readiness(parsed_args)
    if parsed_args.dataset_action == "handoff":
        return run_dataset_handoff(parsed_args)
    if parsed_args.dataset_action == "gold-validate":
        return run_dataset_gold_validate(parsed_args)
    raise ValueError(f"不支持的 dataset 操作：{parsed_args.dataset_action}")


def register_dataset_commands(subparsers):
    """注册 dataset inspect/readiness/handoff/gold-validate/archive。"""
    dataset_parser = subparsers.add_parser(
        "dataset",
        help="检查公共生物医学数据事实、操作输入就绪度和交接包",
    )
    dataset_subparsers = dataset_parser.add_subparsers(
        dest="dataset_action",
        required=True,
        help="公共生物医学数据操作",
    )
    dataset_inspect_parser = dataset_subparsers.add_parser(
        "inspect",
        help="只读解析本地 GEO SOFT 和 filelist，不隐式联网或下载",
    )
    dataset_inspect_parser.add_argument("accession", help="GSE accession")
    dataset_inspect_parser.add_argument(
        "--geo-root",
        default=os.getenv("SPC_GEO_DATA_ROOT") or "~/.cache/spc/geo",
        help="GEO 数据根目录；使用 --soft-file 时不依赖该目录",
    )
    dataset_inspect_parser.add_argument(
        "--soft-file", default=None, help="显式指定本地 SOFT/.gz"
    )
    dataset_inspect_parser.add_argument(
        "--filelist-file", default=None, help="显式指定本地 filelist.txt"
    )
    dataset_inspect_parser.add_argument(
        "--output-dir", default=None, help="事实源和派生文件输出目录"
    )
    dataset_inspect_parser.add_argument(
        "--observed-at", default=None, help="带 UTC 偏移的来源观察时间"
    )
    dataset_inspect_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    dataset_readiness_parser = dataset_subparsers.add_parser(
        "readiness",
        help="按版本化 policy 检查指定操作的输入就绪度",
    )
    dataset_readiness_parser.add_argument(
        "--record-file", required=True, help="dataset_records.jsonl"
    )
    dataset_readiness_parser.add_argument(
        "--operation", required=True, help="受控 intended_operation"
    )
    dataset_readiness_parser.add_argument(
        "--policy-file", default=None, help="版本化 domain policy JSON"
    )
    dataset_readiness_parser.add_argument(
        "--checked-at", default=None, help="带 UTC 偏移的检查时间"
    )
    dataset_readiness_parser.add_argument(
        "--output-file", default=None, help="原子写入 operation_readiness.json"
    )
    dataset_readiness_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    dataset_handoff_parser = dataset_subparsers.add_parser(
        "handoff",
        help="基于事实记录和就绪度生成 AnalysisHandoff",
    )
    dataset_handoff_parser.add_argument(
        "--record-file", required=True, help="dataset_records.jsonl"
    )
    dataset_handoff_parser.add_argument(
        "--readiness-file", required=True, help="operation_readiness.json"
    )
    dataset_handoff_parser.add_argument(
        "--generated-at", default=None, help="带 UTC 偏移的生成时间"
    )
    dataset_handoff_parser.add_argument(
        "--output-file", default=None, help="原子写入 analysis_handoff.json"
    )
    dataset_handoff_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    dataset_gold_parser = dataset_subparsers.add_parser(
        "gold-validate",
        help="回放 DVT/Glioma provisional 医学金标",
    )
    dataset_gold_parser.add_argument(
        "--gold-file", default=None, help="覆盖内置金标 JSONL"
    )
    dataset_gold_parser.add_argument(
        "--policy-file", default=None, help="覆盖内置 provisional policy"
    )
    dataset_gold_parser.add_argument(
        "--report-file", default=None, help="原子写入金标报告 JSON"
    )
    dataset_gold_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    dataset_archive_parser = dataset_subparsers.add_parser(
        "archive",
        help="检查或物化 Zenodo 等公开归档数据集，不污染 GEO 事实模型",
    )
    dataset_archive_subparsers = dataset_archive_parser.add_subparsers(
        dest="archive_action", required=True
    )
    dataset_archive_capabilities_parser = dataset_archive_subparsers.add_parser(
        "capabilities", help="列出归档来源的受支持操作与稳定能力边界"
    )
    dataset_archive_capabilities_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    dataset_archive_inspect_parser = dataset_archive_subparsers.add_parser(
        "inspect", help="读取归档元数据并可用 HTTP Range 审计远程 ZIP"
    )
    dataset_archive_inspect_parser.add_argument(
        "--source", default="zenodo", help="归档来源；先运行 archive capabilities"
    )
    dataset_archive_inspect_parser.add_argument("--record", required=True)
    dataset_archive_inspect_parser.add_argument(
        "--remote-inventory", action="store_true"
    )
    dataset_archive_inspect_parser.add_argument(
        "--max-small-text-bytes", type=int, default=1_048_576
    )
    dataset_archive_inspect_parser.add_argument("--output-dir", required=True)
    dataset_archive_inspect_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    dataset_archive_download_parser = dataset_archive_subparsers.add_parser(
        "download", help="断点续传单个归档文件并按来源 checksum 验收"
    )
    dataset_archive_download_parser.add_argument(
        "--source", default="zenodo", help="归档来源；先运行 archive capabilities"
    )
    dataset_archive_download_parser.add_argument("--record", required=True)
    dataset_archive_download_parser.add_argument("--file", required=True)
    dataset_archive_download_parser.add_argument("--resume", action="store_true")
    dataset_archive_download_parser.add_argument(
        "--verify-checksum", action="store_true"
    )
    dataset_archive_download_parser.add_argument("--output-dir", required=True)
    dataset_archive_download_parser.add_argument("--detach", action="store_true")
    dataset_archive_download_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    from paperfetch.cli.datasets import register_external_dataset_commands
    from paperfetch.cli.gse import register_gse_dataset_commands

    external_parsers = register_external_dataset_commands(dataset_subparsers)
    geo_parsers = register_gse_dataset_commands(dataset_subparsers)
    return [
        dataset_inspect_parser,
        dataset_readiness_parser,
        dataset_handoff_parser,
        dataset_gold_parser,
        dataset_archive_capabilities_parser,
        dataset_archive_inspect_parser,
        dataset_archive_download_parser,
        *geo_parsers,
        *external_parsers,
    ]
