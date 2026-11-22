"""SPC 1.0 内容寻址文件与文件清单契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from paperfetch.core.contracts_v1 import StrictContract


ARTIFACT_MANIFEST_SCHEMA = "spc.artifact-manifest.v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or ":" in path.parts[0]
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("artifact path must be a safe relative path")
    return str(path)


class ArtifactKind(str, Enum):
    PAPER_PDF = "paper_pdf"
    MINERU_FULLTEXT = "mineru_fulltext"


class ArtifactPointer(StrictContract):
    artifact_id: str = Field(pattern=r"^art_[0-9a-f]{32}$")
    kind: ArtifactKind
    manifest_path: str

    @field_validator("manifest_path")
    @classmethod
    def validate_manifest_path(cls, value: str) -> str:
        normalized = _safe_relative_path(value)
        if not normalized.endswith("/manifest.json"):
            raise ValueError("artifact pointer must reference manifest.json")
        return normalized


class ArtifactFile(StrictContract):
    role: str = Field(min_length=1)
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_relative_path(value)


class ArtifactProducer(StrictContract):
    name: str = Field(min_length=1)
    version: str | None = None


class ArtifactManifest(StrictContract):
    schema_version: Literal["spc.artifact-manifest.v1"] = ARTIFACT_MANIFEST_SCHEMA
    artifact_id: str = Field(pattern=r"^art_[0-9a-f]{32}$")
    paper_id: str = Field(pattern=r"^spc_[0-9a-f]{32}$")
    kind: ArtifactKind
    created_at: datetime = Field(default_factory=_utc_now)
    producer: ArtifactProducer
    source_artifact_id: str | None = Field(default=None, pattern=r"^art_[0-9a-f]{32}$")
    files: list[ArtifactFile] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_files(self) -> "ArtifactManifest":
        roles = [item.role for item in self.files]
        paths = [item.path for item in self.files]
        if len(roles) != len(set(roles)) or len(paths) != len(set(paths)):
            raise ValueError("artifact roles and paths must be unique")
        if self.kind == ArtifactKind.PAPER_PDF.value:
            if roles != ["article_pdf"]:
                raise ValueError("paper_pdf artifact must contain exactly article_pdf")
            if self.source_artifact_id is not None:
                raise ValueError("paper_pdf must not declare a source artifact")
        if self.kind == ArtifactKind.MINERU_FULLTEXT.value:
            required = {
                "document_markdown",
                "layout",
                "content_list",
                "model",
                "raw_archive",
            }
            if not required.issubset(roles) or self.source_artifact_id is None:
                raise ValueError(
                    "mineru_fulltext requires Markdown, layout, content list, model, raw ZIP, and source PDF"
                )
        return self
