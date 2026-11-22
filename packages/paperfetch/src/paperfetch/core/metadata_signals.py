# -*- coding: utf-8 -*-
"""
事实目录查询与弱整理信号。

这些辅助函数不是论文质量评分器，只暴露 CCF/CAS 目录匹配、有限引用信号等
已记录元数据，用于成果包内部排序。
"""

import difflib
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from paperfetch.core.models import PaperRecord
from paperfetch.observability import get_event_logger

logger = get_event_logger("paperfetch.core.metadata_signals")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CCF_PATH = os.path.abspath(
    os.path.join(CURRENT_DIR, "..", "data", "reference", "ccf_ranks_2026.json")
)
# 中科院分区 / JCR 等受限数据不随公开版分发；用户可通过该环境变量（或 spc.toml 同名键）
# 指向自备的 journal_master SQLite（表 journal_records(normalized_name, original_name, facts_json)）。
JOURNAL_MASTER_DB_ENV = "SPC_JOURNAL_MASTER_DB"


def configured_journal_master_db() -> Optional[str]:
    """返回用户配置的期刊主库路径；未配置时返回 None。"""

    try:
        from paperfetch.core.settings import get_settings

        value = get_settings().text(JOURNAL_MASTER_DB_ENV)
    except Exception:
        value = os.getenv(JOURNAL_MASTER_DB_ENV)
    value = (value or "").strip()
    return os.path.abspath(os.path.expanduser(value)) if value else None


def journal_master_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """只读报告用户自备期刊主库的可用性，供 doctor 使用。"""

    resolved = db_path or configured_journal_master_db()
    status: Dict[str, Any] = {
        "capability": "cas_zones",
        "env": JOURNAL_MASTER_DB_ENV,
        "source": resolved,
        "configured": resolved is not None,
        "ready": False,
        "journal_records": 0,
        "error_class": None,
    }
    if resolved is None:
        status["error_class"] = "not_configured"
        return status
    if not os.path.isfile(resolved):
        status["error_class"] = "reference_data_missing"
        return status
    try:
        with sqlite3.connect(f"file:{resolved}?mode=ro", uri=True) as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM journal_records").fetchone()
        status["journal_records"] = int(count)
        status["ready"] = count > 0
        if not count:
            status["error_class"] = "reference_data_invalid"
    except (sqlite3.Error, TypeError, ValueError):
        status["error_class"] = "reference_data_invalid"
    return status


def _normalize_title(title: str) -> str:
    return "".join(char.lower() for char in title if char.isalnum())


def _load_journal_master(db_path: str) -> Dict[str, Dict[str, Any]]:
    """把 journal_master.db 的 facts_json 读成 规范化名称 -> facts 的映射。"""

    index: Dict[str, Dict[str, Any]] = {}
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT facts_json FROM journal_records").fetchall()
    for (payload,) in rows:
        facts = json.loads(payload)
        if not isinstance(facts, dict):
            continue
        for name_key in (facts.get("journal_name"), facts.get("normalized_name")):
            if name_key:
                index[_normalize_title(str(name_key))] = facts
    return index


class VenueCatalogLookup:
    """CCF/CAS 目录事实查询辅助类。"""

    def __init__(
        self,
        ccf_path: str = DEFAULT_CCF_PATH,
        cas_path: Optional[str] = None,
        cas_db_path: Optional[str] = None,
    ):
        self.ccf_path = ccf_path
        self.cas_path = cas_path
        # None 表示使用 SPC_JOURNAL_MASTER_DB；仍为 None 时中科院分区能力“未配置”。
        self.cas_db_path = cas_db_path
        self.ccf_data: List[Dict[str, Any]] = []
        self.cas_data: Dict[str, Dict[str, Any]] = {}
        self._cas_index: Dict[str, Dict[str, Any]] = {}
        self._cas_initialized = False
        self._cas_warning_emitted = False
        # CCF 倒排索引（在 _load_ccf 中构建）
        self._abbr_index: Dict[str, Dict[str, Any]] = {}
        self._fullname_index: Dict[str, Dict[str, Any]] = {}
        self._dblp_index: Dict[str, Dict[str, Any]] = {}
        self._load_ccf()

    def _load_ccf(self) -> None:
        if not os.path.exists(self.ccf_path):
            logger.warning("[元数据] 未找到 CCF 目录，路径=%s", self.ccf_path)
            return
        try:
            with open(self.ccf_path, "r", encoding="utf-8") as f:
                self.ccf_data = json.load(f)
        except Exception as exc:
            logger.error("[元数据] CCF 目录加载失败，原因=%s", exc)
            return

        # ── 基于 ref 文件构建多维倒排索引，匹配时直接查表 ──
        # 对于缩写重复的条目（如 ASE 同时是 B 类期刊和 A 类会议），
        # 优先保留 CCF 等级更高的条目（A > B > C）
        _rank_priority = {"A": 3, "B": 2, "C": 1}

        for item in self.ccf_data:
            rank_val = _rank_priority.get(item.get("ccf_rank", ""), 0)

            # 索引 1: abbreviation (小写) → entry
            abbr = str(item.get("abbreviation", "")).strip().lower()
            if abbr:
                existing = self._abbr_index.get(abbr)
                if not existing or rank_val > _rank_priority.get(
                    existing.get("ccf_rank", ""), 0
                ):
                    self._abbr_index[abbr] = item

            # 索引 2: full_name (小写) → entry
            fn = str(item.get("full_name", "")).strip().lower()
            if fn:
                existing = self._fullname_index.get(fn)
                if not existing or rank_val > _rank_priority.get(
                    existing.get("ccf_rank", ""), 0
                ):
                    self._fullname_index[fn] = item

            # 索引 3: dblp_key → entry
            dblp = (item.get("dblp_key") or "").strip()
            if dblp:
                existing = self._dblp_index.get(dblp)
                if not existing or rank_val > _rank_priority.get(
                    existing.get("ccf_rank", ""), 0
                ):
                    self._dblp_index[dblp] = item

        logger.info(
            "CCF 目录索引构建完成: %d 条记录 → abbr=%d, fullname=%d, dblp=%d",
            len(self.ccf_data),
            len(self._abbr_index),
            len(self._fullname_index),
            len(self._dblp_index),
        )

    def find_ccf(self, venue_or_journal: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        基于 ref 文件倒排索引查表匹配 CCF 目录条目。

        匹配优先级（索引查表 → 结构化提取 → 受控模糊兜底）：
          1. exact full_name 精确命中
          2. abbreviation 精确命中（输入文本整体 == 缩写）
          3. 从输入文本的括号中提取缩写（如 "(ICSE-SEIP)" → "ICSE"）
          4. abbreviation 单词边界匹配（≥3 字符的缩写在去年份后的输入中以独立词出现）
          5. full_name 双向子串兜底（双方长度 ≥ 15 字符防止短串误匹配）

        Args:
            venue_or_journal: 来自 API 返回或 brief 配置的 venue/journal 名称

        Returns:
            匹配到的 CCF 目录条目字典，未匹配则为 None
        """
        if not venue_or_journal or not self.ccf_data:
            return None

        value = venue_or_journal.strip().lower()

        # ── 优先级 1: full_name 精确索引匹配 ──
        hit = self._fullname_index.get(value)
        if hit:
            return hit

        # ── 优先级 2: abbreviation 精确索引匹配（输入就是缩写本身）──
        hit = self._abbr_index.get(value)
        if hit:
            return hit

        # ── 优先级 3: 从输入文本中提取括号内的候选缩写 ──
        # 覆盖场景: "(ICSE-SEIP)", "The Web Conference (WWW)"
        paren_matches = re.findall(r"\(([A-Za-z][A-Za-z0-9-]+)\)", venue_or_journal)
        for candidate in paren_matches:
            # 尝试直接匹配括号内全文 (如 "WWW")
            hit = self._abbr_index.get(candidate.lower())
            if hit:
                return hit
            # 尝试取连字符前半段 (如 "ICSE-SEIP" → "ICSE")
            if "-" in candidate:
                prefix = candidate.split("-")[0]
                hit = self._abbr_index.get(prefix.lower())
                if hit:
                    return hit

        # ── 优先级 4: abbreviation 单词边界匹配 ──
        # 剥离年份噪声后，用 \b 正则检查缩写是否以独立词出现
        # 覆盖场景: "IEEE/ACM ICSE", "ICSE 2023", "WWW '24"
        value_no_year = re.sub(r"\b(20\d{2}|19\d{2}|'\d{2})\b", "", value).strip()
        for abbr, item in self._abbr_index.items():
            if len(abbr) >= 3:
                if re.search(
                    r"\b" + re.escape(abbr) + r"\b", value_no_year, re.IGNORECASE
                ):
                    return item

        # ── 优先级 5: full_name 双向子串兜底 ──
        # 仅当双方字符串长度都 ≥ 15 时才允许子串匹配，
        # 避免 "Networks"（6字符）这类短名误匹配 "Neural Networks ..."
        if len(value) >= 15:
            for fn, item in self._fullname_index.items():
                if len(fn) >= 15 and (fn in value or value in fn):
                    return item

        return None

    def _warn_cas_unavailable_once(self, path: Optional[str], reason: str) -> None:
        if self._cas_warning_emitted:
            return
        self._cas_warning_emitted = True
        if reason == "not_configured":
            # 公开版默认不带中科院分区数据，这是正常状态，不应刷屏告警。
            logger.info(
                "[元数据] 中科院分区未配置（可设置 %s 指向自备 journal_master.db），cas_zone 将为空",
                JOURNAL_MASTER_DB_ENV,
            )
            return
        logger.warning(
            "[元数据] 中科院分区能力不可用，来源=%s，原因=%s；可运行 spc doctor 查看修复建议",
            path,
            reason,
        )

    def _ensure_cas_loaded(self) -> None:
        if self._cas_initialized:
            return
        self._cas_initialized = True

        if self.cas_path is None:
            db_path = self.cas_db_path or configured_journal_master_db()
            if db_path is None:
                self._warn_cas_unavailable_once(None, "not_configured")
                return
            if not os.path.isfile(db_path):
                self._warn_cas_unavailable_once(db_path, "reference_data_missing")
                return
            try:
                index = _load_journal_master(db_path)
            except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
                self._warn_cas_unavailable_once(db_path, "reference_data_invalid")
                return
            if not index:
                self._warn_cas_unavailable_once(db_path, "reference_data_invalid")
                return
            self._cas_index = index
            return

        if not os.path.isfile(self.cas_path):
            self._warn_cas_unavailable_once(
                self.cas_path, "legacy_reference_data_missing"
            )
            return
        try:
            with open(self.cas_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            records = (
                raw_data.get("records", []) if isinstance(raw_data, dict) else raw_data
            )
            for rec in records:
                name = str(rec.get("journal_name", "")).strip().lower()
                if name:
                    self.cas_data[name] = rec
        except Exception:
            self._warn_cas_unavailable_once(
                self.cas_path, "legacy_reference_data_invalid"
            )

    def _find_cas_in_master(self, journal_or_venue: str) -> Optional[Dict[str, Any]]:
        normalized = _normalize_title(journal_or_venue)
        if not normalized:
            return None
        row = self._cas_index.get(normalized)
        if row is None and len(normalized) > 5:
            close = difflib.get_close_matches(
                normalized, self._cas_index.keys(), n=1, cutoff=0.85
            )
            row = self._cas_index.get(close[0]) if close else None
        if row is None:
            return None
        cas = row.get("cas") if isinstance(row.get("cas"), dict) else {}
        zone = cas.get("zone") if cas.get("zone") is not None else row.get("zone")
        try:
            zone = int(zone)
        except (TypeError, ValueError):
            return None
        if zone not in (1, 2, 3, 4):
            return None
        top = (
            cas.get("top_journal")
            if cas.get("top_journal") is not None
            else row.get("top_journal")
        )
        return {
            "journal_name": journal_or_venue,
            "zone": zone,
            "top_journal": bool(top),
            "source": "journal_master_db",
        }

    def find_cas(self, journal_or_venue: Optional[str]) -> Optional[Dict[str, Any]]:
        if not journal_or_venue:
            return None
        self._ensure_cas_loaded()
        if self._cas_index:
            return self._find_cas_in_master(journal_or_venue)
        if not self.cas_data:
            return None
        value = journal_or_venue.strip().lower()
        if value in self.cas_data:
            return self.cas_data[value]
        for name, rec in self.cas_data.items():
            if value in name or name in value:
                return rec
        return None

    def metadata_for(self, paper: PaperRecord) -> Dict[str, Any]:
        venue = paper.venue or paper.journal
        ccf_match = self.find_ccf(venue)
        cas_match = self.find_cas(paper.journal or paper.venue)
        return {
            "ccf_rank": ccf_match.get("ccf_rank") if ccf_match else None,
            "ccf_subject": ccf_match.get("subject") if ccf_match else None,
            "cas_zone": cas_match.get("zone") if cas_match else None,
            "cas_top_journal": cas_match.get("top_journal") if cas_match else None,
            "venue_match_name": (
                ccf_match.get("full_name")
                if ccf_match
                else cas_match.get("journal_name")
                if cas_match
                else None
            ),
            "venue_metadata_source": "ccf"
            if ccf_match
            else "cas"
            if cas_match
            else "not_matched",
        }


_VENUE_LOOKUP: Optional[VenueCatalogLookup] = None


def get_venue_lookup() -> VenueCatalogLookup:
    global _VENUE_LOOKUP
    if _VENUE_LOOKUP is None:
        _VENUE_LOOKUP = VenueCatalogLookup()
    return _VENUE_LOOKUP


def venue_metadata(paper: PaperRecord) -> Dict[str, Any]:
    return get_venue_lookup().metadata_for(paper)


def citation_weak_signal(paper: PaperRecord) -> float:
    if not paper.citation_count:
        return 0.0

    current_year = datetime.now().year
    paper_year = paper.year or current_year
    years_diff = max(1, current_year - paper_year)
    expected_citation_multiplier = 20.0 * years_diff
    return min(1.0, paper.citation_count / expected_citation_multiplier)
