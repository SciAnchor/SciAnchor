# -*- coding: utf-8 -*-
"""
BaseAction 模块
此文件声明了原子动作基类 BaseAction，作为所有 Task Pipeline 流水线动作的统一契约接口。
"""

from abc import ABC, abstractmethod
from paperfetch.core.context import CuratorContext


class BaseAction(ABC):
    """
    BaseAction 原子动作基类

    所有具体的功能步骤（如校验 Brief、召回、去重、下载、解析等）均需继承此类，
    并实现 execute 方法以对 CuratorContext 进行就地修改和状态传递。
    """

    @property
    def name(self) -> str:
        """
        获取当前动作的唯一名称，用于日志和审计追踪。

        Returns:
            str: 动作名称
        """
        return self.__class__.__name__

    @abstractmethod
    async def execute(self, ctx: CuratorContext) -> None:
        """
        异步执行当前原子动作。

        Args:
            ctx (CuratorContext): 任务运行时上下文。

        Raises:
            Exception: 当动作执行遭遇不可恢复的错误时抛出。
        """
        pass
