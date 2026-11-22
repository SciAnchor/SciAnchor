# 下载模块架构说明

> 版本：5.0（公开版）

## 1. 模块职责

`downloaders/` 负责根据论文标识和元数据发现合法的开放获取 PDF 候选、执行下载、管理并发、校验文件、维护缓存并生成审计记录。

公开版只包含开放获取与出版商官方 API 路线，不包含任何机构订阅、校园网/WebVPN、联合认证（Shibboleth/SAML）登录或反检测浏览器能力。

生产链路必须满足：

- `curate`、`enrich-seed-pack`、`lookup --download` 无人值守，不等待人工处理挑战。
- 每次尝试都能关联 DOI、出版社、route、阶段、耗时和稳定失败分类。
- HTML、挑战页和无关 PDF 不得冒充下载成功。

## 2. 当前目录与所有权

```text
downloaders/
├── base.py                         # 下载上下文、结果和后端接口
├── registry.py                     # 后端注册
├── pdf_common.py                   # PDF 基础校验和共享工具
├── backends/
│   ├── http_direct.py              # 统一公开 HTTP 流式传输
│   ├── open_access_browser.py      # 允许列表内的公开动态页面/官方 OA PDF 后备
│   └── publisher_api/              # Elsevier、Springer 官方 API
├── browser/                        # OA 下载使用的无持久状态 Playwright 浏览器池
├── routing/                        # 出版商分类与官方 API 路由规划
└── pipeline/                       # direct、resolver、scheduler、orchestrator、cache、report
```

OA 浏览器池使用普通 Playwright（Chromium 或本机 Chrome），不保存登录态，不使用持久 Profile、指纹伪装或人工介入。浏览器后端只在允许列表内使用 CDP 截获已确认的 PDF 响应体，解决 Chrome 内置 Viewer 接管响应后无法物理保存的问题。

## 3. 核心抽象

### 3.1 DownloaderBackend

所有下载通道通过统一后端接口接收 `DownloadContext` 并返回 `PDFDownloadResult`。后端负责：

- 声明 route key 和并发组。
- 只处理自身支持的候选。
- 将异常转换成稳定错误分类。
- 成功时返回实际来源、最终 URL、文件路径、大小和摘要等审计信息。

### 3.2 Direct、Router、Resolver 与 Scheduler

- Direct 对 arXiv、元数据、出版社公开规则、Semantic Scholar、Unpaywall、Crossref TDM、Europe PMC、可信机构知识库（OpenAlex 精确 DOI）和 DOI landing 执行资源发现与 URL 指纹去重。
- Router 根据 DOI 和出版商生成官方 API 候选，不生成公开 URL 下载 route。
- Resolver 负责缓存和官方 API 候选顺序。
- Scheduler 管理全局与单主机并发，执行单篇候选。
- BatchOrchestrator 跨论文执行缓存预检与快速通道两个阶段。

## 4. 当前批量流程

```text
Phase 0  缓存预检
  ├── Seed Pack 本地文件
  └── 全局 PDF cache

Phase 1  快速通道并发
  ├── 本地发现：arXiv、元数据、Frontiers/MDPI/PLOS/RSNA 规则
  ├── 远程发现：Semantic Scholar、Unpaywall、Crossref TDM、Europe PMC、DOI landing
  ├── 完整 URL 指纹规范化与跨来源去重
  ├── Elsevier / Springer 官方 API（已配置时）
  ├── public_http 流式传输
  └── public_browser（允许列表内普通 200 HTML 或明确的官方公开 PDF）

终局  未获得已验证 PDF 的论文统一收敛为失败，并保留逐路由失败分类
```

Phase 1 每篇论文共享 45 秒硬截止时间：远程发现最多 10 秒，官方 API 最多 12 秒，最多传输 6 个唯一公开资源且单资源最多 20 秒；可信知识库资源享有更长的独立预算。

浏览器后备允许 Frontiers、MDPI、PLOS 和 RSNA。普通候选只有在 HTTP 已确认是动态 HTML 时进入浏览器；RSNA `10.1148/*` 的已知官方公开 PDF 可在 HTTP 挑战响应后进入一次无状态浏览器。浏览器若实际出现 Cloudflare、Turnstile、CAPTCHA、Imperva、登录页或设备确认，立即返回挑战，不点击或等待人工处理。PDF 由 CDP 响应体、Playwright 响应体或同一 BrowserContext 请求依次持久化，最终仍须通过统一 PDF 与论文身份校验。

## 5. 官方 API

`10.1016/...` DOI 在配置 `ELSEVIER_API_KEY` 时优先走 Elsevier 官方 Article Retrieval API；API 只返回首页预览或声明无全文权限时记为 `subscription_required` 并继续公开资源发现。Springer Nature 开放获取 API 在配置 `SPRINGER_API_KEY` 时启用。缺少 API 凭证只记录 `planned_skip`。

## 6. PDF 与缓存校验

基础校验包括文件存在性、最小大小、`%PDF` 魔数和摘要。统一身份验证器随后读取 PDF 元数据及前五页文本，按 DOI、arXiv ID 或题名证据绑定目标论文。文件通过后先写唯一 `.part`，再原子替换目标文件。

- `cache_hit` 只在物理校验与论文身份校验都通过后成立。
- DOI/题名明确冲突返回 `metadata_poisoned`；证据不足返回 `identity_unverified`。两类文件都移入 `PDF_CACHE_ROOT/quarantine/` 并写 JSON 审计证据。
- 新全局缓存写入包含 SHA256、目标标识和身份结果的 sidecar manifest；旧缓存缺少可信 manifest 时重新解析 PDF。
- PDF 解析在线程中执行，避免阻塞 async 下载任务；全局缓存命中可通过 manifest 与 SHA256 快速复验。
- 生产能力验收仍使用隔离 `PDF_CACHE_ROOT` 或 `--no-cache`，排除历史缓存和环境差异。

失败退避使用独立的 `failures.v2.json`。键包含论文标识、资源 fingerprint、transport、代理模式和匿名认证状态。默认 TTL 为：404/410/not-PDF 6 小时，挑战 15 分钟，网络/超时 2 分钟，429 遵循 `Retry-After` 且不超过 10 分钟。

`run_report.json` 当前格式为 `paperfetch.run-report.v3`，版本仅描述 schema。报告由统一事件流派生，每篇论文包含发现、规范化资源、传输、身份验证和唯一终局结果；聚合指标按 discovery、deduplication、transfer、verification 四组输出。

全链路验收使用 `spc validate download`。它按轮次创建隔离缓存，执行内置开放获取样本协议，验证样本结果、发现来源、PDF 身份、重复传输、Phase 1 单篇预算和 p95；任一门禁失败返回退出码 `2`。

## 7. 失败分类

| 分类 | 含义 |
|---|---|
| `publisher_challenge` | 出版商或数据面的自动 WAF 验证未在有界等待内消退 |
| `auth_required` | 公开 URL 实际要求登录 |
| `subscription_required` | 出版商官方 API 未对当前凭证提供该资源的全文 |
| `auth_failed` | 出版商或 API 拒绝当前凭证 |
| `metadata_poisoned` | PDF 身份与目标论文不一致 |
| `not_pdf` | 响应不是 PDF |
| `pdf_resource_not_discovered` | 所有发现源均未产生可执行 PDF 资源 |
| `not_found` | DOI 或页面不存在 |
| `rate_limited` | 上游限流 |
| `timeout` / `network_error` | 超时或网络失败 |
| `tool_missing` | 路由依赖缺失（例如未安装 playwright） |

失败必须进入每篇论文的 route attempts 和 `run_report.json`，不能只留在动态进度条中。

## 8. 环境变量

| 变量 | 用途 | 默认值 |
|---|---|---|
| `ELSEVIER_API_KEY` | Elsevier Article Retrieval API | 无 |
| `SPRINGER_API_KEY` | Springer Nature API | 无 |
| `PDF_CACHE_ROOT` | 全局 PDF 缓存根目录 | `<SPC_CACHE_ROOT>/pdf` |
| `PDF_BROWSER_HEADLESS` | OA 无状态浏览器模式；显式配置优先 | Linux 默认 `true` |
| `CHROME_EXECUTABLE_PATH` | OA 浏览器可选使用的本机 Chrome | 无（使用 Playwright Chromium） |
| `PDF_DIRECT_CONCURRENCY` | 快速通道并发 | `6` |
| `PDF_HOST_CONCURRENCY` | 单主机并发 | `2` |

## 9. 新公开来源验收

新增能力必须同时具备：

1. 明确 DOI/出版商适用规则，且来源为开放获取或出版商官方公开接口。
2. 隔离缓存下连续至少 3 轮无人值守成功。
3. PDF 与目标 DOI/题名一致；失败能稳定分类。
4. 单元测试、验收样本和文档同步更新。
