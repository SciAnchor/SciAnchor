# -*- coding: utf-8 -*-
"""
normalizer 模块
提供学术论文唯一标识符（DOI、arXiv ID、PMID 等）的格式规范化归一。
"""

import re
from typing import Optional
from urllib.parse import parse_qs, urlsplit


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """
    规范化 DOI。移除非标准 URL 前缀、多余空格并统一转换为小写。

    Args:
        doi (Optional[str]): 原始 DOI 字符串。

    Returns:
        Optional[str]: 规范化后的 DOI，如果输入为空则返回 None。
    """
    if not doi:
        return None
    cleaned = doi.strip()
    # 行内注释：使用正则忽略大小写，剔除 URL 重定向域名前缀
    cleaned = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip().lower()


def normalize_arxiv_id(arxiv_id: Optional[str]) -> Optional[str]:
    """
    规范化 arXiv ID。移除非标准前缀与末尾的版本号后缀（如 v1, v2）。

    Args:
        arxiv_id (Optional[str]): 原始 arXiv ID 字符串。

    Returns:
        Optional[str]: 规范化后的 arXiv ID (例如 2304.12345)。
    """
    if not arxiv_id:
        return None
    cleaned = arxiv_id.strip()
    # 行内注释：移除可能带有的大小写 arxiv: 前缀
    cleaned = re.sub(r"^arxiv:\s*", "", cleaned, flags=re.IGNORECASE)
    # 行内注释：剔除版本号 (如 v1/v2)，以便使不同版本的同一篇论文指向同一次匹配
    cleaned = re.sub(r"v\d+$", "", cleaned)
    return cleaned.strip()


def normalize_pmid(pmid: Optional[str]) -> Optional[str]:
    """
    规范化 PubMed PMID。移除非必要字符，仅保留数字。

    Args:
        pmid (Optional[str]): 原始 PMID 字符串。

    Returns:
        Optional[str]: 纯数字形式的 PMID。
    """
    if not pmid:
        return None
    cleaned = pmid.strip()
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return cleaned if cleaned else None


def normalize_pmcid(pmcid: Optional[str]) -> Optional[str]:
    """
    规范化 PubMed Central PMC ID。保证带 PMC 前缀并大写。

    Args:
        pmcid (Optional[str]): 原始 PMC ID 字符串。

    Returns:
        Optional[str]: 规范后的 PMC ID (如 PMC123456)。
    """
    if not pmcid:
        return None
    cleaned = pmcid.strip().upper()
    # 行内注释：移除非必要的前缀干扰物并加回标准 PMC 前缀
    cleaned = cleaned.replace("PMC", "")
    cleaned = re.sub(r"[^\d]", "", cleaned)
    return f"PMC{cleaned}" if cleaned else None


def extract_pmcid_from_url(url: Optional[str]) -> Optional[str]:
    """Extract a PMCID only from official PMC or Europe PMC URLs."""
    if not url:
        return None
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    official_host = (
        host == "europepmc.org"
        or host.endswith(".europepmc.org")
        or host == "ncbi.nlm.nih.gov"
        or host.endswith(".ncbi.nlm.nih.gov")
    )
    if not official_host:
        return None
    match = re.search(r"\b(PMC\d+)\b", parts.path, flags=re.IGNORECASE)
    if match:
        return normalize_pmcid(match.group(1))
    query = parse_qs(parts.query)
    for key in ("pmcid", "id"):
        values = query.get(key) or query.get(key.upper()) or []
        for value in values:
            normalized = (
                normalize_pmcid(value) if str(value).upper().startswith("PMC") else None
            )
            if normalized:
                return normalized
    return None
