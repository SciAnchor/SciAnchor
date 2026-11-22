"""FastAPI route registration for primitive analysis and writing actions."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

RunTool = Callable[[str, dict[str, Any]], dict[str, Any]]


class GapDetectRequest(BaseModel):
    focus: str | None = None


class ClaimExtractRequest(BaseModel):
    paper_ids: list[int]
    focus: str | None = None


class DirectionRankingRequest(BaseModel):
    focus: str | None = None


class OutlineGenerateRequest(BaseModel):
    template: str = "neurips"


class SectionDraftRequest(BaseModel):
    section: str
    outline: str | None = None
    max_words: int = 0


class PublicationPackRequest(BaseModel):
    target_profile: str = Field(
        default="high-impact-general", min_length=1, max_length=120
    )
    record_artifact: bool = True


class PublicationPackBackfillRequest(BaseModel):
    target_profile: str = Field(
        default="high-impact-general", min_length=1, max_length=120
    )
    components: list[str] | None = Field(default=None, max_length=20)
    record_artifact: bool = True

    @field_validator("components", mode="after")
    @classmethod
    def _trim_components(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        seen: set[str] = set()
        cleaned: list[str] = []
        for value in values:
            component = str(value or "").strip()[:120]
            if not component or component in seen:
                continue
            seen.add(component)
            cleaned.append(component)
        return cleaned or None


class ClaimVerifyRequest(BaseModel):
    pair_budget: int = 200
    persist: bool = True


class AdversarialSectionReviewRequest(BaseModel):
    section: str
    content: str
    target_words: int = 0
    auto_open_issues: bool = True


class MethodTaxonomyRequest(BaseModel):
    focus: str | None = None


class BaselineIdentifyRequest(BaseModel):
    focus: str | None = None


class EvidenceMatrixRequest(BaseModel):
    focus: str | None = None


def register_primitive_action_routes(app: FastAPI, *, run_tool: RunTool) -> None:
    """Register pure tool-dispatch analysis and writing action routes."""

    @app.post("/api/topics/{topic_id}/gaps")
    def detect_gaps(topic_id: int, body: GapDetectRequest):
        """Detect research gaps in a topic's literature."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("gap_detect", args)

    @app.post("/api/topics/{topic_id}/claims")
    def extract_claims(topic_id: int, body: ClaimExtractRequest):
        """Extract research claims from papers within a topic."""
        args: dict[str, Any] = {"topic_id": topic_id, "paper_ids": body.paper_ids}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("claim_extract", args)

    @app.post("/api/topics/{topic_id}/directions")
    def rank_directions(topic_id: int, body: DirectionRankingRequest):
        """Rank candidate research directions by novelty x feasibility x impact."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("direction_ranking", args)

    @app.post("/api/topics/{topic_id}/outline")
    def generate_outline(topic_id: int, body: OutlineGenerateRequest):
        """Generate a paper outline from contributions and evidence."""
        return run_tool(
            "outline_generate",
            {
                "topic_id": topic_id,
                "template": body.template,
            },
        )

    @app.post("/api/topics/{topic_id}/section-draft")
    def draft_section(topic_id: int, body: SectionDraftRequest):
        """Draft a paper section using linked evidence."""
        args: dict[str, Any] = {"section": body.section, "topic_id": topic_id}
        if body.outline:
            args["outline"] = body.outline
        if body.max_words > 0:
            args["max_words"] = body.max_words
        return run_tool("section_draft", args)

    @app.post("/api/topics/{topic_id}/publication-pack")
    def generate_publication_pack(topic_id: int, body: PublicationPackRequest):
        """Assemble an evidence-bound publication package from topic artifacts."""
        return run_tool(
            "publication_pack_generate",
            {
                "topic_id": topic_id,
                "target_profile": body.target_profile,
                "record_artifact": body.record_artifact,
            },
        )

    @app.post("/api/topics/{topic_id}/publication-pack/backfill")
    def backfill_publication_pack(topic_id: int, body: PublicationPackBackfillRequest):
        """Backfill deterministic publication-pack QA artifacts."""
        args: dict[str, Any] = {
            "topic_id": topic_id,
            "target_profile": body.target_profile,
            "record_artifact": body.record_artifact,
        }
        if body.components:
            args["components"] = body.components
        return run_tool("publication_pack_backfill", args)

    @app.post("/api/topics/{topic_id}/claim-verify")
    def verify_claims_endpoint(topic_id: int, body: ClaimVerifyRequest):
        """v2 Step 5 — bounded pair-wise claim verification."""
        return run_tool(
            "claim_verify",
            {
                "topic_id": topic_id,
                "pair_budget": body.pair_budget,
                "persist": body.persist,
            },
        )

    @app.post("/api/topics/{topic_id}/adversarial-review")
    def adversarial_section_review_endpoint(
        topic_id: int, body: AdversarialSectionReviewRequest
    ):
        """v2 Step 5 — skeptical-reviewer adversarial section review."""
        return run_tool(
            "adversarial_section_review",
            {
                "topic_id": topic_id,
                "section": body.section,
                "content": body.content,
                "target_words": body.target_words,
                "auto_open_issues": body.auto_open_issues,
            },
        )

    @app.post("/api/topics/{topic_id}/method-taxonomy")
    def method_taxonomy(topic_id: int, body: MethodTaxonomyRequest):
        """Build a taxonomy of methods from deep-read papers in the topic."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("method_taxonomy", args)

    @app.post("/api/topics/{topic_id}/baselines")
    def identify_baselines(topic_id: int, body: BaselineIdentifyRequest):
        """Identify baseline methods and their reported results from the literature."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("baseline_identify", args)

    @app.post("/api/topics/{topic_id}/evidence-matrix")
    def evidence_matrix(topic_id: int, body: EvidenceMatrixRequest):
        """Generate a method × metric evidence matrix from the literature."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("evidence_matrix", args)
