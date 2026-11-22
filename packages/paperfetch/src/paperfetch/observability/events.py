"""SPC 唯一结构化日志事件、脱敏、终端输出与 JSONL 审计实现。"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rich.console import Console
from rich.text import Text

from paperfetch.runtime_mode import LogMode, resolve_log_mode

EVENT_OUTCOMES = frozenset(
    {
        "started",
        "success",
        "miss",
        "skipped",
        "degraded",
        "partial",
        "blocked",
        "failed",
    }
)

_SENSITIVE_KEYS = re.compile(
    r"^(?:.*api[_-]?key|.*(?:access|refresh|auth|session|saml|oauth)[_-]?token|token|secret|password|passwd|cookie|cookies|authorization|saml|oauth|.*captcha.*|html|raw_html|body_excerpt|raw_response)$",
    re.IGNORECASE,
)
_SIGNED_QUERY_KEYS = re.compile(
    r"(?:x-amz-|signature|sig$|token|key|auth|credential|policy|expires|session)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]{1,64})@([\w.-]+\.[A-Za-z]{2,})(?![\w.-])")
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_LONG_SECRET = re.compile(r"(?<![A-Za-z0-9])(?:sk-|s2k-|eyJ)[A-Za-z0-9._-]{12,}")
_MESSAGE_FIELD = re.compile(
    r"(?P<separator>[，,]\s*|\s+\|\s+)"
    r"(?P<key>DOI|出版社|出版商|route|路由|来源|错误|耗时|transport|代理)"
    r"[=:：](?P<value>[^，,|]+)",
    re.IGNORECASE,
)


def _mask_email(match: re.Match[str]) -> str:
    local, domain = match.group(1), match.group(2)
    return f"{local[:1]}***@{domain}"


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        query.append((key, "<redacted>" if _SIGNED_QUERY_KEYS.search(key) else item))
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (parsed.scheme == "https" and parsed.port == 443) or (
        parsed.scheme == "http" and parsed.port == 80
    )
    netloc = host if parsed.port is None or default_port else f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), ""))


def redact_sensitive(value: Any, key: Optional[str] = None) -> Any:
    """递归清理凭证、签名参数、账号、验证码与原始页面内容。"""
    if key and _SENSITIVE_KEYS.search(str(key)):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): redact_sensitive(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if not isinstance(value, str):
        return value
    result = _BEARER.sub("<redacted-authorization>", value)
    result = _LONG_SECRET.sub("<redacted-secret>", result)
    result = _EMAIL.sub(_mask_email, result)
    if "http://" in result or "https://" in result:
        parts = re.split(r"(https?://[^\s,，]+)", result)
        result = "".join(
            _redact_url(part) if part.startswith(("http://", "https://")) else part
            for part in parts
        )
    return result


def canonical_publisher_key(value: Optional[str], doi: Optional[str] = None) -> str:
    """将期刊、平台和出版社别名收敛为稳定的审计键。"""
    raw = (value or "").strip().lower()
    doi_value = (doi or "").strip().lower()
    if doi_value.startswith("10.1016/") or any(
        marker in raw
        for marker in ("elsevier", "sciencedirect", "science direct", "cities")
    ):
        return "elsevier"
    aliases = {
        "springer nature": "springer_nature",
        "springerlink": "springer_nature",
        "taylor & francis": "taylor_francis",
        "taylor and francis": "taylor_francis",
        "oxford university press": "oxford_university_press",
    }
    return aliases.get(raw, raw.replace(" ", "_") or "unknown")


@dataclass(frozen=True)
class SPCLogEvent:
    """SPC 跨模块统一事件契约。"""

    event_code: str
    domain: str
    phase: str
    action: str
    outcome: str
    terminal: bool
    level: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sequence: Optional[int] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    task_id: Optional[str] = None
    paper_id: Optional[str] = None
    doi: Optional[str] = None
    publisher_key: Optional[str] = None
    route: Optional[str] = None
    source: Optional[str] = None
    elapsed_ms: Optional[int] = None
    error_class: Optional[str] = None
    message: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if self.outcome not in EVENT_OUTCOMES:
            raise ValueError(f"未知事件结果: {self.outcome}")
        if self.terminal and self.outcome not in {
            "success",
            "partial",
            "failed",
            "blocked",
            "skipped",
        }:
            raise ValueError(
                "最终事件只能是 success、partial、failed、blocked 或 skipped"
            )
        if self.outcome == "failed" and not self.error_class:
            raise ValueError("failed 事件必须提供 error_class")
        if self.elapsed_ms is not None and self.elapsed_ms < 0:
            raise ValueError("elapsed_ms 不能为负数")

    def to_dict(self) -> dict[str, Any]:
        return redact_sensitive(asdict(self))

    def persisted_dict(self, *, details_ref: Optional[str] = None) -> dict[str, Any]:
        """投影成精简的 spc.event.v1；人类文案和诊断只进入 audit。"""

        outcomes = {
            "started": "started",
            "success": "succeeded",
            "miss": "skipped",
            "skipped": "skipped",
            "degraded": "degraded",
            "partial": "partial",
            "blocked": "blocked",
            "failed": "failed",
        }
        entity = None
        if self.paper_id or self.doi:
            entity = {"type": "paper", "id": self.paper_id or self.doi}
        elif self.task_id:
            entity = {"type": "task", "id": self.task_id}
        error = None
        if self.error_class:
            error = {
                "code": self.error_class,
                "error_class": self.error_class,
                "stage": self.phase,
                "retryable": False,
                "message": self.message or self.action,
                "remediation": None,
                "audit_ref": details_ref,
            }
        return redact_sensitive(
            {
                "schema_version": "spc.event.v1",
                "event_id": self.event_id,
                "run_id": self.run_id,
                "job_id": self.job_id,
                "sequence": self.sequence,
                "timestamp": self.timestamp,
                "domain": self.domain,
                "entity": entity,
                "stage": self.phase,
                "action": self.event_code if self.action == "message" else self.action,
                "outcome": outcomes[self.outcome],
                "terminal": self.terminal,
                "elapsed_ms": self.elapsed_ms,
                "source": self.source,
                "route": self.route,
                "progress": None,
                "error": error,
                "details_ref": details_ref,
            }
        )


_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "spc_event_context", default={}
)
_output_capture: contextvars.ContextVar[Optional[Callable[[Any], None]]] = (
    contextvars.ContextVar("spc_output_capture", default=None)
)
_business_status: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "spc_business_status", default=None
)
_public_result_v2: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "spc_public_result_v2", default=False
)
_events: list[SPCLogEvent] = []
_terminal_keys: set[tuple[Any, ...]] = set()
_lock = threading.RLock()
_stderr_enabled = True
_minimum_level = "INFO"
_text_log_path: Optional[Path] = None
_event_log_path: Optional[Path] = None
_audit_dir: Optional[Path] = None
_color_mode: Optional[bool] = None
_log_mode: LogMode = "development"
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_LEVEL_STYLES = {
    "DEBUG": "dim",
    "INFO": "bold #0087ff",
    "WARNING": "bold #ffaf00",
    "ERROR": "bold #ff3030",
    "CRITICAL": "bold white on red",
}
_OUTCOME_STYLES = {
    "started": "cyan",
    "success": "bold green",
    "miss": "dim",
    "skipped": "dim",
    "degraded": "bold yellow",
    "partial": "bold yellow",
    "blocked": "bold dark_orange",
    "failed": "bold red",
}
_DOMAIN_LABELS = {
    "cli": "命令行",
    "download": "下载",
    "downloaders": "下载",
    "sources": "元数据",
    "tasks": "任务",
    "core": "核心流程",
    "crawler": "召回",
    "api": "服务",
    "test": "测试",
}
_PHASE_LABELS = {
    "discovery": "发现",
    "transfer": "传输",
    "verification": "验证",
    "publisher_authorization": "授权",
    "publisher_download": "PDF",
    "final": "最终结果",
    "command": "命令",
}
_OUTCOME_LABELS = {
    "started": "START",
    "success": "OK",
    "miss": "MISS",
    "skipped": "SKIPPED",
    "degraded": "DEGRADED",
    "partial": "PARTIAL",
    "blocked": "BLOCKED",
    "failed": "FAILED",
}


def reset_event_state(run_id: Optional[str] = None) -> str:
    """清空进程内事件并建立新的运行上下文。"""
    resolved = run_id or uuid.uuid4().hex
    with _lock:
        _events.clear()
        _terminal_keys.clear()
    context = {"run_id": resolved}
    if os.getenv("SPC_JOB_ID"):
        context["job_id"] = os.environ["SPC_JOB_ID"]
    _context.set(context)
    _business_status.set(None)
    return resolved


def current_run_id() -> str:
    """返回当前命令已绑定的 run_id，领域结果必须复用它。"""

    return str(_context.get().get("run_id") or "")


def current_business_status() -> str | None:
    """返回本轮唯一 1.0 业务结果状态，供 CLI 终止事件保持一致。"""

    return _business_status.get()


@contextlib.contextmanager
def bind_event_context(**values: Any) -> Iterator[None]:
    """在异步安全的 ContextVar 中绑定运行、任务或论文上下文。"""
    merged = {
        **_context.get(),
        **{key: value for key, value in values.items() if value is not None},
    }
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


@contextlib.contextmanager
def bind_output_capture(callback: Callable[[Any], None]) -> Iterator[None]:
    """让 detached worker 直接捕获业务对象，不解析 stdout 文本。"""

    token = _output_capture.set(callback)
    try:
        yield
    finally:
        _output_capture.reset(token)


@contextlib.contextmanager
def public_result_projection(enabled: bool = True) -> Iterator[None]:
    """将 v2 公共投影限定在当前 CLI 调用，避免污染同进程的库调用。"""
    token = _public_result_v2.set(bool(enabled))
    try:
        yield
    finally:
        _public_result_v2.reset(token)


def configure_observability(
    *,
    level: str = "INFO",
    log_file: Optional[str] = None,
    event_file: Optional[str] = None,
    stderr: bool = True,
    color: Optional[bool] = None,
    mode: Optional[str] = None,
) -> None:
    """配置唯一事件输出；生产模式收敛终端噪声但保留完整审计文件。"""
    global \
        _minimum_level, \
        _text_log_path, \
        _event_log_path, \
        _audit_dir, \
        _stderr_enabled, \
        _color_mode, \
        _log_mode
    _log_mode = resolve_log_mode(mode)
    requested_level = str(level or "INFO").upper()
    _minimum_level = (
        "WARNING"
        if _log_mode == "production"
        and _LEVELS.get(requested_level, 20) < _LEVELS["WARNING"]
        else requested_level
    )
    _stderr_enabled = stderr
    _text_log_path = Path(log_file).resolve() if log_file else None
    _event_log_path = Path(event_file).resolve() if event_file else None
    _audit_dir = _event_log_path.parent / "audit" if _event_log_path else None
    _color_mode = color
    for path in (_text_log_path, _event_log_path):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(handlers=[logging.NullHandler()], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def observability_status() -> dict[str, Any]:
    """返回不含敏感值的当前日志模式。"""

    return {
        "mode": _log_mode,
        "stderr_minimum_level": _minimum_level,
        "text_log_enabled": _text_log_path is not None,
        "event_log_enabled": _event_log_path is not None,
    }


def _terminal_key(event: SPCLogEvent) -> tuple[Any, ...]:
    entity = (
        ("paper", event.paper_id or event.doi)
        if event.paper_id or event.doi
        else ("task", event.task_id or event.action)
    )
    return event.run_id, event.domain, event.task_id, entity


def _short_time(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return timestamp[:8]


def _human_message(event: SPCLogEvent) -> str:
    message = event.message or event.action
    if message.startswith("["):
        return message
    domain = event.domain.split(".", 1)[0]
    if domain == "download" and event.phase == "final":
        return f"[论文下载] {message}"
    if domain == "cli" and event.phase == "command":
        return f"[命令] {message}"
    label = _DOMAIN_LABELS.get(domain, domain or "SPC")
    phase = _PHASE_LABELS.get(event.phase, event.phase)
    prefix = f"[{label}]"
    if phase and phase not in {"runtime", "message"}:
        prefix += f"[{phase}]"
    return f"{prefix} {message}"


def _message_expresses_outcome(event: SPCLogEvent) -> bool:
    markers = {
        "success": ("成功", "完成", "就绪"),
        "miss": ("未命中", "未捕获", "未找到", "无结果"),
        "skipped": ("跳过", "取消"),
        "degraded": ("降级", "继续后续", "未成功", "无订阅全文权限"),
        "blocked": ("阻断", "人工挑战", "停止该路由"),
        "failed": ("失败", "未完成", "异常终止"),
    }
    english_marker = _OUTCOME_LABELS.get(event.outcome, "")
    return english_marker in event.message or any(
        marker in event.message for marker in markers.get(event.outcome, ())
    )


def _human_details(event: SPCLogEvent) -> list[tuple[str, str, str]]:
    identity = event.doi or event.paper_id
    details: list[tuple[str, str, str]] = []
    if (
        event.terminal
        or event.outcome in {"miss", "skipped", "degraded", "blocked", "failed"}
    ) and not _message_expresses_outcome(event):
        details.append(
            (
                "状态",
                _OUTCOME_LABELS[event.outcome],
                _OUTCOME_STYLES.get(event.outcome, "bold"),
            )
        )
    if identity:
        details.append(("DOI", identity, "bold #00afff"))
    if event.publisher_key:
        details.append(("出版社", event.publisher_key, "bold #d75fff"))
    if event.route:
        details.append(("route", event.route, "bold #5fd700"))
    if event.source:
        details.append(("来源", event.source, "cyan"))
    if event.error_class:
        details.append(("错误", event.error_class, "bold red"))
    if event.elapsed_ms is not None:
        details.append(("耗时", f"{event.elapsed_ms}ms", "#ffaf00"))
    return details


def _render_text(event: SPCLogEvent) -> str:
    details = " | ".join(
        f"{key}={value}" for key, value, _style in _human_details(event)
    )
    suffix = f" | {details}" if details else ""
    return f"[{_short_time(event.timestamp)}] {event.level:<8} {_human_message(event)}{suffix}"


def _terminal_supports_color() -> bool:
    if _color_mode is not None:
        return _color_mode
    if os.getenv("NO_COLOR") is not None or (os.getenv("TERM") or "").lower() == "dumb":
        return False
    return bool(getattr(sys.stderr, "isatty", lambda: False)())


def _render_terminal(event: SPCLogEvent) -> Text:
    """生成仅供交互终端使用的 Rich 文本，不改变持久化日志。"""
    text = Text()
    text.append(f"[{_short_time(event.timestamp)}]", style="dim")
    text.append(" ")
    text.append(f"{event.level:<8}", style=_LEVEL_STYLES.get(event.level, "bold"))
    text.append(" ")
    message = Text(_human_message(event))
    for marker, style in (
        ("OK", _OUTCOME_STYLES["success"]),
        ("WARN", _OUTCOME_STYLES["degraded"]),
        ("DEGRADED", _OUTCOME_STYLES["degraded"]),
        ("FAILED", _OUTCOME_STYLES["failed"]),
        ("BLOCKED", _OUTCOME_STYLES["blocked"]),
        ("MISS", _OUTCOME_STYLES["miss"]),
        ("SKIPPED", _OUTCOME_STYLES["skipped"]),
    ):
        message.highlight_regex(rf"(?<![A-Za-z]){marker}(?![A-Za-z])", style)
    text.append_text(message)
    for key, value, style in _human_details(event):
        text.append(" | ", style="dim")
        text.append(f"{key}=", style="dim")
        text.append(value, style=style)
    return text


def _extract_message_fields(message: str) -> tuple[str, dict[str, Any]]:
    """从旧日志文案提取核心审计字段，并移除终端中的重复键值。"""
    extracted: dict[str, Any] = {}

    def replace_field(match: re.Match[str]) -> str:
        key = match.group("key").lower()
        value = match.group("value").strip()
        if key == "doi":
            extracted["doi"] = value
        elif key in {"出版社", "出版商"}:
            extracted["publisher_key"] = value
        elif key in {"route", "路由"}:
            extracted["route"] = value
        elif key == "来源":
            extracted["source"] = value
        elif key == "错误":
            extracted["error_class"] = value
        elif key == "耗时":
            elapsed = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s)?", value, re.IGNORECASE)
            if elapsed:
                amount = float(elapsed.group(1))
                extracted["elapsed_ms"] = int(
                    round(
                        amount
                        * (1000 if (elapsed.group(2) or "ms").lower() == "s" else 1)
                    )
                )
        elif key == "transport":
            extracted["transport"] = value
        elif key == "代理":
            extracted["proxy_mode"] = value
        return ""

    compact = _MESSAGE_FIELD.sub(replace_field, message)
    compact = re.sub(r"[，,]\s*$", "", compact).strip()
    return compact, extracted


def emit_event(event: SPCLogEvent | None = None, **values: Any) -> SPCLogEvent:
    """提交事件到文本日志、JSONL 和内存审计流。"""
    context = _context.get()
    if event is None:
        merged = {**context, **values}
        event = SPCLogEvent(**merged)
    elif context:
        updates = {
            key: value
            for key, value in context.items()
            if getattr(event, key, None) is None
        }
        if updates:
            event = replace(event, **updates)
    with _lock:
        sanitized = SPCLogEvent(**event.to_dict())
        if sanitized.sequence is None:
            sanitized = replace(sanitized, sequence=len(_events) + 1)
        if sanitized.terminal:
            key = _terminal_key(sanitized)
            if key in _terminal_keys:
                raise RuntimeError(f"实体存在重复最终事件: {key}")
            _terminal_keys.add(key)
        _events.append(sanitized)
        text_line = _render_text(sanitized)
        details_ref = None
        # 行内注释：尝试写入 audit 详情文件；若发生权限不足或 I/O 错误则优雅降级，不阻断主流程
        if _audit_dir is not None and (
            sanitized.diagnostics
            or sanitized.outcome in {"degraded", "partial", "blocked", "failed"}
        ):
            try:
                _audit_dir.mkdir(parents=True, exist_ok=True)
                detail_path = _audit_dir / f"event-{sanitized.sequence:06d}.json"
                detail_payload = redact_sensitive(
                    {
                        "schema_version": "spc.event-detail.v1",
                        "event_id": sanitized.event_id,
                        "message": sanitized.message,
                        "doi": sanitized.doi,
                        "paper_id": sanitized.paper_id,
                        "publisher": sanitized.publisher_key,
                        "diagnostics": sanitized.diagnostics,
                    }
                )
                temporary = detail_path.with_name(
                    f".{detail_path.name}.{uuid.uuid4().hex}.tmp"
                )
                temporary.write_text(
                    json.dumps(detail_payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary, detail_path)
                details_ref = f"audit/{detail_path.name}"
            except OSError as exc:
                sys.stderr.write(f"[警告] 无法写入审计详情文件：{exc}\n")
                sys.stderr.flush()

        json_line = json.dumps(
            sanitized.persisted_dict(details_ref=details_ref), ensure_ascii=False
        )
        if _stderr_enabled and _LEVELS.get(sanitized.level, 20) >= _LEVELS.get(
            _minimum_level, 20
        ):
            if _terminal_supports_color():
                Console(
                    file=sys.stderr, stderr=True, force_terminal=True, highlight=False
                ).print(_render_terminal(sanitized), soft_wrap=True)
            else:
                sys.stderr.write(text_line + "\n")
                sys.stderr.flush()

        # 行内注释：尝试向文本日志与事件日志追加写入；若无权限则向 stderr 报告，保持命令业务执行不崩溃
        if _text_log_path:
            try:
                with _text_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(text_line + "\n")
            except OSError as exc:
                sys.stderr.write(f"[警告] 无法写入文本日志 ({_text_log_path})：{exc}\n")
                sys.stderr.flush()

        if _event_log_path:
            try:
                with _event_log_path.open(
                    "a", encoding="utf-8", newline="\n"
                ) as handle:
                    handle.write(json_line + "\n")
            except OSError as exc:
                sys.stderr.write(
                    f"[警告] 无法写入事件日志 ({_event_log_path})：{exc}\n"
                )
                sys.stderr.flush()
    return sanitized


def events_snapshot(**filters: Any) -> list[SPCLogEvent]:
    """返回符合上下文字段的事件快照。"""
    with _lock:
        return [
            event
            for event in _events
            if all(getattr(event, key, None) == value for key, value in filters.items())
        ]


def write_output(value: Any = "", *, pretty: bool = False) -> None:
    """向 stdout 写业务输出；日志不得调用本函数。"""
    capture = _output_capture.get()
    if capture is not None:
        capture(redact_sensitive(value))
    if _public_result_v2.get() and isinstance(value, Mapping):
        from paperfetch.core.public_result import to_public_result

        value = to_public_result(value)
    if isinstance(value, Mapping) and (
        value.get("schema_version") == "spc.command-result.v1"
        or value.get("schema") == "spc.result.v2"
    ):
        _business_status.set(str(value.get("status") or "") or None)
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, ensure_ascii=False, indent=2 if pretty else None)
    sys.stdout.write(payload + ("" if payload.endswith("\n") else "\n"))
    sys.stdout.flush()


def _infer_outcome(level: str, message: str) -> str:
    outcome_message = re.sub(r"(?:失败|异常)数\s*[=:：]\s*0\b", "", message)
    if any(word in outcome_message for word in ("跳过", "取消")):
        return "skipped"
    if any(word in outcome_message for word in ("未命中", "未找到", "为空", "无结果")):
        return "miss"
    if any(word in outcome_message for word in ("挑战", "验证码", "阻断")):
        return "blocked"
    if any(word in outcome_message for word in ("启动", "开始", "正在", "调用")):
        return "started"
    if level in {"ERROR", "CRITICAL"}:
        return "failed"
    if level == "WARNING" or any(
        word in outcome_message for word in ("失败", "异常", "降级")
    ):
        return "degraded"
    return "success"


class SPCEventLogger:
    """业务模块使用的结构化事件记录器。"""

    def __init__(self, domain: str):
        self.domain = domain.removeprefix("paperfetch.")

    def event(
        self,
        event_code: str,
        *,
        phase: str,
        action: str,
        outcome: str,
        terminal: bool = False,
        level: str = "INFO",
        **values: Any,
    ) -> SPCLogEvent:
        return emit_event(
            event_code=event_code,
            domain=self.domain,
            phase=phase,
            action=action,
            outcome=outcome,
            terminal=terminal,
            level=level,
            **values,
        )

    def _message(
        self,
        level: str,
        message: str,
        *args: Any,
        exc_info: bool = False,
        **kwargs: Any,
    ) -> SPCLogEvent:
        rendered = message % args if args else str(message)
        outcome = _infer_outcome(level, rendered)
        if outcome == "failed" and level in {"DEBUG", "INFO"}:
            level = "WARNING"
        rendered, extracted = _extract_message_fields(rendered)
        error_class = kwargs.pop("error_class", None) or extracted.get("error_class")
        if outcome == "failed" and not error_class:
            match = re.search(r"错误[=:：]\s*([A-Za-z0-9_.-]+)", rendered)
            error_class = match.group(1) if match else None
        if outcome == "failed" and not error_class:
            error_class = "unclassified_error"
        diagnostics = dict(kwargs.pop("diagnostics", {}) or {})
        for key in ("transport", "proxy_mode"):
            if extracted.get(key) is not None:
                diagnostics[key] = extracted[key]
        if exc_info:
            diagnostics["exception_captured"] = True
        doi = kwargs.pop("doi", None) or extracted.get("doi")
        raw_publisher = (
            kwargs.pop("publisher_key", None)
            or kwargs.pop("publisher", None)
            or extracted.get("publisher_key")
        )
        return self.event(
            f"{self.domain}.message",
            phase=kwargs.pop("phase", "runtime"),
            action=kwargs.pop("action", "message"),
            outcome=outcome,
            terminal=False,
            level=level,
            doi=doi,
            publisher_key=canonical_publisher_key(raw_publisher, doi)
            if raw_publisher or doi
            else None,
            route=kwargs.pop("route", None) or extracted.get("route"),
            source=kwargs.pop("source", None) or extracted.get("source"),
            elapsed_ms=kwargs.pop("elapsed_ms", None)
            if "elapsed_ms" in kwargs
            else extracted.get("elapsed_ms"),
            error_class=error_class,
            message=rendered,
            diagnostics={**diagnostics, **kwargs},
        )

    def debug(self, message: str, *args: Any, **kwargs: Any) -> SPCLogEvent:
        return self._message("DEBUG", message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> SPCLogEvent:
        return self._message("INFO", message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> SPCLogEvent:
        return self._message("WARNING", message, *args, **kwargs)

    warn = warning

    def error(self, message: str, *args: Any, **kwargs: Any) -> SPCLogEvent:
        return self._message("ERROR", message, *args, **kwargs)

    def critical(self, message: str, *args: Any, **kwargs: Any) -> SPCLogEvent:
        return self._message("CRITICAL", message, *args, **kwargs)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> SPCLogEvent:
        return self._message("ERROR", message, *args, exc_info=True, **kwargs)


def get_event_logger(domain: str) -> SPCEventLogger:
    """返回唯一业务事件记录器。"""
    return SPCEventLogger(domain)
