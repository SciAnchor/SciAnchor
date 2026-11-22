"""Trusted PDF path helpers for Zotero-facing local actions."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def trusted_pdf_roots_for_zotero(
    pdf_roots: Iterable[Path | str],
) -> tuple[list[Path], str | None]:
    roots = list(pdf_roots)
    if not roots:
        return [], "未配置允许的 PDF 根目录"

    trusted_roots: list[Path] = []
    for root in roots:
        try:
            trusted_roots.append(Path(root).expanduser().resolve())
        except OSError:
            continue
    if not trusted_roots:
        return [], "未配置可解析的 PDF 根目录"
    return trusted_roots, None


def trusted_pdf_path_for_zotero(
    raw: str,
    pdf_roots: Iterable[Path | str],
) -> tuple[Path | None, str | None]:
    text = str(raw or "").strip()
    if not text:
        return None, "RH 数据库中还没有 pdf_path"
    try:
        candidate = Path(text).expanduser().resolve()
    except OSError as exc:
        return None, f"pdf_path 无效：{exc}"

    trusted_roots, roots_error = trusted_pdf_roots_for_zotero(pdf_roots)
    if roots_error:
        return None, roots_error
    if not any(candidate.is_relative_to(root) for root in trusted_roots):
        return None, "PDF 路径不在允许的 RH PDF 根目录下"
    if not candidate.is_file():
        return None, "pdf_path 已记录，但本地文件不存在"
    return candidate, None
