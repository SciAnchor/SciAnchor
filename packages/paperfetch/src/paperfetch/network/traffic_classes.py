# -*- coding: utf-8 -*-
"""SPC 出站流量分类契约的加载与按类别真实出口探测。

`doctor` 与 watchdog 此前只探测代理端口是否 accept TCP。端口可以在
订阅失效、节点全部离线或规则错误的情况下继续 accept，因此"端口开着"
不能证明"能下到东西"。本模块按流量类别发起真实请求并统计实际字节，
把这两件事分开。

本模块只描述 SPC 自身的流量属于哪一类，不管理代理、不选择节点，
也不根据探测结果自动改变路由。
"""

from __future__ import annotations

import ipaddress
import json
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

SCHEMA_VERSION = "spc.traffic-classes.v1"

# 出口探测响应体的读取上限。探测只为确认"确实收到了字节"，不需要整文件。
_PROBE_BYTE_LIMIT = 4096
_DEFAULT_TIMEOUT_SECONDS = 12.0


@dataclass(frozen=True)
class TrafficClass:
    """一类出站流量及其出口要求。"""

    id: str
    label: str
    exit_requirement: str
    rationale: str
    probe_url: str
    probe_expects: str
    domains: tuple[str, ...]
    extra_probe_urls: tuple[str, ...] = ()

    @property
    def requires_single_exit(self) -> bool:
        return self.exit_requirement == "single_exit"

    @property
    def requires_stable_exit(self) -> bool:
        return self.exit_requirement == "stable_exit"


def traffic_classes_path() -> Path:
    """返回随 wheel 一起分发的分类契约路径。"""

    return Path(
        resources.files("paperfetch")
        .joinpath("data")
        .joinpath("network")
        .joinpath("traffic_classes.json")
    )


def load_traffic_classes(path: str | Path | None = None) -> tuple[TrafficClass, ...]:
    """加载分类契约；schema 版本不符时直接失败，不做静默降级。"""

    source = Path(path).expanduser().resolve() if path else traffic_classes_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"流量分类契约 schema 版本不受支持：{version!r}")
    classes: list[TrafficClass] = []
    for item in payload.get("classes", []):
        domains = tuple(item["domains"])
        if not domains:
            raise ValueError(f"流量类别 {item.get('id')!r} 没有声明任何域名")
        classes.append(
            TrafficClass(
                id=item["id"],
                label=item["label"],
                exit_requirement=item["exit_requirement"],
                rationale=item["rationale"],
                probe_url=item["probe_url"],
                probe_expects=item.get("probe_expects", "http_response"),
                domains=domains,
                extra_probe_urls=tuple(item.get("extra_probe_urls") or ()),
            )
        )
    if not classes:
        raise ValueError("流量分类契约为空")
    return tuple(classes)


def classify_host(
    host: str, classes: Iterable[TrafficClass] | None = None
) -> str | None:
    """返回 host 归属的类别 id；无归属时返回 None。

    采用最长后缀匹配，避免 `iop.org` 与 `iopscience.iop.org` 同时存在时
    结果依赖声明顺序。
    """

    resolved = (host or "").strip().lower().rstrip(".")
    if not resolved:
        return None
    best_id: str | None = None
    best_len = -1
    for item in classes if classes is not None else load_traffic_classes():
        for domain in item.domains:
            normalized = domain.lower()
            if resolved == normalized or resolved.endswith("." + normalized):
                if len(normalized) > best_len:
                    best_id, best_len = item.id, len(normalized)
    return best_id


def _masked_proxy(proxy_url: str | None) -> str | None:
    """只保留 scheme://host:port，丢弃可能存在的代理认证信息。"""

    if not proxy_url:
        return None
    parsed = urlsplit(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
    if not parsed.hostname:
        return None
    scheme = parsed.scheme or "http"
    port = parsed.port or (443 if scheme == "https" else 80)
    return f"{scheme}://{parsed.hostname}:{port}"


def _probe_exit_ip(client: Any) -> str | None:
    """可选出口 IP 探测。

    只有显式配置 `SPC_EXIT_IP_PROBE_URL` 时才执行，SPC 不内置任何第三方
    IP 回显服务。返回值仅用于诊断，不参与任何路由或就绪度判定。
    """

    from paperfetch.core.settings import get_settings

    endpoint = get_settings().text("SPC_EXIT_IP_PROBE_URL") or ""
    if not endpoint:
        return None
    try:
        response = client.get(endpoint)
        candidate = response.text.strip()[:64]
        return str(ipaddress.ip_address(candidate))
    except Exception:
        return None


def _probe_extra_urls(client: Any, urls: tuple[str, ...]) -> dict[str, Any] | None:
    """依次探测附加入口；任一入口拿不到 HTTP 响应（或代理认证失败 / 5xx 网关错误）即返回失败摘要。"""

    for url in urls:
        try:
            response = client.get(url)
        except Exception as exc:
            return {
                "outcome": "unreachable",
                "error_class": type(exc).__name__,
                "failed_probe_url": url,
            }
        if response.status_code == 407:
            return {
                "outcome": "proxy_auth_required",
                "http_status": 407,
                "failed_probe_url": url,
            }
        if response.status_code >= 500:
            return {
                "outcome": "http_error",
                "http_status": response.status_code,
                "failed_probe_url": url,
            }
    return None


def probe_traffic_class(
    traffic_class: TrafficClass,
    proxy_url: str | None,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """对单个类别发起一次真实请求，报告是否确实收到字节。"""

    import httpx

    result: dict[str, Any] = {
        "class_id": traffic_class.id,
        "label": traffic_class.label,
        "exit_requirement": traffic_class.exit_requirement,
        "probe_url": traffic_class.probe_url,
        "transport": "proxy" if proxy_url else "direct",
        "proxy": _masked_proxy(proxy_url),
        "http_status": None,
        "bytes_received": 0,
        "elapsed_ms": None,
        "exit_ip": None,
        "outcome": "unreachable",
        "error_class": None,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            proxy=proxy_url or None,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(traffic_class.probe_url)
            body = response.content[:_PROBE_BYTE_LIMIT]
            result["http_status"] = response.status_code
            result["bytes_received"] = len(body)
            extra_failure = _probe_extra_urls(client, traffic_class.extra_probe_urls)
            result["exit_ip"] = _probe_exit_ip(client)
    except Exception as exc:  # 探测失败必须结构化上报，不能让 doctor 崩掉
        result["error_class"] = type(exc).__name__
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return result
    if extra_failure is not None and result["http_status"] != 407:
        # 主探针常是国内入口，代理规则多半让它直连；境外入口不通时同样算通路不可用。
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result.update(extra_failure)
        return result

    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    status = result["http_status"]
    if status == 407:
        result["outcome"] = "proxy_auth_required"
        return result
    if traffic_class.probe_expects == "http_body":
        # 数据类必须真的取到字节；只拿到状态行不足以证明数据面可用。
        if status == 200 and result["bytes_received"] > 0:
            result["outcome"] = "ok"
        elif result["bytes_received"] == 0:
            result["outcome"] = "no_bytes"
        else:
            result["outcome"] = "http_error"
    else:
        # 论文类入口通常以 30x 跳转到出版商落地页，收到任何 HTTP 响应即说明通路存在。
        result["outcome"] = "ok" if status is not None else "unreachable"
    return result


def probe_traffic_classes(
    proxy_url: str | None,
    *,
    classes: Iterable[TrafficClass] | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """按类别探测并汇总。任何一类拿不到字节都会反映在 `degraded` 上。"""

    from paperfetch.core.settings import get_settings

    resolved = tuple(classes) if classes is not None else load_traffic_classes()
    probes = [
        probe_traffic_class(item, proxy_url, timeout_seconds=timeout_seconds)
        for item in resolved
    ]
    exit_ips = {item["exit_ip"] for item in probes if item["exit_ip"]}
    return {
        "schema_version": SCHEMA_VERSION,
        "transport": "proxy" if proxy_url else "direct",
        "proxy": _masked_proxy(proxy_url),
        "classes": probes,
        "degraded": [item["class_id"] for item in probes if item["outcome"] != "ok"],
        "exit_ip_probe_configured": bool(get_settings().text("SPC_EXIT_IP_PROBE_URL")),
        "distinct_exit_ips": sorted(exit_ips),
    }
