# SPC 2.0 架构基线

本文记录 paperfetch 稳定的产品边界、运行环境、模块、数据和测试决策。命令与参数以实时
`spc --help` 和 `spc schema` 为准。

## 1. 产品边界

SPC 是 Linux 上的科研资源 CLI，负责论文与公共数据的检索、合法获取、身份校验、本地文件和
客观就绪事实。Agent（或用户）负责选题、判断、分析和写作。SPC 不保存 Agent 评审、不执行
领域科研方法。

- 公共 Agent 架构只有 `Skill -> spc CLI -> 领域服务`，没有 SPC MCP，也没有 `agent-guide`。
- Codex Plugin 只是 Skill 的安装包，不是业务或运行时层。
- CLI 的实时 parser 是命令权威，`spc schema` 为 Agent 生成机器可读参数契约。
- 一个公共结果状态同时表达作业执行和业务终局，Agent 不需要合并两套状态机。
- 详细路由尝试、浏览器事件、性能和进程信息属于 debug/audit，不进入默认结果。
- 下载路线、访问类型和 PDF 身份校验是公共业务事实，不能被“简化”掉。

paperfetch 只包含开放获取、官方 API 与公开 HTTP 路线；不包含机构图书馆/订阅访问，也不内置
商业期刊评价数据。

## 2. 运行环境

| `SPC_ENVIRONMENT` | 含义 | 默认状态目录 |
| --- | --- | --- |
| `development`（默认） | 源码检出 + `pip install -e .` | `~/.spc/{state,cache,data,logs}` |
| `production` | 从 wheel 安装的不可变 release | 由安装位置决定，见 `spc system preflight` |

`SPC_ENVIRONMENT`、`spc --environment` 与 `spc system preflight --profile` 是同一个值；声明与
实际运行位置不一致时 `doctor` / `preflight` 失败。`SPC_LOG_MODE` 只控制日志详细程度，不能代替
环境身份。凭据默认从 `~/.config/spc/secrets.env` 读取，也可用 `--env-file` 显式指定；仓库根的
`.env` 不会被自动加载。

`SPC_STATE_ROOT`、`SPC_CACHE_ROOT`、`SPC_DATA_ROOT` 可把状态、缓存与数据移到任意持久目录。
缓存与状态不得位于源码、wheel、`site-packages` 或 Seed Pack 目录中。

## 3. 模块边界

```text
core           配置、错误、公共结果、事件、事务
jobs           后台执行、等待、取消、心跳与进程树回收
papers         标识、检索、引用图和元数据
sources        OpenAlex、Crossref、Semantic Scholar、PubMed 等元数据源适配器
fulltext       单篇 PDF 获取/身份校验、MinerU 解析与无绑定本地解析
downloaders    合法下载方式（OA、官方 API、公开 HTTP）
artifacts      内部文件与哈希管理
seedpacks      Seed Pack 原子事务
datasets       GEO、NCBI、Dryad、Zenodo、Figshare 等公共数据适配器
workflows      客观资源 readiness
cli            唯一 Agent/自动化公共适配层
```

下载器、解析器不直接修改 PaperRecord。Seed Pack 更新由事务层完成“读取最新记录、合并、校验
实际文件、暂存、原子替换、重新读取”。

## 4. CLI 和公共信息契约

命令是否存在及参数选择以 `spc --help`、子命令 `--help` 和 `spc schema <command path>` 为准。
所有默认 JSON 使用 `spc.result.v2`，顶层只有：

```text
schema status job_id data files results error
```

空字段可以不输出。公共状态只有：

```text
queued running cancelling completed partial failed cancelled
```

后台任务统一使用：

```text
spc job list
spc job show <job-id>
spc job wait <job-id> --timeout-seconds 300
spc job cancel <job-id>
```

stdout 只放一个最终业务 JSON；默认 stderr 为空；`-v`/`--debug`/显式日志文件才提供诊断。
详见 [CLI 与 Skill 契约](SPC2.0CLI与Skill重构契约.md)。

## 5. 论文下载事实

`paper lookup` 只查元数据；`paper download` 获取并验证 PDF，默认继续 MinerU；`paper parse`
对本地 PDF 做无论文身份绑定的物理解析；`seed-pack enrich` 补齐已有记录。

- `--route auto` 允许本安装中最佳的合法路线；`--route public` 只允许开放/公开路线。
- 成功结果保留 `download.route`、`download.access`、`download.identity_verified`。
- PDF 成功必须同时满足真实 `%PDF-`、非空字节、SHA-256、目标论文身份和原子落盘。
- PDF 成功但 MinerU 失败为 `partial`，已验证 PDF 仍必须返回。
- `doctor` 只报告 `verdict` / `checks` / `blockers`，不等于真实下载成功。

网络类下载失败通过 `spc doctor --probe-traffic-classes` 诊断。端点不可达和 407 认证失败可以
确诊；其余只是候选原因。详见 [论文全文下载架构](论文全文下载架构.md)。

## 6. 网络与代理

SPC 只消费显式配置的 HTTP 代理，不读取 ambient system proxy。`METADATA_PROXY`、
`DOWNLOAD_PROXY`、`MINERU_PROXY`、`ARCHIVE_PROXY` 各自独立，不允许某个通用开关隐式改变其他
能力的出口。数据集路线使用来源专属配置（如 `SPC_GEO_PROXY`、`ARCHIVE_PROXY`）。公共结果只
返回 `resolved_route` 与不可逆 `proxy_ref`，不返回代理 host、port、认证或出口。

SPC 可以在硬截止时间内被动等待页面声明的自动验证；复选框、hCaptcha、Turnstile、MFA、扫码
或其他人工动作必须返回 `unattended_auth_blocked`，不点击、不绕过、不调用挑战求解服务。

## 7. 配置与安全边界

完整字段名、类型、默认值、密级和所属能力以 `spc schema config` 与
`src/paperfetch/data/config/settings.schema.json` 为准，不在文档手抄变量表。
非密配置可进入 `spc.toml`（`SPC_CONFIG_FILE`）；API Key 等凭据只进入权限收敛的
`secrets.env`。未注册的 `SPC_*` 变量会让 `doctor` 与 `system preflight` 失败。

凭据、代理认证、会话和研究数据不得进入 Git、stdout、stderr、事件或日志。

## 8. Seed Pack 与数据

```text
seed-pack/
├─ manifest.json
├─ papers.jsonl
├─ artifacts/<paper-id>/
│  ├─ pdf/<sha-prefix>/article.pdf
│  └─ fulltext/mineru-<version>-<pdf-sha-prefix>/...
└─ .spc/{transactions,staging,locks,audit}/
```

`papers.jsonl` 是 Seed Pack 论文事实的唯一权威文件。旧 0.x `seed_papers.jsonl` 包返回稳定的
不支持错误，不静默迁移。解析成功只证明物理 Markdown 存在，不能追认论文身份。公共数据的
manifest readiness、payload readiness、许可和 checksum 分层保留；文章 PDF 与 Supporting
Information 不得混同。详见 [Seed Pack 契约](智能体种子包契约.md)。

## 9. 测试与构建

测试标记为 `unit|contract|integration|browser|live|release`。日常离线运行：

```bash
python -m pytest -q -m "not online and not live and not release and not browser"
```

`scripts/build_release.py` 从 Git archive（干净、已提交的 Python 3.12 SHA）构建唯一 wheel，
并生成包含 Git SHA、wheel 名称、字节和 SHA-256 的 manifest；`scripts/verify_release.py`
校验 manifest 与 wheel 一致。

## 10. 2.0 迁移删除清单

| 旧表面 | 2.0 决策 |
| --- | --- |
| SPC MCP、MCP 配置与依赖 | 删除；不保留兼容壳 |
| `spc agent-guide` | 删除；用 live parser + `spc schema` |
| `job status/watch/result` | 删除；用 `list/show/wait/cancel` |
| 分离的 Job lifecycle 与业务终局 | 公共投影合并为一个 `status` |
| 顶层 download/data/source 旧命令 | 迁入 `validate`、`dataset`、`system` 域 |
| 默认大型结果、metrics/audit/process 字段 | 默认不暴露；通过显式 debug/audit 诊断 |
