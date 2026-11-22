# -*- coding: utf-8 -*-
"""
test_rotator.py
针对 KeyRotator 的密钥轮转与冷却机制进行单元测试。
"""

import asyncio
from paperfetch.sources.rotator import KeyRotator


def test_key_rotator_basic():
    # 测试初始化解析，逗号和分号分割，去除空字符与空格
    rotator = KeyRotator("key1, key2; key3, ,key4")
    assert rotator.get_total_keys_count() == 4
    assert rotator.keys == ["key1", "key2", "key3", "key4"]


def test_key_rotator_rotation():
    async def run():
        rotator = KeyRotator("key1,key2,key3")
        # 测试 Round-Robin 循环轮转分发
        k1 = await rotator.get_key()
        k2 = await rotator.get_key()
        k3 = await rotator.get_key()
        k4 = await rotator.get_key()

        assert k1 == "key1"
        assert k2 == "key2"
        assert k3 == "key3"
        assert k4 == "key1"

    asyncio.run(run())


def test_key_rotator_cooldown():
    async def run():
        # 设置 0.1 秒的冷却时间以测试到期恢复
        rotator = KeyRotator("key1,key2", cooldown_duration=0.1)

        # 报告 key1 失败，进入冷却
        await rotator.report_failure("key1")

        # 再次获取，应该跳过冷却中的 key1 只能拿到 key2
        for _ in range(5):
            k = await rotator.get_key()
            assert k == "key2"

        # 报告 key2 也失败，全员冷却
        await rotator.report_failure("key2")

        # 所有 Key 冷却时调用必须等待最早恢复，不能向业务层返回 None。
        started = asyncio.get_running_loop().time()
        k_after = await rotator.get_key()
        assert asyncio.get_running_loop().time() - started >= 0.09
        assert k_after in ["key1", "key2"]

    asyncio.run(run())


def test_key_rotator_per_failure_cooldown_override():
    async def run():
        rotator = KeyRotator("key1,key2", cooldown_duration=60.0)

        await rotator.report_failure("key1", cooldown_duration=0.05)

        assert await rotator.get_key() == "key2"
        await asyncio.sleep(0.08)
        assert await rotator.get_key() in ["key1", "key2"]

    asyncio.run(run())
