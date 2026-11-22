"""Focused tests for Zotero PDF attachment materialization helper extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from research_harness.acquisition.downloader import DownloadResult
from research_harness.pdf_download import PaperDownloadCandidate
from research_harness_mcp.zotero_action_preview import finalize_zotero_action_preview
from research_harness_mcp.zotero_models_http import (
    ZoteroChatRequest,
    ZoteroChatTargetRef,
)


def _paper_conn(
    *,
    pdf_path: str = "",
    doi: str = "",
    arxiv_id: str = "",
    pmid: str = "",
    pmcid: str = "",
    url: str = "",
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            year INTEGER,
            venue TEXT,
            doi TEXT,
            arxiv_id TEXT,
            pmid TEXT,
            pmcid TEXT,
            url TEXT,
            pdf_path TEXT,
            status TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO papers
            (id, title, year, venue, doi, arxiv_id, pmid, pmcid, url, pdf_path, status)
        VALUES (1, 'Attachable PDF', 2026, 'ICLR', ?, ?, ?, ?, ?, ?, 'pdf_ready')
        """,
        (doi, arxiv_id, pmid, pmcid, url, pdf_path),
    )
    conn.commit()
    return conn


def _trusted_path_for(root: Path):
    def trusted_pdf_path(raw: str) -> tuple[Path | None, str | None]:
        if not raw:
            return None, "pdf_path missing"
        path = Path(raw).expanduser().resolve()
        if not path.is_relative_to(root):
            return None, "PDF path is outside trusted roots"
        return path, None

    return trusted_pdf_path


def test_zotero_pdf_attachment_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_pdf_attachment

    assert http_api.ZoteroAttachablePdf is zotero_pdf_attachment.ZoteroAttachablePdf
    assert (
        http_api._zotero_paper_has_download_source
        is zotero_pdf_attachment.zotero_paper_has_download_source
    )
    assert (
        http_api._download_zotero_attachable_pdf
        is zotero_pdf_attachment.download_zotero_attachable_pdf
    )


def test_zotero_paper_has_download_source_accepts_pmcid_only():
    from research_harness_mcp import zotero_pdf_attachment

    assert zotero_pdf_attachment.zotero_paper_has_download_source(
        {"doi": "", "arxiv_id": "", "url": "", "pmcid": "PMC1234567"}
    )


def test_ensure_zotero_attachable_pdf_materializes_and_persists_download(
    tmp_path: Path,
):
    from research_harness_mcp import zotero_pdf_attachment

    conn = _paper_conn(url="https://openreview.net/forum?id=abc123")
    db_path = tmp_path / "pool.db"
    calls: list[dict[str, Any]] = []

    def fake_download(
        candidate: PaperDownloadCandidate, output_dir: Path
    ) -> DownloadResult:
        calls.append({"paper_id": candidate.paper_id, "output_dir": output_dir})
        assert candidate.url == "https://openreview.net/forum?id=abc123"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "1_downloaded.pdf"
        path.write_bytes(b"%PDF-1.4\n% test\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="test-provider",
        )

    result = zotero_pdf_attachment.ensure_zotero_attachable_pdf(
        conn,
        1,
        db_path=db_path,
        trusted_pdf_path_for_zotero=_trusted_path_for(tmp_path),
        trusted_pdf_roots_for_zotero=lambda: ([tmp_path], None),
        download_zotero_attachable_pdf=fake_download,
    )

    assert result.ok is True
    assert result.materialized is True
    assert result.provider == "test-provider"
    assert result.pdf_path == tmp_path / "papers" / "1_downloaded.pdf"
    assert calls == [{"paper_id": 1, "output_dir": tmp_path / "papers"}]

    row = conn.execute("SELECT pdf_path, status FROM papers WHERE id = 1").fetchone()
    assert Path(row["pdf_path"]) == result.pdf_path
    assert row["status"] == "downloaded"


def test_ensure_zotero_attachable_pdf_materializes_from_pmcid_only(
    tmp_path: Path,
):
    from research_harness_mcp import zotero_pdf_attachment

    conn = _paper_conn(pmid="12345678", pmcid="PMC1234567")
    db_path = tmp_path / "pool.db"
    calls: list[PaperDownloadCandidate] = []

    def fake_download(
        candidate: PaperDownloadCandidate, output_dir: Path
    ) -> DownloadResult:
        calls.append(candidate)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "pmc.pdf"
        path.write_bytes(b"%PDF-1.4\n% pmc\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="europe-pmc-test",
        )

    result = zotero_pdf_attachment.ensure_zotero_attachable_pdf(
        conn,
        1,
        db_path=db_path,
        trusted_pdf_path_for_zotero=_trusted_path_for(tmp_path),
        trusted_pdf_roots_for_zotero=lambda: ([tmp_path], None),
        download_zotero_attachable_pdf=fake_download,
    )

    assert result.ok is True
    assert calls[0].pmid == "12345678"
    assert calls[0].pmcid == "PMC1234567"


def test_ensure_zotero_attachable_pdf_preserves_missing_source_reason(
    tmp_path: Path,
):
    from research_harness_mcp import zotero_pdf_attachment

    conn = _paper_conn(pdf_path="/outside/recorded.pdf")

    result = zotero_pdf_attachment.ensure_zotero_attachable_pdf(
        conn,
        1,
        db_path=tmp_path / "pool.db",
        trusted_pdf_path_for_zotero=_trusted_path_for(tmp_path),
        trusted_pdf_roots_for_zotero=lambda: ([tmp_path], None),
        download_zotero_attachable_pdf=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("download should not run without DOI/arXiv/url")
        ),
    )

    assert result.ok is False
    assert result.paper_id == 1
    assert "PDF path is outside trusted roots" in result.reason
    assert "没有 DOI/arXiv/PMCID/url 可用于 RH 下载" in result.reason


def test_http_api_ensure_zotero_attachable_pdf_uses_patchable_download_alias(
    monkeypatch,
    tmp_path: Path,
):
    from research_harness_mcp import http_api

    conn = _paper_conn(url="https://openreview.net/forum?id=patched")
    db_path = tmp_path / ".research-harness" / "pool.db"
    db_path.parent.mkdir()
    calls: list[int] = []

    def fake_download(
        candidate: PaperDownloadCandidate, output_dir: Path
    ) -> DownloadResult:
        calls.append(candidate.paper_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "patched.pdf"
        path.write_bytes(b"%PDF-1.4\n% patched\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="patched-provider",
        )

    monkeypatch.setattr(http_api, "DB_PATH", db_path)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [db_path.parent])
    monkeypatch.setattr(http_api, "_download_zotero_attachable_pdf", fake_download)

    result = http_api.ensure_zotero_attachable_pdf(conn, 1)

    assert calls == [1]
    assert result.ok is True
    assert result.provider == "patched-provider"
    assert result.pdf_path == db_path.parent / "papers" / "patched.pdf"


def test_prepare_zotero_pdf_attachment_action_builds_single_item_preview(
    tmp_path: Path,
):
    from research_harness_mcp import zotero_pdf_attachment

    conn = object()
    pdf_path = tmp_path / "single.pdf"
    body = ZoteroChatRequest.model_validate(
        {
            "message": "帮我附加 PDF",
            "item": {
                "zotero_item_key": "ITEM1",
                "library_id": "42",
                "library_type": "group",
                "title": "Zotero Title",
                "arxiv_id": "2601.00001",
            },
        }
    )
    calls: list[Any] = []

    @contextmanager
    def fake_get_db():
        calls.append("get_db")
        yield conn

    def fake_ensure(db_conn, paper_id):
        assert db_conn is conn
        calls.append(f"ensure:{paper_id}")
        return zotero_pdf_attachment.ZoteroAttachablePdf(
            ok=True,
            paper_id=paper_id,
            row={
                "title": "Attachable Single",
                "doi": "10.1234/single",
                "arxiv_id": "2601.99999",
            },
            pdf_path=pdf_path,
            materialized=True,
        )

    result = zotero_pdf_attachment.prepare_zotero_pdf_attachment_action(
        body,
        {"paper": {"id": 7, "title": "Matched Title"}, "topic": {"id": 3}},
        looks_like_zotero_pdf_attachment_request=lambda message: (
            calls.append(("looks_like", message)) or True
        ),
        get_db_context=fake_get_db,
        ensure_zotero_attachable_pdf=fake_ensure,
        normalize_zotero_library_id=lambda value: f"normalized:{value}",
        finalize_zotero_action_preview=finalize_zotero_action_preview,
        prepare_zotero_pdf_attachment_batch_action=lambda **_kwargs: (
            _ for _ in ()
        ).throw(AssertionError("batch helper should not run")),
    )

    assert calls == [("looks_like", "帮我附加 PDF"), "get_db", "ensure:7"]
    assert result["kind"] == "action_preview"
    preview = result["preview"]
    assert preview["action_type"] == "zotero_attach_pdf"
    assert preview["paper_id"] == 7
    assert preview["topic_id"] == 3
    assert preview["source_label"] == "RH PDF · arXiv 2601.99999 · 已由 RH 下载补齐"
    assert preview["target_label"] == "Zotero item ITEM1"
    assert preview["pdf_path"] == str(pdf_path)
    assert preview["records"] == [
        {
            "paper_id": 7,
            "title": "Attachable Single",
            "doi": "10.1234/single",
            "arxiv_id": "2601.99999",
            "pdf_path": str(pdf_path),
        }
    ]
    assert preview["apply"] == {
        "type": "zotero_local",
        "handler": "zotero_import_file_attachment",
        "label": "确认附加 PDF",
        "payload": {
            "parent_item_key": "ITEM1",
            "parent_library_id": "normalized:42",
            "library_type": "group",
            "paper_id": 7,
            "topic_id": 3,
            "pdf_path": str(pdf_path),
            "title": "Attachable Single",
            "replace_existing": False,
        },
    }
    assert preview["target_set"] == {
        "source": "current_item",
        "record_count": 1,
        "writable_count": 1,
        "blocked_count": 0,
    }


def test_prepare_zotero_pdf_attachment_action_delegates_batch_targets():
    from research_harness_mcp import zotero_pdf_attachment

    body = ZoteroChatRequest.model_validate(
        {"message": "批量附加 PDF", "item": {"zotero_item_key": "ITEM1"}}
    )
    target = ZoteroChatTargetRef(paper_id=1, zotero_item_key="ITEM1")
    calls: list[dict[str, Any]] = []

    result = zotero_pdf_attachment.prepare_zotero_pdf_attachment_action(
        body,
        {"paper": {"id": 1}},
        target_refs=[target],
        target_source="selected_items",
        looks_like_zotero_pdf_attachment_request=lambda _message: (_ for _ in ()).throw(
            AssertionError("single-item intent check should not run for batch targets")
        ),
        get_db_context=lambda: (_ for _ in ()).throw(
            AssertionError("db should be owned by batch helper")
        ),
        ensure_zotero_attachable_pdf=lambda *_args: (_ for _ in ()).throw(
            AssertionError("single-item ensure should not run for batch targets")
        ),
        normalize_zotero_library_id=lambda value: value,
        finalize_zotero_action_preview=finalize_zotero_action_preview,
        prepare_zotero_pdf_attachment_batch_action=lambda **kwargs: (
            calls.append(kwargs) or {"kind": "action_preview", "preview": "batch"}
        ),
    )

    assert result == {"kind": "action_preview", "preview": "batch"}
    assert calls == [
        {
            "body": body,
            "matched": {"paper": {"id": 1}},
            "target_refs": [target],
            "target_source": "selected_items",
        }
    ]


def test_http_api_prepare_zotero_pdf_attachment_action_uses_dynamic_dependencies(
    monkeypatch,
    tmp_path: Path,
):
    from research_harness_mcp import http_api

    conn = object()
    calls: list[str] = []
    body = ZoteroChatRequest.model_validate(
        {
            "message": "附加 PDF",
            "item": {
                "zotero_item_key": "ITEMDYN",
                "library_id": "lib-dyn",
            },
        }
    )

    @contextmanager
    def fake_get_db():
        calls.append("get_db")
        yield conn

    def fake_ensure(db_conn, paper_id):
        assert db_conn is conn
        calls.append(f"ensure:{paper_id}")
        return http_api.ZoteroAttachablePdf(
            ok=True,
            paper_id=paper_id,
            row={"title": "Dynamic Single"},
            pdf_path=tmp_path / "dynamic.pdf",
        )

    def fake_finalize(preview, **kwargs):
        calls.append("finalize")
        return {"preview": preview, "kwargs": kwargs}

    monkeypatch.setattr(
        http_api,
        "_looks_like_zotero_pdf_attachment_request",
        lambda message: calls.append(f"looks_like:{message}") or True,
    )
    monkeypatch.setattr(http_api, "get_db", fake_get_db)
    monkeypatch.setattr(http_api, "ensure_zotero_attachable_pdf", fake_ensure)
    monkeypatch.setattr(
        http_api,
        "_normalize_zotero_library_id",
        lambda value: f"normalized:{value}",
    )
    monkeypatch.setattr(http_api, "_finalize_zotero_action_preview", fake_finalize)

    result = http_api._prepare_zotero_pdf_attachment_action(
        body,
        {"paper": {"id": 9}, "topic": {}},
    )

    assert calls == ["looks_like:附加 PDF", "get_db", "ensure:9", "finalize"]
    assert result["kind"] == "action_preview"
    preview = result["preview"]["preview"]
    assert preview["apply"]["payload"]["parent_library_id"] == "normalized:lib-dyn"
    assert result["preview"]["kwargs"] == {
        "capability": "rh.zotero.attach_pdf",
        "target_source": "current_item",
        "target_record_count": 1,
        "writable_count": 1,
        "undo_supported": True,
    }


def test_prepare_zotero_pdf_attachment_batch_action_builds_preview(
    tmp_path: Path,
):
    from research_harness_mcp import zotero_pdf_attachment

    conn = object()
    pdf_path = tmp_path / "paper-one.pdf"
    body = ZoteroChatRequest.model_validate(
        {
            "message": "批量附加 PDF",
            "item": {
                "library_id": "99",
                "library_type": "group",
            },
        }
    )
    targets = [
        ZoteroChatTargetRef(
            paper_id=1,
            zotero_item_key="ITEM1",
            library_id="42",
            library_type="user",
            title="Target One",
        ),
        ZoteroChatTargetRef(
            paper_id=2,
            zotero_item_key="ITEM2",
            title="Target Two",
        ),
        ZoteroChatTargetRef(title="Unmatched"),
    ]
    resolved_by_title = {
        "Target One": {
            "paper_id": 1,
            "topic_id": 7,
            "title": "Resolved One",
            "doi": "10.1234/one",
            "arxiv_id": "2601.00001",
            "zotero_item_key": "ITEM1",
        },
        "Target Two": {
            "paper_id": 2,
            "topic_id": 8,
            "title": "Resolved Two",
            "zotero_item_key": "ITEM2",
        },
        "Unmatched": {"title": "Unmatched"},
    }
    ensured_ids: list[int] = []

    @contextmanager
    def fake_get_db():
        yield conn

    def fake_resolve_target(db_conn, target):
        assert db_conn is conn
        return resolved_by_title[target.title]

    def fake_ensure_attachable_pdf(db_conn, paper_id):
        assert db_conn is conn
        ensured_ids.append(paper_id)
        if paper_id == 1:
            return zotero_pdf_attachment.ZoteroAttachablePdf(
                ok=True,
                paper_id=1,
                row={
                    "title": "Attachable One",
                    "doi": "10.9999/module",
                    "arxiv_id": "2601.99999",
                },
                pdf_path=pdf_path,
            )
        return zotero_pdf_attachment.ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            reason="PDF path missing",
        )

    result = zotero_pdf_attachment.prepare_zotero_pdf_attachment_batch_action(
        body=body,
        matched={"paper": {"id": 1}},
        target_refs=targets,
        target_source="selected_items_test",
        get_db_context=fake_get_db,
        resolve_zotero_attachment_target=fake_resolve_target,
        ensure_zotero_attachable_pdf=fake_ensure_attachable_pdf,
        normalize_zotero_library_id=lambda value: f"normalized:{value}",
        finalize_zotero_action_preview=finalize_zotero_action_preview,
    )

    assert ensured_ids == [1, 2]
    assert result["kind"] == "action_preview"
    preview = result["preview"]
    assert preview["action_type"] == "zotero_attach_pdf"
    assert preview["planned_count"] == 1
    assert preview["target_label"] == "1 个 Zotero 条目"
    assert preview["message"] == (
        "已尝试用 RH 下载/验证 PDF：可写 1 / 下载失败 1 / identity 缺失 1。"
        "确认时只会写入可写记录。"
    )
    assert preview["target_set"] == {
        "source": "selected_items_test",
        "record_count": 3,
        "writable_count": 1,
        "blocked_count": 2,
    }
    assert preview["blocked_records"] == [
        {
            "index": 1,
            "paper_id": 2,
            "title": "Resolved Two",
            "zotero_item_key": "ITEM2",
            "reason": "RH paper #2: PDF path missing",
        },
        {
            "index": 2,
            "paper_id": None,
            "title": "Unmatched",
            "zotero_item_key": "",
            "reason": "无法把该 Zotero 目标重新解析到 RH paper",
        },
    ]
    assert preview["warnings"] == [
        "RH paper #2: PDF path missing",
        "无法把该 Zotero 目标重新解析到 RH paper",
    ]
    assert preview["records"] == [
        {
            "record_id": "paper:1",
            "paper_id": 1,
            "topic_id": 7,
            "title": "Attachable One",
            "doi": "10.9999/module",
            "arxiv_id": "2601.99999",
            "pdf_path": str(pdf_path),
            "zotero_item_key": "ITEM1",
            "parent_item_key": "ITEM1",
            "parent_library_id": "normalized:42",
            "library_type": "user",
        }
    ]
    assert preview["apply"] == {
        "type": "zotero_local",
        "handler": "zotero_import_file_attachments",
        "label": "确认附加 PDF",
        "payload": {
            "records": preview["records"],
            "blocked_count": 2,
        },
    }


def test_http_api_prepare_zotero_pdf_attachment_batch_action_uses_dynamic_dependencies(
    monkeypatch,
    tmp_path: Path,
):
    from research_harness_mcp import http_api

    conn = object()
    calls: list[str] = []
    body = ZoteroChatRequest.model_validate(
        {
            "message": "批量附加 PDF",
            "item": {
                "library_id": "body-lib",
                "library_type": "group",
            },
        }
    )
    target = ZoteroChatTargetRef(
        paper_id=5,
        zotero_item_key="ITEM5",
        library_id=None,
        title="Target Five",
    )

    @contextmanager
    def fake_get_db():
        calls.append("get_db")
        yield conn

    def fake_resolve_target(db_conn, target_ref):
        assert db_conn is conn
        assert target_ref is target
        calls.append("resolve")
        return {
            "paper_id": 5,
            "topic_id": 9,
            "title": "Resolved Five",
            "zotero_item_key": "ITEM5",
        }

    def fake_ensure_attachable_pdf(db_conn, paper_id):
        assert db_conn is conn
        calls.append(f"ensure:{paper_id}")
        return http_api.ZoteroAttachablePdf(
            ok=True,
            paper_id=paper_id,
            row={"title": "Dynamic Five"},
            pdf_path=tmp_path / "five.pdf",
        )

    def fake_finalize(preview, **kwargs):
        calls.append("finalize")
        return {"preview": preview, "kwargs": kwargs}

    monkeypatch.setattr(http_api, "get_db", fake_get_db)
    monkeypatch.setattr(
        http_api, "_resolve_zotero_attachment_target", fake_resolve_target
    )
    monkeypatch.setattr(
        http_api, "ensure_zotero_attachable_pdf", fake_ensure_attachable_pdf
    )
    monkeypatch.setattr(
        http_api,
        "_normalize_zotero_library_id",
        lambda value: f"normalized:{value}",
    )
    monkeypatch.setattr(http_api, "_finalize_zotero_action_preview", fake_finalize)

    result = http_api._prepare_zotero_pdf_attachment_batch_action(
        body=body,
        matched={},
        target_refs=[target],
        target_source="last_preview_targets",
    )

    assert calls == ["get_db", "resolve", "ensure:5", "finalize"]
    assert result["kind"] == "action_preview"
    preview = result["preview"]["preview"]
    assert preview["records"][0]["parent_library_id"] == "normalized:body-lib"
    assert result["preview"]["kwargs"] == {
        "capability": "rh.zotero.attach_pdf",
        "target_source": "last_preview_targets",
        "target_record_count": 1,
        "writable_count": 1,
        "blocked_records": [],
        "warnings": [],
        "undo_supported": True,
    }
