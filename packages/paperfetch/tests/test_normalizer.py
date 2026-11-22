# -*- coding: utf-8 -*-
"""
test_normalizer.py
针对学术论文唯一标识符标准化的元数据清洗单元测试。
"""

from paperfetch.utils.normalizer import (
    normalize_doi,
    normalize_arxiv_id,
    normalize_pmid,
    normalize_pmcid,
)


def test_normalize_doi():
    # 1. 正常移除 URL 域名前缀、忽略大小写、去前后空格
    assert normalize_doi("https://doi.org/10.1000/xyz123") == "10.1000/xyz123"
    assert normalize_doi("http://dx.doi.org/10.1000/XYZ123") == "10.1000/xyz123"
    assert normalize_doi("10.1000/xyz123  ") == "10.1000/xyz123"
    # 2. 空输入安全校验
    assert normalize_doi(None) is None
    assert normalize_doi("") is None


def test_normalize_arxiv_id():
    # 3. 正常移除非标准前缀与版本号
    assert normalize_arxiv_id("arXiv:2304.12345v2") == "2304.12345"
    assert normalize_arxiv_id("arxiv: 2304.12345") == "2304.12345"
    # 4. 空输入安全校验
    assert normalize_arxiv_id(None) is None


def test_normalize_pmid():
    # 5. 移除非数字符号
    assert normalize_pmid("PMID: 1234567") == "1234567"
    assert normalize_pmid("12345-67") == "1234567"
    # 6. 空输入安全校验
    assert normalize_pmid(None) is None


def test_normalize_pmcid():
    # 7. 清理前缀与格式化为 PMC+数字
    assert normalize_pmcid("PMC123456") == "PMC123456"
    assert normalize_pmcid("pmc 123456") == "PMC123456"
    assert normalize_pmcid("123456") == "PMC123456"


def test_extract_pmcid_from_current_official_urls():
    from paperfetch.utils.normalizer import extract_pmcid_from_url

    assert (
        extract_pmcid_from_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC13157918/")
        == "PMC13157918"
    )
    assert (
        extract_pmcid_from_url("https://europepmc.org/api/getPdf?pmcid=PMC13157918")
        == "PMC13157918"
    )
    assert extract_pmcid_from_url("https://example.org/articles/PMC13157918/") is None
    # 8. 空输入安全校验
    assert normalize_pmcid(None) is None
