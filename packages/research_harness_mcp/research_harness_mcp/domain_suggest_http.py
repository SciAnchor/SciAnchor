"""FastAPI route registration for domain suggestion."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class DomainSuggestRequest(BaseModel):
    idea: str


def register_domain_suggest_routes(app: FastAPI) -> None:
    """Register domain suggestion route."""

    @app.post("/api/domains/suggest")
    def domain_suggest(body: DomainSuggestRequest):
        """Suggest a domain from a research idea (stub — returns structured suggestion)."""
        idea = body.idea.strip()
        if not idea:
            raise HTTPException(status_code=400, detail="Idea text is required")
        words = idea.split()
        name_suggestion = (
            " ".join(words[:5]).title() if len(words) >= 3 else idea.title()
        )
        return {
            "suggestion": {
                "name": name_suggestion,
                "description": idea,
                "keywords": words[:10],
            },
            "source": "stub",
        }
