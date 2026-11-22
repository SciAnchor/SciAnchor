"""Verified PDF cache and failure TTL cache for RH-native routes.

Both caches are opt-in via ``RESEARCH_HARNESS_PDF_CACHE_DIR``; unset means
fully disabled and the downloader behaves exactly as before. The verified
cache only ever stores files that already passed the downloader's magic /
size / identity-audit gauntlet, and cache hits are re-audited against the
requesting paper before being served, so a key collision can never hand a
paper someone else's PDF.

The failure cache remembers (paper, route, host) failures for a bounded TTL
(``RESEARCH_HARNESS_PDF_FAILURE_TTL_SEC``, default one day, ``0`` disables)
so reruns do not hammer known-bad routes; expiry is the retry mechanism.

Key derivation matches paperfetch's pack filename scheme
(``doi:…`` / ``arxiv:…`` / ``title:<sha256[:24]>``) so RH cache entries and
SPC seed-pack PDFs stay mutually recognizable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR_ENV = "RESEARCH_HARNESS_PDF_CACHE_DIR"
FAILURE_TTL_ENV = "RESEARCH_HARNESS_PDF_FAILURE_TTL_SEC"
DEFAULT_FAILURE_TTL_SEC = 86_400


def pdf_cache_key(doi: str = "", arxiv_id: str = "", title: str = "") -> str:
    doi = (doi or "").strip()
    arxiv_id = (arxiv_id or "").strip()
    if doi:
        raw = f"doi:{doi.lower()}"
    elif arxiv_id:
        raw = f"arxiv:{arxiv_id.lower()}"
    else:
        digest = hashlib.sha256((title or "").lower().encode("utf-8")).hexdigest()[:24]
        raw = f"title:{digest}"
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("_")


def _cache_root_from_env() -> Path | None:
    raw = os.environ.get(CACHE_DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


class VerifiedPDFCache:
    def __init__(self, root: Path | None, *, min_bytes: int = 10_000) -> None:
        self.root = root
        self.min_bytes = min_bytes

    @classmethod
    def from_env(cls, *, min_bytes: int = 10_000) -> "VerifiedPDFCache":
        return cls(_cache_root_from_env(), min_bytes=min_bytes)

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def path_for(self, key: str) -> Path:
        assert self.root is not None
        return self.root / "pdf" / f"{key}.pdf"

    def _valid(self, path: Path) -> bool:
        try:
            if path.stat().st_size < self.min_bytes:
                return False
            with path.open("rb") as handle:
                return handle.read(5).startswith(b"%PDF")
        except OSError:
            return False

    def find(self, key: str) -> Path | None:
        if not self.enabled:
            return None
        path = self.path_for(key)
        return path if self._valid(path) else None

    def store(self, key: str, source: Path) -> Path | None:
        """Archive an already-verified PDF; callers own the identity audit."""
        if not self.enabled or not self._valid(source):
            return None
        target = self.path_for(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
        except OSError:
            logger.debug("pdf cache store failed for %s", key, exc_info=True)
            return None
        return target


class FailureTTLCache:
    def __init__(self, root: Path | None, ttl_sec: float) -> None:
        self.root = root
        self.ttl_sec = ttl_sec

    @classmethod
    def from_env(cls) -> "FailureTTLCache":
        raw = os.environ.get(FAILURE_TTL_ENV, "").strip()
        try:
            ttl = float(raw) if raw else float(DEFAULT_FAILURE_TTL_SEC)
        except ValueError:
            ttl = float(DEFAULT_FAILURE_TTL_SEC)
        return cls(_cache_root_from_env(), ttl)

    @property
    def enabled(self) -> bool:
        return self.root is not None and self.ttl_sec > 0

    def _store_path(self) -> Path:
        assert self.root is not None
        return self.root / "failures.json"

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self._store_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _entry_key(key: str, route: str, host: str) -> str:
        return f"{key}|{route}|{host}"

    def get_fresh(self, key: str, route: str, host: str) -> dict[str, object] | None:
        if not self.enabled:
            return None
        entry = self._load().get(self._entry_key(key, route, host))
        if not isinstance(entry, dict):
            return None
        recorded_at = entry.get("recorded_at")
        if not isinstance(recorded_at, (int, float)):
            return None
        if time.time() - recorded_at >= self.ttl_sec:
            return None
        return entry

    def record(self, key: str, route: str, host: str, error_class: str) -> None:
        if not self.enabled:
            return
        entries = self._load()
        entries[self._entry_key(key, route, host)] = {
            "error_class": error_class,
            "recorded_at": time.time(),
        }
        try:
            path = self._store_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.debug("failure cache write failed", exc_info=True)
