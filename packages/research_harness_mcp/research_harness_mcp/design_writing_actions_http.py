"""FastAPI route registration for thin design, code, and writing actions."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class AlgorithmDesignLoopRequest(BaseModel):
    focus: str | None = None
    max_rounds: int = 3


class CompetitiveLearningRequest(BaseModel):
    venue: str = "EMNLP"
    focus: str | None = None


class DesignBriefExpandRequest(BaseModel):
    direction: str = ""
    focus: str | None = None


class CodeGenerateRequest(BaseModel):
    spec: str = ""
    focus: str | None = None


class SectionReviewRequest(BaseModel):
    section: str
    content: str


class SectionReviseRequest(BaseModel):
    section: str
    content: str
    feedback: str = ""


class ConsistencyCheckRequest(BaseModel):
    sections: list[str] | None = None


class WritingPatternExtractRequest(BaseModel):
    paper_id: int


class WritingArchitectureRequest(BaseModel):
    template: str = "neurips"


def register_design_writing_action_routes(
    app: FastAPI,
    *,
    run_tool: Callable[[str, dict[str, Any]], Any],
) -> None:
    """Register thin design, code, and writing action routes."""

    @app.post("/api/topics/{topic_id}/algorithm-design-loop")
    def algorithm_design_loop(topic_id: int, body: AlgorithmDesignLoopRequest):
        """Iterative algorithm design: generate, probe, refine, and check."""
        args: dict[str, Any] = {"topic_id": topic_id, "max_rounds": body.max_rounds}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("algorithm_design_loop", args)

    @app.post("/api/topics/{topic_id}/competitive-learning")
    def competitive_learning(topic_id: int, body: CompetitiveLearningRequest):
        """Analyze competitive landscape: venue-level method trends + positioning."""
        args: dict[str, Any] = {"topic_id": topic_id, "venue": body.venue}
        if body.focus:
            args["focus"] = body.focus
        return run_tool("competitive_learning", args)

    @app.post("/api/topics/{topic_id}/design-brief")
    def design_brief_expand(topic_id: int, body: DesignBriefExpandRequest):
        """Expand a high-level design brief into actionable sub-problems."""
        direction = body.direction or body.focus or ""
        if not direction:
            raise HTTPException(
                status_code=422,
                detail="Either 'direction' or 'focus' must be provided.",
            )
        args: dict[str, Any] = {"topic_id": topic_id, "direction": direction}
        return run_tool("design_brief_expand", args)

    @app.post("/api/topics/{topic_id}/code-generate")
    def code_generate(topic_id: int, body: CodeGenerateRequest):
        """Generate experiment code from study spec and topic context."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.spec:
            args["spec"] = body.spec
        if body.focus:
            args["focus"] = body.focus
        return run_tool("code_generate", args)

    @app.post("/api/topics/{topic_id}/section-review")
    def review_section(topic_id: int, body: SectionReviewRequest):
        """Review a draft section for quality, citations, and coherence."""
        return run_tool(
            "section_review",
            {"topic_id": topic_id, "section": body.section, "content": body.content},
        )

    @app.post("/api/topics/{topic_id}/section-revise")
    def revise_section(topic_id: int, body: SectionReviseRequest):
        """Revise a draft section based on review feedback."""
        args: dict[str, Any] = {
            "topic_id": topic_id,
            "section": body.section,
            "content": body.content,
        }
        if body.feedback:
            args["feedback"] = body.feedback
        return run_tool("section_revise", args)

    @app.post("/api/topics/{topic_id}/consistency-check")
    def consistency_check(topic_id: int, body: ConsistencyCheckRequest):
        """Cross-section consistency check for the draft paper."""
        args: dict[str, Any] = {"topic_id": topic_id}
        if body.sections:
            args["sections"] = body.sections
        return run_tool("consistency_check", args)

    @app.post("/api/topics/{topic_id}/writing-pattern")
    def writing_pattern_extract(topic_id: int, body: WritingPatternExtractRequest):
        """Extract narrative writing patterns from a target venue paper."""
        return run_tool(
            "writing_pattern_extract",
            {"topic_id": topic_id, "paper_id": body.paper_id},
        )

    @app.post("/api/topics/{topic_id}/writing-architecture")
    def writing_architecture(topic_id: int, body: WritingArchitectureRequest):
        """Design the paper's narrative architecture."""
        return run_tool(
            "writing_architecture",
            {"topic_id": topic_id, "template": body.template},
        )
