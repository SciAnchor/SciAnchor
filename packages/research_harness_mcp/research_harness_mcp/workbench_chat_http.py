"""Chat and human-decision HTTP routes for the RH paper-production workbench.

The workbench chat is the human-in-the-loop surface for non-technical
researchers: a free-form assistant conversation plus structured decision
cards. Decision recording never goes through the LLM; option clicks call the
same deterministic checkpoint path as the MCP decision tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from research_harness_mcp.paper_production_workbench_http import (
    _hypothesis_tree_payload,
    _latest_run,
    _topic_or_404,
    _tree_status_summary,
)


logger = logging.getLogger(__name__)

CHAT_HISTORY_LIMIT = 200
PROMPT_HISTORY_LIMIT = 12

# Mirrors migrations/073_workbench_chat_messages.sql so the HTTP surface also
# works against databases that have not run `Database.migrate()` yet.
_CHAT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS workbench_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chat',
    content TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
)
"""


def _ensure_chat_table(conn: Any) -> None:
    conn.execute(_CHAT_TABLE_DDL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workbench_chat_messages_topic "
        "ON workbench_chat_messages(topic_id, id)"
    )


class WorkbenchChatMessageRequest(BaseModel):
    message: str


class WorkbenchDecisionRequest(BaseModel):
    choice: str
    reasoning: str = ""


def register_workbench_chat_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
    now_iso: Callable[[], str],
    pending_decisions_provider: Callable[[int], dict[str, Any]],
    decision_recorder: Callable[[int, str, str], dict[str, Any]],
    chat_reply_provider: Callable[[str], str],
) -> None:
    """Register workbench chat and decision endpoints."""

    @app.get("/api/workbench/topics/{topic_id}/chat")
    def get_workbench_chat(topic_id: int):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
            _ensure_chat_table(conn)
            messages = _load_messages(
                conn,
                topic_id=topic_id,
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
            )
        return {
            "topic_id": topic_id,
            "messages": messages,
            "pending_decision": _pending_decision(pending_decisions_provider, topic_id),
        }

    @app.get("/api/workbench/topics/{topic_id}/pending-decisions")
    def get_workbench_pending_decisions(topic_id: int):
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)
        return pending_decisions_provider(topic_id)

    @app.post("/api/workbench/topics/{topic_id}/chat")
    def post_workbench_chat_message(topic_id: int, body: WorkbenchChatMessageRequest):
        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="message must not be empty")

        pending = _pending_decision(pending_decisions_provider, topic_id)
        with get_db_context() as conn:
            topic = _topic_or_404(conn, topic_id, row_to_dict)
            _ensure_chat_table(conn)
            history = _load_messages(
                conn,
                topic_id=topic_id,
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
                limit=PROMPT_HISTORY_LIMIT,
            )
            prompt = _build_chat_prompt(
                conn,
                topic=topic,
                topic_id=topic_id,
                row_to_dict=row_to_dict,
                parse_json_field=parse_json_field,
                pending=pending,
                history=history,
                message=message,
            )

        try:
            reply = str(chat_reply_provider(prompt)).strip()
            reply_kind = "chat"
            if not reply:
                reply = "（助手没有返回内容，请重试。）"
                reply_kind = "error"
        except Exception as exc:  # noqa: BLE001 - surface any provider failure in chat
            logger.exception("workbench chat reply provider failed")
            reply = f"（助手暂时不可用：{exc}。请检查 RH 的 LLM 配置后重试。）"
            reply_kind = "error"

        with get_db_context() as conn:
            _ensure_chat_table(conn)
            user_message = _insert_message(
                conn,
                topic_id=topic_id,
                role="user",
                kind="chat",
                content=message,
                payload=None,
                now_iso=now_iso,
            )
            assistant_message = _insert_message(
                conn,
                topic_id=topic_id,
                role="assistant",
                kind=reply_kind,
                content=reply,
                payload=None,
                now_iso=now_iso,
            )
            conn.commit()

        return {
            "topic_id": topic_id,
            "messages": [user_message, assistant_message],
            "pending_decision": pending,
        }

    @app.post("/api/workbench/topics/{topic_id}/decisions")
    def post_workbench_decision(topic_id: int, body: WorkbenchDecisionRequest):
        choice = body.choice.strip()
        if not choice:
            raise HTTPException(status_code=422, detail="choice must not be empty")
        with get_db_context() as conn:
            _topic_or_404(conn, topic_id, row_to_dict)

        pending = _pending_decision(pending_decisions_provider, topic_id)
        if pending is None:
            raise HTTPException(
                status_code=409,
                detail=f"Topic {topic_id} has no pending decision",
            )
        options = [
            option for option in pending.get("options", []) if isinstance(option, dict)
        ]
        allowed = [str(option.get("action") or "") for option in options]
        if allowed and choice not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"choice must be one of: {', '.join(allowed)}",
            )

        result = decision_recorder(topic_id, choice, body.reasoning.strip())
        if not isinstance(result, dict):
            result = {"status": "error", "message": "decision recorder failed"}

        messages: list[dict[str, Any]] = []
        if result.get("status") == "accepted":
            chosen_label = choice
            for option in options:
                if str(option.get("action") or "") == choice:
                    chosen_label = str(option.get("label") or choice)
                    break
            content = f"已选择：{chosen_label}"
            if body.reasoning.strip():
                content += f"\n补充说明：{body.reasoning.strip()}"
            with get_db_context() as conn:
                _ensure_chat_table(conn)
                messages.append(
                    _insert_message(
                        conn,
                        topic_id=topic_id,
                        role="user",
                        kind="decision",
                        content=content,
                        payload={
                            "choice": choice,
                            "request_id": pending.get("request_id"),
                            "reason_code": pending.get("reason_code"),
                        },
                        now_iso=now_iso,
                    )
                )
                messages.append(
                    _insert_message(
                        conn,
                        topic_id=topic_id,
                        role="assistant",
                        kind="decision_ack",
                        content=(
                            f"决定已记录：{chosen_label}。"
                            "工作流将按这个选择继续，你可以随时在这里查看进展或继续提问。"
                        ),
                        payload={"choice": choice},
                        now_iso=now_iso,
                    )
                )
                conn.commit()

        return {
            "topic_id": topic_id,
            "status": result.get("status", "error"),
            "result": result,
            "messages": messages,
            "pending_decision": _pending_decision(pending_decisions_provider, topic_id),
        }


def _pending_decision(
    pending_decisions_provider: Callable[[int], dict[str, Any]],
    topic_id: int,
) -> dict[str, Any] | None:
    try:
        payload = pending_decisions_provider(topic_id)
    except Exception:  # noqa: BLE001 - checkpoint state must not break chat reads
        logger.exception("workbench pending-decision lookup failed")
        return None
    if not isinstance(payload, dict) or not payload.get("has_pending"):
        return None
    decision = payload.get("decision")
    return dict(decision) if isinstance(decision, dict) else None


def _load_messages(
    conn: Any,
    *,
    topic_id: int,
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
    limit: int = CHAT_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, topic_id, role, kind, content, payload_json, created_at
        FROM workbench_chat_messages
        WHERE topic_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (topic_id, limit),
    ).fetchall()
    messages: list[dict[str, Any]] = []
    for row in reversed(rows):
        record = row_to_dict(row)
        record["payload"] = parse_json_field(record.pop("payload_json", None), None)
        messages.append(record)
    return messages


def _insert_message(
    conn: Any,
    *,
    topic_id: int,
    role: str,
    kind: str,
    content: str,
    payload: dict[str, Any] | None,
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    created_at = now_iso()
    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    cursor = conn.execute(
        """
        INSERT INTO workbench_chat_messages
            (topic_id, role, kind, content, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (topic_id, role, kind, content, payload_json, created_at),
    )
    return {
        "id": cursor.lastrowid,
        "topic_id": topic_id,
        "role": role,
        "kind": kind,
        "content": content,
        "payload": payload,
        "created_at": created_at,
    }


def _build_chat_prompt(
    conn: Any,
    *,
    topic: dict[str, Any],
    topic_id: int,
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
    pending: dict[str, Any] | None,
    history: list[dict[str, Any]],
    message: str,
) -> str:
    run = _latest_run(conn, topic_id, row_to_dict)
    tree_payload = _hypothesis_tree_payload(conn, topic_id, parse_json_field)
    summary = _tree_status_summary(tree_payload)

    lines = [
        "你是 Research Harness（RH）科研工作流的研究助手，服务对象是非技术背景的研究者。",
        "请用简洁通俗的语言回答；用户用什么语言提问，你就用什么语言回答。",
        "你可以解释当前进度和术语、建议下一步，并认真听取用户的经验反馈。",
        "你不能替用户执行工作流决策：当存在待人工决策事项时，"
        "请解释各选项的利弊，并提醒用户点击界面上的选项按钮确认。",
        "",
        "[研究主题]",
        f"名称: {topic.get('name') or ''}",
        f"描述: {topic.get('description') or '（无）'}",
        f"目标会议/期刊: {topic.get('target_venue') or '（未设定）'}",
        "",
        "[工作流状态]",
        f"当前阶段: {(run or {}).get('current_stage') or '尚未开始论文生产流程'}",
        f"阶段状态: {(run or {}).get('stage_status') or '（无）'}",
        "假设进展: "
        f"支持 {summary['supported']} / 反驳 {summary['refuted']} / "
        f"不确定 {summary['inconclusive']} / 受阻 {summary['blocked']} / "
        f"未测试 {summary['untested']}",
    ]

    if pending is None:
        lines += ["", "[待人工决策]", "当前没有等待用户确认的决策。"]
    else:
        lines += ["", "[待人工决策]", f"问题: {pending.get('prompt') or ''}"]
        for option in pending.get("options", []):
            if not isinstance(option, dict):
                continue
            option_line = f"- {option.get('action')}（{option.get('label') or option.get('action')}）"
            if option.get("description"):
                option_line += f": {option['description']}"
            if option.get("expected_effect"):
                option_line += f"（预期效果: {option['expected_effect']}）"
            if option.get("recommended"):
                option_line += " [AI 推荐]"
            lines.append(option_line)

    if history:
        lines += ["", "[最近对话]"]
        for record in history[-PROMPT_HISTORY_LIMIT:]:
            speaker = "用户" if record.get("role") == "user" else "助手"
            lines.append(f"{speaker}: {record.get('content') or ''}")

    lines += [
        "",
        "[用户新消息]",
        message,
        "",
        "请直接给出回复内容，不要重复以上上下文。",
    ]
    return "\n".join(lines)
