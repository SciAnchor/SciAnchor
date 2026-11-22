"""Pydantic request models for Zotero HTTP endpoints."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ZOTERO_CODEX_MODEL_OPTIONS: dict[str, str] = {
    "gpt-5.3-codex-spark": "快速",
    "gpt-5.4-mini": "平衡",
    "gpt-5.4": "强力",
    "gpt-5.5": "更强",
    "gpt-6-astra": "最强",
}
ZOTERO_CODEX_DEFAULT_MODEL = "gpt-6-astra"
# Selected-text translation is a cheap one-shot call; it intentionally does
# not follow the (strongest) chat default.
ZOTERO_CODEX_TRANSLATE_MODEL = "gpt-5.4-mini"


def default_zotero_codex_model() -> str:
    configured = os.environ.get("RESEARCH_HARNESS_ZOTERO_CODEX_MODEL", "").strip()
    if configured in ZOTERO_CODEX_MODEL_OPTIONS:
        return configured
    return ZOTERO_CODEX_DEFAULT_MODEL


def validate_zotero_codex_model(value: str) -> str:
    model = str(value or "").strip()
    if model not in ZOTERO_CODEX_MODEL_OPTIONS:
        allowed = ", ".join(ZOTERO_CODEX_MODEL_OPTIONS)
        raise ValueError(f"unsupported Zotero Codex model: {model}; allowed: {allowed}")
    return model


class ZoteroSyncRequest(BaseModel):
    direction: Literal["push", "pull", "both"] = "push"
    root_collection: str = "Research Harness"
    topic_collection_name: str | None = Field(default=None, max_length=240)
    target_collection_key: str | None = Field(default=None, max_length=64)
    parent_collection_key: str | None = Field(default=None, max_length=64)
    target_collection_name: str | None = Field(default=None, max_length=240)
    target_collection_path: str | None = Field(default=None, max_length=1000)
    library_id: str | int | None = None
    library_type: Literal["user", "group"] = "user"
    api_key: str | None = None
    api_base: str | None = None
    limit: int | None = Field(default=None, ge=1)
    paper_ids: list[int] = Field(default_factory=list, max_length=500)
    skip_notes: bool = False
    force: bool = False
    include_rh_generated: bool = False
    dry_run: bool = True

    @field_validator("paper_ids", mode="after")
    @classmethod
    def _dedupe_paper_ids(cls, values: list[int]) -> list[int]:
        seen: set[int] = set()
        result: list[int] = []
        for value in values:
            paper_id = int(value)
            if paper_id <= 0 or paper_id in seen:
                continue
            seen.add(paper_id)
            result.append(paper_id)
        return result


class ZoteroChatTargetRef(BaseModel):
    paper_id: int | None = Field(default=None, ge=1)
    topic_id: int | None = Field(default=None, ge=1)
    zotero_item_key: str = Field(default="", max_length=64)
    library_id: str | int | None = None
    library_type: Literal["user", "group"] = "user"
    title: str = Field(default="", max_length=1000)
    doi: str = Field(default="", max_length=300)
    arxiv_id: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=80)

    @field_validator("tags", mode="after")
    @classmethod
    def _trim_tags(cls, values: list[str]) -> list[str]:
        return [str(value).strip()[:500] for value in values if str(value).strip()]


class ZoteroChatItemContext(BaseModel):
    zotero_item_key: str = Field(default="", max_length=64)
    library_id: str | int | None = None
    library_type: Literal["user", "group"] = "user"
    title: str = Field(default="", max_length=1000)
    creators: list[str] = Field(default_factory=list, max_length=50)
    year: int | None = None
    doi: str = Field(default="", max_length=300)
    arxiv_id: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=2000)
    abstract: str = Field(default="", max_length=12000)
    extra: str = Field(default="", max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=200)
    selected_text: str = Field(default="", max_length=20000)
    note_text: str = Field(default="", max_length=20000)
    screenshots: list[str] = Field(default_factory=list, max_length=2)
    current_directory_key: str = Field(default="", max_length=64)
    current_directory_name: str = Field(default="", max_length=240)
    current_directory_path: str = Field(default="", max_length=1200)
    selected_items: list[ZoteroChatTargetRef] = Field(
        default_factory=list, max_length=100
    )
    last_preview_targets: list[ZoteroChatTargetRef] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("tags", "creators", mode="after")
    @classmethod
    def _trim_string_lists(cls, values: list[str]) -> list[str]:
        return [str(value).strip()[:500] for value in values if str(value).strip()]

    @field_validator("screenshots", mode="after")
    @classmethod
    def _validate_screenshots(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if not re.match(
                r"^data:image/(png|jpeg|jpg|webp);base64,", text, flags=re.I
            ):
                raise ValueError("screenshots must be data:image base64 URLs")
            if len(text) > 4_000_000:
                raise ValueError("each screenshot must be under 4MB as a data URL")
            cleaned.append(text)
        return cleaned[:2]


class ZoteroChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    item: ZoteroChatItemContext = Field(default_factory=ZoteroChatItemContext)
    conversation_id: str | None = Field(default=None, max_length=120)
    requested_action_type: str = Field(default="", max_length=120)
    locale: str = Field(default="zh-CN", max_length=32)
    model: str = Field(default_factory=default_zotero_codex_model, max_length=80)

    @field_validator("model", mode="after")
    @classmethod
    def _validate_codex_model(cls, value: str) -> str:
        return validate_zotero_codex_model(value)

    @field_validator("requested_action_type", mode="after")
    @classmethod
    def _trim_requested_action_type(cls, value: str) -> str:
        return str(value or "").strip()


class ZoteroWarmupRequest(BaseModel):
    model: str = Field(default_factory=default_zotero_codex_model, max_length=80)
    # Additional models to prewarm together with the primary chat model.
    # Defaults to the translate model so the first "翻译" click does not pay
    # the full Codex app-server cold start.
    extra_models: list[str] = Field(
        default_factory=lambda: [ZOTERO_CODEX_TRANSLATE_MODEL], max_length=4
    )

    @field_validator("model", mode="after")
    @classmethod
    def _validate_codex_model(cls, value: str) -> str:
        return validate_zotero_codex_model(value)

    @field_validator("extra_models", mode="after")
    @classmethod
    def _validate_extra_models(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            model = str(value or "").strip()
            if not model or model in seen:
                continue
            if model not in ZOTERO_CODEX_MODEL_OPTIONS:
                continue  # silently drop unknown models so warmup never 422s
            seen.add(model)
            cleaned.append(model)
        return cleaned


class ZoteroTranslateRequest(BaseModel):
    """Lightweight on-demand translation for selected PDF / note text.

    Intentionally does not carry paper context, conversation_id, or
    screenshots — translation should be as cheap as possible and must not
    pollute the multi-turn chat thread.
    """

    text: str = Field(min_length=1, max_length=20000)
    model: str = Field(default=ZOTERO_CODEX_TRANSLATE_MODEL, max_length=80)
    target_locale: str = Field(default="zh-CN", max_length=32)
    source_locale: str = Field(default="", max_length=32)

    @field_validator("model", mode="after")
    @classmethod
    def _validate_codex_model(cls, value: str) -> str:
        return validate_zotero_codex_model(value)


class ZoteroSeedPaperApplyRequest(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    topic_id: int | None = None
    topic_name: str = Field(default="", max_length=240)
    topic_description: str = Field(default="", max_length=2000)
    candidate_sources: list[str] = Field(default_factory=list, max_length=20)
    target_collection_key: str = Field(default="", max_length=64)
    parent_collection_key: str = Field(default="", max_length=64)
    target_collection_name: str = Field(default="", max_length=240)
    target_collection_path: str = Field(default="", max_length=1200)
    library_id: str | int | None = None
    library_type: Literal["user", "group"] = "user"
    request_deep_read: bool = False
    request_pdf_attachment: bool = False
    request_pdf_annotations: bool = False
    target_is_topic_collection: bool = False
    dry_run: bool = True

    @field_validator("candidate_sources", mode="after")
    @classmethod
    def _trim_candidate_sources(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for value in values:
            text = str(value or "").strip()[:1000]
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned
