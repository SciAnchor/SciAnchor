# -*- coding: utf-8 -*-
"""HTTP 客户端、显式能力代理和有界重试。"""

import os
import ipaddress
import socket
import time
import asyncio
from paperfetch.observability import get_event_logger
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import httpx
from typing import Any, Optional
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)
from tenacity.wait import wait_base

logger = get_event_logger("paperfetch.client")

# 定义网络请求重试触发的异常类别
retry_exceptions = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
)


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


class wait_retry_after_or_exponential(wait_base):
    """HTTP 429 优先遵守服务端 Retry-After，否则退回带抖动的指数退避。"""

    def __init__(self, multiplier: float = 1.0, max_seconds: float = 10.0):
        self.fallback = wait_random_exponential(multiplier=multiplier, max=max_seconds)

    def __call__(self, retry_state) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            retry_after = _retry_after_seconds(exc.response)
            if retry_after is not None:
                from paperfetch.core.settings import get_settings

                cap = get_settings().number("HTTP_RETRY_AFTER_MAX_SECONDS")
                return min(retry_after, max(0.0, cap))
        return self.fallback(retry_state)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_retry_after_or_exponential(multiplier=1, max_seconds=10),
    retry=retry_if_exception_type(retry_exceptions),
    reraise=True,
)
async def async_request_with_retry(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    """
    带指数退避重试的异步 HTTP 请求包装器

    在遇到连接超时、网络中断或 HTTP 429/5xx 错误时进行随机抖动的指数退避重试。

    Args:
        client (httpx.AsyncClient): HTTP 异步客户端。
        method (str): 请求方式 (GET, POST, etc.)。
        url (str): 请求的目标 URL。
        **kwargs: 传入 httpx 客户端的额外参数。

    Returns:
        httpx.Response: 请求响应。

    Raises:
        httpx.HTTPStatusError: HTTP 状态码表示错误。
        Exception: 重试上限后的网络异常。
    """
    logger.debug(f"正在发送请求: [{method}] {url}")
    response = await client.request(method, url, **kwargs)

    # 行内注释：若返回服务器瞬时错误或频控限流 (429)，抛出异常触发 tenacity 重试机制
    if response.status_code in [429, 500, 502, 503, 504]:
        logger.warning(
            f"请求返回错误状态码 {response.status_code}，触发重试。URL: {url}"
        )
        response.raise_for_status()

    return response


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_proxy_url(value: str | None) -> Optional[str]:
    """规范化代理配置；常见布尔禁用值稳定解释为未配置。"""

    value = (value or "").strip().strip("'\"").strip()
    if not value or value.casefold() in {
        "0",
        "false",
        "no",
        "off",
        "none",
        "null",
        "disabled",
        "direct",
    }:
        return None
    return value


def configured_proxy_url(name: str) -> Optional[str]:
    """读取已注册能力代理。各能力互不复用。"""

    from paperfetch.core.settings import (
        CAPABILITY_PROXY_NAMES,
        capability_proxy,
    )

    if name in CAPABILITY_PROXY_NAMES:
        return capability_proxy(name)
    raise KeyError(f"未注册代理：{name}")


def metadata_fallback_proxy_configured() -> bool:
    return configured_proxy_url("METADATA_PROXY") is not None


def hosts_use_tun_fake_ip(hosts: tuple[str, ...]) -> bool:
    """识别 TUN fake-IP；不输出解析地址，也不把普通私网地址视为代理。"""

    fake_network = ipaddress.ip_network("198.18.0.0/15")
    for host in hosts:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except OSError:
            continue
        for value in addresses:
            try:
                if ipaddress.ip_address(value) in fake_network:
                    return True
            except ValueError:
                continue
    return False


def create_async_client(proxy_mode: Optional[str] = None) -> httpx.AsyncClient:
    """按显式代理策略创建共享异步 HTTP 客户端。"""
    from paperfetch.core.settings import get_settings

    if proxy_mode is None:
        proxy_mode = get_settings().text("DOWNLOAD_PROXY_MODE") or "route-aware"
    proxy_mode = proxy_mode.strip().lower()
    no_proxy = proxy_mode in {"none", "no_proxy", "no-proxy", "direct"}
    general_proxy = None if no_proxy else configured_proxy_url("DOWNLOAD_PROXY")

    mounts = {}
    for host in ["127.0.0.1", "localhost"]:
        mounts[f"all://{host}"] = httpx.AsyncHTTPTransport()
    if general_proxy:
        mounts["all://"] = httpx.AsyncHTTPTransport(proxy=general_proxy)

    logger.info(
        "HTTP 代理策略已配置: mode=%s, general_proxy=%s",
        proxy_mode,
        "已配置" if general_proxy else "已禁用",
    )
    return httpx.AsyncClient(
        mounts=mounts,
        timeout=httpx.Timeout(20.0, connect=5.0),
        follow_redirects=True,
        trust_env=not no_proxy,
    )


def _metadata_timeout() -> httpx.Timeout:
    from paperfetch.core.settings import get_settings

    settings = get_settings()
    read_timeout = settings.number("METADATA_READ_TIMEOUT")
    return httpx.Timeout(
        timeout=read_timeout,
        connect=settings.number("METADATA_CONNECT_TIMEOUT"),
        read=read_timeout,
        write=settings.number("METADATA_WRITE_TIMEOUT"),
        pool=settings.number("METADATA_POOL_TIMEOUT"),
    )


def create_metadata_client(
    *,
    metadata_proxy_fallback: bool = False,
    timeout: httpx.Timeout | float | None = None,
) -> httpx.AsyncClient:
    """为官方元数据 API 创建轻量客户端，不加载论文下载路由。"""

    metadata_proxy = (
        configured_proxy_url("METADATA_PROXY") if metadata_proxy_fallback else None
    )
    transport = "metadata-proxy-fallback" if metadata_proxy else "direct"
    logger.info(
        "元数据 HTTP 策略已配置: transport=%s",
        transport,
    )
    if timeout is None:
        client_timeout = _metadata_timeout()
    elif isinstance(timeout, (int, float)):
        client_timeout = httpx.Timeout(
            float(timeout), connect=min(float(timeout), 10.0)
        )
    else:
        client_timeout = timeout

    client = httpx.AsyncClient(
        proxy=metadata_proxy,
        timeout=client_timeout,
        follow_redirects=True,
        # 1.0 不继承系统代理，避免同机用户或服务环境产生不可审计漂移。
        trust_env=False,
    )
    client._spc_transport = transport
    return client


def create_external_service_client(*, timeout: float = 120.0) -> httpx.AsyncClient:
    """为 MinerU 等外部服务选择一个明确出口；不继承系统/TUN 代理状态。"""

    proxy = configured_proxy_url("MINERU_PROXY")
    transport = "mineru-proxy" if proxy else "direct"
    logger.info("外部服务 HTTP 策略已配置: transport=%s", transport)
    client = httpx.AsyncClient(
        proxy=proxy,
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,
    )
    client._spc_transport = transport
    return client


class AsyncRateLimiter:
    """
    轻量级异步速率限制器，限制每路数据源请求之间的最小时间间隔。
    通过为每个独立的数据源分配专有的锁，防止某个源等待限流时阻塞其他源。
    """

    def __init__(self):
        self._last_times = {}
        self._locks = {}  # 存储各个源专属的 Lock 实例
        self._meta_lock = asyncio.Lock()  # 用于并发安全地创建锁的元锁

    async def _get_lock(self, source: str) -> asyncio.Lock:
        """
        根据数据源名称获取或创建专属的 asyncio.Lock 互斥锁。

        Args:
            source (str): 数据源标识名称。

        Returns:
            asyncio.Lock: 该数据源专属的协程互斥锁。
        """
        if source not in self._locks:
            async with self._meta_lock:
                if source not in self._locks:
                    self._locks[source] = asyncio.Lock()
        return self._locks[source]

    async def wait(self, source: str, min_interval: float) -> None:
        """
        若当前请求与上一次该源的请求时间差小于 min_interval，则执行异步休眠等待。
        通过专属锁确保同一源的限流等待是串行的，而不同源之间是并行的。

        Args:
            source (str): 数据源标识（如 'openalex'、'semantic_scholar'）。
            min_interval (float): 允许的最小时间间隔，单位为秒。
        """
        lock = await self._get_lock(source)
        async with lock:
            last_time = self._last_times.get(source, 0.0)
            now = time.time()
            elapsed = now - last_time
            if elapsed < min_interval:
                sleep_time = min_interval - elapsed
                logger.debug(
                    f"AsyncRateLimiter: [{source}] 控速等待 {sleep_time:.3f} 秒。"
                )
                await asyncio.sleep(sleep_time)
            # 行内注释：记录休眠过后的实际执行时间戳以供后续请求参考
            self._last_times[source] = time.time()


global_rate_limiter = AsyncRateLimiter()
