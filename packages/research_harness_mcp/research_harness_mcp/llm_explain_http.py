"""FastAPI route registration for the local PDF-reader LLM explain endpoint."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


_EXPLAIN_PRESETS: dict[str, str] = {
    "explain": (
        "Explain the following passage in clear, concise English. "
        "Define jargon, expand abbreviations, and clarify any implicit "
        "assumptions. If the passage references a method or result, briefly "
        "describe what it is and why it matters."
    ),
    "summarize": (
        "Summarize the following passage in 2-3 sentences. Capture the main "
        "claim, the evidence, and any caveat the authors explicitly call out."
    ),
    "translate_zh": (
        "Translate the following passage into fluent Simplified Chinese. "
        "Preserve technical terms and cite the English original term in "
        "parentheses on first use."
    ),
    "critique": (
        "Critically evaluate the following passage. Identify any unsupported "
        "claims, ambiguities, or potential weaknesses in reasoning. Be "
        "specific and brief."
    ),
}


class ExplainRequest(BaseModel):
    text: str = Field(..., description="Selected text from the PDF")
    preset: str | None = Field(
        None,
        description="Optional preset id: explain | summarize | translate_zh | critique",
    )
    custom_prompt: str | None = Field(
        None,
        description="User-supplied prompt — overrides preset if both provided",
    )
    paper_title: str | None = Field(None, description="Paper title for context")
    paper_id: int | None = Field(None, description="Paper id for provenance")
    tier: Literal["light", "medium", "heavy"] = Field(
        "medium", description="LLM routing tier"
    )


def register_llm_explain_routes(
    app: FastAPI, *, logger: logging.Logger | None = None
) -> None:
    """Register the local single-shot LLM explain endpoint."""

    route_logger = logger or logging.getLogger(__name__)

    @app.post("/api/llm/explain")
    def llm_explain(body: ExplainRequest):
        """Run a single-shot LLM call against selected PDF text."""
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        if len(text) > 8000:
            raise HTTPException(
                status_code=400,
                detail=f"selection too long ({len(text)} chars > 8000)",
            )

        instruction = (body.custom_prompt or "").strip()
        if not instruction and body.preset:
            instruction = _EXPLAIN_PRESETS.get(body.preset, "").strip()
        if not instruction:
            instruction = _EXPLAIN_PRESETS["explain"]

        prompt_parts = [instruction, ""]
        if body.paper_title:
            prompt_parts.append(f"Paper: {body.paper_title}")
        prompt_parts.extend(["Passage:", '"""', text, '"""'])
        prompt = "\n".join(prompt_parts)

        try:
            from llm_router import LLMClient
        except Exception as exc:  # pragma: no cover
            raise HTTPException(
                status_code=500, detail=f"llm_router import failed: {exc}"
            ) from exc

        try:
            client = LLMClient()
            response, usage = client.chat_with_usage(prompt, tier=body.tier)
        except Exception as exc:
            route_logger.exception("llm.explain failed")
            raise HTTPException(
                status_code=502, detail=f"LLM call failed: {exc}"
            ) from exc

        usage_payload: dict[str, Any] | None = None
        if usage is not None:
            usage_payload = {
                "provider": getattr(usage, "provider", None),
                "model": getattr(usage, "model", None),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            }

        return {
            "response": response,
            "preset_used": body.preset if not body.custom_prompt else None,
            "tier": body.tier,
            "usage": usage_payload,
        }
