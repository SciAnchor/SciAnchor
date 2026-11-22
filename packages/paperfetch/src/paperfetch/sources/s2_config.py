# -*- coding: utf-8 -*-
"""Semantic Scholar / S2 环境配置辅助函数。"""

from __future__ import annotations

from paperfetch.observability import get_event_logger
import os
from dataclasses import dataclass
from typing import Iterable, List, Tuple

logger = get_event_logger("paperfetch.sources.s2_config")


CANONICAL_SINGLE_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"
CANONICAL_MULTI_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEYS"

MIN_INTERVAL_WITH_KEY_ENV = "SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS"
MIN_INTERVAL_WITHOUT_KEY_ENV = "SEMANTIC_SCHOLAR_ANON_MIN_INTERVAL_SECONDS"
RATE_LIMIT_COOLDOWN_ENV = "SEMANTIC_SCHOLAR_RATE_LIMIT_COOLDOWN_SECONDS"

DEFAULT_MIN_INTERVAL_WITH_KEY = 1.1
DEFAULT_MIN_INTERVAL_WITHOUT_KEY = 3.6
DEFAULT_RATE_LIMIT_COOLDOWN = 300.0


@dataclass(frozen=True)
class SemanticScholarConfig:
    api_keys: Tuple[str, ...]
    key_sources: Tuple[str, ...]
    min_interval_with_key: float
    min_interval_without_key: float
    rate_limit_cooldown: float

    @property
    def has_key(self) -> bool:
        return bool(self.api_keys)

    @property
    def key_count(self) -> int:
        return len(self.api_keys)

    @property
    def key_source_summary(self) -> str:
        return ", ".join(self.key_sources) if self.key_sources else "none"


def get_semantic_scholar_config() -> SemanticScholarConfig:
    keys, sources = _read_api_keys()
    return SemanticScholarConfig(
        api_keys=tuple(keys),
        key_sources=tuple(sources),
        min_interval_with_key=_env_float(
            MIN_INTERVAL_WITH_KEY_ENV,
            DEFAULT_MIN_INTERVAL_WITH_KEY,
        ),
        min_interval_without_key=_env_float(
            MIN_INTERVAL_WITHOUT_KEY_ENV,
            DEFAULT_MIN_INTERVAL_WITHOUT_KEY,
        ),
        rate_limit_cooldown=_env_float(
            RATE_LIMIT_COOLDOWN_ENV,
            DEFAULT_RATE_LIMIT_COOLDOWN,
        ),
    )


def _read_api_keys() -> tuple[List[str], List[str]]:
    raw_items: List[tuple[str, str]] = []
    for env_name in (CANONICAL_MULTI_KEY_ENV, CANONICAL_SINGLE_KEY_ENV):
        value = os.getenv(env_name)
        if value:
            for key in _split_keys(value):
                raw_items.append((key, env_name))

    seen = set()
    keys: List[str] = []
    sources: List[str] = []
    duplicate_sources: List[str] = []
    for key, source in raw_items:
        if key in seen:
            duplicate_sources.append(source)
            continue
        seen.add(key)
        keys.append(key)
        sources.append(source)

    if duplicate_sources:
        logger.debug(
            "[S2 配置] API 密钥别名存在重复值，已去重，来源=%s",
            sorted(set(duplicate_sources)),
        )
    return keys, sources


def _split_keys(raw_value: str) -> Iterable[str]:
    for item in raw_value.replace(";", ",").split(","):
        key = item.strip()
        if key:
            yield key


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(
            "[S2 配置] 环境变量不是数值，变量=%s，值=%r，默认值=%.2f",
            name,
            value,
            default,
        )
        return default
