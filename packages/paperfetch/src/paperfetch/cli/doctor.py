# -*- coding: utf-8 -*-
"""SPC 系统环境诊断与自愈建议子命令处理器。"""

import os
import socket
from urllib.parse import urlsplit

from paperfetch.core.metadata_signals import DEFAULT_CCF_PATH, journal_master_status
from paperfetch.observability import get_event_logger, write_output
from paperfetch.sources.s2_config import get_semantic_scholar_config
from paperfetch.utils.client import configured_proxy_url

logger = get_event_logger("paperfetch.cli.doctor")


def _credential_configured(name: str) -> bool:
    from paperfetch.core.settings import SETTINGS_BY_NAME, get_settings

    if name == "DOWNLOAD_PROXY":
        return configured_proxy_url(name) is not None
    if name in SETTINGS_BY_NAME:
        return bool(get_settings().text(name))
    return bool(os.getenv(name))


def _proxy_endpoint_status(name: str, timeout_seconds: float = 1.0) -> dict:
    """Return credential-free configuration and TCP reachability facts."""
    raw = configured_proxy_url(name)
    if not raw:
        return {
            "configured": False,
            "scheme": None,
            "tcp_reachable": None,
        }
    parsed = urlsplit(raw if "://" in raw else f"http://{raw}")
    scheme = parsed.scheme or "http"
    host = parsed.hostname
    port = parsed.port or (443 if scheme in {"https", "socks5h"} else 80)
    reachable = False
    if host and port:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                reachable = True
        except OSError:
            reachable = False
    return {
        "configured": True,
        "scheme": scheme,
        "tcp_reachable": reachable,
    }


def _download_proxy_status(timeout_seconds: float = 1.0) -> dict:
    """Compatibility wrapper for the public-download proxy."""

    return _proxy_endpoint_status("DOWNLOAD_PROXY", timeout_seconds)


def _probe_semantic_scholar_scheduler() -> dict:
    """显式验证一次可靠调度链；429 留在池内等待，不逐 key 消耗额度。"""

    import asyncio
    import time

    from paperfetch.sources.s2_pool import PersistentS2KeyPool
    from paperfetch.sources.semantic_scholar import SemanticScholarSource
    from paperfetch.utils.client import create_metadata_client

    config = get_semantic_scholar_config()
    if not config.api_keys:
        return {
            "configured": False,
            "attempted": False,
            "available": False,
            "status_summary": "未配置 API key",
        }

    async def run() -> dict:
        pool = PersistentS2KeyPool(
            config.api_keys,
            min_interval_seconds=config.min_interval_with_key,
        )
        started = time.perf_counter()
        try:
            async with create_metadata_client() as client:
                source = SemanticScholarSource(client, key_pool=pool)
                response = await source._send_request_with_key_rotator(
                    "GET",
                    "/paper/DOI:10.1016/j.cities.2023.104510",
                    params={"fields": "title"},
                )
            available = response.status_code == 200
            error_class = None if available else f"http_{response.status_code}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            available = False
            error_class = type(exc).__name__
        return {
            "configured": True,
            "attempted": True,
            "available": available,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error_class": error_class,
            "pool": await pool.snapshot(),
            "status_summary": "调度请求成功" if available else "调度请求失败",
        }

    return asyncio.run(run())


def _semantic_scholar_pool_snapshot() -> dict:
    import asyncio

    from paperfetch.sources.s2_pool import PersistentS2KeyPool

    config = get_semantic_scholar_config()
    if not config.api_keys:
        return {"configured": 0, "ready": 0, "cooling": 0, "leased": 0, "disabled": 0}
    pool = PersistentS2KeyPool(
        config.api_keys,
        min_interval_seconds=config.min_interval_with_key,
    )
    return asyncio.run(pool.snapshot())


def _openalex_pool_snapshot() -> dict:
    import asyncio

    from paperfetch.sources.key_pool import PersistentApiKeyPool
    from paperfetch.sources.openalex import _openalex_api_keys

    keys = _openalex_api_keys()
    if not keys:
        return {"configured": 0, "ready": 0, "cooling": 0, "leased": 0, "disabled": 0}
    return asyncio.run(PersistentApiKeyPool("openalex", keys).snapshot())


def _probe_openalex_scheduler() -> dict:
    import asyncio
    import time

    from paperfetch.sources.key_pool import PersistentApiKeyPool
    from paperfetch.sources.openalex import OpenAlexSource, _openalex_api_keys
    from paperfetch.utils.client import create_metadata_client

    if not _openalex_api_keys():
        return {
            "configured": False,
            "attempted": False,
            "available": False,
            "status_summary": "未配置 API Key",
        }

    async def run() -> dict:
        started = time.perf_counter()
        source = None
        try:
            async with create_metadata_client(metadata_proxy_fallback=True) as client:
                source = OpenAlexSource(client)
                response = await source._request_reliably(
                    "GET",
                    "https://api.openalex.org/works/https://doi.org/10.1016/j.cities.2023.104510",
                    params={"select": "id,doi,title"},
                )
            available = response.status_code == 200
            error_class = None if available else f"http_{response.status_code}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            available = False
            error_class = type(exc).__name__
        pool = (
            await source.key_pool.snapshot()
            if source and source.key_pool
            else await PersistentApiKeyPool("openalex", _openalex_api_keys()).snapshot()
        )
        return {
            "configured": True,
            "attempted": True,
            "available": available,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error_class": error_class,
            "pool": pool,
            "status_summary": "调度请求成功" if available else "调度请求失败",
        }

    return asyncio.run(run())


def _probe_live_api_endpoints(
    timeout_seconds: float = 3.0,
    *,
    probe_semantic_scholar: bool = False,
    probe_openalex: bool = False,
) -> dict:
    """实时探测已配置的外部学术 API、大模型网关与数据源的可用性与状态码。"""
    import httpx
    import time

    proxy_url = configured_proxy_url("DOWNLOAD_PROXY")
    mounts = None
    if proxy_url:
        mounts = {
            "http://": httpx.HTTPTransport(proxy=proxy_url),
            "https://": httpx.HTTPTransport(proxy=proxy_url),
        }

    results = {}

    # 1. 探测用户配置的 OpenAI 兼容 LLM
    llm_key = os.getenv("LLM_API_KEY")
    llm_url = os.getenv("LLM_BASE_URL")
    llm_model = (os.getenv("LLM_MODEL") or "").strip()
    if llm_key and llm_url and llm_model:
        try:
            start_t = time.perf_counter()
            with httpx.Client(mounts=mounts, timeout=timeout_seconds) as client:
                r = client.post(
                    f"{llm_url}/chat/completions",
                    headers={"Authorization": f"Bearer {llm_key}"},
                    json={
                        "model": llm_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                results["llm_gateway"] = {
                    "configured": True,
                    "model": llm_model,
                    "status_code": r.status_code,
                    "latency_ms": latency_ms,
                    "available": r.status_code == 200,
                    "message": f"200 OK (正常, {latency_ms}ms)"
                    if r.status_code == 200
                    else f"HTTP {r.status_code}",
                }
        except Exception as exc:
            results["llm_gateway"] = {
                "configured": True,
                "model": llm_model,
                "status_code": None,
                "available": False,
                "message": f"连接受阻 ({type(exc).__name__})",
            }
    else:
        results["llm_gateway"] = {
            "configured": False,
            "available": False,
            "message": "未配置",
        }

    # 2. 默认只读配置/状态，不逐 key 发流量；显式参数才验证一次调度链。
    s2_config = get_semantic_scholar_config()
    if probe_semantic_scholar:
        results["semantic_scholar_live"] = _probe_semantic_scholar_scheduler()
    else:
        results["semantic_scholar_live"] = {
            "configured": s2_config.has_key,
            "attempted": False,
            "available": None,
            "configured_keys": s2_config.key_count,
            "pool": _semantic_scholar_pool_snapshot(),
            "status_summary": "未发起真实请求；使用 --probe-semantic-scholar 显式验证",
        }

    # 3. 探测 NCBI API Key
    ncbi_key = os.getenv("NCBI_API_KEY")
    if ncbi_key:
        try:
            start_t = time.perf_counter()
            with httpx.Client(mounts=mounts, timeout=timeout_seconds) as client:
                r = client.get(
                    f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?retmode=json&api_key={ncbi_key}"
                )
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                results["ncbi_live"] = {
                    "configured": True,
                    "status_code": r.status_code,
                    "latency_ms": latency_ms,
                    "available": r.status_code == 200,
                    "message": f"200 OK (正常, {latency_ms}ms)"
                    if r.status_code == 200
                    else f"HTTP {r.status_code}",
                }
        except Exception as exc:
            results["ncbi_live"] = {
                "configured": True,
                "available": False,
                "message": f"连接受阻 ({type(exc).__name__})",
            }
    else:
        results["ncbi_live"] = {
            "configured": False,
            "available": False,
            "message": "未配置",
        }

    # 4. OpenAlex 同样默认只读池状态，显式参数才消费一个调度请求。
    from paperfetch.sources.openalex import _openalex_api_keys

    openalex_keys = _openalex_api_keys()
    if probe_openalex:
        results["openalex_live"] = _probe_openalex_scheduler()
    else:
        results["openalex_live"] = {
            "configured": bool(openalex_keys),
            "attempted": False,
            "available": None,
            "configured_keys": len(openalex_keys),
            "pool": _openalex_pool_snapshot(),
            "status_summary": "未发起真实请求；使用 --probe-openalex 显式验证",
        }

    return results


def _traffic_class_status(
    proxy_url: str | None,
    *,
    class_ids: set[str] | None = None,
) -> dict:
    """按流量类别做真实取字节探测。

    端口 accept TCP 不等于能下到东西：订阅失效、节点全部离线或路由规则
    写错时，端口照样 accept。论文下载与数据下载是两条独立的关键通路，
    必须分别验证。
    """
    from paperfetch.network import load_traffic_classes, probe_traffic_classes

    classes = load_traffic_classes()
    if class_ids is not None:
        classes = tuple(item for item in classes if item.id in class_ids)
    try:
        result = probe_traffic_classes(proxy_url, classes=classes)
        result.pop("proxy", None)
        result.pop("distinct_exit_ips", None)
        for item in result.get("classes", []):
            item.pop("proxy", None)
            item.pop("exit_ip", None)
        return result
    except Exception as exc:  # 探测本身失败不能让整个 doctor 中断
        return {
            "schema_version": None,
            "classes": [],
            "degraded": [],
            "error_class": type(exc).__name__,
        }


def _diagnose_proxy_path(
    endpoint: dict,
    traffic: dict | None,
    *,
    proxy_required: bool,
) -> dict:
    """Separate confirmed path state from unconfirmed provider causes."""

    if not endpoint.get("configured"):
        if proxy_required:
            return {
                "state": "unavailable",
                "code": "proxy_not_configured",
                "cause_confirmed": True,
            }
        return {
            "state": "direct",
            "code": "direct_transport",
            "cause_confirmed": True,
        }
    if endpoint.get("tcp_reachable") is False:
        return {
            "state": "unavailable",
            "code": "proxy_endpoint_unreachable",
            "cause_confirmed": True,
        }
    probes = list((traffic or {}).get("classes") or [])
    if not probes:
        return {
            "state": "unknown",
            "code": "proxy_probe_failed",
            "cause_confirmed": False,
        }
    failed = [item for item in probes if item.get("outcome") != "ok"]
    if not failed:
        return {
            "state": "working",
            "code": "proxy_path_working",
            "cause_confirmed": True,
        }
    if any(item.get("http_status") == 407 for item in failed):
        return {
            "state": "unavailable",
            "code": "proxy_auth_failed",
            "cause_confirmed": True,
        }
    return {
        "state": "degraded",
        "code": "proxy_path_degraded",
        "cause_confirmed": False,
        "possible_causes": [
            "subscription_expired",
            "nodes_unavailable",
            "routing_misconfigured",
            "upstream_unavailable",
        ],
    }


def _check(check_id: str, verdict: str, message: str) -> dict[str, str]:
    return {"id": check_id, "verdict": verdict, "message": message}


def _public_proxy_check() -> dict[str, str]:
    endpoint = _download_proxy_status()
    if not endpoint["configured"]:
        return _check("proxy.public", "ok", "未配置 DOWNLOAD_PROXY，公共下载将直连")
    if not endpoint["tcp_reachable"]:
        return _check("proxy.public", "wrong", "DOWNLOAD_PROXY 已配置但端点不可达")
    return _check(
        "proxy.public", "ok", "DOWNLOAD_PROXY 端点 TCP 可达，不代表论文可下载"
    )


def _environment_check() -> dict[str, str]:
    from paperfetch.core.environment import (
        current_environment,
        infer_environment,
    )

    declared = current_environment()
    inferred = infer_environment()
    if declared != inferred:
        return _check(
            "environment",
            "wrong",
            f"SPC_ENVIRONMENT={declared} 与运行位置不符（推断为 {inferred}）",
        )
    return _check("environment", "ok", f"SPC_ENVIRONMENT={declared}")


def _unknown_settings_check() -> dict[str, str]:
    from paperfetch.core.settings import unknown_settings_env

    unknown = unknown_settings_env()
    if unknown:
        return _check(
            "settings.unknown",
            "wrong",
            f"未注册配置：{', '.join(unknown)}",
        )
    return _check("settings.unknown", "ok", "受管环境变量均已注册")


def _metadata_files_check() -> dict[str, str]:
    if not os.path.exists(DEFAULT_CCF_PATH):
        return _check(
            "paper.metadata.files", "wrong", "元数据文件缺失：ccf_ranks_2026.json"
        )
    return _check("paper.metadata.files", "ok", "CCF 目录文件存在")


def _journal_master_check() -> dict[str, str]:
    """用户自备的中科院分区主库；公开版不内置，未配置不是阻断项。"""

    status = journal_master_status()
    if status["error_class"] == "not_configured":
        return _check(
            "paper.metadata.journal_master",
            "unknown",
            f"未配置 {status['env']}，中科院分区（cas_zone）字段将为空；检索与下载不受影响",
        )
    if not status["ready"]:
        return _check(
            "paper.metadata.journal_master",
            "wrong",
            f"{status['env']} 指向的期刊主库不可用（{status['error_class']}）：{status['source']}",
        )
    return _check(
        "paper.metadata.journal_master",
        "ok",
        f"期刊主库已加载 {status['journal_records']} 条记录",
    )


def _metadata_keys_check() -> dict[str, str]:
    configured = bool(
        os.getenv("OPENALEX_API_KEYS")
        or os.getenv("OPENALEX_API_KEY")
        or os.getenv("SEMANTIC_SCHOLAR_API_KEYS")
        or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        or os.getenv("NCBI_API_KEY")
    )
    if configured:
        return _check("paper.metadata.keys", "ok", "至少配置了一个元数据源密钥")
    return _check(
        "paper.metadata.keys",
        "unknown",
        "未配置 OpenAlex / Semantic Scholar / NCBI 密钥",
    )


def _parse_check() -> dict[str, str]:
    if os.getenv("MINERU_API_TOKEN"):
        return _check("paper.parse", "ok", "MINERU_API_TOKEN 已配置")
    return _check("paper.parse", "unknown", "未配置 MINERU_API_TOKEN")


def _proxy_path_check(
    check_id: str,
    *,
    env_name: str,
    proxy_required: bool,
) -> dict[str, str]:
    endpoint = _proxy_endpoint_status(env_name)
    traffic = _traffic_class_status(
        configured_proxy_url(env_name),
        class_ids={"paper_download"},
    )
    diagnosis = _diagnose_proxy_path(endpoint, traffic, proxy_required=proxy_required)
    code = diagnosis["code"]
    if diagnosis["state"] in {"unavailable", "degraded", "unknown"}:
        extra = ""
        if code == "proxy_path_degraded":
            extra = "；代理订阅过期只是候选原因，不能据此确诊"
        return _check(check_id, "wrong", f"{check_id}={code}{extra}")
    if code == "proxy_path_working":
        return _check(check_id, "ok", f"{check_id} 探针通路正常，不代表论文 PDF 可用")
    return _check(check_id, "ok", f"{check_id}={code}")


def _live_probe_check(check_id: str, probe: dict) -> dict[str, str]:
    if not probe.get("configured"):
        return _check(check_id, "unknown", f"{check_id} 未配置")
    if probe.get("available"):
        return _check(check_id, "ok", f"{check_id} 实网请求成功")
    return _check(check_id, "wrong", f"{check_id} 实网请求失败")


def _collect_doctor_checks(parsed_args) -> list[dict[str, str]]:
    checks = [
        _environment_check(),
        _public_proxy_check(),
        _unknown_settings_check(),
        _metadata_files_check(),
        _journal_master_check(),
        _metadata_keys_check(),
        _parse_check(),
    ]
    if getattr(parsed_args, "probe_traffic_classes", False):
        checks.append(
            _proxy_path_check(
                "proxy.public_path",
                env_name="DOWNLOAD_PROXY",
                proxy_required=False,
            )
        )
    if getattr(parsed_args, "probe_semantic_scholar", False) or getattr(
        parsed_args, "probe_openalex", False
    ):
        live = _probe_live_api_endpoints(
            probe_semantic_scholar=bool(
                getattr(parsed_args, "probe_semantic_scholar", False)
            ),
            probe_openalex=bool(getattr(parsed_args, "probe_openalex", False)),
        )
        if getattr(parsed_args, "probe_semantic_scholar", False):
            checks.append(
                _live_probe_check(
                    "metadata.s2", live.get("semantic_scholar_live") or {}
                )
            )
        if getattr(parsed_args, "probe_openalex", False):
            checks.append(
                _live_probe_check("metadata.openalex", live.get("openalex_live") or {})
            )
    return checks


def _doctor_public_payload(checks: list[dict[str, str]]) -> dict:
    blockers = [item["message"] for item in checks if item["verdict"] == "wrong"]
    verdict = "wrong" if blockers else "ok"
    payload = {
        "schema": "spc.result.v2",
        "status": "failed" if verdict == "wrong" else "completed",
        "data": {
            "verdict": verdict,
            "checks": checks,
            "blockers": blockers,
        },
    }
    if blockers:
        payload["error"] = {
            "code": "doctor_blocked",
            "message": blockers[0],
        }
    return payload


def run_doctor(parsed_args) -> int:
    """检查公开下载、元数据与解析的配置与运行面；不证明 PDF 一定可下载。"""
    logger.info("[环境诊断] 开始检查系统环境")
    checks = _collect_doctor_checks(parsed_args)
    payload = _doctor_public_payload(checks)
    output_format = getattr(parsed_args, "output_format", "json")
    if output_format == "json":
        write_output(payload, pretty=True)
    else:
        labels = {"ok": "OK", "wrong": "WRONG", "unknown": "UNKNOWN"}
        write_output("=== doctor ===")
        write_output(f"verdict={payload['data']['verdict']}")
        for item in checks:
            write_output(
                f"[{labels.get(item['verdict'], item['verdict'])}] {item['id']}: {item['message']}"
            )
        blockers = payload["data"]["blockers"]
        if blockers:
            write_output("blockers:")
            for message in blockers:
                write_output(f"- {message}")
    return 0


def register_doctor_commands(subparsers):
    """注册 doctor。"""
    # 1. doctor
    doctor_parser = subparsers.add_parser(
        "doctor", help="检查下载、元数据与解析的配置与运行面，不证明 PDF 一定可下载"
    )
    doctor_parser.add_argument(
        "--output-format",
        type=str,
        choices=["text", "json"],
        default="json",
        help="输出格式 (text 或 json)",
    )
    doctor_parser.add_argument(
        "--probe-traffic-classes",
        action="store_true",
        help="增加公共下载代理通路检查；端点不可达和 407 可确诊，通路正常不代表论文 PDF 可用",
    )
    doctor_parser.add_argument(
        "--probe-semantic-scholar",
        action="store_true",
        help="通过可靠调度池发起一次 S2 实网请求；默认 doctor 不消耗 Key 额度",
    )
    doctor_parser.add_argument(
        "--probe-openalex",
        action="store_true",
        help="通过可靠调度池发起一次 OpenAlex 实网请求；默认 doctor 不消耗 Key 额度",
    )
    return [doctor_parser]
