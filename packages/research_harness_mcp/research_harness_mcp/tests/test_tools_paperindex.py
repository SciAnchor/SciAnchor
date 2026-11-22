"""Focused tests for MCP Paperindex tool helpers."""

from __future__ import annotations


def test_paperindex_tool_definitions_preserve_names_and_schemas() -> None:
    from research_harness_mcp.tools_paperindex import _PAPERINDEX_TOOLS

    assert set(_PAPERINDEX_TOOLS) == {
        "paperindex_search",
        "paperindex_structure",
        "paperindex_card",
    }

    search = _PAPERINDEX_TOOLS["paperindex_search"]
    assert search.name == "paperindex_search"
    assert search.inputSchema == {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": ["query"],
    }

    for name in ("paperindex_structure", "paperindex_card"):
        tool = _PAPERINDEX_TOOLS[name]
        assert tool.inputSchema == {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to PDF file"},
            },
            "required": ["pdf_path"],
        }


def test_execute_paperindex_fallback_preserves_payloads(
    tmp_path,
    monkeypatch,
) -> None:
    import research_harness_mcp.tools_paperindex as tools_paperindex
    from research_harness_mcp.tools_paperindex import _execute_paperindex

    class FakeSearchResult:
        def to_dict(self) -> dict[str, object]:
            return {"title": "Indexed Paper"}

    class FakeStructure:
        def to_dict(self) -> dict[str, object]:
            return {"sections": [{"title": "Intro"}]}

    class FakeRecord:
        card = {"title": "Card Paper"}

    class FakePaperIndexer:
        def search(self, query: str, *, library_root: str, limit: int):
            assert query == "indexed"
            assert library_root == str(tmp_path / ".paperindex")
            assert limit == 2
            return [FakeSearchResult()]

        def extract_structure(self, pdf_path: str):
            assert pdf_path == "paper.pdf"
            return FakeStructure()

        def build_record(self, pdf_path: str):
            assert pdf_path == "paper.pdf"
            return FakeRecord()

    monkeypatch.setattr(tools_paperindex, "PaperIndexer", FakePaperIndexer)
    monkeypatch.setattr(tools_paperindex, "find_workspace_root", lambda: tmp_path)

    assert _execute_paperindex(
        "paperindex_search", {"query": "indexed", "limit": 2}
    ) == {"results": [{"title": "Indexed Paper"}]}
    assert _execute_paperindex("paperindex_structure", {"pdf_path": "paper.pdf"}) == {
        "sections": [{"title": "Intro"}]
    }
    assert _execute_paperindex("paperindex_card", {"pdf_path": "paper.pdf"}) == {
        "title": "Card Paper"
    }
    assert _execute_paperindex("missing", {}) == {
        "error": "Unknown paperindex tool: missing"
    }
