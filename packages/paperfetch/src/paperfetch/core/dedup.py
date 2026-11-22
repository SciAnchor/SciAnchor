# -*- coding: utf-8 -*-
"""
dedup 模块
实现学术文献强匹配与弱匹配两阶段合并去重算法，并提供合并中的字段冲突解决与全字段 SourceRef 归并。
"""

import re
from paperfetch.observability import get_event_logger
from typing import List, Dict, Any, Tuple, Optional, Set
from paperfetch.core.models import (
    PaperRecord,
    MergeConfidence,
    AuthorRecord,
    FulltextStatus,
)

logger = get_event_logger("paperfetch.core.dedup")


def normalize_and_tokenize(title: str) -> Set[str]:
    """
    清洗标题文本并分词为 Token Set。

    Args:
        title (str): 原始标题。

    Returns:
        Set[str]: 分词后的 Token 集合。
    """
    if not title:
        return set()
    # 行内注释：转小写并剔除所有特殊标点符号，仅保留英文字符与数字，防止格式差异导致相似度偏低
    t = title.lower()
    t = re.sub(r"[^\w\s]", "", t)
    return set(t.split())


def calculate_jaccard_similarity(t1: str, t2: str) -> float:
    """
    计算两个标题的 Jaccard Token 相似度。
    """
    tokens1 = normalize_and_tokenize(t1)
    tokens2 = normalize_and_tokenize(t2)
    union = tokens1 | tokens2
    if not union:
        return 0.0
    return len(tokens1 & tokens2) / len(union)


def _check_venue_fuzzy_match(v1: Optional[str], v2: Optional[str]) -> bool:
    """
    模糊匹配两个期刊/会议名。
    """
    if not v1 or not v2:
        return False
    # 行内注释：清除标点和空白，转换为小写，检查是否相互包含
    clean_v1 = re.sub(r"[^\w]", "", v1.lower())
    clean_v2 = re.sub(r"[^\w]", "", v2.lower())
    return clean_v1 == clean_v2 or clean_v1 in clean_v2 or clean_v2 in clean_v1


def _check_first_author_match(a1: List[AuthorRecord], a2: List[AuthorRecord]) -> bool:
    """
    比对两篇文献首作者姓氏是否一致。
    """
    if not a1 or not a2:
        return False
    name1 = a1[0].name.lower()
    name2 = a2[0].name.lower()

    # 行内注释：提取 LastName (通常为最后一个单词)
    last_name1 = name1.split()[-1] if name1.split() else name1
    last_name2 = name2.split()[-1] if name2.split() else name2

    return last_name1 == last_name2


def _candidate_key(candidate: Dict[str, Any]) -> str:
    url = str(candidate.get("url") or candidate.get("pdf_url") or "").strip()
    source = str(candidate.get("source") or candidate.get("pdf_source") or "").strip()
    return f"{url}|{source}"


def _append_status_candidate(
    candidates: List[Dict[str, Any]], candidate: Dict[str, Any]
) -> None:
    url = str(candidate.get("url") or candidate.get("pdf_url") or "").strip()
    if not url:
        return
    normalized = dict(candidate)
    normalized["url"] = url
    normalized.setdefault("source", normalized.pop("pdf_source", None) or "metadata")
    seen = {_candidate_key(item) for item in candidates}
    if _candidate_key(normalized) not in seen:
        candidates.append(normalized)


def _status_rank(status: FulltextStatus) -> tuple:
    downloaded = status.download_status == "downloaded" and status.magic_pdf
    has_file = bool(status.local_path)
    has_url = bool(status.pdf_url)
    return (downloaded, has_file, has_url, len(status.pdf_candidates))


def merge_fulltext_status(
    left: FulltextStatus, right: FulltextStatus
) -> FulltextStatus:
    """
    合并两侧全文状态，保留已下载结果，同时归并所有元数据源发现的 PDF 候选。
    """
    base = left if _status_rank(left) >= _status_rank(right) else right
    other = right if base is left else left
    merged = base.model_copy(deep=True)

    candidates: List[Dict[str, Any]] = []
    for status in (left, right):
        for candidate in status.pdf_candidates:
            _append_status_candidate(candidates, candidate)
        if status.pdf_url:
            _append_status_candidate(
                candidates,
                {
                    "url": status.pdf_url,
                    "source": status.pdf_source or "metadata_primary",
                    "kind": "primary",
                },
            )

    merged.pdf_candidates = candidates
    if not merged.pdf_url and other.pdf_url:
        merged.pdf_url = other.pdf_url
        merged.pdf_source = other.pdf_source
    if merged.oa_status == "unknown" and other.oa_status != "unknown":
        merged.oa_status = other.oa_status
    return merged


def should_merge(r1: PaperRecord, r2: PaperRecord) -> Tuple[bool, MergeConfidence]:
    """
    判断两条学术记录是否可以判定为同一篇论文。

    进行两阶段去重匹配：
    1. 强唯一标识符 (DOI, PMID, arXiv ID, CorpusID) 精确匹配。
    2. 标题 Jaccard 相似度与发表年份双阈值匹配。

    Args:
        r1 (PaperRecord): 论文记录一。
        r2 (PaperRecord): 论文记录二。

    Returns:
        Tuple[bool, MergeConfidence]: 是否可以合并，及合并置信度分级。
    """
    # === 阶段一：强唯一标识符精确匹配 ===
    if r1.doi and r2.doi and r1.doi == r2.doi:
        return True, MergeConfidence.HIGH
    if r1.pubmed_id and r2.pubmed_id and r1.pubmed_id == r2.pubmed_id:
        return True, MergeConfidence.HIGH
    if r1.arxiv_id and r2.arxiv_id and r1.arxiv_id == r2.arxiv_id:
        return True, MergeConfidence.HIGH
    if r1.corpus_id and r2.corpus_id and r1.corpus_id == r2.corpus_id:
        return True, MergeConfidence.HIGH

    # === 阶段二：弱匹配条件校验 ===
    # 限制条件：发表年份跨度不得超过 1 年
    if r1.year and r2.year and abs(r1.year - r2.year) > 1:
        return False, MergeConfidence.SINGLE_SOURCE

    sim = calculate_jaccard_similarity(r1.title, r2.title)

    # 阈值 1：若相似度高达 90% 以上，直接判定为同一论文
    if sim >= 0.90:
        return True, MergeConfidence.MEDIUM

    # 阈值 2：若在 75%-90% 之间，需要会议期刊名或首位作者姓氏匹配佐证
    if sim >= 0.75:
        venue_match = _check_venue_fuzzy_match(
            r1.venue or r1.journal, r2.venue or r2.journal
        )
        author_match = _check_first_author_match(r1.authors, r2.authors)
        if venue_match or author_match:
            return True, MergeConfidence.MEDIUM

    return False, MergeConfidence.SINGLE_SOURCE


def merge_records(
    r1: PaperRecord, r2: PaperRecord, confidence: MergeConfidence
) -> PaperRecord:
    """
    合并两篇判定为一致的论文记录。

    就地比对字段，取置信度源更高的内容；保留完整字段溯源 references，记录字段冲突并转存。

    Args:
        r1 (PaperRecord): 基础论文记录（合并后作为主数据体返回）。
        r2 (PaperRecord): 待并入的第二条论文记录。
        confidence (MergeConfidence): 合并时所采用的置信度。

    Returns:
        PaperRecord: 合并后的论文记录实体。
    """
    # 1. 归并标识符字段（保留非空且长度更长者）
    doi = r1.doi or r2.doi
    openalex_id = r1.openalex_id or r2.openalex_id
    s2_id = r1.semantic_scholar_id or r2.semantic_scholar_id
    corpus_id = r1.corpus_id or r2.corpus_id
    pubmed_id = r1.pubmed_id or r2.pubmed_id
    pmc_id = r1.pmc_id or r2.pmc_id
    arxiv_id = r1.arxiv_id or r2.arxiv_id
    dblp_key = r1.dblp_key or r2.dblp_key

    # 2. 字段冲突排查与优选
    field_conflicts = list(r1.field_conflicts) + list(r2.field_conflicts)

    # 辅助字段冲突校验函数
    def merge_field(field_name: str, val1: Any, val2: Any, conf_field: str) -> Any:
        if not val1:
            return val2
        if not val2 or val1 == val2:
            return val1

        # 双侧均有值且不一致时，通过 source_refs 中的字段置信度决定取舍。
        conf1 = next(
            (ref.confidence for ref in r1.source_refs if ref.field == conf_field), 0.5
        )
        conf2 = next(
            (ref.confidence for ref in r2.source_refs if ref.field == conf_field), 0.5
        )

        if conf1 >= conf2:
            chosen = val1
        else:
            chosen = val2

        # 记录到冲突列表以方便后续人工审计
        field_conflicts.append(
            {
                "field": field_name,
                "value_1": str(val1),
                "value_2": str(val2),
                "chosen_value": str(chosen),
                "confidence_1": conf1,
                "confidence_2": conf2,
            }
        )
        return chosen

    # 归并主字段
    title = merge_field("title", r1.title, r2.title, "title")
    year = merge_field("year", r1.year, r2.year, "year")
    venue = merge_field("venue", r1.venue, r2.venue, "venue")
    journal = merge_field("journal", r1.journal, r2.journal, "journal")
    abstract = merge_field("abstract", r1.abstract, r2.abstract, "abstract")
    citation_count = max(r1.citation_count or 0, r2.citation_count or 0) or None
    reference_count = max(r1.reference_count or 0, r2.reference_count or 0) or None

    # 3. 作者列表合并（优先取较长且带有 affiliations 的作者列表）
    authors = r1.authors
    if len(r2.authors) > len(r1.authors):
        authors = r2.authors
    elif len(r2.authors) == len(r1.authors) and any(a.affiliations for a in r2.authors):
        authors = r2.authors

    # 4. MeSH Terms 归并
    mesh_set = set(r1.mesh_terms) | set(r2.mesh_terms)
    mesh_terms = list(mesh_set)

    # 5. 合并 Source Refs 溯源列表，去重处理
    seen_refs = set()
    merged_source_refs = []
    for ref in list(r1.source_refs) + list(r2.source_refs):
        ref_key = (ref.source, ref.field, ref.value)
        if ref_key not in seen_refs:
            seen_refs.add(ref_key)
            merged_source_refs.append(ref)

    # 6. 合并原始 ID
    merged_from = list(
        set(r1.merged_from + r2.merged_from + [r1.paper_id, r2.paper_id])
    )

    seen_hits = set()
    merged_recall_hits = []
    for hit in list(r1.recall_hits) + list(r2.recall_hits):
        hit_key = (hit.source, hit.query_family, hit.query, hit.source_rank)
        if hit_key not in seen_hits:
            seen_hits.add(hit_key)
            merged_recall_hits.append(hit)

    selection_basis = []
    for item in list(r1.selection_basis) + list(r2.selection_basis):
        if item not in selection_basis:
            selection_basis.append(item)

    requires_agent_review = []
    for item in list(r1.requires_agent_review) + list(r2.requires_agent_review):
        if item not in requires_agent_review:
            requires_agent_review.append(item)

    # 7. 合并机构背景信号（取高校或企业信号更完备的侧）
    inst1 = r1.institution_signals
    inst2 = r2.institution_signals

    merged_inst = inst1
    if inst2 and (
        not inst1
        or inst2.org_signal_confidence == "medium"
        and inst1.org_signal_confidence == "low"
    ):
        merged_inst = inst2
    elif inst1 and inst2:
        # 归并各机构标志位
        merged_inst.has_university_affiliation = (
            inst1.has_university_affiliation or inst2.has_university_affiliation
        )
        merged_inst.has_company_affiliation = (
            inst1.has_company_affiliation or inst2.has_company_affiliation
        )
        merged_inst.has_research_institute_affiliation = (
            inst1.has_research_institute_affiliation
            or inst2.has_research_institute_affiliation
        )
        merged_inst.has_government_affiliation = (
            inst1.has_government_affiliation or inst2.has_government_affiliation
        )
        merged_inst.has_hospital_affiliation = (
            inst1.has_hospital_affiliation or inst2.has_hospital_affiliation
        )
        merged_inst.has_industry_academic_collaboration = (
            merged_inst.has_university_affiliation
            and merged_inst.has_company_affiliation
        )
        merged_inst.organizations = list(
            {
                org.raw: org for org in (inst1.organizations + inst2.organizations)
            }.values()
        )

    return PaperRecord(
        paper_id=r1.paper_id,  # 维持 r1 的唯一 paper_id 不变
        doi=doi,
        openalex_id=openalex_id,
        semantic_scholar_id=s2_id,
        corpus_id=corpus_id,
        pubmed_id=pubmed_id,
        pmc_id=pmc_id,
        arxiv_id=arxiv_id,
        dblp_key=dblp_key,
        title=title,
        year=year,
        venue=venue,
        journal=journal,
        authors=authors,
        abstract=abstract,
        citation_count=citation_count,
        reference_count=reference_count,
        mesh_terms=mesh_terms,
        source_refs=merged_source_refs,
        recall_hits=merged_recall_hits,
        institution_signals=merged_inst,
        merge_confidence=confidence,
        merged_from=merged_from,
        field_conflicts=field_conflicts,
        recorded_facts={**r2.recorded_facts, **r1.recorded_facts},
        available_files={**r2.available_files, **r1.available_files},
        curation_signals={**r2.curation_signals, **r1.curation_signals},
        selection_rank=r1.selection_rank or r2.selection_rank,
        selection_bucket=r1.selection_bucket or r2.selection_bucket,
        selection_basis=selection_basis,
        agent_review_status=r1.agent_review_status or r2.agent_review_status,
        requires_agent_review=requires_agent_review,
        fulltext_status=merge_fulltext_status(r1.fulltext_status, r2.fulltext_status),
    )
