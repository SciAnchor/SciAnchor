"""Shared Pydantic models for the Research Harness HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class PaginatedResponse(BaseModel):
    data: list[dict[str, Any]]
    pagination: PaginationMeta


class DomainSummary(BaseModel):
    id: int
    name: str
    description: str
    status: str
    topic_count: int
    created_at: str


class DomainDetail(BaseModel):
    id: int
    name: str
    description: str
    status: str
    created_at: str
    topics: list  # list[TopicSummary] — forward-ref resolved below


class CreateDomainRequest(BaseModel):
    name: str
    description: str = ""


class PatchDomainRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class PatchTopicRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    domain_id: int | None = Field(
        default=None, description="Pass null via JSON to unset"
    )
    target_venue: str | None = None
    deadline: str | None = None
    status: str | None = None

    # Pydantic v2: treat explicitly set None as "clear" signal for domain_id.
    model_config = {"extra": "forbid"}


class TopicSummary(BaseModel):
    id: int
    name: str
    description: str
    status: str
    target_venue: str
    deadline: str
    created_at: str
    paper_count: int
    domain_id: int | None
    domain_name: str | None
    current_stage: str | None = None
    stage_status: str | None = None


class TopicDetail(BaseModel):
    id: int
    name: str
    description: str
    status: str
    target_venue: str
    deadline: str
    created_at: str
    paper_count: int
    annotation_count: int
    domain_id: int | None
    domain_name: str | None
    current_stage: str | None
    stage_status: str | None
    gate_status: str | None
    contributions: str
    mode: str | None
    stop_before: str | None
    blocking_issue_count: int
    unresolved_issue_count: int
    artifact_counts: dict[str, int]


DomainDetail.model_rebuild()


class PaperDetail(BaseModel):
    id: int
    title: str
    authors: list[Any]
    year: int | None
    venue: str
    doi: str
    arxiv_id: str
    s2_id: str
    url: str
    abstract: str
    citation_count: int | None
    deep_read: bool
    status: str
    pdf_path: str
    created_at: str
    annotations: list[dict[str, Any]]
    topics: list[dict[str, Any]]


class RecordArtifactRequest(BaseModel):
    artifact_type: str
    payload: dict[str, Any]
    stage: str | None = None
    title: str = ""

    model_config = {"extra": "forbid"}


class ForceAdvanceRequest(BaseModel):
    target_stage: str | None = None
    actor: str = "web_ui"


class CreateExperimentRequest(BaseModel):
    """Body for POST /api/topics/{topic_id}/experiments."""

    name: str = ""
    task_description: str
    fixture_files: dict[str, str] = Field(default_factory=dict)
    mutable_entry: str = "main.py"
    primary_metric: str
    direction: str = "max"
    mode: str = "agent"
    timeout_sec: float = 300.0
    env_vars: dict[str, str] = Field(default_factory=dict)
    max_iterations: int = 5
    max_cost_usd: float = 0.0
    max_tokens: int = 0
    patience: int = 3


class CreateTopicRequest(BaseModel):
    name: str
    description: str = ""
    target_venue: str = ""
    deadline: str = ""
    domain_id: int | None = None


class AdvanceRequest(BaseModel):
    actor: str = "web_ui"


class ExpansionRequest(BaseModel):
    retrieval_target: int = Field(default=100)
    deep_read_target: int = Field(default=20)
    rounds: int = Field(default=3)


class PaperIngestRequest(BaseModel):
    source: str  # arxiv ID, DOI, or URL
    topic_id: int | None = None
    relevance: str = "medium"


class BatchEnrichRequest(BaseModel):
    topic_id: int | None = None
    missing_fields: list[str] = ["venue", "citation_count"]
    limit: int = 50


class RollbackRequest(BaseModel):
    to_stage: str
    reason: str
