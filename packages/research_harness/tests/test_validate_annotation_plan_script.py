from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "skills/paper-reading-annotation/scripts/validate_annotation_plan.py"
)


def _annotation(
    category: str, subject: str, anchor: str, comment: str
) -> dict[str, object]:
    return {
        "anchor": anchor,
        "page": 1,
        "category": category,
        "subject": subject,
        "comment": comment,
        "priority": 5,
    }


def test_validate_annotation_plan_accepts_valid_zotero_batch_plan(tmp_path: Path):
    annotations = [
        _annotation(
            "problem",
            "问题定义",
            "problem anchor",
            "【问题定义】这里先把要解决的 forecasting 痛点钉住。",
        ),
        _annotation(
            "motivation",
            "研究动机",
            "motivation anchor",
            "【研究动机】这句解释为什么这个问题值得做。",
        ),
        _annotation(
            "core-claim",
            "核心主张",
            "claim anchor",
            "【核心主张】这里是作者真正希望读者相信的命题。",
        ),
        _annotation(
            "method-taxonomy",
            "方法框架",
            "method anchor 1",
            "【方法框架】这里给出整体 pipeline。",
        ),
        _annotation(
            "method-taxonomy",
            "方法细节",
            "method anchor 2",
            "【方法细节】这里补足关键机制。",
        ),
        _annotation(
            "evidence",
            "证据强度",
            "evidence anchor 1",
            "【证据检查】这句对应主要实验支撑。",
        ),
        _annotation(
            "baseline",
            "基线比较",
            "baseline anchor",
            "【基线比较】这里要看比较对象是否足够强。",
        ),
        _annotation(
            "limitation-risk",
            "局限风险",
            "limitation anchor",
            "【局限风险】这句提示方法成立的边界。",
        ),
        _annotation(
            "writing-move",
            "写作动作",
            "writing anchor",
            "【写作思路】这里的 framing 方式值得借鉴。",
        ),
        _annotation(
            "rh-mapping",
            "RH映射",
            "mapping anchor",
            "【RH映射】这句最适合映射到当前 topic 的方法线。",
        ),
        _annotation(
            "follow-up",
            "后续动作",
            "follow-up anchor",
            "【后续动作】这里适合继续追引用或补基线。",
        ),
        _annotation(
            "problem",
            "问题补充",
            "problem anchor 2",
            "【问题定义】这里补充问题设定的难点。",
        ),
        _annotation(
            "motivation",
            "动机补充",
            "motivation anchor 2",
            "【研究动机】这句把应用价值说得更具体。",
        ),
        _annotation(
            "core-claim",
            "主张补充",
            "claim anchor 2",
            "【核心主张】这里是更强的性能或泛化主张。",
        ),
        _annotation(
            "evidence",
            "实验证据",
            "evidence anchor 2",
            "【证据检查】这里对应更细的结果证据。",
        ),
        _annotation(
            "baseline",
            "比较补充",
            "baseline anchor 2",
            "【基线比较】这里要核对是否遗漏关键对手。",
        ),
        _annotation(
            "writing-move",
            "结构设计",
            "writing anchor 2",
            "【写作思路】这里的组织顺序有明显引导作用。",
        ),
        _annotation(
            "rh-mapping",
            "主题映射",
            "mapping anchor 2",
            "【RH映射】这里能直接接到我们当前的研究问题。",
        ),
        _annotation(
            "follow-up",
            "追踪问题",
            "follow-up anchor 2",
            "【后续动作】这里值得顺着 limitation 继续查。",
        ),
    ]
    spec_path = tmp_path / "plan.json"
    spec_path.write_text(
        json.dumps(
            {
                "paper_id": 1,
                "title": "Demo Paper",
                "profile": "zotero-marginalia-batch-v1",
                "annotations": annotations,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(spec_path), "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["planned_count"] == 19
    assert payload["missing_categories"] == []


def test_validate_annotation_plan_accepts_content_primitives_v2_plan(tmp_path: Path):
    primitive_map = {
        "problem": ["paper_summarize", "claim_extract"],
        "motivation": ["paper_summarize", "section_draft"],
        "core-claim": ["claim_extract", "evidence_matrix"],
        "concept-boundary": ["method_taxonomy", "consistency_check"],
        "method-taxonomy": ["deep_read", "method_taxonomy"],
        "theoretical-innovation": ["deep_read", "method_taxonomy"],
        "algorithm-step": ["deep_read", "section_draft"],
        "hidden-assumption": ["claim_extract", "gap_detect"],
        "evidence": ["claim_extract", "evidence_matrix"],
        "baseline": ["baseline_identify", "evidence_matrix"],
        "reproducibility": ["deep_read", "consistency_check"],
        "critical-assessment": ["deep_read", "contradiction_detect"],
        "limitation-risk": ["deep_read", "gap_detect"],
        "cross-paper-link": ["deep_read", "contradiction_detect"],
        "rh-mapping": ["gap_detect", "section_draft"],
        "follow-up": ["gap_detect", "section_draft"],
    }
    rows = [
        ("problem", "问题定义", "a1", "【问题定义】这里钉住论文要解决的核心痛点。"),
        (
            "motivation",
            "研究动机",
            "a2",
            "【研究动机】这句解释为什么作者认为这条路线值得做。",
        ),
        (
            "core-claim",
            "核心主张",
            "a3",
            "【核心主张】这里是作者真正希望你接受的命题。",
        ),
        (
            "motivation",
            "研究动机补充",
            "a4",
            "【研究动机】这句补充应用价值或泛化叙事。",
        ),
        (
            "concept-boundary",
            "概念边界",
            "a5",
            "【概念边界】这句限定了结论能外推到哪里。",
        ),
        ("method-taxonomy", "方法框架", "a6", "【方法框架】这里给出总体 pipeline。"),
        (
            "theoretical-innovation",
            "理论创新",
            "a7",
            "【理论创新】这里说明真正新的抽象或机制。",
        ),
        (
            "algorithm-step",
            "算法步骤",
            "a8",
            "【算法步骤】这一步决定接口转换是否会损失关键信息。",
        ),
        ("hidden-assumption", "隐含前提", "a9", "【隐含前提】这里藏着方法成立的条件。"),
        (
            "method-taxonomy",
            "方法细节",
            "a10",
            "【方法细节】这句补足关键模块如何协同。",
        ),
        ("evidence", "证据检查", "a11", "【证据检查】这条证据对应主要结果支撑。"),
        (
            "baseline",
            "基线比较",
            "a12",
            "【基线比较】这里要核对比较对象和预算是否公平。",
        ),
        (
            "reproducibility",
            "复现判断",
            "a13",
            "【复现判断】这句最适合判断协议与细节是否透明。",
        ),
        (
            "critical-assessment",
            "批判评价",
            "a14",
            "【批判评价】这句适合判断增益究竟来自机制还是额外容量。",
        ),
        (
            "evidence",
            "证据边界",
            "a15",
            "【证据边界】这条更像增益来源切片，不等于普适结论。",
        ),
        ("limitation-risk", "局限风险", "a16", "【局限风险】这里暴露的是结构性边界。"),
        (
            "rh-mapping",
            "研究映射",
            "a17",
            "【研究映射】这句决定它在当前 topic 里的正确位置。",
        ),
        ("follow-up", "后续动作", "a18", "【后续动作】这里适合继续追引用或补对照。"),
        (
            "cross-paper-link",
            "跨论文关系",
            "a19",
            "【跨论文关系】这句最适合和邻近路线做正面对照。",
        ),
    ]
    annotations = []
    for category, subject, anchor, comment in rows:
        item = _annotation(category, subject, anchor, comment)
        item["primitive_focus"] = primitive_map[category]
        annotations.append(item)

    spec_path = tmp_path / "plan-v2.json"
    spec_path.write_text(
        json.dumps(
            {
                "paper_id": 2,
                "title": "Content Dense Demo",
                "profile": "zotero-content-primitives-v2",
                "annotations": annotations,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(spec_path), "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["planned_count"] == 19
    assert payload["missing_categories"] == []
    assert payload["missing_required_primitives"] == []


def test_validate_annotation_plan_rejects_sparse_or_forbidden_plan(tmp_path: Path):
    spec_path = tmp_path / "bad-plan.json"
    spec_path.write_text(
        json.dumps(
            {
                "paper_id": 1,
                "title": "Bad Demo Paper",
                "profile": "zotero-marginalia-batch-v1",
                "annotations": [
                    _annotation(
                        "problem",
                        "问题定义",
                        "a1",
                        "【问题定义】我会先给新读者解释这个问题。",
                    ),
                    _annotation(
                        "method-taxonomy",
                        "方法框架",
                        "a2",
                        "【方法框架】这里只有一个摘要级方法说明。",
                    ),
                    _annotation(
                        "evidence",
                        "证据检查",
                        "a3",
                        "【证据检查】这里只有一句实验结论。",
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(spec_path), "--json"],
        check=False,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert any("exactly 19" in msg for msg in payload["errors"])
    assert any("3-note abstract-only" in msg for msg in payload["errors"])
    assert payload["forbidden_hits"]
