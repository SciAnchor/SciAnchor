"""SPC 1.0 Seed Pack 静态身份契约。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from paperfetch.core.contracts_v1 import StrictContract


SEED_PACK_MANIFEST_SCHEMA = "spc.seed-pack-manifest.v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SeedPackManifest(StrictContract):
    """仅保存包身份和布局版本；易变化计数由 status 实时投影。"""

    schema_version: Literal["spc.seed-pack-manifest.v1"] = SEED_PACK_MANIFEST_SCHEMA
    seed_pack_id: str = Field(
        default_factory=lambda: f"pack_{uuid.uuid4().hex}",
        pattern=r"^pack_[0-9a-f]{32}$",
    )
    layout_version: Literal[1] = 1
    name: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=_utc_now)
