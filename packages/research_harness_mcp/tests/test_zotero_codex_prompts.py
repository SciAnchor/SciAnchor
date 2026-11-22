"""Focused tests for Zotero Codex prompt helper extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


class _Broker:
    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "rh.paper.list",
                "description": "List papers",
                "read_only": True,
            }
        ]


def _body() -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": "  请基于当前论文给出下一步  ",
            "item": {
                "zotero_item_key": "ITEM1",
                "library_id": 123,
                "title": "Agentic Research Harness",
                "doi": "10.1000/demo",
                "tags": ["agent", "rh"],
                "selected_text": "A" * 6100,
                "note_text": "human note",
                "screenshots": ["data:image/png;base64,abc"],
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Reading",
                "current_directory_path": "Root/Agent Reading",
            },
        }
    )


def _matched() -> dict[str, Any]:
    return {
        "source": "doi",
        "confidence": "high",
        "paper": {
            "id": 7,
            "title": "Matched Paper",
            "doi": "10.1000/matched",
            "arxiv_id": "2501.00001",
        },
        "topic": {"id": 3, "name": "demo-topic"},
    }


def test_zotero_codex_prompts_module_imports_and_http_private_wrappers_exist():
    from research_harness_mcp import http_api, zotero_codex_prompts

    assert callable(zotero_codex_prompts.build_zotero_codex_handoff_prompt)
    assert callable(zotero_codex_prompts.build_zotero_codex_turn_prompt)
    assert callable(http_api._build_zotero_codex_handoff_prompt)
    assert callable(http_api._build_zotero_codex_turn_prompt)


def test_handoff_prompt_preserves_context_and_capability_listing():
    from research_harness_mcp import zotero_codex_prompts

    prompt = zotero_codex_prompts.build_zotero_codex_handoff_prompt(
        _body(),
        _matched(),
        build_zotero_capability_broker=lambda **_kwargs: _Broker(),
    )

    assert (
        "你正在 Research Harness 项目中接手一个来自 Zotero 侧边栏的实时请求。" in prompt
    )
    assert "请基于当前论文给出下一步" in prompt
    assert "- match_source: doi" in prompt
    assert "- topic_id: 3" in prompt
    assert "- paper_title: Matched Paper" in prompt
    assert "- library_id: 123" in prompt
    assert "- tags: agent, rh" in prompt
    assert '"name":"rh.paper.list"' in prompt
    assert "## Zotero 选中文本" in prompt
    assert "## Zotero 笔记片段" in prompt
    assert "用户附带了 1 张截图" in prompt
    assert "A" * 6000 in prompt
    assert "A" * 6001 not in prompt


def test_turn_prompt_preserves_first_turn_and_followup_guidance():
    from research_harness_mcp import zotero_codex_prompts

    first_turn = zotero_codex_prompts.build_zotero_codex_turn_prompt(
        _body(),
        _matched(),
        is_followup=False,
        build_zotero_capability_broker=lambda **_kwargs: _Broker(),
    )
    followup = zotero_codex_prompts.build_zotero_codex_turn_prompt(
        _body(),
        _matched(),
        is_followup=True,
        build_zotero_capability_broker=lambda **_kwargs: _Broker(),
    )

    assert "直接回答用户问题，不要输出交接说明。" in first_turn
    assert "这是同一个 Zotero/RH 会话的后续问题" not in first_turn
    assert "这是同一个 Zotero/RH 会话的后续问题" in followup
    assert "直接接着上一轮回答，不要重新介绍系统。" in followup
