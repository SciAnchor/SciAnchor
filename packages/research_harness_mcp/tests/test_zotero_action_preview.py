"""Focused tests for Zotero action preview helper extraction."""

from __future__ import annotations


def test_zotero_action_preview_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_action_preview

    assert (
        http_api._finalize_zotero_action_preview
        is zotero_action_preview.finalize_zotero_action_preview
    )
    assert (
        http_api._zotero_preview_target_source
        is zotero_action_preview.zotero_preview_target_source
    )
    assert (
        http_api._unique_zotero_preview_warnings
        is zotero_action_preview.unique_zotero_preview_warnings
    )
    assert (
        http_api._zotero_available_actions
        is zotero_action_preview.zotero_available_actions
    )


def test_finalize_zotero_action_preview_adds_review_card_defaults():
    from research_harness_mcp import zotero_action_preview

    preview = zotero_action_preview.finalize_zotero_action_preview(
        {
            "action_type": "zotero_attach_pdf",
            "planned_count": 3,
            "warnings": [" duplicate ", "", "duplicate"],
            "records": [{"paper_id": 1}, {"paper_id": 2}, {"paper_id": 3}],
        },
        capability="rh.zotero.attach_pdf",
        blocked_records=[{"paper_id": 4, "reason": "missing key"}],
        warnings=["duplicate", "fresh"],
    )

    assert preview["preview_id"].startswith("zotero-preview-")
    assert preview["capability"] == "rh.zotero.attach_pdf"
    assert preview["target_set"] == {
        "source": "current_item",
        "record_count": 3,
        "writable_count": 3,
        "blocked_count": 1,
    }
    assert preview["warnings"] == ["duplicate", "fresh"]
    assert preview["blocked_records"] == [{"paper_id": 4, "reason": "missing key"}]
    assert preview["undo_supported"] is True


def test_finalize_zotero_action_preview_preserves_existing_target_set_and_overrides():
    from research_harness_mcp import zotero_action_preview

    preview = zotero_action_preview.finalize_zotero_action_preview(
        {
            "action_type": "sync_rh_papers_to_collection",
            "target_set": {"source": "custom", "record_count": 9},
        },
        capability="rh.zotero.sync_papers",
        target_source="manual",
        target_record_count=2,
        writable_count=1,
        undo_supported=True,
    )

    assert preview["target_set"] == {"source": "custom", "record_count": 9}
    assert preview["capability"] == "rh.zotero.sync_papers"
    assert preview["undo_supported"] is True


def test_unique_zotero_preview_warnings_trims_deduplicates_and_caps():
    from research_harness_mcp import zotero_action_preview

    values = ["", "  alpha  ", "alpha", "x" * 600]
    values.extend(f"warning-{index}" for index in range(30))

    warnings = zotero_action_preview.unique_zotero_preview_warnings(values)

    assert warnings[0] == "alpha"
    assert warnings[1] == "x" * 500
    assert len(warnings) == 20
    assert len(set(warnings)) == len(warnings)


def test_zotero_available_actions_preserves_paper_and_collection_modes():
    from research_harness_mcp import zotero_action_preview

    paper_actions = zotero_action_preview.zotero_available_actions(
        {
            "kind": "paper",
            "directory": {"key": "COLL", "name": "Collection"},
        },
        {
            "paper": {"id": 7},
            "topic": {"id": 3},
        },
    )
    assert [action["action_type"] for action in paper_actions] == [
        "ask_rh_about_current_paper",
        "zotero_attach_pdf",
        "sync_current_paper_to_collection",
    ]
    assert paper_actions[-1]["target_collection_key"] == "COLL"

    collection_actions = zotero_action_preview.zotero_available_actions(
        {
            "kind": "collection",
            "directory": {"key": "COLL", "name": "Collection"},
        },
        {},
    )
    assert [action["action_type"] for action in collection_actions] == [
        "init_topic_from_collection",
        "sync_rh_missing_papers_to_collection",
    ]
    assert collection_actions[0]["target_collection_name"] == "Collection"
