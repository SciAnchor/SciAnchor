# -*- coding: utf-8 -*-
"""
test_repro_auditor.py
对 repro_auditor 模块的代码链接提取、非 GitHub HTTP 存活校验、
以及 GitHub API 深度可复现性核验进行单元与集成测试。
"""

import asyncio
import os

import httpx
import pytest

from paperfetch.core.repro_auditor import GitHubAuditor, extract_code_urls

RUN_ONLINE_TESTS = os.getenv("SPC_RUN_ONLINE_TESTS") == "1"


def test_extract_code_urls():
    """
    测试从 Markdown 中提取代码托管地址的正则表达式。
    """
    text = (
        "我们的方法已经在 Github 上开源。官方代码仓库位于 "
        "https://github.com/Luckybuff728/paperfetch.git，"
        "另外我们也在 GitLab 上备份了一份：https://gitlab.com/test-user/backup-repo.git。\n"
        "这里有一些无关的干扰链接：https://github.com/blog/news，"
        "以及重复的代码库 https://github.com/Luckybuff728/paperfetch。"
    )

    urls = extract_code_urls(text)

    # 验证是否正确去重并排序（GitHub 优先）
    assert len(urls) == 2
    assert urls[0] == "https://github.com/Luckybuff728/paperfetch"
    assert urls[1] == "https://gitlab.com/test-user/backup-repo"


@pytest.mark.asyncio
async def test_github_api_repro_audit(monkeypatch):
    """
    确定性验证 GitHub API 仓库身份和依赖配置识别。
    """

    async def mock_get(self, url, **kwargs):
        request = httpx.Request("GET", str(url))
        if str(url).endswith("/contents"):
            return httpx.Response(
                200,
                json=[
                    {"name": "pyproject.toml", "type": "file"},
                    {"name": "main.py", "type": "file"},
                ],
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "full_name": "psf/requests",
                "stargazers_count": 100,
                "fork": False,
                "pushed_at": "2026-08-01T00:00:00Z",
                "size": 1,
                "default_branch": "main",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    auditor = GitHubAuditor(github_token="test-token")

    status, meta = await auditor.audit_url("https://github.com/psf/requests")

    assert status == "verified_accessible"
    assert meta["repo"] == "requests"
    assert meta["owner"] == "psf"
    assert meta["detected_configs"] == ["python_pyproject"]
    assert meta["code_file_count"] == 1
    assert meta["runtime_validation"] == "not_attempted"
    assert meta["runnable_evidence"] is False
    assert meta["runnable_blocker"] == "isolated_runtime_smoke_not_completed"


@pytest.mark.asyncio
async def test_github_placeholder_repository_has_no_code_payload(monkeypatch):
    async def mock_get(self, url, **kwargs):
        request = httpx.Request("GET", str(url))
        if "/git/trees/" in str(url):
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {"path": "LICENSE", "type": "blob", "size": 35149, "sha": "a"},
                        {"path": "README.md", "type": "blob", "size": 10, "sha": "b"},
                    ],
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "full_name": "AurelienCD/CFB-GBM",
                "stargazers_count": 0,
                "fork": False,
                "pushed_at": "2025-08-28T00:00:00Z",
                "size": 15,
                "default_branch": "main",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    status, meta = await GitHubAuditor(github_token="test-token").audit_url(
        "https://github.com/AurelienCD/CFB-GBM"
    )

    assert status == "repository_no_code_payload"
    assert meta["inventory_file_count"] == 2
    assert meta["code_file_count"] == 0
    assert meta["notebook_count"] == 0
    assert meta["entrypoint_count"] == 0
    assert len(meta["inventory_digest"]) == 64
    assert meta["inventory_source"] == "github_recursive_tree"
    assert meta["inventory_complete"] is True


@pytest.mark.asyncio
async def test_github_code_without_environment_is_missing_env_config(monkeypatch):
    async def mock_get(self, url, **kwargs):
        request = httpx.Request("GET", str(url))
        if "/git/trees/" in str(url):
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {
                            "path": "src/model.py",
                            "type": "blob",
                            "size": 100,
                            "sha": "a",
                        },
                        {"path": "README.md", "type": "blob", "size": 20, "sha": "b"},
                    ],
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "full_name": "example/code-without-env",
                "stargazers_count": 0,
                "fork": False,
                "size": 1,
                "default_branch": "main",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    status, meta = await GitHubAuditor().audit_url(
        "https://github.com/example/code-without-env"
    )

    assert status == "missing_env_config"
    assert meta["code_file_count"] == 1
    assert meta["detected_configs"] == []


@pytest.mark.asyncio
async def test_truncated_inventory_without_observed_code_is_not_missing_env(
    monkeypatch,
):
    async def mock_get(self, url, **kwargs):
        request = httpx.Request("GET", str(url))
        if "/git/trees/" in str(url):
            return httpx.Response(
                200,
                json={
                    "truncated": True,
                    "tree": [
                        {"path": "README.md", "type": "blob", "size": 20, "sha": "a"}
                    ],
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "full_name": "example/large-repository",
                "stargazers_count": 0,
                "fork": False,
                "size": 1,
                "default_branch": "feature/inventory",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    status, meta = await GitHubAuditor().audit_url(
        "https://github.com/example/large-repository"
    )

    assert status == "repository_inventory_incomplete"
    assert meta["inventory_complete"] is False
    assert meta["code_file_count"] == 0


@pytest.mark.asyncio
async def test_repository_inventory_audit_is_structured(monkeypatch):
    async def mock_audit_url(self, url):
        return "repository_no_code_payload", {
            "url": url,
            "inventory_file_count": 2,
            "code_file_count": 0,
            "notebook_count": 0,
            "entrypoint_count": 0,
            "inventory_digest": "a" * 64,
        }

    monkeypatch.setattr(GitHubAuditor, "audit_url", mock_audit_url)
    auditor = GitHubAuditor()
    status, meta = await auditor.audit_url("https://github.com/example/placeholder")
    assert status == "repository_no_code_payload"
    assert meta["code_file_count"] == 0
    assert meta["inventory_file_count"] == 2


@pytest.mark.asyncio
async def test_github_api_404_audit(monkeypatch):
    """
    确定性验证 GitHub API 404 分类。
    """

    async def mock_get(self, url, **kwargs):
        request = httpx.Request("GET", str(url))
        return httpx.Response(404, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    auditor = GitHubAuditor(github_token="test-token")

    status, meta = await auditor.audit_url(
        "https://github.com/Luckybuff728/nonexistent-repo-987654321"
    )
    assert status == "repo_404"


@pytest.mark.asyncio
async def test_non_github_accessible_audit(monkeypatch):
    """
    确定性验证非 GitHub HTTP 轻量存活核验。
    """

    async def mock_head(self, url, **kwargs):
        request = httpx.Request("HEAD", str(url))
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "head", mock_head)
    auditor = GitHubAuditor()

    status, meta = await auditor.audit_url("https://gitlab.com/explore")
    assert status == "verified_accessible"
    assert meta["http_status"] == 200


@pytest.mark.asyncio
async def test_code_audit_action_parallel(monkeypatch):
    """
    测试 CodeAuditAction 的并发 audit_papers 方法。
    """
    from paperfetch.core.models import PaperRecord
    from paperfetch.core.code_audit import CodeAuditAction

    async def mock_audit_url(self, url):
        if "nonexistent-repo" in url:
            return "repo_404", {"url": url}
        return "verified_runnable", {
            "url": url,
            "detected_configs": ["python_pyproject"],
        }

    monkeypatch.setattr(GitHubAuditor, "audit_url", mock_audit_url)

    # 模拟两篇带有不同代码仓库链接的论文记录
    p1 = PaperRecord(
        paper_id="spc:1",
        title="Title X",
        doi="10.1000/x",
    )
    p1.curation_signals = {
        "code_url": "https://github.com/psf/requests"
    }  # 合法的公开 requests 仓库

    p2 = PaperRecord(
        paper_id="spc:2",
        title="Title Y",
        doi="10.1000/y",
    )
    p2.curation_signals = {
        "code_url": "https://github.com/Luckybuff728/nonexistent-repo-987654321"
    }  # 不存在仓库

    action = CodeAuditAction(enrich_top_k=2)
    audited = await action.audit_papers([p1, p2])

    # 验证并发调度是否全部正确完成并正确写入了对应的复现判定状态
    assert p1.fulltext_status.reproducibility_status in [
        "verified_runnable",
        "verified_accessible",
    ]
    assert p2.fulltext_status.reproducibility_status == "repo_404"
    assert audited == 2


@pytest.mark.asyncio
async def test_code_audit_action_has_bounded_optional_audit(monkeypatch):
    """可选代码审计超时不得阻塞 PDF/MinerU 富集终局。"""
    from paperfetch.core.models import PaperRecord
    from paperfetch.core.code_audit import CodeAuditAction

    started = asyncio.Event()

    async def hanging_audit_url(self, url):
        started.set()
        await asyncio.sleep(30)
        return "verified_accessible", {"url": url}

    monkeypatch.setenv("SPC_CODE_AUDIT_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(GitHubAuditor, "audit_url", hanging_audit_url)
    paper = PaperRecord(
        paper_id="spc:audit-timeout",
        title="Audit timeout must not block enrichment",
        doi="10.1000/audit-timeout",
    )
    paper.curation_signals = {"code_url": "https://github.com/example/slow"}

    audited = await asyncio.wait_for(
        CodeAuditAction(enrich_top_k=1).audit_papers([paper]),
        timeout=2,
    )

    assert started.is_set()
    assert audited == 0
    assert paper.fulltext_status.reproducibility_status == "unchecked"
    assert paper.fulltext_status.repo_metadata == {
        "error_class": "audit_timeout",
        "stage": "code_audit",
        "timeout_seconds": 0.1,
    }


@pytest.mark.asyncio
async def test_repro_auditor_deep_probing(monkeypatch):
    """
    测试非 GitHub 托管平台（Gitee）与 AI Hub (Hugging Face) 的深度配置探测。
    使用 monkeypatch 拦截并模拟 httpx 网络请求以保障测试的高可靠与独立性。
    """
    import httpx

    async def mock_get(self, url, **kwargs):
        req = httpx.Request("GET", url)
        if "gitee.com/test-owner/test-repo" in url:
            # 模拟 Gitee 项目主页存活
            return httpx.Response(200, text="Gitee Repo Page", request=req)
        if "huggingface.co/api/models/test-user/test-model" in url:
            # 模拟 Hugging Face 模型 API
            return httpx.Response(
                200,
                json={
                    "likes": 12,
                    "downloads": 100,
                    "siblings": [{"rpath": "config.json"}, {"rpath": "README.md"}],
                },
                request=req,
            )
        return httpx.Response(404, request=req)

    async def mock_head(self, url, **kwargs):
        req = httpx.Request("HEAD", url)
        if "gitee.com/test-owner/test-repo/raw/main/requirements.txt" in url:
            # 模拟主分支 main 存在 requirements.txt
            return httpx.Response(200, request=req)
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    monkeypatch.setattr(httpx.AsyncClient, "head", mock_head)

    auditor = GitHubAuditor()

    # 静态环境配置只证明仓库可访问，不能证明已完成 runtime smoke。
    status_git, meta_git = await auditor.audit_url(
        "https://gitee.com/test-owner/test-repo"
    )
    assert status_git == "verified_accessible"
    assert "requirements.txt" in meta_git["detected_configs"]
    assert meta_git["runtime_validation"] == "not_attempted"

    status_hf, meta_hf = await auditor.audit_url(
        "https://huggingface.co/test-user/test-model"
    )
    assert status_hf == "verified_accessible"
    assert "model_config" in meta_hf["detected_configs"]
    assert meta_hf["runtime_validation"] == "not_attempted"


@pytest.mark.asyncio
async def test_code_audit_action_no_cache(monkeypatch):
    """
    测试 CodeAuditAction 的 no_cache 强刷机制。
    验证在 no_cache=True 时，Paper 上原有的策展复现缓存状态会被强制清空并重算。
    """
    from paperfetch.core.models import PaperRecord
    from paperfetch.core.code_audit import CodeAuditAction

    async def mock_audit_url(self, url):
        return "verified_runnable", {
            "url": url,
            "detected_configs": ["python_pyproject"],
        }

    monkeypatch.setattr(GitHubAuditor, "audit_url", mock_audit_url)

    p = PaperRecord(
        paper_id="spc:test-nocache",
        title="Title Test NoCache",
        doi="10.1000/test-nocache",
    )
    p.fulltext_status.reproducibility_status = "missing_env_config"
    p.fulltext_status.extracted_code_url = "https://github.com/psf/requests"
    p.curation_signals = {
        "code_url": "https://github.com/psf/requests",
        "reproducibility_status": "missing_env_config",
        "extracted_code_url": "https://github.com/psf/requests",
    }

    # 使用 no_cache=True，强制重刷
    action = CodeAuditAction(enrich_top_k=1, no_cache=True)
    await action.audit_papers([p])

    # requests 应重新计算为 verified_runnable，说明缓存被成功刷写了
    assert p.fulltext_status.reproducibility_status in [
        "verified_runnable",
        "verified_accessible",
    ]


@pytest.mark.online
@pytest.mark.skipif(
    not RUN_ONLINE_TESTS,
    reason="设置SPC_RUN_ONLINE_TESTS=1后才运行真实GitHub smoke",
)
@pytest.mark.asyncio
async def test_github_api_online_smoke():
    """显式在线通道只验证一个稳定公共仓库，不参与默认确定性回归。"""

    auditor = GitHubAuditor(github_token=os.getenv("GITHUB_TOKEN"))

    status, meta = await auditor.audit_url("https://github.com/psf/requests")

    assert status in {"verified_runnable", "verified_accessible"}, meta
