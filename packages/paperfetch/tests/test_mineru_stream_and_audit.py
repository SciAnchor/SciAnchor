# -*- coding: utf-8 -*-
"""针对 Issue #13: MinerU 流式分块下载与 Parse Audit 补齐回归测试。"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import pytest

from paperfetch.fulltext.parser import _write_parse_audit


def test_write_parse_audit_contains_doi_endpoint_and_duration():
    """测试 MinerU 解析审计文件包含 doi, endpoint, duration_ms 等核心字段。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        seed_pack = Path(temp_dir)
        mock_status = SimpleNamespace(
            mineru_status="parsed",
            mineru_failure_stage=None,
            mineru_failure_class=None,
            mineru_attempts=[],
            mineru_error_summary=None,
        )

        # 行内注释：写入审计记录，验证必须包含 doi、endpoint 和 duration_ms
        rel_audit_path = _write_parse_audit(
            seed_pack,
            "spc_paper_001",
            mock_status,
            doi="10.1000/182",
            duration_ms=2500,
            endpoint="https://mineru.net/api/v4",
        )

        assert rel_audit_path is not None
        audit_file = seed_pack / rel_audit_path
        assert audit_file.is_file()

        data = json.loads(audit_file.read_text(encoding="utf-8"))
        assert data["schema_version"] == "spc.paper-parse-audit.v1"
        assert data["paper_id"] == "spc_paper_001"
        assert data["doi"] == "10.1000/182"
        assert data["endpoint"] == "https://mineru.net/api/v4"
        assert data["duration_ms"] == 2500
        assert data["status"] == "parsed"
