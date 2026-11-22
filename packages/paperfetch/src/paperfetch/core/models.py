# -*- coding: utf-8 -*-
"""
models 模块
定义统一的学术文献数据模型。所有模型均使用 Pydantic v2 构建，以保证强类型约束与快速校验。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class MergeConfidence(str, Enum):
    """合并置信度枚举"""

    HIGH = "high"  # DOI 或强 ID 完全一致匹配
    MEDIUM = "medium"  # title + year 匹配
    LOW = "low"  # 仅 title 模糊相似匹配
    SINGLE_SOURCE = "single_source"  # 单一数据源，未触发合并


class AuthorRecord(BaseModel):
    """作者信息记录"""

    name: str = Field(description="作者姓名")
    orcid: Optional[str] = Field(default=None, description="ORCID 标识")
    affiliations: List[str] = Field(default_factory=list, description="机构隶属关系")
    source: str = Field(description="该作者数据的来源数据源")


class SourceRef(BaseModel):
    """字段级溯源参考"""

    source: str = Field(description="学术数据源名称 (如 openalex, semantic_scholar)")
    source_record_id: Optional[str] = Field(
        default=None, description="该数据源中的原始记录 ID"
    )
    field: str = Field(description="受影响的 PaperRecord 字段名")
    value: str = Field(description="该数据源返回的原始文本值")
    retrieved_at: datetime = Field(description="数据的抓取时间")
    query_or_endpoint: str = Field(description="发起检索时使用的 query 或 API endpoint")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="该源数据的置信度分数"
    )


class RecallHit(BaseModel):
    """把论文带入候选池的一次召回事件。"""

    source: str = Field(description="元数据源或种子来源")
    query_family: Optional[str] = Field(default=None, description="Search Brief 查询族")
    query: Optional[str] = Field(default=None, description="原始查询式或种子标识")
    source_rank: Optional[int] = Field(
        default=None, description="该数据源或查询结果中的排序名次"
    )
    retrieved_at: datetime = Field(
        default_factory=datetime.now, description="召回时间戳"
    )
    reason: Optional[str] = Field(default=None, description="手工种子或数据源备注")


class FulltextStatus(BaseModel):
    """全文获取与解析状态"""

    oa_status: str = Field(
        default="unknown", description="Open Access 状态 (open, closed, unknown)"
    )
    oa_declaration_status: str = Field(
        default="unknown", description="OA 来源声明状态，不代表当前执行面可传输"
    )
    oa_transport_status: str = Field(
        default="not_attempted",
        description="OA 传输状态 (not_attempted, retrievable, not_retrieved)",
    )
    pdf_url: Optional[str] = Field(default=None, description="可下载的 PDF URL")
    pdf_source: Optional[str] = Field(
        default=None, description="PDF 链接来源 (如 unpaywall, arxiv, pmc)"
    )
    pdf_candidates: List[Dict[str, Any]] = Field(
        default_factory=list, description="元数据源发现的 PDF/落地页候选 URL"
    )
    download_status: str = Field(
        default="not_attempted",
        description="下载状态 (not_attempted, downloaded, failed)",
    )
    download_attempted: bool = Field(
        default=False, description="该论文是否进入过 PDF 下载流程"
    )
    attempted_routes: List[str] = Field(
        default_factory=list, description="本轮尝试过的 PDF 下载路由"
    )
    successful_route: Optional[str] = Field(
        default=None, description="产出已验证 PDF 的路由"
    )
    resolved_pdf_url: Optional[str] = Field(
        default=None, description="下载过程中最终解析到的 PDF URL"
    )
    failure_stage: Optional[str] = Field(
        default=None, description="最后失败的下载路由或阶段"
    )
    route_errors: List[Dict[str, str]] = Field(
        default_factory=list, description="按路由记录的下载失败明细"
    )
    candidate_pdf_urls: List[Dict[str, Any]] = Field(
        default_factory=list, description="用于审计的 PDF 路由候选"
    )
    download_attempts: List[Dict[str, Any]] = Field(
        default_factory=list, description="用于审计的逐路由尝试明细"
    )
    discovery_events: List[Dict[str, Any]] = Field(
        default_factory=list, description="Phase 1 资源发现事件"
    )
    normalized_resources: List[Dict[str, Any]] = Field(
        default_factory=list, description="Phase 1 规范化和去重后的资源"
    )
    verification: Dict[str, Any] = Field(
        default_factory=dict, description="最终 PDF 身份验证审计"
    )
    failure_taxonomy: Optional[str] = Field(
        default=None, description="规范化下载失败类别"
    )
    primary_failure_class: Optional[str] = Field(
        default=None, description="首个可行动的传输失败类别"
    )
    last_failure_class: Optional[str] = Field(
        default=None, description="最后一个可行动的传输失败类别"
    )
    attempted_route_summary: List[Dict[str, Any]] = Field(
        default_factory=list, description="稳定、脱敏的逐路由终局摘要"
    )
    resource_outcome: str = Field(
        default="not_attempted",
        description="资源终局 (not_attempted, downloaded, resource_discovered_but_transfer_failed, resource_not_discovered)",
    )
    cache_hit: bool = Field(
        default=False, description="已验证 PDF 是否来自本地或全局缓存"
    )
    cache_miss: List[str] = Field(
        default_factory=list, description="检查过但未命中的缓存路由"
    )
    global_cache_path: Optional[str] = Field(
        default=None, description="已验证全局 PDF 缓存路径"
    )
    failure_reason: Optional[str] = Field(
        default=None, description="下载失败原因 (如 NOT_A_PDF, PDF_TOO_LARGE)"
    )
    content_type: Optional[str] = Field(default=None, description="HTTP Content-Type")
    file_size_bytes: Optional[int] = Field(
        default=None, description="PDF 文件大小字节数"
    )
    magic_pdf: bool = Field(default=False, description="是否通过了 %PDF 头部魔数验证")
    sha256: Optional[str] = Field(default=None, description="文件的 SHA256 哈希")
    identity_verified: bool = Field(
        default=False, description="PDF 是否通过目标论文身份校验"
    )
    identity_status: str = Field(default="not_checked", description="PDF 身份校验状态")
    identity_confidence: str = Field(default="none", description="PDF 身份校验置信度")
    identity_evidence: Dict[str, Any] = Field(
        default_factory=dict, description="PDF 身份校验的结构化证据"
    )
    local_path: Optional[str] = Field(default=None, description="本地 PDF 保存路径")
    mineru_status: str = Field(
        default="not_attempted",
        description="MinerU 解析状态 (not_attempted, parsed, failed)",
    )
    mineru_failure_stage: Optional[str] = Field(
        default=None, description="MinerU 独立失败阶段"
    )
    mineru_failure_class: Optional[str] = Field(
        default=None, description="MinerU 独立稳定失败类别"
    )
    mineru_attempts: List[Dict[str, Any]] = Field(
        default_factory=list, description="MinerU 脱敏逐尝试摘要"
    )
    mineru_error_summary: Optional[str] = Field(
        default=None, description="MinerU 脱敏终局错误摘要"
    )
    mineru_markdown_path: Optional[str] = Field(
        default=None, description="MinerU 解析后的 markdown 存储路径"
    )
    mineru_archive_path: Optional[str] = Field(
        default=None, description="MinerU 解析后的完整 zip 归档包路径"
    )
    mineru_extracted_dir: Optional[str] = Field(
        default=None, description="MinerU 解析后完整包解压目录路径"
    )
    parse_quality: str = Field(
        default="unknown", description="解析质量评估 (unknown, low, medium, high)"
    )
    # 新增：代码库可复现核验状态与仓库元数据，用于整合 baseline-selector 证据链
    reproducibility_status: str = Field(
        default="unchecked",
        description="代码库可复现核验状态；verified_runnable 仅允许隔离 runtime smoke 或外部可核验证据通过后使用",
    )
    extracted_code_url: Optional[str] = Field(
        default=None, description="从论文中提取的代码仓库 URL"
    )
    repo_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="代码仓库元数据审计结果"
    )

    @field_validator("repo_metadata", mode="before")
    @classmethod
    def normalize_nullable_repo_metadata(cls, value: Any) -> Dict[str, Any]:
        """Backwards-compatible normalization; persisted state is always an object."""
        return {} if value is None else value


class OrganizationRecord(BaseModel):
    """标准化机构记录"""

    raw: str = Field(description="原始机构名称文本")
    normalized_name: Optional[str] = Field(default=None, description="规范化机构名称")
    type: str = Field(
        default="unknown",
        description="机构类型 (education, company, research_institute, hospital, government, unknown)",
    )
    source: str = Field(description="提供该机构信息的数据源")
    ror_id: Optional[str] = Field(default=None, description="ROR 唯一机构 ID")
    country: Optional[str] = Field(default=None, description="机构所在国家代码 (ISO)")


class InstitutionSignal(BaseModel):
    """从 Affiliations 抽取的机构类型信号"""

    has_university_affiliation: bool = Field(
        default=False, description="是否包含高校背景"
    )
    has_company_affiliation: bool = Field(
        default=False, description="是否包含企业/工业界背景"
    )
    has_research_institute_affiliation: bool = Field(
        default=False, description="是否包含独立科研机构背景"
    )
    has_government_affiliation: bool = Field(
        default=False, description="是否包含政府机构背景"
    )
    has_hospital_affiliation: bool = Field(
        default=False, description="是否包含医院/医疗机构背景"
    )
    has_industry_academic_collaboration: bool = Field(
        default=False, description="是否属于产学研合作论文"
    )
    org_signal_confidence: str = Field(
        default="low", description="机构判定置信度 (low, medium, high)"
    )
    organizations: List[OrganizationRecord] = Field(
        default_factory=list, description="机构明细列表"
    )
    limitations: List[str] = Field(default_factory=list, description="判定局限性备注")


class AgentReviewQualityAssessment(BaseModel):
    """Agent 对论文质量的结构化判断。"""

    method_reliability: str = Field(default="unknown")
    reproducibility: str = Field(default="unknown")
    novelty: str = Field(default="unknown")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AgentReview(BaseModel):
    """协同审查事实，作为 Markdown 审查视图的数据源。"""

    core_contribution: str = Field(default="")
    methodology_design: str = Field(default="")
    evaluation_setup: str = Field(default="")
    limitations_and_risks: str = Field(default="")
    quality_assessment: AgentReviewQualityAssessment = Field(
        default_factory=AgentReviewQualityAssessment
    )


class PaperRecord(BaseModel):
    """统一学术论文记录"""

    # === 身份标识 ===
    paper_id: str = Field(description="系统内部唯一 ID，格式 spc:<uuid>")
    doi: Optional[str] = Field(default=None, description="数字对象唯一标识符")
    openalex_id: Optional[str] = Field(default=None, description="OpenAlex 记录 ID")
    semantic_scholar_id: Optional[str] = Field(
        default=None, description="Semantic Scholar 记录 ID"
    )
    corpus_id: Optional[int] = Field(
        default=None, description="Semantic Scholar 学术库 Corpus ID"
    )
    pubmed_id: Optional[str] = Field(default=None, description="PubMed PMID")
    pmc_id: Optional[str] = Field(default=None, description="PubMed Central PMC ID")
    arxiv_id: Optional[str] = Field(default=None, description="arXiv ID")
    dblp_key: Optional[str] = Field(default=None, description="DBLP 检索 Key")

    # === 元数据 ===
    title: str = Field(description="规范化后的论文标题")
    year: Optional[int] = Field(default=None, description="发表年份")
    venue: Optional[str] = Field(default=None, description="发表会议名")
    journal: Optional[str] = Field(default=None, description="发表期刊名")
    volume: Optional[str] = Field(default=None, description="期刊卷号")
    issue: Optional[str] = Field(default=None, description="期刊期号")
    pages: Optional[str] = Field(default=None, description="页码范围")
    publisher: Optional[str] = Field(default=None, description="出版商")
    document_type: Optional[str] = Field(
        default=None,
        description="文档类型 (journal_article, conference_paper, preprint, etc.)",
    )
    authors: List[AuthorRecord] = Field(default_factory=list, description="作者列表")
    abstract: Optional[str] = Field(default=None, description="论文摘要文本")
    citation_count: Optional[int] = Field(default=None, description="被引次数")
    reference_count: Optional[int] = Field(default=None, description="引用文献数")
    mesh_terms: List[str] = Field(
        default_factory=list, description="MeSH 医学主题术语列表"
    )
    openalex_topics: List[Dict[str, Any]] = Field(
        default_factory=list, description="OpenAlex Topic/Subfield/Field/Domain 层级"
    )

    # === 溯源与事实信号 ===
    source_refs: List[SourceRef] = Field(
        default_factory=list, description="字段级数据抓取溯源列表"
    )
    recall_hits: List[RecallHit] = Field(
        default_factory=list, description="召回命中记录"
    )
    institution_signals: Optional[InstitutionSignal] = Field(
        default=None, description="机构属性信号"
    )
    fulltext_status: FulltextStatus = Field(
        default_factory=FulltextStatus, description="全文下载及解析状态"
    )

    # === 合并与去重元数据 ===
    merge_confidence: MergeConfidence = Field(
        default=MergeConfidence.SINGLE_SOURCE, description="合并匹配置信度"
    )
    merged_from: List[str] = Field(
        default_factory=list, description="所合并的各数据源原始 ID 列表"
    )
    field_conflicts: List[Dict[str, Any]] = Field(
        default_factory=list, description="合并中发生冲突的字段与原始记录"
    )

    # === 种子论文专有属性 (选入 seed 后填充) ===
    recorded_facts: Dict[str, Any] = Field(
        default_factory=dict, description="可追溯事实快照，不代表质量判断"
    )
    available_files: Dict[str, Any] = Field(
        default_factory=dict, description="PDF/MinerU 等本地文件可用性索引"
    )
    curation_signals: Dict[str, Any] = Field(
        default_factory=dict, description="整理入包用弱信号，不代表学术质量"
    )
    selection_rank: Optional[int] = Field(
        default=None, description="当前 Seed Pack 内的入包顺序"
    )
    selection_bucket: Optional[str] = Field(
        default=None, description="当前任务中的候选类别"
    )
    selection_basis: List[str] = Field(default_factory=list, description="入包原因列表")
    agent_review_status: str = Field(
        default="requires_review", description="Agent 后续审查状态"
    )
    agent_review: Optional[AgentReview] = Field(
        default=None, description="Agent 结构化协同审查"
    )
    requires_agent_review: List[str] = Field(
        default_factory=list, description="需要 Agent 继续核查的问题"
    )
