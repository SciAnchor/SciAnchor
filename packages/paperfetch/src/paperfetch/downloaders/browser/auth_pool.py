"""开放获取浏览器后端使用的共享 Playwright 浏览器池。"""

from __future__ import annotations

import asyncio
from paperfetch.observability import get_event_logger
import os
import shutil
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    async_playwright = None
    PLAYWRIGHT_AVAILABLE = False

logger = get_event_logger("paperfetch.downloaders.browser_pool")


def resolve_browser_headless(configured: Optional[str], *, platform_name: str) -> bool:
    """解析 OA 浏览器模式；Windows 默认可见，其他平台默认无头。"""
    value = (
        configured
        if configured is not None
        else ("false" if platform_name == "nt" else "true")
    )
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_chrome_executable_path() -> Optional[str]:
    """返回可用的本地 Google Chrome 可执行文件路径。"""
    configured = os.getenv("CHROME_EXECUTABLE_PATH") or os.getenv("CHROME_PATH")
    if configured and os.path.isfile(configured):
        return configured

    discovered = shutil.which("chrome.exe") or shutil.which("chrome")
    if discovered:
        return discovered

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(
            os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe")
        )
    return next((path for path in candidates if os.path.exists(path)), None)


class BrowserPool:
    """为 OA 浏览器下载复用一个无持久登录态的浏览器上下文。"""

    _instance: Optional["BrowserPool"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.is_ready = False

    @classmethod
    async def get_instance(cls) -> "BrowserPool":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    instance = cls()
                    await instance.start()
                    cls._instance = instance
        return cls._instance

    @classmethod
    def current_instance(cls) -> Optional["BrowserPool"]:
        return cls._instance

    async def start(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("未安装 playwright，无法启动 OA 浏览器下载后端")
        if self.is_ready:
            return

        try:
            self.playwright = await async_playwright().start()
            headless = resolve_browser_headless(
                os.getenv("PDF_BROWSER_HEADLESS"),
                platform_name=os.name,
            )
            launch_options = {
                "headless": headless,
            }
            chrome_path = resolve_chrome_executable_path()
            if chrome_path:
                launch_options["executable_path"] = chrome_path
            self.browser = await self.playwright.chromium.launch(**launch_options)
            self.is_ready = True
            logger.info("[OA 浏览器] 无状态浏览器进程已就绪，headless=%s", headless)
        except Exception:
            await self.close()
            raise

    async def get_context(self) -> BrowserContext:
        if not self.is_ready or self.browser is None:
            await self.start()
        assert self.browser is not None
        return await self.browser.new_context(accept_downloads=True)

    async def close(self) -> None:
        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright is not None:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        self.is_ready = False
        self.browser = None
        self.playwright = None
        type(self)._instance = None
