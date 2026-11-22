"""Pure Zotero chat intent classifiers and extractors."""

from __future__ import annotations

import re
from typing import Any


def looks_like_zotero_create_collection_request(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    lowered = compact.lower()
    if any(hint in compact for hint in ("新建会话", "新对话", "新聊天")):
        return False
    create_terms = ("新建", "创建", "新增", "建一个", "建个", "create", "new")
    folder_terms = ("文件夹", "目录", "collection", "folder")
    return any(term in compact or term in lowered for term in create_terms) and any(
        term in compact or term in lowered for term in folder_terms
    )


def extract_zotero_create_collection_name(message: str) -> str:
    text = str(message or "").strip()
    patterns = [
        r"(?:叫|名为|命名为|名称为|名字叫)\s*[“\"']?([^”\"'，。；;,\n]+)[”\"']?",
        r"(?:文件夹|目录|collection|folder)\s*[:：=]\s*[“\"']?([^”\"'，。；;,\n]+)[”\"']?",
        r"(?:新建|创建|新增|建一个|建个)\s*(?:一个|1个)?\s*(?:Zotero\s*)?(?:文件夹|目录|collection|folder)\s*[“\"']([^”\"'\n]+)[”\"']",
        r"(?:新建|创建|新增|建一个|建个)\s*(?:一个|1个)?\s*(?:Zotero\s*)?(?:文件夹|目录|collection|folder)\s+([^”\"'，。；;,\n]+)",
        r"(?:create|new)\s+(?:a\s+)?(?:zotero\s+)?(?:collection|folder)\s+[“\"']?([^”\"'，。；;,\n]+)[”\"']?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = clean_zotero_collection_name(match.group(1))
            if value:
                return value
    return ""


def clean_zotero_collection_name(value: str) -> str:
    cleaned = str(value or "").strip().strip("“”\"'` ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(
        r"\s*(?:，|,)?\s*(?:先)?(?:给我)?(?:预览|确认卡|dry[- ]?run)\s*$",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    if not cleaned:
        return ""
    blocked = {"文件夹", "目录", "collection", "folder", "zotero"}
    if cleaned.casefold() in blocked:
        return ""
    return cleaned[:240]


def looks_like_unsupported_zotero_write_request(message: str) -> bool:
    """Catch Zotero/RH writes that do not yet have a side-panel apply path."""

    text = str(message or "").strip()
    if not text:
        return False
    if looks_like_zotero_import_request(text):
        return False

    compact = re.sub(r"\s+", "", text)
    lowered = compact.lower()
    write_verbs = (
        "写入",
        "同步",
        "下载",
        "附加",
        "添加",
        "加入",
        "修改",
        "更新",
        "删除",
        "替换",
        "导出",
        "apply",
        "confirm",
        "dry-run",
        "dryrun",
    )
    zotero_targets = (
        "zotero",
        "当前条目",
        "当前论文",
        "条目",
        "pdf",
        "附件",
        "attachment",
        "标签",
        "tag",
        "tags",
        "元数据",
        "metadata",
        "笔记",
        "note",
        "notes",
    )
    if not any(verb in compact or verb in lowered for verb in write_verbs):
        return False
    if not any(target in compact or target in lowered for target in zotero_targets):
        return False
    return True


def looks_like_zotero_pdf_attachment_request(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message or ""))
    lowered = compact.lower()
    pdf_terms = ("pdf", "PDF", "附件", "附加", "attachment", "attach")
    write_terms = (
        "下载",
        "附加",
        "添加",
        "加入",
        "导入",
        "同步",
        "替换",
        "写入",
        "apply",
    )
    return any(term in compact or term in lowered for term in pdf_terms) and any(
        term in compact or term in lowered for term in write_terms
    )


def looks_like_zotero_import_request(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    lowered = compact.lower()
    if looks_like_zotero_metadata_edit_request(compact, lowered):
        return False
    target_hints = (
        "当前目录",
        "这个目录",
        "该目录",
        "此目录",
        "这里",
        "collection",
        "zotero",
    )
    if not any(hint in compact or hint in lowered for hint in target_hints):
        return False
    if any(keyword in compact for keyword in ("导入", "加入", "添加", "放入", "放到")):
        return True
    if "同步" not in compact:
        return False
    return any(
        pattern in compact or pattern in lowered
        for pattern in (
            "同步到当前目录",
            "同步至当前目录",
            "同步到这个目录",
            "同步至这个目录",
            "同步到该目录",
            "同步至该目录",
            "同步到此目录",
            "同步至此目录",
            "同步到这里",
            "同步至这里",
            "同步到collection",
            "同步至collection",
            "同步到zotero",
            "同步至zotero",
        )
    )


def looks_like_zotero_metadata_edit_request(compact: str, lowered: str) -> bool:
    """Avoid treating metadata/tag editing chat as RH-to-Zotero paper imports."""

    edit_verbs = ("添加", "加入", "修改", "更新", "整理")
    metadata_targets = (
        "标签",
        "tag",
        "tags",
        "笔记",
        "note",
        "notes",
        "标注",
        "annotation",
        "annotations",
    )
    if not any(verb in compact for verb in edit_verbs):
        return False
    if not any(target in compact or target in lowered for target in metadata_targets):
        return False
    return not any(import_verb in compact for import_verb in ("导入", "放入", "放到"))


def last_zotero_path_segment(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    segments = [
        segment.strip()
        for segment in re.split(r"\s*(?:/|>|›|\\\\)\s*", text)
        if segment.strip()
    ]
    return segments[-1] if segments else text


def zotero_names_equal(left: str, right: str) -> bool:
    return (
        re.sub(r"\s+", " ", str(left or "").strip()).casefold()
        == re.sub(r"\s+", " ", str(right or "").strip()).casefold()
    )


def looks_like_zotero_seed_search_request(message: str) -> bool:
    text = str(message or "").strip()
    lowered = text.lower()
    if not text:
        return False
    paper_terms = (
        "论文",
        "文章",
        "文献",
        "paper",
        "papers",
        "literature",
        "reference",
    )
    search_terms = (
        "找",
        "寻找",
        "推荐",
        "搜索",
        "检索",
        "补",
        "discover",
        "recommend",
        "search",
        "find",
    )
    seed_terms = (
        "最开始",
        "开始",
        "初始",
        "初始化",
        "起步",
        "入门",
        "种子",
        "第一批",
        "新的研究方向",
        "新研究方向",
        "seed",
        "starter",
        "空目录",
        "空文件夹",
        "新目录",
        "新文件夹",
    )
    return (
        any(term in lowered for term in paper_terms)
        and any(term in lowered for term in search_terms)
        and any(term in lowered for term in seed_terms)
    )


def zotero_seed_request_flags(message: str) -> dict[str, bool]:
    text = str(message or "").strip().lower()
    deep_read_terms = ("精读", "深读", "deep read", "deep-read", "deepread")
    pdf_terms = ("pdf", "附件", "全文", "原文")
    annotation_terms = (
        "高亮",
        "批注",
        "标注",
        "annotation",
        "annotations",
        "annotate",
        "highlight",
        "highlights",
    )
    requests_annotations = any(term in text for term in annotation_terms)
    return {
        "request_deep_read": any(term in text for term in deep_read_terms),
        "request_pdf_attachment": any(term in text for term in pdf_terms)
        or requests_annotations,
        "request_pdf_annotations": requests_annotations,
    }


def zotero_explicit_seed_topic_name(message: str) -> str:
    text = str(message or "").strip()
    patterns = [
        r"(?:新的研究方向|新研究方向|研究方向)\s*[“\"']?([^”\"'，。；;,]+)[”\"']?",
        r"(?:topic|主题)\s*[:：=]\s*([^，。；;,]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = match.group(1).strip()
            if value and not is_zotero_seed_placeholder_phrase(value):
                return value[:240]
    return ""


def zotero_seed_search_query(body: Any, *, topic_name: str = "") -> str:
    message = str(body.message or "").strip()
    explicit_patterns = [
        r"(?:query|关键词|检索词|搜索词)\s*[:：=]\s*(.+)$",
        r"(?:新的研究方向|新研究方向|研究方向)\s*[“\"']?([^”\"'，。；;,]+)[”\"']?",
        r"(?:围绕|关于)\s*[“\"']?([^”\"'，。；;]+)[”\"']?\s*(?:找|寻找|推荐|搜索|检索)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, message, flags=re.I)
        if match:
            value = match.group(1).strip()
            if value and not is_zotero_seed_placeholder_phrase(value):
                return value[:240]

    topic = str(topic_name or "").strip()
    if topic:
        return topic[:240]

    for candidate in (
        last_zotero_path_segment(body.item.current_directory_path),
        body.item.current_directory_name,
        body.item.title,
    ):
        value = str(candidate or "").strip()
        if value:
            return value[:240]
    return message[:240] or "research seed papers"


def is_zotero_seed_placeholder_phrase(value: str) -> bool:
    """Return true for prompt scaffolding that should defer to folder context."""

    compact = re.sub(r"\s+", "", str(value or "").strip()).casefold()
    if not compact:
        return True
    context_placeholders = (
        "当前文件夹",
        "当前目录",
        "当前collection",
        "当前folder",
        "这个文件夹",
        "这个目录",
        "该文件夹",
        "该目录",
        "此文件夹",
        "此目录",
        "文件夹的研究方向",
        "目录的研究方向",
    )
    if any(term in compact for term in context_placeholders):
        return True

    action_starts = ("推荐", "找", "寻找", "搜索", "检索", "先给", "给我")
    paper_terms = (
        "篇",
        "论文",
        "文献",
        "文章",
        "起步",
        "候选",
        "种子",
        "paper",
        "papers",
        "seed",
        "starter",
    )
    return compact.startswith(action_starts) and any(
        term in compact for term in paper_terms
    )


def looks_like_zotero_directory_capability_question(
    body: Any, matched: dict[str, Any]
) -> bool:
    from research_harness_mcp.zotero_chat_match import zotero_context_payload

    context = zotero_context_payload(body, matched)
    if context.get("kind") not in {"collection", "library"}:
        return False
    compact = re.sub(r"\s+", "", str(body.message or ""))
    return any(
        hint in compact
        for hint in (
            "可以怎么推进",
            "怎么推进",
            "能做什么",
            "有什么功能",
            "有哪些功能",
            "目录可以",
            "文库可以",
        )
    )


def extract_explicit_topic_id(message: str) -> int | None:
    text = str(message or "")
    patterns = [
        r"\btopic[_\s-]?id[:：=\s]*(\d+)\b",
        r"\btopic[:：=\s]+(\d+)\b",
        r"主题[:：=\s]+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return int(match.group(1))
    return None


def message_targets_current_paper_only(message: str) -> bool:
    text = str(message or "")
    return any(
        hint in text
        for hint in ("这篇", "当前论文", "当前文章", "这篇论文", "这篇文章", "本文")
    )


def message_targets_deep_read_only(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        hint in lowered for hint in ("精读", "deepread", "deep read", "deep-read")
    )


def extract_zotero_import_count(message: str) -> int | None:
    text = str(message or "")
    digit_match = re.search(r"(\d{1,3})\s*篇", text)
    if digit_match:
        return max(1, int(digit_match.group(1)))
    chinese_match = re.search(r"([一二三四五六七八九十两]{1,4})\s*篇", text)
    if chinese_match:
        return simple_chinese_number(chinese_match.group(1))
    return None


def simple_chinese_number(text: str) -> int | None:
    text = str(text or "").strip()
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if not text:
        return None
    if text == "十":
        return 10
    if text in digits:
        return digits[text]
    if len(text) == 2 and text.startswith("十") and text[1] in digits:
        return 10 + digits[text[1]]
    if len(text) == 2 and text.endswith("十") and text[0] in digits:
        return digits[text[0]] * 10
    if len(text) == 3 and text[1] == "十" and text[0] in digits and text[2] in digits:
        return digits[text[0]] * 10 + digits[text[2]]
    return None
