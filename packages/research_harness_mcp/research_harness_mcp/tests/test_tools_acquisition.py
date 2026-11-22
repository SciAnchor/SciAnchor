"""Focused tests for MCP acquisition compatibility tool helpers."""

from __future__ import annotations


def test_acquisition_tool_definitions_preserve_names_and_schemas() -> None:
    from research_harness_mcp.tools_acquisition import _ACQUISITION_TOOLS

    assert set(_ACQUISITION_TOOLS) == {
        "paper_ingest_manual",
        "paper_resolve_pdfs",
    }

    manual = _ACQUISITION_TOOLS["paper_ingest_manual"]
    assert manual.name == "paper_ingest_manual"
    assert manual.inputSchema == {
        "type": "object",
        "properties": {},
    }

    resolver = _ACQUISITION_TOOLS["paper_resolve_pdfs"]
    assert resolver.name == "paper_resolve_pdfs"
    assert resolver.inputSchema == {
        "type": "object",
        "properties": {
            "topic_id": {
                "type": "integer",
                "description": "Topic ID to scope resolution (optional, resolves all if omitted)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, report matches without writing to DB",
                "default": False,
            },
        },
    }


def test_execute_acquisition_preserves_payloads_and_db_resolution_order(
    monkeypatch,
) -> None:
    import research_harness_mcp.tools_acquisition as tools_acquisition
    from research_harness_mcp.tools_acquisition import _execute_acquisition

    calls: list[object] = []
    fake_db = object()

    def fake_db_resolver():
        calls.append("resolve_db")
        return fake_db

    def fake_ingest_manual_downloads(db):
        calls.append(("ingest", db))
        return [{"paper_id": 1}, {"paper_id": 2}]

    class FakeBackfillStats:
        def to_dict(self) -> dict[str, object]:
            return {"linked": 3, "dry_run": True}

    def fake_backfill_pdf_paths(db, *, topic_id, dry_run):
        calls.append(("backfill", db, topic_id, dry_run))
        return FakeBackfillStats()

    monkeypatch.setattr(
        tools_acquisition,
        "ingest_manual_downloads",
        fake_ingest_manual_downloads,
    )
    monkeypatch.setattr(
        tools_acquisition,
        "backfill_pdf_paths",
        fake_backfill_pdf_paths,
    )

    assert _execute_acquisition(
        "paper_ingest_manual",
        {},
        db_resolver=fake_db_resolver,
    ) == {"results": [{"paper_id": 1}, {"paper_id": 2}], "count": 2}
    assert calls == ["resolve_db", ("ingest", fake_db)]

    calls.clear()
    assert _execute_acquisition(
        "paper_resolve_pdfs",
        {"topic_id": 7, "dry_run": True},
        db_resolver=fake_db_resolver,
    ) == {"linked": 3, "dry_run": True}
    assert calls == ["resolve_db", ("backfill", fake_db, 7, True)]

    calls.clear()
    assert _execute_acquisition(
        "unknown",
        {},
        db_resolver=fake_db_resolver,
    ) == {"error": "Unknown acquisition tool: unknown"}
    assert calls == ["resolve_db"]
