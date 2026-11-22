"""Focused tests for Zotero trusted PDF path helper extraction."""

from __future__ import annotations

from pathlib import Path


def test_trusted_pdf_path_helpers_preserve_http_api_wrappers(
    monkeypatch,
    tmp_path: Path,
):
    from research_harness_mcp import http_api, zotero_pdf_paths

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])

    assert http_api._trusted_pdf_roots_for_zotero() == (
        [tmp_path.resolve()],
        None,
    )
    assert http_api._trusted_pdf_roots_for_zotero() == (
        zotero_pdf_paths.trusted_pdf_roots_for_zotero([tmp_path])
    )
    assert http_api._trusted_pdf_path_for_zotero(str(pdf_path)) == (
        pdf_path.resolve(),
        None,
    )
    assert http_api._trusted_pdf_path_for_zotero(str(pdf_path)) == (
        zotero_pdf_paths.trusted_pdf_path_for_zotero(str(pdf_path), [tmp_path])
    )


def test_trusted_pdf_roots_report_empty_configuration():
    from research_harness_mcp import zotero_pdf_paths

    assert zotero_pdf_paths.trusted_pdf_roots_for_zotero([]) == (
        [],
        "未配置允许的 PDF 根目录",
    )


def test_trusted_pdf_path_rejects_missing_outside_and_missing_file(tmp_path: Path):
    from research_harness_mcp import zotero_pdf_paths

    inside_missing = tmp_path / "missing.pdf"
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    outside_pdf = outside_dir / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\n")

    assert zotero_pdf_paths.trusted_pdf_path_for_zotero("", [tmp_path]) == (
        None,
        "RH 数据库中还没有 pdf_path",
    )
    assert zotero_pdf_paths.trusted_pdf_path_for_zotero(
        str(outside_pdf),
        [tmp_path],
    ) == (
        None,
        "PDF 路径不在允许的 RH PDF 根目录下",
    )
    assert zotero_pdf_paths.trusted_pdf_path_for_zotero(
        str(inside_missing),
        [tmp_path],
    ) == (
        None,
        "pdf_path 已记录，但本地文件不存在",
    )
