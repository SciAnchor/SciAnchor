"""Unit tests for deposit.zenodo path resolve + pack (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.deposit.zenodo import (
    pack_zip,
    resolve_deposit_paths,
    _creator_from_email,
)


def test_pack_zip_skips_pycache(tmp_path: Path) -> None:
    code = tmp_path / "code"
    code.mkdir()
    (code / "main.py").write_text("print(1)\n", encoding="utf-8")
    cache = code / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_text("skip", encoding="utf-8")
    out = tmp_path / "out.zip"
    files = pack_zip(code, out, "code")
    assert "code/main.py" in files
    assert not any("__pycache__" in f for f in files)
    assert out.exists() and out.stat().st_size > 0


def test_resolve_explicit_paths(tmp_path: Path) -> None:
    code = tmp_path / "code"
    data = tmp_path / "data"
    code.mkdir()
    data.mkdir()
    (code / "a.py").write_text("x", encoding="utf-8")
    (data / "a.csv").write_text("x", encoding="utf-8")
    c, d, meta = resolve_deposit_paths(code_path=code, data_path=data)
    assert c == code.resolve()
    assert d == data.resolve()
    assert meta["resolved_from"] == "explicit_paths"


def test_resolve_deposit_root_zh(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "代码").mkdir(parents=True)
    (root / "数据").mkdir(parents=True)
    (root / "代码" / "main.py").write_text("x", encoding="utf-8")
    (root / "数据" / "a.csv").write_text("x", encoding="utf-8")
    c, d, meta = resolve_deposit_paths(deposit_root=root)
    assert c.name == "代码"
    assert d.name == "数据"
    assert meta["resolved_from"].startswith("deposit_root:")


def test_resolve_search_by_topic_name(tmp_path: Path) -> None:
    root = tmp_path / "四篇论文数据代码包"
    pkg = root / "教师编排的LLM教学对中国大学EFL课堂参与与跨文化交际能力"
    (pkg / "代码").mkdir(parents=True)
    (pkg / "数据").mkdir(parents=True)
    (pkg / "代码" / "main.py").write_text("x", encoding="utf-8")
    (pkg / "数据" / "a.csv").write_text("x", encoding="utf-8")
    # decoy
    other = root / "公共艺术介入乡村空间"
    (other / "代码").mkdir(parents=True)
    (other / "数据").mkdir(parents=True)
    c, d, meta = resolve_deposit_paths(
        topic_name="hssc-llm-efl-intercultural-competence EFL 跨文化",
        search_roots=[tmp_path],
    )
    assert "EFL" in str(c) or "efl" in str(c).lower() or "跨文化" in str(c)
    assert meta["resolved_from"].startswith("search:")


def test_creator_from_email() -> None:
    assert _creator_from_email("jane_doe@example.com", None)["name"] == "Doe, Jane"
    assert _creator_from_email(None, "Du, Hairong")["name"] == "Du, Hairong"
    assert _creator_from_email(None, "Hairong Du")["name"] == "Du, Hairong"


def test_resolve_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_deposit_paths(topic_name="no-such-topic-zzz", search_roots=[tmp_path])
