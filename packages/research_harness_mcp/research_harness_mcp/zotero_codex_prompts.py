"""Prompt builders for Zotero-backed Codex handoff and chat turns."""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol

from research_harness_mcp.zotero_chat_match import zotero_context_payload
from research_harness_mcp.zotero_identity import (
    normalize_zotero_library_id,
    truncate_text,
)
from research_harness_mcp.zotero_models_http import ZoteroChatRequest


class _CapabilityBrokerLike(Protocol):
    def list(self) -> list[dict[str, Any]]: ...


CapabilityBrokerBuilder = Callable[..., _CapabilityBrokerLike]


def build_zotero_codex_turn_prompt(
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    *,
    is_followup: bool,
    build_zotero_capability_broker: CapabilityBrokerBuilder,
) -> str:
    handoff = build_zotero_codex_handoff_prompt(
        body,
        matched,
        build_zotero_capability_broker=build_zotero_capability_broker,
    )
    if not is_followup:
        return "\n".join(
            [
                handoff,
                "",
                "## 侧边栏实时回答要求",
                "- 直接回答用户问题，不要输出交接说明。",
                "- 控制在 3-6 个要点；必要时给出下一步 RH 操作建议。",
            ]
        )
    return "\n".join(
        [
            "这是同一个 Zotero/RH 会话的后续问题，请沿用当前 Codex thread 的多轮上下文。",
            "下面仍提供最新 Zotero/RH 匹配信息，若与历史上下文冲突，以最新信息为准。",
            "",
            handoff,
            "",
            "## 侧边栏实时回答要求",
            "- 直接接着上一轮回答，不要重新介绍系统。",
            "- 用中文，短而具体。",
        ]
    )


def build_zotero_codex_handoff_prompt(
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    *,
    build_zotero_capability_broker: CapabilityBrokerBuilder,
) -> str:
    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    item = body.item
    context_payload = zotero_context_payload(body, matched)
    capability_broker = build_zotero_capability_broker(
        body=body,
        matched=matched,
        context_payload=context_payload,
    )
    lines = [
        "你正在 Research Harness 项目中接手一个来自 Zotero 侧边栏的实时请求。",
        "请优先使用 RH 数据库、已有 deepread/provenance/topic notes，而不是重新发明状态。",
        "",
        "## 用户问题",
        body.message.strip(),
        "",
        "## RH 匹配结果",
        f"- match_source: {matched.get('source')}",
        f"- confidence: {matched.get('confidence')}",
        f"- topic_id: {topic.get('id', '')}",
        f"- topic_name: {topic.get('name', '')}",
        f"- paper_id: {paper.get('id', '')}",
        f"- paper_title: {paper.get('title') or item.title}",
        f"- doi: {paper.get('doi') or item.doi}",
        f"- arxiv_id: {paper.get('arxiv_id') or item.arxiv_id}",
        "",
        "## Zotero 当前上下文",
        f"- zotero_item_key: {item.zotero_item_key}",
        f"- library_id: {normalize_zotero_library_id(item.library_id)}",
        f"- title: {item.title}",
        f"- tags: {', '.join(item.tags[:40])}",
        f"- current_directory_key: {item.current_directory_key}",
        f"- current_directory_name: {item.current_directory_name}",
        f"- current_directory_path: {item.current_directory_path}",
        "",
        "## Zotero Capability 工具",
        "这些 capability 由 RH broker allowlist 执行。写入类 capability 只返回 action_preview；用户点击确认前不会写 RH/Zotero。",
        "自然语言意图由你判断；不要用固定短语猜 topic/query。如果用户说“当前文件夹的研究方向”，优先使用当前 collection 名称。",
        "如果用户要求为当前文件夹找起步/种子/候选论文并预览，调用 rh.zotero.prepare_seed_import；topic_name/query 可省略，broker 会默认用当前 collection 名称。",
        json.dumps(
            capability_broker.list(),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    ]
    if item.selected_text:
        lines.extend(
            ["", "## Zotero 选中文本", truncate_text(item.selected_text, 6000)]
        )
    if item.note_text:
        lines.extend(["", "## Zotero 笔记片段", truncate_text(item.note_text, 6000)])
    if item.screenshots:
        lines.extend(
            [
                "",
                "## Zotero 截图",
                f"用户附带了 {len(item.screenshots)} 张截图，请结合图像内容回答。",
            ]
        )
    lines.extend(
        [
            "",
            "## 输出要求",
            "- 用中文回答，简洁但给出可执行下一步。",
            "- 如果需要修改 RH/Zotero 状态，先说明计划和风险；不要绕过 RH sync/provenance 规则。",
            "- 若用户要把论文/PDF 加入 Zotero 并希望可读性增强，触发 paper-reading-annotation skill，生成博士生精读级 PDF 高亮/批注。",
            "- 若匹配不到 RH paper/topic，请建议入库或同步路径。",
        ]
    )
    return "\n".join(lines)
