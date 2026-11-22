# -*- coding: utf-8 -*-
"""PDF 验证器与全局缓存管理器。

负责校验本地 PDF 文件的物理合法性、计算 SHA256 指纹去重、
以及管理全局持久化缓存和短效失败退避 TTL。
"""

from __future__ import annotations

import hashlib
import json
from paperfetch.observability import get_event_logger
import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pypdf import PdfReader

from paperfetch.core.models import PaperRecord
from paperfetch.core.config_v1 import runtime_cache_root
from paperfetch.downloaders.base import PDFRouteCandidate
from paperfetch.downloaders.pdf_common import verify_pdf_file

logger = get_event_logger("paperfetch.downloaders.pipeline.cache")

FAILURE_TTL_SECONDS = 6 * 60 * 60  # 失败缓存生存时间 6 小时


def resolve_pdf_cache_root(root: Path | str | None = None) -> Path:
    """解析 PDF 缓存根目录，支持测试与运行任务隔离缓存。"""
    if root is not None:
        return Path(root)
    configured = os.getenv("PDF_CACHE_ROOT")
    if configured and configured.strip():
        return Path(configured.strip())
    return runtime_cache_root() / "pdf"


class PDFVerifier:
    """PDF 物理特征与论文身份验证器。"""

    min_size_bytes = 100

    @staticmethod
    def sha256_file(path: str) -> str:
        """分块计算文件的 SHA256 哈希值。"""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def verify_file(
        self, path: str, paper: Optional[PaperRecord] = None
    ) -> Dict[str, Any]:
        """校验 PDF 物理有效性，并在提供论文时验证文档身份。"""
        if not path or not os.path.exists(path):
            return {"valid": False, "error_class": "missing_file"}
        size = os.path.getsize(path)
        if size < self.min_size_bytes:
            return {"valid": False, "error_class": "too_small", "size": size}
        if not verify_pdf_file(path):
            return {"valid": False, "error_class": "not_pdf", "size": size}
        result: Dict[str, Any] = {
            "valid": True,
            "size": size,
            "sha256": self.sha256_file(path),
            "identity_status": "not_checked",
            "identity_verified": False,
            "identity_confidence": "none",
            "identity_evidence": {},
        }
        if paper is None:
            return result

        identity = self.verify_identity(path, paper)
        result.update(identity)
        result["valid"] = bool(identity.get("identity_verified"))
        if not result["valid"]:
            result["error_class"] = identity.get("error_class") or "identity_unverified"
        return result

    def verify_identity(self, path: str, paper: PaperRecord) -> Dict[str, Any]:
        """从 PDF 元数据和前五页文本中核对 DOI、arXiv 或题名。"""
        expected_doi = self._normalize_doi(paper.doi)
        expected_arxiv = self._normalize_arxiv(paper.arxiv_id)
        expected_title = self._normalize_title(paper.title)

        try:
            reader = PdfReader(path, strict=False)
            metadata = reader.metadata or {}
            metadata_title = str(metadata.get("/Title") or "").strip()
            metadata_subject = str(metadata.get("/Subject") or "").strip()
            metadata_keywords = str(metadata.get("/Keywords") or "").strip()
            page_text = []
            for page in reader.pages[:5]:
                try:
                    page_text.append(page.extract_text() or "")
                except Exception:
                    continue
        except Exception as exc:
            return {
                "identity_status": "unverified",
                "identity_verified": False,
                "identity_confidence": "none",
                "error_class": "identity_unverified",
                "identity_evidence": {
                    "reason": "pdf_text_extraction_failed",
                    "detail": str(exc)[:200],
                },
            }

        primary_text = "\n".join(
            [metadata_title, metadata_subject, metadata_keywords, *page_text[:2]]
        )
        combined = "\n".join([primary_text, *page_text[2:]])
        primary_dois = sorted(
            self._extract_dois(primary_text, expected_doi=expected_doi)
        )
        discovered_dois = sorted(
            self._extract_dois(combined, expected_doi=expected_doi)
        )
        normalized_text = self._normalize_title(primary_text[:60_000])
        normalized_metadata_title = self._normalize_title(metadata_title)
        title_ratio = self._title_ratio(expected_title, normalized_metadata_title)
        title_coverage = self._title_token_coverage(expected_title, normalized_text)
        title_exact = bool(expected_title and expected_title in normalized_text)

        evidence: Dict[str, Any] = {
            "expected_doi": expected_doi,
            "primary_dois": primary_dois[:10],
            "discovered_dois": discovered_dois[:10],
            "metadata_title": metadata_title[:300],
            "title_ratio": round(title_ratio, 3),
            "title_token_coverage": round(title_coverage, 3),
            "pages_checked": min(5, len(reader.pages)),
        }

        if expected_doi and expected_doi in primary_dois:
            return self._identity_success("verified_doi", "high", evidence)
        if expected_arxiv and expected_arxiv in primary_text.lower():
            evidence["expected_arxiv"] = expected_arxiv
            return self._identity_success("verified_arxiv", "high", evidence)
        if title_exact or title_ratio >= 0.82 or title_coverage >= 0.9:
            return self._identity_success("verified_title", "medium", evidence)

        metadata_dois = self._extract_dois(
            "\n".join([metadata_subject, metadata_keywords]),
            expected_doi=expected_doi,
        )
        strong_foreign_doi = bool(
            expected_doi and metadata_dois and expected_doi not in metadata_dois
        )
        conflicting_title = bool(normalized_metadata_title and title_ratio < 0.35)
        foreign_first_pages = bool(
            expected_doi and primary_dois and expected_doi not in primary_dois
        )
        if strong_foreign_doi or (conflicting_title and foreign_first_pages):
            evidence["reason"] = "document_identity_conflicts_with_target"
            return {
                "identity_status": "mismatch",
                "identity_verified": False,
                "identity_confidence": "high",
                "error_class": "metadata_poisoned",
                "identity_evidence": evidence,
            }

        evidence["reason"] = "insufficient_identity_evidence"
        return {
            "identity_status": "unverified",
            "identity_verified": False,
            "identity_confidence": "low",
            "error_class": "identity_unverified",
            "identity_evidence": evidence,
        }

    @staticmethod
    def _identity_success(
        status: str, confidence: str, evidence: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "identity_status": status,
            "identity_verified": True,
            "identity_confidence": confidence,
            "identity_evidence": evidence,
        }

    @staticmethod
    def _normalize_doi(value: Optional[str]) -> str:
        if not value:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
        text = re.sub(r"^doi\s*:\s*", "", text)
        return text.rstrip(".,;:")

    @staticmethod
    def _normalize_arxiv(value: Optional[str]) -> str:
        if not value:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text)
        text = re.sub(r"^arxiv\s*:\s*", "", text)
        return text.removesuffix(".pdf")

    @staticmethod
    def _normalize_title(value: Optional[str]) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
        return " ".join(text.split())

    @classmethod
    def _extract_dois(cls, text: str, *, expected_doi: str = "") -> set[str]:
        matches = re.findall(
            r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text or "", flags=re.IGNORECASE
        )
        normalized_expected = cls._normalize_doi(expected_doi)
        result: set[str] = set()
        for item in matches:
            normalized = cls._normalize_doi(item)
            if not normalized:
                continue
            # 某些出版社 PDF 的文本层会把 DOI 后紧随的字段标签 ``doi``
            # 粘到标识符末尾。只针对当前待核验 DOI 做精确修复，避免猜测
            # 或截断其他合法 DOI 后缀。
            if normalized_expected and normalized == f"{normalized_expected}doi":
                normalized = normalized_expected
            result.add(normalized)
        return result

    @staticmethod
    def _title_ratio(expected: str, actual: str) -> float:
        if not expected or not actual:
            return 0.0
        return SequenceMatcher(None, expected, actual).ratio()

    @staticmethod
    def _title_token_coverage(expected: str, document: str) -> float:
        tokens = [token for token in expected.split() if len(token) >= 3]
        if len(tokens) < 4 or not document:
            return 0.0
        document_tokens = set(document.split())
        return sum(1 for token in tokens if token in document_tokens) / len(tokens)


class PDFGlobalCache:
    """全局 PDF 文档缓存与失败隔离管理系统。"""

    def __init__(
        self,
        root: Path | str | None = None,
        failure_ttl_seconds: int = FAILURE_TTL_SECONDS,
    ) -> None:
        self.root = resolve_pdf_cache_root(root)
        self.pdf_dir = self.root / "files"
        self.quarantine_dir = self.root / "quarantine"
        self.failure_file = self.root / "failures.v2.json"
        self.failure_ttl_seconds = failure_ttl_seconds
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self._failures: Dict[str, Any] = self._load_failures()

    @staticmethod
    def key_for_paper(paper: PaperRecord) -> str:
        """根据论文的 DOI、arXiv 或标题生成唯一的哈希缓存键名。"""
        if paper.doi:
            raw = f"doi:{paper.doi.lower()}"
        elif paper.arxiv_id:
            raw = f"arxiv:{paper.arxiv_id.lower()}"
        else:
            raw = (
                "title:"
                + hashlib.sha256(
                    (paper.title or paper.paper_id).lower().encode("utf-8")
                ).hexdigest()[:24]
            )
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("_")

    def paper_key(self, paper: PaperRecord) -> str:
        return self.key_for_paper(paper)

    def pdf_path(self, paper: PaperRecord) -> Path:
        """获取目标 PDF 在缓存目录下的标准物理路径。"""
        return self.pdf_dir / f"{self.paper_key(paper)}.pdf"

    def inspect_verified(
        self, paper: PaperRecord, verifier: PDFVerifier
    ) -> Tuple[Optional[Path], Dict[str, Any]]:
        """检查全局缓存并返回路径与完整校验结果。"""
        path = self.pdf_path(paper)
        manifest_path = path.with_suffix(".json")
        if path.exists() and manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                basic = verifier.verify_file(str(path))
                manifest_matches = (
                    basic.get("valid")
                    and manifest.get("sha256") == basic.get("sha256")
                    and verifier._normalize_doi(manifest.get("doi"))
                    == verifier._normalize_doi(paper.doi)
                    and verifier._normalize_title(manifest.get("title"))
                    == verifier._normalize_title(paper.title)
                    and str(manifest.get("identity_status") or "").startswith(
                        "verified_"
                    )
                )
                if manifest_matches:
                    return path, {
                        **basic,
                        "identity_verified": True,
                        "identity_status": manifest.get("identity_status"),
                        "identity_confidence": manifest.get("identity_confidence")
                        or "none",
                        "identity_evidence": manifest.get("identity_evidence") or {},
                    }
            except Exception:
                pass
        meta = verifier.verify_file(str(path), paper)
        if meta.get("valid"):
            return path, meta
        if path.exists() and meta.get("error_class") in {
            "metadata_poisoned",
            "identity_unverified",
        }:
            self.quarantine(paper, path, meta)
        return None, meta

    def find_verified(
        self, paper: PaperRecord, verifier: PDFVerifier
    ) -> Optional[Path]:
        """在全局缓存中检索已通过论文身份验证的 PDF。"""
        path, _ = self.inspect_verified(paper, verifier)
        return path

    def store_verified(
        self,
        paper: PaperRecord,
        source_path: str,
        verifier: PDFVerifier,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """将验证通过的外部 PDF 文件同步归档至全局缓存系统中。"""
        meta = verification or verifier.verify_file(source_path, paper)
        if not meta.get("valid"):
            return None
        target = self.pdf_path(paper)
        if os.path.abspath(source_path) != os.path.abspath(target):
            shutil.copy2(source_path, target)
        manifest = {
            "paper_key": self.paper_key(paper),
            "doi": paper.doi,
            "title": paper.title,
            "sha256": meta.get("sha256"),
            "identity_status": meta.get("identity_status"),
            "identity_confidence": meta.get("identity_confidence"),
            "identity_evidence": meta.get("identity_evidence") or {},
            "stored_at": datetime.now().isoformat(),
        }
        target.with_suffix(".json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def quarantine(
        self, paper: PaperRecord, path: Path | str, meta: Dict[str, Any]
    ) -> Optional[Path]:
        """隔离身份不可信的 PDF，并保存可审计的校验证据。"""
        source = Path(path)
        if not source.exists():
            return None
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        target = self.quarantine_dir / f"{self.paper_key(paper)}__{stamp}.pdf"
        shutil.move(str(source), str(target))
        source_manifest = source.with_suffix(".json")
        if source_manifest.exists():
            source_manifest.unlink()
        audit = {
            "paper_key": self.paper_key(paper),
            "doi": paper.doi,
            "title": paper.title,
            "error_class": meta.get("error_class"),
            "identity_status": meta.get("identity_status"),
            "identity_evidence": meta.get("identity_evidence") or {},
            "original_path": str(source),
            "quarantined_at": datetime.now().isoformat(),
        }
        target.with_suffix(".json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.warning(
            "[PDF 缓存] 隔离身份校验失败的文件，DOI=%s，文件=%s，错误=%s",
            paper.doi or paper.paper_id,
            target,
            meta.get("error_class") or "identity_unverified",
        )
        return target

    def should_skip(
        self,
        paper: PaperRecord,
        candidate: PDFRouteCandidate,
        retry_failed: bool = False,
    ) -> bool:
        """判断是否需要因历史失败而在 TTL 时限内强行退避并跳过该路由通道。"""
        if retry_failed:
            return False
        entry = self._failures.get(self._failure_key(paper, candidate))
        if not entry:
            return False
        return time.time() < float(entry.get("expires_at_epoch") or 0)

    def record_failure(
        self, paper: PaperRecord, candidate: PDFRouteCandidate, attempt: Any
    ) -> None:
        """记录该路由的失败记录及时间戳，作为后续退避依据。"""
        error_class = str(getattr(attempt, "error_class", "unknown") or "unknown")
        if error_class in {"missing_credentials", "planned_skip"}:
            return
        ttl_seconds = self._failure_ttl(
            error_class, getattr(attempt, "diagnostics", None)
        )
        self._failures[self._failure_key(paper, candidate)] = {
            "paper_key": self.paper_key(paper),
            "route": candidate.route,
            "host": candidate.host,
            "resource_fingerprint": self._resource_fingerprint(candidate),
            "transport": candidate.metadata.get("transport") or candidate.route,
            "proxy_mode": candidate.metadata.get("proxy_mode") or "environment",
            "anonymous_auth": bool(candidate.metadata.get("anonymous_auth", True)),
            "error_class": error_class,
            "status_code": getattr(attempt, "status_code", None),
            "content_type": getattr(attempt, "content_type", ""),
            "timestamp": getattr(attempt, "started_at", ""),
            "timestamp_epoch": time.time(),
            "ttl_seconds": ttl_seconds,
            "expires_at_epoch": time.time() + ttl_seconds,
        }
        self._save_failures()

    def _failure_key(self, paper: PaperRecord, candidate: PDFRouteCandidate) -> str:
        proxy_mode = str(candidate.metadata.get("proxy_mode") or "")
        fingerprint = self._resource_fingerprint(candidate)
        transport = str(candidate.metadata.get("transport") or candidate.route)
        anonymous_auth = str(
            bool(candidate.metadata.get("anonymous_auth", True))
        ).lower()
        return f"{self.paper_key(paper)}|{fingerprint}|{transport}|{proxy_mode}|{anonymous_auth}"

    @staticmethod
    def _resource_fingerprint(candidate: PDFRouteCandidate) -> str:
        configured = str(candidate.metadata.get("resource_fingerprint") or "")
        if configured:
            return configured
        raw = candidate.url or candidate.metadata.get("resource_id") or candidate.route
        return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()

    def _failure_ttl(
        self, error_class: str, diagnostics: Optional[Dict[str, Any]]
    ) -> int:
        if error_class in {"not_found", "not_pdf", "html_landing", "metadata_poisoned"}:
            return 6 * 60 * 60
        if error_class in {
            "publisher_challenge",
            "waf_challenge",
            "auth_required",
            "auth_failed",
            "unattended_auth_blocked",
        }:
            return 15 * 60
        if error_class == "rate_limited":
            value = str((diagnostics or {}).get("retry_after") or "").strip()
            try:
                return min(10 * 60, max(1, int(value)))
            except ValueError:
                return 10 * 60
        if error_class in {"timeout", "network_error", "connection_error"}:
            return 2 * 60
        return self.failure_ttl_seconds

    def _load_failures(self) -> Dict[str, Any]:
        if not self.failure_file.exists():
            return {}
        try:
            return json.loads(self.failure_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_failures(self) -> None:
        self.failure_file.write_text(
            json.dumps(self._failures, ensure_ascii=False, indent=2), encoding="utf-8"
        )
