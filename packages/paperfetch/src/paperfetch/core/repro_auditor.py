# -*- coding: utf-8 -*-
"""
repro_auditor 模块
提供学术论文中代码仓库链接的自动提取、非 GitHub 托管链接的存活性与深度配置核验、
以及对 GitHub 仓库的 API 级深度可复现性审计（依赖配置文件检测）。
"""

import re
from paperfetch.observability import get_event_logger
import hashlib
import json
import os
import asyncio
from typing import List, Tuple, Dict, Any, Optional
from urllib.parse import quote
import httpx

logger = get_event_logger("paperfetch.core.repro_auditor")

# 正则表达式用于匹配主流代码托管平台及人工智能Hub/数据仓库链接 (连字符必须放在末尾，防止中括号范围解析隐患)
GITHUB_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+",
    re.IGNORECASE,
)
OTHER_GIT_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:gitlab\.com|gitee\.com|bitbucket\.org|openi\.org\.cn)/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+",
    re.IGNORECASE,
)
HF_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:huggingface\.co|hf\.co)/(?:datasets/|spaces/)?([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+)",
    re.IGNORECASE,
)
MODELSCOPE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?modelscope\.cn/(?:datasets/|models/)?([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-\.]+)",
    re.IGNORECASE,
)
DATA_ARCHIVE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:zenodo\.org/record/|zenodo\.org/records/|osf\.io/|figshare\.com/articles/)[a-zA-Z0-9_\-]+",
    re.IGNORECASE,
)

# 保留字过滤黑名单，排除 GitHub 官方的辅助页面
BLACK_LIST_ORGS = {
    "blog",
    "features",
    "pricing",
    "explore",
    "trending",
    "notifications",
    "settings",
    "about",
    "site",
    "contact",
    "security",
    "organizations",
    "sponsors",
    "readme",
    "topics",
    "collections",
    "customer-stories",
    "premium-support",
    "enterprise",
    "marketplace",
    "guides",
    "desktop",
}

CODE_FILE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".cu",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".jl",
    ".js",
    ".jsx",
    ".kt",
    ".m",
    ".php",
    ".ps1",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
}
ENTRYPOINT_NAMES = {
    "app.py",
    "cli.py",
    "eval.py",
    "evaluate.py",
    "main.py",
    "predict.py",
    "run.py",
    "run.sh",
    "serve.py",
    "test.py",
    "train.py",
}
CONFIG_PATTERNS = {
    "requirements.txt": "python_requirements",
    "setup.py": "python_setup",
    "pyproject.toml": "python_pyproject",
    "environment.yml": "conda_env",
    "environment.yaml": "conda_env",
    "package.json": "nodejs_package",
    "pom.xml": "java_maven",
    "build.gradle": "java_gradle",
    "dockerfile": "docker_image",
}


def summarize_repository_inventory(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 GitHub tree/contents 条目生成稳定、无内容泄露的代码资产摘要。"""
    files = []
    for item in entries:
        item_type = str(item.get("type") or "").lower()
        if item_type not in {"blob", "file"}:
            continue
        path = (
            str(item.get("path") or item.get("name") or "")
            .replace("\\", "/")
            .strip("/")
        )
        if not path:
            continue
        files.append(
            {
                "path": path,
                "type": "file",
                "size": int(item.get("size") or 0),
                "sha": str(item.get("sha") or ""),
            }
        )

    files.sort(key=lambda item: item["path"].lower())
    names = [item["path"].rsplit("/", 1)[-1].lower() for item in files]
    code_file_count = sum(
        1
        for item in files
        if os.path.splitext(item["path"].lower())[1] in CODE_FILE_SUFFIXES
    )
    notebook_count = sum(1 for item in files if item["path"].lower().endswith(".ipynb"))
    entrypoint_count = sum(1 for name in names if name in ENTRYPOINT_NAMES)
    detected_configs = sorted(
        {tag for name, tag in CONFIG_PATTERNS.items() if name in names}
    )
    digest_payload = json.dumps(files, ensure_ascii=True, separators=(",", ":"))
    return {
        "inventory_file_count": len(files),
        "code_file_count": code_file_count,
        "notebook_count": notebook_count,
        "entrypoint_count": entrypoint_count,
        "inventory_digest": hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
        "detected_configs": detected_configs,
        "has_entry_script": entrypoint_count > 0,
    }


def clean_extracted_url(url: str) -> str:
    """
    清洗提取出的 URL，去除末尾由于正则边界引起的标点符号（如句号、右括号、引号等），
    并自动为简写 URL 补齐 https:// 前缀防止 HTTP 客户端请求异常。

    Args:
        url (str): 原始匹配到的 URL

    Returns:
        str: 清洗并补齐协议后的标准仓库 URL
    """
    cleaned = url.strip().rstrip(".,;)\"'>`")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    # 补齐协议前缀以兼容 httpx 审计请求
    if not cleaned.lower().startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


def is_relevant_code_url(text: str, url: str) -> bool:
    """
    检查 URL 在上下文中的相关性。
    若周围 120 字符窗口内包含明确的三方依赖、引用基准或数据集，且没有作者的自指代码声明，则予以排除。
    """
    idx = text.lower().find(url.lower())
    if idx == -1:
        # 尝试寻找 host/path 片段
        from urllib.parse import urlsplit

        try:
            path = urlsplit(url).path.strip("/")
            if path:
                idx = text.lower().find(path.lower())
        except Exception:
            pass

    if idx == -1:
        return True  # 找不到上下文，默认保留以防漏检

    start = max(0, idx - 120)
    end = min(len(text), idx + len(url) + 120)
    window = text[start:end].lower()

    strong_indicators = [
        "our code",
        "our repository",
        "we open source",
        "we open-source",
        "implementation of our",
        "we release",
        "released at",
        "source code of",
        "our framework",
        "source code is at",
        "implementation is at",
        "code is available",
    ]
    exclusion_indicators = [
        "dataset from",
        "dataset is available",
        "inspired by",
        "evaluation baseline",
        "refer to",
        "third-party",
        "existing tool",
        "benchmark from",
        "benchmark is at",
    ]

    has_strong = any(word in window for word in strong_indicators)
    has_exclude = any(word in window for word in exclusion_indicators)

    if has_exclude and not has_strong:
        logger.info(
            "is_relevant_code_url: 链接 %s 在上下文中被判定为第三方基准/数据集或依赖，将被剔除。上下文窗口: %r",
            url,
            window,
        )
        return False

    return True


def extract_repo_urls_from_text(text: str) -> List[str]:
    """
    从给定的清洗后的文本中提取符合规范的 GitHub, GitLab, Gitee, Bitbucket, OpenI, HuggingFace, ModelScope, Zenodo, OSF 链接。
    """
    # 替换转义字符如 \_ 为 _，防止正则截断
    cleaned_text = text.replace(r"\_", "_").replace(r"\-", "-").replace(r"\\", "")

    found_urls = []
    seen = set()

    # 提取所有候选正则匹配
    for pattern in [
        GITHUB_PATTERN,
        OTHER_GIT_PATTERN,
        HF_PATTERN,
        MODELSCOPE_PATTERN,
        DATA_ARCHIVE_PATTERN,
    ]:
        for match in pattern.finditer(cleaned_text):
            url = match.group(0)
            cleaned_url = clean_extracted_url(url)

            # 判断 owner 是否为保留字（针对 GitHub/GitLab）
            if "github.com" in cleaned_url.lower():
                sub_match = re.search(
                    r"github\.com/([a-zA-Z0-9-_]+)", cleaned_url, re.IGNORECASE
                )
                if sub_match and sub_match.group(1).lower() in BLACK_LIST_ORGS:
                    continue

            if cleaned_url not in seen:
                if is_relevant_code_url(cleaned_text, cleaned_url):
                    seen.add(cleaned_url)
                    found_urls.append(cleaned_url)

    return found_urls


def extract_code_urls(
    markdown_content: str, mineru_dir: Optional[str] = None
) -> List[str]:
    """
    从论文的 Markdown 源码中提取所有的代码仓库链接（包含 GitHub 和其他主流 Git 平台），并进行去重和清洗。
    如果提供了 mineru_dir，则会尝试通过 content_list.json 进行智能结构化提取，排除参考文献 (ref_text)。

    Args:
        markdown_content (str): 论文的 Markdown 文本内容
        mineru_dir (str, optional): MinerU 提取包的解压目录路径

    Returns:
        List[str]: 去重清洗后的代码/资源链接列表
    """
    # 1. 尝试使用结构化的 content_list.json 提取
    if mineru_dir and os.path.exists(mineru_dir):
        content_list_file = None
        for file in os.listdir(mineru_dir):
            if file.endswith("content_list.json"):
                content_list_file = os.path.join(mineru_dir, file)
                break

        if content_list_file:
            try:
                with open(content_list_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                all_urls = []
                seen = set()

                # 排除 ref_text 类型（参考文献）以阻断第三方被引系统的虚警干扰
                for item in data:
                    item_type = item.get("type", "")
                    if item_type == "ref_text":
                        continue

                    text = item.get("text", "")
                    if text:
                        extracted = extract_repo_urls_from_text(text)
                        for url in extracted:
                            if url not in seen:
                                seen.add(url)
                                all_urls.append(url)

                if all_urls:
                    logger.info(
                        "extract_code_urls: 成功通过结构化 JSON 剔除参考文献后提取出 %s 个候选链接",
                        len(all_urls),
                    )
                    return all_urls
            except Exception as e:
                logger.warning(
                    "extract_code_urls: 读取或解析 content_list.json 发生异常: %s", e
                )

    # 2. 降级备选：对 markdown_content 进行正文切片提取
    if not markdown_content:
        return []

    content_unescaped = (
        markdown_content.replace(r"\_", "_").replace(r"\-", "-").replace(r"\\", "")
    )

    # 定位参考文献/致谢分界线
    ref_match = None
    ref_headers = [
        r"\n#+\s+References",
        r"\n#+\s+参考文献",
        r"\n#+\s+BIBLIOGRAPHY",
        r"\n#+\s+Bibliography",
        r"\n#+\s+ACKNOWLEDGEMENTS?",
        r"\n#+\s+ACKOWNLEDGEMENTS?",
        r"\n#+\s+致谢",
        r"\nREFERENCES\s*\n",
        r"\nBIBLIOGRAPHY\s*\n",
    ]
    for pattern in ref_headers:
        ref_match = re.search(pattern, content_unescaped, re.IGNORECASE)
        if ref_match:
            break

    # 检索 brackets citation fallback [1]
    if not ref_match:
        text_len = len(content_unescaped)
        search_start = int(text_len * 0.6)
        bracket_match = re.search(r"\n\[1\]\s+", content_unescaped[search_start:])
        if bracket_match:
            body_content = content_unescaped[: search_start + bracket_match.start()]
        else:
            body_content = content_unescaped
    else:
        body_content = content_unescaped[: ref_match.start()]

    return extract_repo_urls_from_text(body_content)


class GitHubAuditor:
    """仓库/AI Hub 深度可复现性审计与核验类。"""

    def __init__(self, github_token: Optional[str] = None):
        """
        初始化审计器，可选传入 GITHUB_TOKEN 以避免速率限制。

        Args:
            github_token (str, optional): GitHub 个人访问令牌 (PAT)
        """
        self.github_token = github_token

    def _get_headers(self) -> Dict[str, str]:
        """
        构建 GitHub API 请求头部标头，注入 Token 和必要 User-Agent。
        """
        headers = {
            "User-Agent": "paperfetch-agent",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    async def audit_url(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        审计单个代码库/AI模型库链接。根据域名分流执行不同校验逻辑。

        Args:
            code_url (str): 仓库的 URL 链接

        Returns:
            Tuple[str, Dict[str, Any]]: (状态标签, 审计元数据字典)
        """
        cleaned_url = clean_extracted_url(code_url)
        lowered_url = cleaned_url.lower()

        if "github.com" in lowered_url:
            return await self._audit_github(cleaned_url)
        elif "huggingface.co" in lowered_url or "hf.co" in lowered_url:
            return await self._audit_huggingface(cleaned_url)
        elif "modelscope.cn" in lowered_url:
            return await self._audit_modelscope(cleaned_url)
        elif "zenodo.org" in lowered_url:
            return await self._audit_zenodo(cleaned_url)
        elif "osf.io" in lowered_url:
            return await self._audit_osf(cleaned_url)
        else:
            return await self._audit_other_platform(cleaned_url)

    async def _audit_github(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        对 GitHub 仓库调用 REST API 进行深度可复现性核验。
        """
        match = re.search(
            r"github\.com/([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-\.]+)",
            code_url,
            re.IGNORECASE,
        )
        if not match:
            return "repo_404", {
                "error": "无法从 URL 中解析出 owner 和 repo",
                "url": code_url,
                "category": "code_repository",
            }

        owner = match.group(1)
        repo = match.group(2)

        if owner.lower() in BLACK_LIST_ORGS:
            return "repo_404", {
                "error": "GitHub 官方保留字，非代码仓库",
                "url": code_url,
                "category": "code_repository",
            }

        api_base = f"https://api.github.com/repos/{owner}/{repo}"
        headers = self._get_headers()
        metadata = {
            "owner": owner,
            "repo": repo,
            "url": code_url,
            "platform": "github",
            "category": "code_repository",
            "stars": 0,
            "is_fork": False,
            "detected_configs": [],
            "inventory_file_count": 0,
            "code_file_count": 0,
            "notebook_count": 0,
            "entrypoint_count": 0,
            "inventory_digest": None,
        }

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            try:
                repo_resp = await client.get(api_base, headers=headers)

                if repo_resp.status_code == 401 and self.github_token:
                    logger.warning(
                        "GitHubAuditor: Token 认证无效 (401)，已自动降级为匿名请求核验..."
                    )
                    anon_headers = {
                        "User-Agent": "paperfetch-agent",
                        "Accept": "application/vnd.github.v3+json",
                    }
                    repo_resp = await client.get(api_base, headers=anon_headers)

                if repo_resp.status_code == 404:
                    logger.warning(f"GitHubAuditor: 仓库不存在 (404) -> {code_url}")
                    return "repo_404", {
                        "error": "仓库不存在 (404)",
                        "url": code_url,
                        "category": "code_repository",
                    }

                if repo_resp.status_code in (401, 403):
                    logger.warning(
                        f"GitHubAuditor: API 限流或无权(HTTP {repo_resp.status_code})，降级为常规网页校验..."
                    )
                    web_resp = await client.head(code_url, follow_redirects=True)
                    if web_resp.status_code >= 400:
                        web_resp = await client.get(code_url, follow_redirects=True)
                    if 200 <= web_resp.status_code < 400:
                        return "verified_accessible", {
                            "error": "API限制降级网页可通",
                            "url": code_url,
                            "category": "code_repository",
                        }
                    else:
                        return "repo_404", {
                            "error": f"降级网页不可达 ({web_resp.status_code})",
                            "url": code_url,
                            "category": "code_repository",
                        }

                repo_resp.raise_for_status()
                repo_info = repo_resp.json()

                full_name = repo_info.get("full_name") or f"{owner}/{repo}"
                if "/" in full_name:
                    real_owner, real_repo = full_name.split("/", 1)
                    if real_owner != owner or real_repo != repo:
                        logger.info(
                            "GitHubAuditor: 检测到仓库重定向 301，自动校准: %s/%s -> %s/%s",
                            owner,
                            repo,
                            real_owner,
                            real_repo,
                        )
                        owner, repo = real_owner, real_repo
                        metadata["owner"] = real_owner
                        metadata["repo"] = real_repo
                        api_base = (
                            f"https://api.github.com/repos/{real_owner}/{real_repo}"
                        )

                metadata["stars"] = repo_info.get("stargazers_count", 0)
                metadata["is_fork"] = repo_info.get("fork", False)
                metadata["last_pushed"] = repo_info.get("pushed_at")

                if repo_info.get("size") == 0 and not repo_info.get("default_branch"):
                    return "empty_repo", metadata

                inventory_entries = []
                inventory_source = None
                inventory_complete = False
                default_branch = str(repo_info.get("default_branch") or "")
                if default_branch:
                    tree_url = f"{api_base}/git/trees/{quote(default_branch, safe='')}?recursive=1"
                    tree_resp = await client.get(tree_url, headers=headers)
                    if tree_resp.status_code == 200:
                        tree_payload = tree_resp.json()
                        if isinstance(tree_payload, dict) and isinstance(
                            tree_payload.get("tree"), list
                        ):
                            inventory_entries = tree_payload["tree"]
                            inventory_source = "github_recursive_tree"
                            inventory_complete = not bool(tree_payload.get("truncated"))

                contents_url = f"{api_base}/contents"
                contents_resp = None
                if not inventory_entries:
                    contents_resp = await client.get(contents_url, headers=headers)

                if (
                    contents_resp is not None
                    and contents_resp.status_code == 401
                    and self.github_token
                ):
                    anon_headers = {
                        "User-Agent": "paperfetch-agent",
                        "Accept": "application/vnd.github.v3+json",
                    }
                    contents_resp = await client.get(contents_url, headers=anon_headers)

                if contents_resp is not None and contents_resp.status_code != 200:
                    if contents_resp.status_code in (401, 403):
                        return "verified_accessible", metadata
                    return "empty_repo", metadata

                if not inventory_entries:
                    contents = contents_resp.json()
                    if not isinstance(contents, list):
                        return "empty_repo", metadata
                    inventory_entries = contents
                    inventory_source = "github_root_contents"
                    inventory_complete = not any(
                        str(item.get("type") or "").lower() in {"dir", "tree"}
                        for item in contents
                    )

                inventory = summarize_repository_inventory(inventory_entries)
                metadata.update(inventory)
                metadata["inventory_source"] = inventory_source
                metadata["inventory_complete"] = inventory_complete

                has_code_payload = bool(
                    inventory["code_file_count"] or inventory["notebook_count"]
                )
                if not has_code_payload:
                    if inventory_complete:
                        logger.warning(
                            "GitHubAuditor: 仓库中未检测到代码 payload -> %s", code_url
                        )
                        return "repository_no_code_payload", metadata
                    logger.warning(
                        "GitHubAuditor: 仓库 inventory 不完整，无法判定代码 payload -> %s",
                        code_url,
                    )
                    return "repository_inventory_incomplete", metadata
                if inventory["detected_configs"]:
                    metadata["runtime_validation"] = "not_attempted"
                    metadata["runnable_evidence"] = False
                    metadata["runnable_blocker"] = (
                        "entrypoint_not_detected"
                        if not inventory["has_entry_script"]
                        else "isolated_runtime_smoke_not_completed"
                    )
                    return "verified_accessible", metadata
                logger.warning(
                    "GitHubAuditor: 仓库有代码但未检测到有效依赖配置 -> %s", code_url
                )
                return "missing_env_config", metadata

            except Exception as exc:
                logger.error(
                    f"GitHubAuditor: 核验 GitHub 仓库发生网络异常 -> {code_url}: {exc}"
                )
                return "unchecked", {
                    "error": f"核验网络异常: {exc}",
                    "url": code_url,
                    "category": "code_repository",
                }

    async def _audit_huggingface(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        对 Hugging Face 平台执行 API 级深度可复现性与存活审计。
        """
        match = re.search(
            r"(?:huggingface\.co|hf\.co)/(?:datasets/|spaces/)?([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-\.]+)",
            code_url,
            re.IGNORECASE,
        )
        if not match:
            status, meta = await self._http_status_check(code_url)
            return status, {
                **meta,
                "url": code_url,
                "platform": "huggingface",
                "category": "ai_hub",
            }

        owner = match.group(1)
        repo = match.group(2).rstrip(".,;)")
        repo_id = f"{owner}/{repo}"

        is_dataset = "datasets/" in code_url.lower()
        is_space = "spaces/" in code_url.lower()

        metadata = {
            "owner": owner,
            "repo": repo,
            "url": code_url,
            "platform": "huggingface",
            "category": "ai_hub",
            "downloads": 0,
            "likes": 0,
            "detected_configs": [],
        }

        headers = {"User-Agent": "paperfetch-agent"}

        api_urls = []
        if is_dataset:
            api_urls.append(f"https://huggingface.co/api/datasets/{repo_id}")
        elif is_space:
            api_urls.append(f"https://huggingface.co/api/spaces/{repo_id}")
        else:
            api_urls.append(f"https://huggingface.co/api/models/{repo_id}")
            api_urls.append(f"https://huggingface.co/api/datasets/{repo_id}")

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = None
            for api_url in api_urls:
                try:
                    r = await client.get(api_url, headers=headers)
                    if r.status_code == 200:
                        resp = r
                        break
                except Exception:
                    pass

            if resp is None:
                status, meta = await self._http_status_check(code_url)
                return status, {**metadata, **meta}

            info = resp.json()
            metadata["likes"] = info.get("likes", 0)
            metadata["downloads"] = info.get("downloads", 0)

            siblings = info.get("siblings", [])
            file_names = {item.get("rpath", "").lower() for item in siblings}

            config_patterns = {
                "config.json": "model_config",
                "requirements.txt": "python_requirements",
                "setup.py": "python_setup",
                "pyproject.toml": "python_pyproject",
                "environment.yml": "conda_env",
                "environment.yaml": "conda_env",
            }

            has_dataset_script = False
            if "dataset" in str(resp.url).lower():
                script_name = f"{repo.lower()}.py"
                if script_name in file_names:
                    has_dataset_script = True
                    metadata["detected_configs"].append("dataset_script")

            detected = []
            for name, tag in config_patterns.items():
                if name in file_names:
                    detected.append(tag)
            metadata["detected_configs"].extend(detected)

            if detected or has_dataset_script:
                metadata["runtime_validation"] = "not_attempted"
                metadata["runnable_evidence"] = False
                return "verified_accessible", metadata
            else:
                return "verified_accessible", metadata

    async def _audit_modelscope(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        对 ModelScope 平台执行 API 级深度可复现性与存活审计。
        """
        match = re.search(
            r"modelscope\.cn/(?:datasets/|models/)?([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-\.]+)",
            code_url,
            re.IGNORECASE,
        )
        if not match:
            status, meta = await self._http_status_check(code_url)
            return status, {
                **meta,
                "url": code_url,
                "platform": "modelscope",
                "category": "ai_hub",
            }

        owner = match.group(1)
        repo = match.group(2).rstrip(".,;)")
        repo_id = f"{owner}/{repo}"

        is_dataset = "datasets/" in code_url.lower()

        metadata = {
            "owner": owner,
            "repo": repo,
            "url": code_url,
            "platform": "modelscope",
            "category": "ai_hub",
            "detected_configs": [],
        }

        headers = {"User-Agent": "paperfetch-agent"}

        api_urls = []
        if is_dataset:
            api_urls.append(
                f"https://modelscope.cn/api/v1/datasets/{repo_id}/repo/files?recursive=true"
            )
        else:
            api_urls.append(
                f"https://modelscope.cn/api/v1/models/{repo_id}/repo/files?recursive=true"
            )
            api_urls.append(
                f"https://modelscope.cn/api/v1/datasets/{repo_id}/repo/files?recursive=true"
            )

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = None
            for api_url in api_urls:
                try:
                    r = await client.get(api_url, headers=headers)
                    if r.status_code == 200:
                        resp = r
                        break
                except Exception:
                    pass

            if resp is None:
                status, meta = await self._http_status_check(code_url)
                return status, {**metadata, **meta}

            info = resp.json()
            files_data = info.get("Data", {}).get("Files", [])
            file_names = {item.get("Name", "").lower() for item in files_data}

            config_patterns = {
                "config.json": "model_config",
                "requirements.txt": "python_requirements",
                "setup.py": "python_setup",
                "configuration.json": "model_configuration",
            }

            detected = []
            for name, tag in config_patterns.items():
                if name in file_names:
                    detected.append(tag)
            metadata["detected_configs"] = detected

            if detected:
                metadata["runtime_validation"] = "not_attempted"
                metadata["runnable_evidence"] = False
                return "verified_accessible", metadata
            else:
                return "verified_accessible", metadata

    async def _audit_zenodo(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {
            "url": code_url,
            "platform": "zenodo",
            "category": "data_archive",
            "http_status": 0,
        }
        status, meta = await self._http_status_check(code_url)
        metadata.update(meta)
        return status, metadata

    async def _audit_osf(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        metadata = {
            "url": code_url,
            "platform": "osf",
            "category": "data_archive",
            "http_status": 0,
        }
        status, meta = await self._http_status_check(code_url)
        metadata.update(meta)
        return status, metadata

    async def _http_status_check(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        轻量级通用 HTTP 存活性检查。
        """
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                resp = await client.head(code_url, headers=headers)
                if resp.status_code >= 400:
                    resp = await client.get(code_url, headers=headers)

                if 200 <= resp.status_code < 400:
                    return "verified_accessible", {"http_status": resp.status_code}
                else:
                    return "repo_404", {
                        "http_status": resp.status_code,
                        "error": f"HTTP status error: {resp.status_code}",
                    }
            except Exception as e:
                return "repo_404", {"error": f"Network exception: {e}"}

    async def _audit_other_platform(self, code_url: str) -> Tuple[str, Dict[str, Any]]:
        """
        对 GitLab/Gitee/Bitbucket/OpenI 等其他平台发起深度依赖配置审计。
        通过探测其 RAW 接口的配置文件（requirements.txt 等）来判定其 runnable 状态。
        """
        match = re.search(
            r"(gitee\.com|gitlab\.com|bitbucket\.org|openi\.org\.cn)/([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-\.]+)",
            code_url,
            re.IGNORECASE,
        )
        if not match:
            status, meta = await self._http_status_check(code_url)
            return status, {
                **meta,
                "url": code_url,
                "platform": "other",
                "category": "code_repository",
            }

        domain = match.group(1).lower()
        owner = match.group(2)
        repo = match.group(3).rstrip(".,;)")

        platform = "other"
        if "gitee.com" in domain:
            platform = "gitee"
        elif "gitlab.com" in domain:
            platform = "gitlab"
        elif "bitbucket.org" in domain:
            platform = "bitbucket"
        elif "openi.org.cn" in domain:
            platform = "openi"

        metadata = {
            "owner": owner,
            "repo": repo,
            "url": code_url,
            "platform": platform,
            "category": "code_repository",
            "detected_configs": [],
        }

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            try:
                home_resp = await client.get(code_url, headers=headers)
                if home_resp.status_code >= 400:
                    logger.warning(
                        "_audit_other_platform: 仓库主页不可达 %s (status: %s)",
                        code_url,
                        home_resp.status_code,
                    )
                    return "repo_404", {
                        "error": f"仓库主页返回状态码: {home_resp.status_code}",
                        "url": code_url,
                        "platform": platform,
                        "category": "code_repository",
                    }
            except Exception as e:
                logger.warning(
                    "_audit_other_platform: 请求主页发生网络异常 %s: %s", code_url, e
                )
                return "repo_404", {
                    "error": f"主页连接异常: {e}",
                    "url": code_url,
                    "platform": platform,
                    "category": "code_repository",
                }

            branches = ["main", "master", "develop"]
            config_files = [
                "requirements.txt",
                "setup.py",
                "pyproject.toml",
                "environment.yml",
                "environment.yaml",
                "package.json",
                "pom.xml",
                "Dockerfile",
            ]

            detect_tasks = []

            async def probe_file(branch: str, filename: str) -> Optional[str]:
                if platform == "gitee":
                    raw_url = (
                        f"https://gitee.com/{owner}/{repo}/raw/{branch}/{filename}"
                    )
                elif platform == "gitlab":
                    raw_url = (
                        f"https://gitlab.com/{owner}/{repo}/-/raw/{branch}/{filename}"
                    )
                elif platform == "bitbucket":
                    raw_url = (
                        f"https://bitbucket.org/{owner}/{repo}/raw/{branch}/{filename}"
                    )
                elif platform == "openi":
                    raw_url = f"https://openi.org.cn/{owner}/{repo}/raw/branch/{branch}/{filename}"
                else:
                    return None

                try:
                    resp = await client.head(raw_url, headers=headers, timeout=5.0)
                    if resp.status_code == 200:
                        return filename
                except Exception:
                    pass
                return None

            for branch in branches:
                for filename in config_files:
                    detect_tasks.append(probe_file(branch, filename))

            results = await asyncio.gather(*detect_tasks)
            detected_configs = list(set([res for res in results if res is not None]))

            metadata["detected_configs"] = detected_configs
            if detected_configs:
                metadata["runtime_validation"] = "not_attempted"
                metadata["runnable_evidence"] = False
                return "verified_accessible", metadata
            else:
                return "missing_env_config", metadata
