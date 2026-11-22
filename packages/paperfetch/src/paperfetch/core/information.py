"""SPC 信息分层：内部诊断、论文事实与 CLI 公共终局。

三层不得混写。

1. `durable`（`spc.paper-record.v1` / `papers.jsonl`）
   可重开的论文事实。PDF 只记成功路由 `fulltext.pdf.route`，不记逐次尝试、
   URL、浏览器或页面状态。

2. `public`（`spc.command-result.v1`）
   CLI stdout 是唯一公共结果。Skill 只选择命令，不发明字段、
   不维护会话。   下载类命令必须给出 `items[].data.download`：
   成功只有 `route` / `access` / `identity_verified`。
   失败看 `error.code` / `error.message` / `error.stage` / `error.next`。
   hops、页面快照和浏览器细节属于 audit，不得进入默认 stdout。
   无绑定物理解析给出 `items[].data.parse`：
   `status` / `identity_bound=false` / `paper_record_written=false`。
   解析成功不是论文全文事实，不得写入 `papers.jsonl`。

3. `timeline`（`spc.event.v1`）
   作业进度。可含 `route`，但不是业务终局；禁止用事件代替 command-result。

4. `audit`（`audit_ref`）
   脱敏后的逐次尝试、发现事件、页面/浏览器细节。人排障用。

5. `operator`（doctor）
   只回答配置与运行面：`verdict` / `checks[]` / `blockers[]`。
   不是论文下载终局，也不等于订阅 PDF 可用。

词汇：对外只用 `route`。内部下载器里的 `source` / `pdf_source` /
`successful_route` 在跨出下载器边界时必须收敛为 `route`。
事件落盘 outcome 以 `succeeded|failed|skipped|blocked|partial|started|degraded`
为准；内部 logger 的 `success` 只在投影时映射。
"""

from __future__ import annotations

import html
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

LAYER_DURABLE = "durable"
LAYER_PUBLIC = "public"
LAYER_TIMELINE = "timeline"
LAYER_AUDIT = "audit"
LAYER_OPERATOR = "operator"

PUBLIC_ROUTE_OUTCOMES = frozenset({"succeeded", "failed", "skipped"})

PUBLIC_EVENT_OUTCOMES = {
    "started": "started",
    "success": "succeeded",
    "miss": "skipped",
    "skipped": "skipped",
    "degraded": "degraded",
    "partial": "partial",
    "blocked": "blocked",
    "failed": "failed",
}


def unescape_public_text(value: str | None) -> str | None:
    """去掉元数据里未解码的 HTML 实体，再压缩空白。"""

    if value is None:
        return None
    normalized = " ".join(html.unescape(value).split())
    return normalized or None


def identity_method_from_status(identity_status: str | None) -> str | None:
    raw = str(identity_status or "").strip()
    if raw.startswith("verified_"):
        return raw.removeprefix("verified_") or None
    return None


def compact_route_attempts(attempts: Iterable[Any] | None) -> list[dict[str, Any]]:
    """把内部 `download_attempts` 收成公共 `attempted`，不含 URL/正文。"""

    compacted: list[dict[str, Any]] = []
    for item in attempts or ():
        if not isinstance(item, Mapping):
            continue
        route = str(item.get("route") or "").strip()
        if not route:
            continue
        if item.get("skipped") or item.get("cache_miss"):
            outcome = "skipped"
        elif item.get("error_class") or item.get("error"):
            outcome = "failed"
        else:
            outcome = "succeeded"
        compacted.append(
            {
                "route": route,
                "outcome": outcome,
                "error_class": item.get("error_class"),
            }
        )
    return compacted


def ensure_successful_attempt(
    attempted: list[dict[str, Any]],
    route: str | None,
) -> list[dict[str, Any]]:
    if not route:
        return list(attempted)
    if any(
        item.get("route") == route and item.get("outcome") == "succeeded"
        for item in attempted
    ):
        return list(attempted)
    return [*attempted, {"route": route, "outcome": "succeeded", "error_class": None}]


def public_download_fact(
    *,
    status: str,
    route: str | None = None,
    identity_verified: bool = False,
    identity_method: str | None = None,
    attempted: list[dict[str, Any]] | None = None,
    proof: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """内部下载事实；CLI 2.0 在最终边界投影为 route/access/identity_verified。"""

    payload: dict[str, Any] = {
        "status": status,
        "route": route,
        "identity_verified": bool(identity_verified),
        "attempted": ensure_successful_attempt(
            list(attempted or []), route if status == "available" else None
        ),
    }
    if identity_method:
        payload["identity_method"] = identity_method
    if proof:
        payload["proof"] = proof
    _ = diagnostics
    return payload


def public_parse_fact(
    *,
    status: str,
    identity_bound: bool = False,
    paper_record_written: bool = False,
    input_path: str | None = None,
    input_sha256: str | None = None,
    input_size_bytes: int | None = None,
    producer: str = "mineru",
) -> dict[str, Any]:
    """内部物理解析事实。默认不绑定论文身份，也不写 papers.jsonl。"""

    payload: dict[str, Any] = {
        "status": status,
        "identity_bound": bool(identity_bound),
        "paper_record_written": bool(paper_record_written),
        "producer": producer,
    }
    if input_path:
        payload["input_path"] = input_path
    if input_sha256:
        payload["input_sha256"] = input_sha256
    if input_size_bytes is not None:
        payload["input_size_bytes"] = input_size_bytes
    return payload


def public_fulltext_fact(
    *,
    pdf_status: str,
    pdf_identity_verified: bool,
    parse_status: str,
    pdf_identity_method: str | None = None,
    pdf_route: str | None = None,
) -> dict[str, Any]:
    """论文记录上的全文终局投影；`pdf_route` 来自 durable，不是本轮 attempted。"""

    payload: dict[str, Any] = {
        "pdf_status": pdf_status,
        "pdf_identity_verified": bool(pdf_identity_verified),
        "pdf_route": pdf_route,
        "parse_status": parse_status,
    }
    if pdf_identity_method:
        payload["pdf_identity_method"] = pdf_identity_method
    return payload


def normalize_audit_ref(
    path: str | Path | None, root: str | Path | None = None
) -> str | None:
    """审计引用优先写成相对根目录的 POSIX 路径。"""

    if path is None or str(path).strip() == "":
        return None
    raw = Path(str(path))
    if root is None:
        return raw.as_posix()
    try:
        return PurePosixPath(raw.resolve().relative_to(Path(root).resolve())).as_posix()
    except ValueError:
        return (
            raw.resolve().as_posix()
            if raw.exists() or raw.is_absolute()
            else raw.as_posix()
        )
