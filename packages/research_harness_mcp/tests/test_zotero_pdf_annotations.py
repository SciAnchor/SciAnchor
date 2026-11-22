"""Focused tests for Zotero PDF annotation plan helper extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _annotation_paper_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            pdf_path TEXT,
            doi TEXT,
            arxiv_id TEXT,
            year INTEGER,
            venue TEXT,
            deep_read TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO papers
            (id, title, abstract, pdf_path, doi, arxiv_id, year, venue, deep_read)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "Annotation One",
                "Abstract one",
                "/tmp/one.pdf",
                "10.1234/one",
                "2601.00001",
                2026,
                "ICLR",
                "{}",
            ),
            (
                2,
                "Annotation Two",
                "Abstract two",
                "/tmp/two.pdf",
                "10.1234/two",
                "2601.00002",
                2025,
                "NeurIPS",
                "{}",
            ),
        ],
    )
    conn.commit()
    return conn


def test_zotero_pdf_annotation_plan_helpers_preserve_http_api_aliases(
    monkeypatch,
    tmp_path: Path,
):
    from research_harness_mcp import http_api, zotero_pdf_annotations

    assert (
        http_api._ZOTERO_ANNOTATION_PROFILE
        == zotero_pdf_annotations.ZOTERO_ANNOTATION_PROFILE
    )
    assert (
        http_api._ZOTERO_ANNOTATION_MARKER
        == zotero_pdf_annotations.ZOTERO_ANNOTATION_MARKER
    )
    assert (
        http_api._ZOTERO_ANNOTATION_SPECS
        is zotero_pdf_annotations.ZOTERO_ANNOTATION_SPECS
    )
    assert (
        http_api._build_zotero_pdf_annotation_plan
        is zotero_pdf_annotations.build_zotero_pdf_annotation_plan
    )
    assert (
        http_api._extract_zotero_pdf_anchor_candidates
        is zotero_pdf_annotations.extract_zotero_pdf_anchor_candidates
    )
    assert (
        http_api._normalize_zotero_pdf_anchor
        is zotero_pdf_annotations.normalize_zotero_pdf_anchor
    )
    assert (
        http_api._validate_zotero_annotation_plan
        is zotero_pdf_annotations.validate_zotero_annotation_plan
    )
    assert (
        http_api._reset_rh_pdf_annotations
        is zotero_pdf_annotations.reset_rh_pdf_annotations
    )
    assert (
        http_api._apply_zotero_pdf_annotation_plan
        is zotero_pdf_annotations.apply_zotero_pdf_annotation_plan
    )
    assert (
        http_api._load_annotation_tool_module
        is zotero_pdf_annotations.load_annotation_tool_module
    )
    assert (
        http_api._backup_pdf_for_zotero_annotations
        is zotero_pdf_annotations.backup_pdf_for_zotero_annotations
    )
    assert (
        http_api._count_rh_pdf_annotations
        is zotero_pdf_annotations.count_rh_pdf_annotations
    )

    db_path = tmp_path / ".research-harness" / "pool.db"
    monkeypatch.setattr(http_api, "DB_PATH", db_path)
    assert http_api._zotero_pdf_annotation_plan_path(
        7, 11
    ) == zotero_pdf_annotations.zotero_pdf_annotation_plan_path(
        db_path=db_path,
        topic_id=7,
        paper_id=11,
    )


def test_normalize_zotero_pdf_anchor_preserves_boundaries():
    from research_harness_mcp import zotero_pdf_annotations

    assert zotero_pdf_annotations.normalize_zotero_pdf_anchor("too short") == ""
    assert zotero_pdf_annotations.normalize_zotero_pdf_anchor("!!! ??? ...") == ""
    assert (
        zotero_pdf_annotations.normalize_zotero_pdf_anchor(
            "•  This anchor sentence contains enough stable evidence for annotation.  "
        )
        == "This anchor sentence contains enough stable evidence for annotation."
    )
    assert (
        zotero_pdf_annotations.normalize_zotero_pdf_anchor(
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen fifteen sixteen seventeen eighteen"
        )
        == "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    )


def test_build_zotero_pdf_annotation_plan_cycles_anchor_candidates(monkeypatch):
    from research_harness_mcp import zotero_pdf_annotations

    anchors = [
        {"anchor": "First stable anchor sentence for annotation.", "page": 1},
        {"anchor": "Second stable anchor sentence for annotation.", "page": 2},
    ]
    monkeypatch.setattr(
        zotero_pdf_annotations,
        "extract_zotero_pdf_anchor_candidates",
        lambda _pdf_path: list(anchors),
    )

    plan = zotero_pdf_annotations.build_zotero_pdf_annotation_plan(
        paper={"id": 42, "title": "Annotation Plan"},
        pdf_path=Path("/tmp/paper.pdf"),
        topic_id=7,
        topic_name="demo-topic",
        focus="focused reading",
    )

    assert plan["paper_id"] == 42
    assert plan["topic_id"] == 7
    assert plan["topic_name"] == "demo-topic"
    assert plan["focus"] == "focused reading"
    assert plan["title"] == "Annotation Plan"
    assert plan["profile"] == zotero_pdf_annotations.ZOTERO_ANNOTATION_PROFILE
    assert len(plan["annotations"]) == len(
        zotero_pdf_annotations.ZOTERO_ANNOTATION_SPECS
    )
    assert plan["annotations"][0]["anchor"] == anchors[0]["anchor"]
    assert plan["annotations"][1]["anchor"] == anchors[1]["anchor"]
    assert plan["annotations"][2]["anchor"] == anchors[0]["anchor"]
    assert plan["annotations"][0]["priority"] == 5
    assert plan["annotations"][7]["priority"] == 5
    assert plan["annotations"][8]["priority"] == 4


def test_apply_rh_pdf_annotations_for_papers_records_found_and_missing_papers():
    from research_harness_mcp import zotero_pdf_annotations

    calls: list[dict[str, Any]] = []

    receipts = zotero_pdf_annotations.apply_rh_pdf_annotations_for_papers(
        paper_ids=[1, "0", 2, -4],
        topic_id=7,
        topic_name="demo-topic",
        focus="focused",
        load_paper_rows=lambda paper_ids: {
            1: {"id": 1, "title": "Found Paper", "pdf_path": "/tmp/found.pdf"}
        },
        apply_rh_pdf_annotations_for_paper=lambda **kwargs: {
            "status": "completed",
            "paper_id": int(kwargs["paper"]["id"]),
            "title": kwargs["paper"]["title"],
        },
        record_zotero_pdf_annotation_artifact=lambda **kwargs: calls.append(kwargs),
    )

    assert receipts == [
        {"status": "completed", "paper_id": 1, "title": "Found Paper"},
        {
            "status": "failed",
            "paper_id": 2,
            "title": "",
            "profile": zotero_pdf_annotations.ZOTERO_ANNOTATION_PROFILE,
            "pdf_path": "",
            "plan_path": "",
            "planned_count": 0,
            "applied_count": 0,
            "verified_count": 0,
            "missing_count": 0,
            "missing": [],
            "error": "paper not found",
        },
    ]
    assert calls == [{"topic_id": 7, "topic_name": "demo-topic", "receipts": receipts}]


def test_zotero_annotation_paper_rows_loads_requested_rows():
    from research_harness_mcp import zotero_pdf_annotations

    conn = _annotation_paper_conn()

    @contextmanager
    def fake_get_db():
        yield conn

    rows = zotero_pdf_annotations.zotero_annotation_paper_rows(
        [2, 1],
        get_db_context=fake_get_db,
    )

    assert rows == {
        1: {
            "id": 1,
            "title": "Annotation One",
            "abstract": "Abstract one",
            "pdf_path": "/tmp/one.pdf",
            "doi": "10.1234/one",
            "arxiv_id": "2601.00001",
            "year": 2026,
            "venue": "ICLR",
            "deep_read": "{}",
        },
        2: {
            "id": 2,
            "title": "Annotation Two",
            "abstract": "Abstract two",
            "pdf_path": "/tmp/two.pdf",
            "doi": "10.1234/two",
            "arxiv_id": "2601.00002",
            "year": 2025,
            "venue": "NeurIPS",
            "deep_read": "{}",
        },
    }


def test_http_api_zotero_annotation_paper_rows_uses_dynamic_get_db(monkeypatch):
    from research_harness_mcp import http_api

    conn = _annotation_paper_conn()
    calls: list[str] = []

    @contextmanager
    def fake_get_db():
        calls.append("get_db")
        yield conn

    monkeypatch.setattr(http_api, "get_db", fake_get_db)

    rows = http_api._zotero_annotation_paper_rows([1])

    assert calls == ["get_db"]
    assert rows[1]["title"] == "Annotation One"
    assert set(rows) == {1}


def test_apply_rh_pdf_annotations_for_paper_returns_skip_receipt_for_untrusted_pdf():
    from research_harness_mcp import zotero_pdf_annotations

    receipt = zotero_pdf_annotations.apply_rh_pdf_annotations_for_paper(
        paper={"id": 3, "title": "No PDF", "pdf_path": "/outside.pdf"},
        topic_id=7,
        topic_name="demo-topic",
        focus="",
        trusted_pdf_path_for_zotero=lambda _raw: (None, "outside trusted roots"),
        build_zotero_pdf_annotation_plan=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("plan should not be built for untrusted PDFs")
        ),
    )

    assert receipt["status"] == "skipped"
    assert receipt["paper_id"] == 3
    assert receipt["title"] == "No PDF"
    assert receipt["error"] == "outside trusted roots"


def test_apply_rh_pdf_annotations_for_paper_writes_plan_and_completed_receipt(
    tmp_path: Path,
):
    from research_harness_mcp import zotero_pdf_annotations

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    plan_path = tmp_path / "annotation_plan.json"
    backup_path = tmp_path / "paper.pdf.backup"
    plan = {
        "profile": zotero_pdf_annotations.ZOTERO_ANNOTATION_PROFILE,
        "annotations": [{"anchor": "stable anchor", "page": 1}],
    }

    receipt = zotero_pdf_annotations.apply_rh_pdf_annotations_for_paper(
        paper={"id": 4, "title": "Completed", "pdf_path": str(pdf_path)},
        topic_id=7,
        topic_name="demo-topic",
        focus="focus",
        trusted_pdf_path_for_zotero=lambda raw: (Path(raw), None),
        build_zotero_pdf_annotation_plan=lambda **_kwargs: dict(plan),
        validate_zotero_annotation_plan=lambda _plan: {"ok": True, "errors": []},
        zotero_pdf_annotation_plan_path=lambda _topic_id, _paper_id: plan_path,
        backup_pdf_for_zotero_annotations=lambda _pdf_path: backup_path,
        reset_rh_pdf_annotations=lambda _pdf_path: {"removed_count": 2},
        apply_zotero_pdf_annotation_plan=lambda _pdf_path, _plan_path: {
            "profile": zotero_pdf_annotations.ZOTERO_ANNOTATION_PROFILE,
            "marker": zotero_pdf_annotations.ZOTERO_ANNOTATION_MARKER,
            "planned_count": 1,
            "applied_count": 1,
            "duplicate_count": 0,
            "missing_count": 0,
            "missing": [],
        },
        count_rh_pdf_annotations=lambda _pdf_path, *, marker: 1,
    )

    assert plan_path.exists()
    assert '"annotations"' in plan_path.read_text(encoding="utf-8")
    assert receipt["status"] == "completed"
    assert receipt["paper_id"] == 4
    assert receipt["planned_count"] == 1
    assert receipt["applied_count"] == 1
    assert receipt["verified_count"] == 1
    assert receipt["reset_removed_count"] == 2
    assert receipt["backup_path"] == str(backup_path)


def test_record_zotero_pdf_annotation_artifact_builds_payload():
    from research_harness_mcp import zotero_pdf_annotations

    calls: list[tuple[str, dict[str, Any]]] = []
    receipts = [{"paper_id": 4, "status": "completed"}]

    zotero_pdf_annotations.record_zotero_pdf_annotation_artifact(
        topic_id=7,
        topic_name="demo-topic",
        receipts=receipts,
        execute_tool=lambda name, arguments: calls.append((name, arguments)),
    )

    assert calls == [
        (
            "orchestrator_record_artifact",
            {
                "topic_id": 7,
                "stage": "collect",
                "artifact_type": "zotero_pdf_annotation_receipt",
                "title": "Zotero PDF annotation receipt: demo-topic",
                "payload": {
                    "schema": "rh.schema.zotero_pdf_annotation_receipt.v1",
                    "topic_id": 7,
                    "topic_name": "demo-topic",
                    "receipts": receipts,
                },
            },
        )
    ]

    zotero_pdf_annotations.record_zotero_pdf_annotation_artifact(
        topic_id=0,
        topic_name="demo-topic",
        receipts=receipts,
        execute_tool=lambda *_args: (_ for _ in ()).throw(
            AssertionError("missing topic_id should be a no-op")
        ),
    )
    zotero_pdf_annotations.record_zotero_pdf_annotation_artifact(
        topic_id=7,
        topic_name="demo-topic",
        receipts=[],
        execute_tool=lambda *_args: (_ for _ in ()).throw(
            AssertionError("empty receipts should be a no-op")
        ),
    )


def test_http_api_record_zotero_pdf_annotation_artifact_uses_dynamic_execute_tool(
    monkeypatch,
):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(
        http_api,
        "execute_tool",
        lambda name, arguments: calls.append((name, arguments)),
    )

    http_api._record_zotero_pdf_annotation_artifact(
        topic_id=8,
        topic_name="dynamic-topic",
        receipts=[{"paper_id": 5, "status": "completed"}],
    )

    assert calls == [
        (
            "orchestrator_record_artifact",
            {
                "topic_id": 8,
                "stage": "collect",
                "artifact_type": "zotero_pdf_annotation_receipt",
                "title": "Zotero PDF annotation receipt: dynamic-topic",
                "payload": {
                    "schema": "rh.schema.zotero_pdf_annotation_receipt.v1",
                    "topic_id": 8,
                    "topic_name": "dynamic-topic",
                    "receipts": [{"paper_id": 5, "status": "completed"}],
                },
            },
        )
    ]
