"""Zotero PDF annotation plan and tool bridge helpers."""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager

ANNOTATION_TOOL_CACHE: dict[str, Any] = {}
ZOTERO_ANNOTATION_PROFILE = "zotero-content-primitives-v2"
ZOTERO_ANNOTATION_MARKER = "RH-PHD-v2"
ZOTERO_ANNOTATION_SPECS: tuple[dict[str, Any], ...] = (
    {
        "category": "problem",
        "subject": "问题定义",
        "comment": "【问题定义】这处文本钉住论文真正要解决的研究痛点，先判断它是否值得进入当前 topic。",
        "primitive_focus": ["paper_summarize", "claim_extract"],
    },
    {
        "category": "motivation",
        "subject": "研究动机",
        "comment": "【研究动机】这里解释作者为什么选择这条路线，可用于判断问题设定的现实或理论压力。",
        "primitive_focus": ["paper_summarize", "section_draft"],
    },
    {
        "category": "core-claim",
        "subject": "核心主张",
        "comment": "【核心主张】这是作者希望读者接受的主要命题，后续需要逐条对照证据强度。",
        "primitive_focus": ["claim_extract", "evidence_matrix"],
    },
    {
        "category": "motivation",
        "subject": "动机补充",
        "comment": "【研究动机】这处补足应用价值或研究缺口，适合写入 topic 的问题背景。",
        "primitive_focus": ["paper_summarize", "section_draft"],
    },
    {
        "category": "concept-boundary",
        "subject": "概念边界",
        "comment": "【概念边界】这里限定概念、任务或适用范围，防止把结论外推到不相干场景。",
        "primitive_focus": ["method_taxonomy", "consistency_check"],
    },
    {
        "category": "method-taxonomy",
        "subject": "方法框架",
        "comment": "【方法框架】这处适合抽出方法结构，后续和同类路线放进同一 taxonomy 比较。",
        "primitive_focus": ["deep_read", "method_taxonomy"],
    },
    {
        "category": "theoretical-innovation",
        "subject": "理论创新",
        "comment": "【理论创新】这里需要判断作者的新意来自抽象机制、理论解释，还是只是工程组合。",
        "primitive_focus": ["deep_read", "method_taxonomy"],
    },
    {
        "category": "algorithm-step",
        "subject": "算法步骤",
        "comment": "【算法步骤】这一步决定方法如何真正运行，精读时要还原输入、输出和失败条件。",
        "primitive_focus": ["deep_read", "section_draft"],
    },
    {
        "category": "hidden-assumption",
        "subject": "隐含前提",
        "comment": "【隐含前提】这里暴露方法成立所依赖的条件，后续要检查这些条件是否在实验中被满足。",
        "primitive_focus": ["claim_extract", "gap_detect"],
    },
    {
        "category": "method-taxonomy",
        "subject": "方法细节",
        "comment": "【方法细节】这处补足关键模块如何协同，可作为和 baseline 拆解比较的依据。",
        "primitive_focus": ["deep_read", "method_taxonomy"],
    },
    {
        "category": "evidence",
        "subject": "证据检查",
        "comment": "【证据检查】这条证据直接支撑主要结论，需要记录指标、数据和对照条件。",
        "primitive_focus": ["claim_extract", "evidence_matrix"],
    },
    {
        "category": "baseline",
        "subject": "基线比较",
        "comment": "【基线比较】这里要核对比较对象是否公平，尤其是数据、预算、调参和任务定义。",
        "primitive_focus": ["baseline_identify", "evidence_matrix"],
    },
    {
        "category": "reproducibility",
        "subject": "复现判断",
        "comment": "【复现判断】这处最适合检查实现细节是否足够透明，以及复现实验还缺哪些信息。",
        "primitive_focus": ["deep_read", "consistency_check"],
    },
    {
        "category": "critical-assessment",
        "subject": "批判评价",
        "comment": "【批判评价】这里需要判断增益究竟来自核心机制，还是来自额外资源、设定或评估选择。",
        "primitive_focus": ["deep_read", "contradiction_detect"],
    },
    {
        "category": "evidence",
        "subject": "证据边界",
        "comment": "【证据边界】这条证据说明结论能支持到什么程度，也提示哪些推断仍然过强。",
        "primitive_focus": ["claim_extract", "evidence_matrix"],
    },
    {
        "category": "limitation-risk",
        "subject": "局限风险",
        "comment": "【局限风险】这里暴露结构性边界，适合转化为后续 gap 或负面证据。",
        "primitive_focus": ["deep_read", "gap_detect"],
    },
    {
        "category": "rh-mapping",
        "subject": "研究映射",
        "comment": "【研究映射】这处决定论文在当前 topic 中的位置，是背景、方法候选、证据还是反例。",
        "primitive_focus": ["gap_detect", "section_draft"],
    },
    {
        "category": "follow-up",
        "subject": "后续动作",
        "comment": "【后续动作】这里适合继续追引用、补实验对照，或记录一个待验证问题。",
        "primitive_focus": ["gap_detect", "section_draft"],
    },
    {
        "category": "cross-paper-link",
        "subject": "跨论文关系",
        "comment": "【跨论文关系】这处适合和相邻路线做正面对照，判断它继承、替代还是反驳了哪些工作。",
        "primitive_focus": ["deep_read", "contradiction_detect"],
    },
)


def build_zotero_pdf_annotation_plan(
    *,
    paper: dict[str, Any],
    pdf_path: Path,
    topic_id: int,
    topic_name: str,
    focus: str,
) -> dict[str, Any]:
    anchors = extract_zotero_pdf_anchor_candidates(pdf_path)
    if not anchors:
        raise ValueError("PDF text extraction found no usable anchor text")

    annotations: list[dict[str, Any]] = []
    for index, spec in enumerate(ZOTERO_ANNOTATION_SPECS, start=1):
        anchor = anchors[(index - 1) % len(anchors)]
        annotations.append(
            {
                "anchor": anchor["anchor"],
                "page": anchor["page"],
                "category": spec["category"],
                "subject": spec["subject"],
                "comment": spec["comment"],
                "priority": 5 if index <= 8 else 4,
                "primitive_focus": list(spec["primitive_focus"]),
            }
        )

    return {
        "paper_id": int(paper.get("id") or 0),
        "topic_id": topic_id,
        "topic_name": topic_name,
        "focus": focus,
        "title": str(paper.get("title") or ""),
        "profile": ZOTERO_ANNOTATION_PROFILE,
        "annotations": annotations,
    }


def extract_zotero_pdf_anchor_candidates(pdf_path: Path) -> list[dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("PyMuPDF is required for Zotero PDF annotations") from exc

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    doc = fitz.open(str(pdf_path))
    try:
        for page_index, page in enumerate(doc, start=1):
            page_text = str(page.get_text("text") or "")
            raw_candidates = list(page_text.splitlines())
            raw_candidates.extend(re.split(r"(?<=[.!?。！？])\s+", page_text))
            for raw in raw_candidates:
                anchor = normalize_zotero_pdf_anchor(raw)
                if not anchor or anchor in seen:
                    continue
                seen.add(anchor)
                candidates.append({"anchor": anchor, "page": page_index})
                if len(candidates) >= 80:
                    return candidates
    finally:
        doc.close()
    return candidates


def normalize_zotero_pdf_anchor(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    text = text.strip("•*-–— \t")
    if len(text) < 24:
        return ""
    words = text.split()
    if len(words) > 16:
        text = " ".join(words[:16])
    if len(text) > 180:
        text = text[:180].rsplit(" ", 1)[0].strip()
    alnum = [char for char in text if char.isalnum()]
    if len(alnum) < 12:
        return ""
    return text


def validate_zotero_annotation_plan(plan: dict[str, Any]) -> dict[str, Any]:
    module = load_annotation_tool_module("validate_annotation_plan")
    return dict(module.validate_plan(plan, profile_override=ZOTERO_ANNOTATION_PROFILE))


def reset_rh_pdf_annotations(pdf_path: Path) -> dict[str, Any]:
    module = load_annotation_tool_module("reset_rh_pdf_annotations")
    return dict(
        module.reset_annotations(
            pdf_path,
            pdf_path,
            ("RH-PHD-v1", ZOTERO_ANNOTATION_MARKER),
        )
    )


def apply_zotero_pdf_annotation_plan(pdf_path: Path, plan_path: Path) -> dict[str, Any]:
    module = load_annotation_tool_module("phd_pdf_annotator")
    return dict(module.apply_annotations(pdf_path, pdf_path, plan_path))


def load_annotation_tool_module(name: str) -> Any:
    cached = ANNOTATION_TOOL_CACHE.get(name)
    if cached is not None:
        return cached
    path = (
        Path(__file__).resolve().parents[3]
        / "skills"
        / "paper-reading-annotation"
        / "scripts"
        / f"{name}.py"
    )
    if not path.exists():
        raise FileNotFoundError(f"annotation tool script not found: {path}")
    spec = importlib.util.spec_from_file_location(f"rh_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load annotation tool script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ANNOTATION_TOOL_CACHE[name] = module
    return module


def zotero_pdf_annotation_plan_path(
    *,
    db_path: Path,
    topic_id: int,
    paper_id: int,
) -> Path:
    return (
        db_path.parent
        / "artifacts"
        / "zotero_pdf_annotations"
        / f"topic_{topic_id}"
        / f"paper_{paper_id}"
        / "annotation_plan.json"
    )


def _missing_zotero_pdf_annotation_plan_path(_topic_id: int, _paper_id: int) -> Path:
    raise RuntimeError("zotero_pdf_annotation_plan_path dependency was not provided")


def apply_rh_pdf_annotations_for_papers(
    *,
    paper_ids: list[int],
    topic_id: int,
    topic_name: str,
    focus: str = "",
    load_paper_rows: Callable[[list[int]], dict[int, dict[str, Any]]],
    apply_rh_pdf_annotations_for_paper: Callable[..., dict[str, Any]] = (
        lambda **kwargs: globals()["apply_rh_pdf_annotations_for_paper"](**kwargs)
    ),
    record_zotero_pdf_annotation_artifact: Callable[..., None] | None = None,
) -> list[dict[str, Any]]:
    requested_ids = [int(item) for item in paper_ids if int(item or 0) > 0]
    if not requested_ids:
        return []

    rows_by_id = load_paper_rows(requested_ids)
    receipts: list[dict[str, Any]] = []
    for paper_id in requested_ids:
        row = rows_by_id.get(paper_id)
        if row is None:
            receipts.append(
                zotero_pdf_annotation_skip_receipt(
                    paper_id=paper_id,
                    title="",
                    status="failed",
                    error="paper not found",
                )
            )
            continue
        receipts.append(
            apply_rh_pdf_annotations_for_paper(
                paper=dict(row),
                topic_id=topic_id,
                topic_name=topic_name,
                focus=focus,
            )
        )

    if record_zotero_pdf_annotation_artifact is not None:
        record_zotero_pdf_annotation_artifact(
            topic_id=topic_id,
            topic_name=topic_name,
            receipts=receipts,
        )
    return receipts


def zotero_annotation_paper_rows(
    paper_ids: list[int],
    *,
    get_db_context: Callable[[], ContextManager[sqlite3.Connection]],
) -> dict[int, dict[str, Any]]:
    placeholders = ",".join("?" for _ in paper_ids)
    with get_db_context() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, abstract, pdf_path, doi, arxiv_id, year, venue, deep_read
            FROM papers
            WHERE id IN ({placeholders})
            """,
            tuple(paper_ids),
        ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def apply_rh_pdf_annotations_for_paper(
    *,
    paper: dict[str, Any],
    topic_id: int,
    topic_name: str,
    focus: str,
    trusted_pdf_path_for_zotero: Callable[[str], tuple[Path | None, str | None]],
    build_zotero_pdf_annotation_plan: Callable[..., dict[str, Any]] = (
        build_zotero_pdf_annotation_plan
    ),
    validate_zotero_annotation_plan: Callable[[dict[str, Any]], dict[str, Any]] = (
        validate_zotero_annotation_plan
    ),
    zotero_pdf_annotation_plan_path: Callable[[int, int], Path] = (
        _missing_zotero_pdf_annotation_plan_path
    ),
    backup_pdf_for_zotero_annotations: Callable[[Path], Path] = (
        lambda pdf_path: globals()["backup_pdf_for_zotero_annotations"](pdf_path)
    ),
    reset_rh_pdf_annotations: Callable[
        [Path], dict[str, Any]
    ] = reset_rh_pdf_annotations,
    apply_zotero_pdf_annotation_plan: Callable[[Path, Path], dict[str, Any]] = (
        apply_zotero_pdf_annotation_plan
    ),
    count_rh_pdf_annotations: Callable[..., int] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    paper_id = int(paper.get("id") or 0)
    title = str(paper.get("title") or "")
    pdf_path, path_error = trusted_pdf_path_for_zotero(str(paper.get("pdf_path") or ""))
    if pdf_path is None:
        return zotero_pdf_annotation_skip_receipt(
            paper_id=paper_id,
            title=title,
            status="skipped",
            error=path_error or "PDF path is unavailable",
        )

    try:
        plan = build_zotero_pdf_annotation_plan(
            paper=paper,
            pdf_path=pdf_path,
            topic_id=topic_id,
            topic_name=topic_name,
            focus=focus,
        )
        validation = validate_zotero_annotation_plan(plan)
        if not validation.get("ok"):
            return zotero_pdf_annotation_skip_receipt(
                paper_id=paper_id,
                title=title,
                status="failed",
                error="annotation plan validation failed: "
                + "; ".join(str(item) for item in validation.get("errors") or []),
                pdf_path=str(pdf_path),
                validation=validation,
            )

        plan_path = zotero_pdf_annotation_plan_path(topic_id, paper_id)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        backup_path = backup_pdf_for_zotero_annotations(pdf_path)
        reset_receipt = reset_rh_pdf_annotations(pdf_path)
        apply_receipt = apply_zotero_pdf_annotation_plan(pdf_path, plan_path)
        count_annotations = (
            count_rh_pdf_annotations or globals()["count_rh_pdf_annotations"]
        )
        verified_count = count_annotations(
            pdf_path,
            marker=str(apply_receipt.get("marker") or ZOTERO_ANNOTATION_MARKER),
        )
        missing_count = int(apply_receipt.get("missing_count") or 0)
        applied_count = int(apply_receipt.get("applied_count") or 0)
        status = (
            "completed"
            if applied_count > 0
            and missing_count == 0
            and verified_count >= applied_count
            else "partial"
            if applied_count > 0
            else "failed"
        )
        receipt: dict[str, Any] = {
            "status": status,
            "paper_id": paper_id,
            "title": title,
            "profile": str(apply_receipt.get("profile") or ZOTERO_ANNOTATION_PROFILE),
            "marker": str(apply_receipt.get("marker") or ZOTERO_ANNOTATION_MARKER),
            "pdf_path": str(pdf_path),
            "plan_path": str(plan_path),
            "backup_path": str(backup_path),
            "planned_count": int(apply_receipt.get("planned_count") or 0),
            "applied_count": applied_count,
            "duplicate_count": int(apply_receipt.get("duplicate_count") or 0),
            "missing_count": missing_count,
            "verified_count": verified_count,
            "missing": list(apply_receipt.get("missing") or []),
            "reset_removed_count": int(reset_receipt.get("removed_count") or 0),
            "validation": validation,
        }
        if verified_count < applied_count:
            receipt["status"] = "partial"
            receipt["warning"] = (
                f"verified {verified_count} RH annotations after applying {applied_count}"
            )
        return receipt
    except Exception as exc:  # pragma: no cover - defensive guard
        log = logger or logging.getLogger(__name__)
        log.warning(
            "failed to apply Zotero PDF annotations for paper %s: %s",
            paper_id,
            exc,
        )
        return zotero_pdf_annotation_skip_receipt(
            paper_id=paper_id,
            title=title,
            status="failed",
            error=str(exc)[:1000],
            pdf_path=str(pdf_path),
        )


def zotero_pdf_annotation_skip_receipt(
    *,
    paper_id: int,
    title: str,
    status: str,
    error: str,
    pdf_path: str = "",
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "status": status,
        "paper_id": paper_id,
        "title": title,
        "profile": ZOTERO_ANNOTATION_PROFILE,
        "pdf_path": pdf_path,
        "plan_path": "",
        "planned_count": 0,
        "applied_count": 0,
        "verified_count": 0,
        "missing_count": 0,
        "missing": [],
        "error": error,
    }
    if validation is not None:
        receipt["validation"] = validation
    return receipt


def record_zotero_pdf_annotation_artifact(
    *,
    topic_id: int,
    topic_name: str,
    receipts: list[dict[str, Any]],
    execute_tool: Callable[[str, dict[str, Any]], Any],
    logger: logging.Logger | None = None,
) -> None:
    if not topic_id or not receipts:
        return
    try:
        execute_tool(
            "orchestrator_record_artifact",
            {
                "topic_id": topic_id,
                "stage": "collect",
                "artifact_type": "zotero_pdf_annotation_receipt",
                "title": f"Zotero PDF annotation receipt: {topic_name}",
                "payload": {
                    "schema": "rh.schema.zotero_pdf_annotation_receipt.v1",
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "receipts": receipts,
                },
            },
        )
    except Exception as exc:  # pragma: no cover - provenance must not block sync
        log = logger or logging.getLogger(__name__)
        log.warning("could not record Zotero PDF annotation artifact: %s", exc)


def backup_pdf_for_zotero_annotations(pdf_path: Path) -> Path:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_path = pdf_path.with_name(
        f"{pdf_path.name}.bak-rh-zotero-annotations-{suffix}"
    )
    shutil.copy2(pdf_path, backup_path)
    return backup_path


def count_rh_pdf_annotations(pdf_path: Path, *, marker: str) -> int:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("PyMuPDF is required for Zotero PDF annotations") from exc

    count = 0
    doc = fitz.open(str(pdf_path))
    try:
        for page in doc:
            annot = page.first_annot
            while annot:
                content = str((annot.info or {}).get("content") or "")
                if marker in content:
                    count += 1
                annot = annot.next
    finally:
        doc.close()
    return count
