# -*- coding: utf-8 -*-
"""数据库分类器与证据证据库。

根据论文 DOI 前缀、出版商文本、期刊名称等字段在内存中快速匹配可能所属的
目标学术数据库画像 (ScienceDirect, SpringerLink, IEEE Xplore, Nature, Science, Taylor 等)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

from paperfetch.core.models import PaperRecord


@dataclass(frozen=True)
class PDFDatabaseProfile:
    """定义特定数据库的匹配指纹特征。"""

    key: str
    label: str
    doi_prefixes: tuple[str, ...] = ()
    publisher_terms: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PDFDatabaseMatch:
    """记录一次数据库匹配命中的证据和可信度。"""

    profile: PDFDatabaseProfile
    confidence: int
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.profile.key

    @property
    def label(self) -> str:
        return self.profile.label

    def metadata(self) -> Dict[str, Any]:
        return {
            "database_key": self.key,
            "database_label": self.label,
            "database_confidence": self.confidence,
            "database_match_reason": self.reason,
            "database_evidence": self.evidence,
        }


DATABASE_PROFILES: tuple[PDFDatabaseProfile, ...] = (
    PDFDatabaseProfile(
        key="sciencedirect",
        label="ScienceDirect",
        doi_prefixes=("10.1016/",),
        publisher_terms=("elsevier", "sciencedirect", "science direct"),
        hosts=("sciencedirect.com", "www.sciencedirect.com", "linkinghub.elsevier.com"),
    ),
    PDFDatabaseProfile(
        key="ieee",
        label="IEEE Xplore",
        doi_prefixes=("10.1109/",),
        publisher_terms=("ieee", "ieeexplore", "xplore"),
        hosts=("ieeexplore.ieee.org",),
    ),
    PDFDatabaseProfile(
        key="springer",
        label="SpringerLink",
        doi_prefixes=("10.1007/", "10.1186/"),
        publisher_terms=("springer", "springerlink", "springer link"),
        hosts=("link.springer.com",),
    ),
    PDFDatabaseProfile(
        key="nature",
        label="Nature",
        doi_prefixes=("10.1038/",),
        publisher_terms=("nature.com", "springer nature"),
        hosts=("www.nature.com", "nature.com"),
    ),
    PDFDatabaseProfile(
        key="science",
        label="Science",
        doi_prefixes=("10.1126/",),
        publisher_terms=("science.org", "aaas", "science magazine"),
        hosts=("www.science.org", "science.org"),
    ),
    PDFDatabaseProfile(
        key="taylor",
        label="Taylor",
        doi_prefixes=("10.1080/",),
        publisher_terms=("taylor", "taylor & francis", "tandfonline"),
        hosts=("www.tandfonline.com", "tandfonline.com"),
    ),
    PDFDatabaseProfile(
        key="acm",
        label="ACM",
        doi_prefixes=("10.1145/",),
        publisher_terms=("acm", "association for computing machinery", "dl.acm"),
        hosts=("dl.acm.org",),
    ),
    PDFDatabaseProfile(
        key="wiley",
        label="Wiley",
        doi_prefixes=("10.1002/", "10.1111/", "10.1034/", "10.1046/"),
        publisher_terms=("wiley", "wiley-blackwell", "onlinelibrary.wiley"),
        hosts=("onlinelibrary.wiley.com",),
    ),
    PDFDatabaseProfile(
        key="bioone",
        label="BioOne",
        doi_prefixes=("10.31931/",),
        publisher_terms=("bioone", "bio one"),
        hosts=("bioone.org", "www.bioone.org"),
    ),
)


def normalize_doi(value: Optional[str]) -> str:
    text = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.lstrip("/")


def _host_matches(host: str, candidates: Iterable[str]) -> bool:
    host = (host or "").lower()
    for candidate in candidates:
        value = candidate.lower()
        if host == value or host.endswith("." + value):
            return True
    return False


def _publisher_text(paper: PaperRecord) -> str:
    return " ".join(
        item.strip().lower()
        for item in (paper.publisher, paper.journal, paper.venue)
        if item and item.strip()
    )


class PDFDatabaseClassifier:
    """分析论文元数据将其分类为匹配的学术库的分类器。"""

    def __init__(
        self, profiles: Sequence[PDFDatabaseProfile] = DATABASE_PROFILES
    ) -> None:
        self.profiles = tuple(profiles)

    def classify(
        self, paper: PaperRecord, resolved_url: Optional[str] = None
    ) -> List[PDFDatabaseMatch]:
        """根据元数据和已解析 URL 给出匹配的分类命中匹配项。"""
        doi = normalize_doi(paper.doi)
        publisher = _publisher_text(paper)
        host = ""
        if resolved_url:
            try:
                host = urlsplit(resolved_url).hostname or ""
            except Exception:
                host = ""

        matches: List[PDFDatabaseMatch] = []
        for profile in self.profiles:
            # 1. 优先匹配 DOI 前缀
            if doi and any(doi.startswith(prefix) for prefix in profile.doi_prefixes):
                matches.append(
                    PDFDatabaseMatch(
                        profile,
                        95,
                        "doi_prefix_match",
                        {"doi_prefix": doi.split("/", 1)[0]},
                    )
                )
                continue
            # 2. 次选匹配 URL 域名
            if host and _host_matches(host, profile.hosts):
                matches.append(
                    PDFDatabaseMatch(profile, 85, "host_match", {"host": host})
                )
                continue
            # 3. 备选匹配出版商元数据文本
            for term in profile.publisher_terms:
                if term and term.lower() in publisher:
                    matches.append(
                        PDFDatabaseMatch(profile, 75, "publisher_match", {"term": term})
                    )
                    break
        return sorted(matches, key=lambda item: item.confidence, reverse=True)
