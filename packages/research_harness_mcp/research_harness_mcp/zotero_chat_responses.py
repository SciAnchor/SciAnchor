"""Pure response helpers for Zotero chat routes."""

from __future__ import annotations

import hashlib
from typing import Any

from research_harness_mcp.zotero_chat_intent import (
    looks_like_zotero_pdf_attachment_request,
)
from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def unsupported_zotero_write_message(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> str:
    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    item = body.item
    is_pdf_request = looks_like_zotero_pdf_attachment_request(body.message)
    action_label = "PDF 附件写入" if is_pdf_request else "这个 Zotero/RH 写入动作"
    identity_bits = []
    if paper.get("id"):
        identity_bits.append(f"RH paper_id={paper['id']}")
    if item.zotero_item_key:
        identity_bits.append(f"Zotero {item.zotero_item_key}")
    arxiv_id = paper.get("arxiv_id") or item.arxiv_id
    if arxiv_id:
        identity_bits.append(f"arXiv {arxiv_id}")
    if topic.get("id"):
        identity_bits.append(f"topic_id={topic['id']}")
    identity_text = "；".join(identity_bits) if identity_bits else "当前条目"
    return (
        f"我识别到你要对 {identity_text} 执行{action_label}，但这个动作还没有接入侧边栏确认按钮，"
        "所以我不会让你点击不存在的按钮。\n\n"
        "现在侧边栏可确认执行的写入动作包括：新建 Zotero 文件夹、找种子论文并导入、"
        "把 RH 论文导入当前目录、确保 RH PDF 可用后附加到当前 Zotero 条目。"
        "要让这里继续推进，需要先实现一个专门的 dry-run/确认/apply action："
        "预览目标 Zotero 条目、PDF 来源、是否会新增/替换附件，然后再执行写入。"
    )


def zotero_chat_suggested_actions(matched: dict[str, Any]) -> list[dict[str, Any]]:
    paper = matched.get("paper")
    topic = matched.get("topic")
    if not paper:
        return [
            {
                "kind": "sync_or_ingest",
                "label": "先把当前 Zotero 条目同步/入库到 RH",
                "requires_confirmation": True,
            }
        ]
    return [
        {
            "kind": "codex_handoff",
            "label": "把当前问题交给 Codex/RH 继续处理",
            "requires_confirmation": False,
            "paper_id": paper["id"],
            "topic_id": topic["id"] if topic else None,
        },
        {
            "kind": "pull_human_notes",
            "label": "导入 Zotero 人类笔记/标注到 RH",
            "requires_confirmation": True,
            "paper_id": paper["id"],
            "topic_id": topic["id"] if topic else None,
        },
        {
            "kind": "paper_reading_annotation",
            "label": "生成博士精读 PDF 高亮/批注",
            "requires_confirmation": True,
            "paper_id": paper["id"],
            "topic_id": topic["id"] if topic else None,
            "skill": "paper-reading-annotation",
        },
    ]


def stable_zotero_chat_conversation_id(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> str:
    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    seed = "|".join(
        [
            str(topic.get("id") or ""),
            str(paper.get("id") or ""),
            body.item.zotero_item_key,
            body.item.title,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"zotero-chat-{digest}"
