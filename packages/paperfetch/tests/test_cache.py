# -*- coding: utf-8 -*-
"""
test_cache 模块
测试基于 SQLite 的本地持久化缓存 LocalMetadataCache。
"""

import os
import tempfile
import asyncio
import pytest
from paperfetch.utils.cache import LocalMetadataCache


@pytest.mark.asyncio
async def test_cache_resolves_environment_path_at_first_use(tmp_path, monkeypatch):
    cache = LocalMetadataCache()
    configured = tmp_path / "runtime" / "metadata_cache.db"

    monkeypatch.setenv("SPC_METADATA_CACHE_DB", str(configured))
    await cache.initialize()

    assert cache.db_path == str(configured)
    assert configured.exists()


@pytest.mark.asyncio
async def test_local_metadata_cache_lifecycle():
    """
    测试本地持久化缓存的生命周期，包括初始化、键值读写和异常覆盖。
    """
    # 建立临时测试数据库
    temp_dir = tempfile.gettempdir()
    db_path = os.path.join(temp_dir, "test_spc_cache.db")

    # 确保清除可能存在的旧测试文件
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    cache = LocalMetadataCache(db_path=db_path)
    await cache.initialize()

    # 验证数据库文件是否物理产生
    assert os.path.exists(db_path)

    # 1. 验证未命中缓存时返回 None
    val = await cache.get("test_key")
    assert val is None

    # 2. 验证写入并成功读出
    test_data = {"title": "Test Paper", "authors": ["Author A"]}
    await cache.set("test_key", test_data, "test_source")

    val2 = await cache.get("test_key")
    assert val2 is not None
    assert val2["title"] == "Test Paper"
    assert val2["authors"] == ["Author A"]

    # 3. 验证对大小写键名的统一规范化 (Case Insensitivity)
    val_upper = await cache.get("TEST_KEY")
    assert val_upper is not None
    assert val_upper["title"] == "Test Paper"

    # 4. 验证 INSERT OR REPLACE 重写逻辑
    updated_data = {"title": "Updated Paper", "year": 2026}
    await cache.set("test_key", updated_data, "test_source")

    val3 = await cache.get("test_key")
    assert val3["title"] == "Updated Paper"
    assert val3.get("year") == 2026

    # 5. 验证并发写入的稳定性
    async def task_write(i):
        await cache.set(f"concurrent_key_{i}", {"index": i}, "test_source")

    await asyncio.gather(*(task_write(i) for i in range(10)))

    # 检查并发写入的结果
    for i in range(10):
        c_val = await cache.get(f"concurrent_key_{i}")
        assert c_val is not None
        assert c_val["index"] == i

    # 清理临时物理数据库
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
