# -*- coding: utf-8 -*-
"""
rotator 模块
提供 KeyRotator 类，实现多 API 密钥轮转、冷却控制与可用性管理。
"""

import time
from paperfetch.observability import get_event_logger
import asyncio
from typing import List, Dict, Optional
from datetime import datetime

logger = get_event_logger("paperfetch.rotator")


class KeyRotator:
    """
    KeyRotator 密钥轮转与冷却管理器

    采用 Round-Robin 轮转分发密钥，并在捕获频控/配额限制时冷却密钥。
    """

    def __init__(self, raw_keys_str: str, cooldown_duration: float = 60.0):
        """
        初始化轮转器。

        Args:
            raw_keys_str (str): 以逗号 `,` 或分号 `;` 分割的原始密钥字符串。
            cooldown_duration (float): 发生频控时的冷却时间 (秒)，默认 60.0 秒。
        """
        # 分割并去除多余空格，剔除空字符
        self.keys: List[str] = [
            k.strip() for k in raw_keys_str.replace(";", ",").split(",") if k.strip()
        ]
        self.cooldown_duration: float = cooldown_duration

        # 冷却结束时间戳字典，Key 为密钥，Value 为冷却结束的 float 时间戳
        self.cooldown_until: Dict[str, float] = {}

        self.current_index: int = 0
        self.lock = asyncio.Lock()  # 协程锁以保证高并发下分配 Key 的一致性

    def get_total_keys_count(self) -> int:
        """
        获取当前轮转器中管理的密钥总数。

        Returns:
            int: 密钥数量。
        """
        return len(self.keys)

    async def get_key(self) -> Optional[str]:
        """
        异步获取一个当前未处于冷却期的可用 API 密钥。

        Returns:
            Optional[str]: 可用的密钥，若所有密钥均在冷却中，则返回 None。
        """
        if not self.keys:
            return None
        while True:
            async with self.lock:
                now = time.time()
                total_keys = len(self.keys)
                for _ in range(total_keys):
                    candidate_key = self.keys[self.current_index]
                    self.current_index = (self.current_index + 1) % total_keys
                    until = self.cooldown_until.get(candidate_key, 0.0)
                    if now >= until:
                        return candidate_key
                wake_at = min(self.cooldown_until.get(key, now) for key in self.keys)
            logger.info("全部本进程 S2 key 正在冷却，等待最早 key 恢复")
            await asyncio.sleep(min(max(0.01, wake_at - time.time()), 30.0))

    async def report_failure(
        self, key: str, cooldown_duration: Optional[float] = None
    ) -> None:
        """
        当某个 Key 请求返回 429 (频控) 或 403 (超限) 时，报告该 Key 失败，启动冷却时间。

        Args:
            key (str): 发生限制的 API 密钥。
            cooldown_duration (Optional[float]): 本次失败的冷却时间。未提供时使用默认冷却时间。
        """
        async with self.lock:
            if key in self.keys:
                now = time.time()
                duration = (
                    self.cooldown_duration
                    if cooldown_duration is None
                    else max(0.0, cooldown_duration)
                )
                until = now + duration
                self.cooldown_until[key] = until
                time_str = datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M:%S")
                logger.info("S2 key 已进入本进程冷却，恢复时间=%s", time_str)
