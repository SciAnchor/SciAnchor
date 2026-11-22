# -*- coding: utf-8 -*-
"""下载后端的注册与发现机制。

支持使用装饰器将具体的下载器后端类注册到全局容器中，并提供动态发现和加载的能力。
"""

from __future__ import annotations

import importlib
from paperfetch.observability import get_event_logger
import pkgutil
from typing import Dict, List, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from paperfetch.downloaders.base import DownloaderBackend

logger = get_event_logger(__name__)


class BackendRegistry:
    """管理全局已注册下载后端的单例/静态注册表。"""

    _backends: Dict[str, Type[DownloaderBackend]] = {}

    @classmethod
    def register(cls, backend_cls: Type[DownloaderBackend]) -> Type[DownloaderBackend]:
        """装饰器：将一个下载后端类注册到表中。

        Args:
            backend_cls: 继承自 DownloaderBackend 的下载器类。

        Returns:
            Type[DownloaderBackend]: 返回原类，支持链式修饰。
        """
        route_key = getattr(backend_cls, "route_key", None)
        if not route_key:
            raise ValueError(
                f"后端类 {backend_cls.__name__} 缺失必要的 'route_key' 属性"
            )

        # 允许通过 supported_routes 注册多个关联路由名
        routes = getattr(backend_cls, "supported_routes", frozenset({route_key}))
        for route in routes:
            if route in cls._backends:
                logger.warning(
                    "[后端注册] 路由重复注册，路由=%s，原后端=%s，新后端=%s",
                    route,
                    cls._backends[route].__name__,
                    backend_cls.__name__,
                )
            cls._backends[route] = backend_cls

        logger.debug(
            "[后端注册] 注册成功，后端=%s，路由=%s", backend_cls.__name__, list(routes)
        )
        return backend_cls

    @classmethod
    def get_backend(cls, route_key: str) -> Optional[Type[DownloaderBackend]]:
        """获取路由匹配的后端类。

        Args:
            route_key: 路由键值（例如 'elsevier_api', 'public_http'）。

        Returns:
            Optional[Type[DownloaderBackend]]: 匹配的后端类。
        """
        # 确保已扫描并加载所有 backends 目录下的模块
        cls.discover()
        return cls._backends.get(route_key)

    @classmethod
    def get_backends_by_type(cls, base_type: Type) -> List[DownloaderBackend]:
        """获取继承自特定基类（如 PublisherAPIBackend）的所有后端实例。"""
        cls.discover()
        seen = set()
        instances = []
        for backend_cls in cls._backends.values():
            if issubclass(backend_cls, base_type) and backend_cls not in seen:
                seen.add(backend_cls)
                try:
                    instances.append(backend_cls())
                except Exception as e:
                    logger.error(
                        "[后端注册] 后端实例化失败，后端=%s，原因=%s",
                        backend_cls.__name__,
                        e,
                    )
        return instances

    @classmethod
    def all_backends(cls) -> Dict[str, Type[DownloaderBackend]]:
        """获取全部已注册的后端字典。"""
        cls.discover()
        return dict(cls._backends)

    _discovered: bool = False

    @classmethod
    def discover(cls) -> None:
        """自动扫描并导入 backends/ 包下的所有子模块，从而触发 @BackendRegistry.register 的装饰逻辑。"""
        if cls._discovered:
            return
        cls._discovered = True
        try:
            # 引入 backends 根模块
            backends_pkg = importlib.import_module("paperfetch.downloaders.backends")
            if hasattr(backends_pkg, "__path__"):
                for _, module_name, _ in pkgutil.walk_packages(
                    backends_pkg.__path__, backends_pkg.__name__ + "."
                ):
                    try:
                        importlib.import_module(module_name)
                    except Exception:
                        logger.exception(
                            "[后端注册] 模块加载失败，模块=%s", module_name
                        )
        except ModuleNotFoundError:
            logger.warning("[后端注册] 未找到 backends 根模块，停止自动扫描")
