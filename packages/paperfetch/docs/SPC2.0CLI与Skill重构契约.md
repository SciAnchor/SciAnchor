# SPC 2.0 CLI 与 Skill 重构契约

状态：SPC 2.0 权威公共交互契约。

## 1. 目的

SPC 2.0 的目标是清理和简化产品，而不是增加新的协议层。用户和 Agent 不需要理解
进程监管、浏览器上下文、事件、审计文件或内部状态机，只需要知道 SPC 能做什么、应调用
哪个命令、任务是否完成、文件在哪里，以及失败后怎么办。

公共架构只有两层：Skill 负责选择和解释命令，`spc` CLI 是唯一执行入口。
Codex Plugin 只是 Skill 的安装包装。SPC 不再提供 MCP，也不再维护独立的
`agent-guide` 命令契约。

## 2. 不变边界

- 保留论文检索、合法下载、PDF 身份验证、MinerU、Seed Pack、公共数据集和客观 Workflow
  readiness 领域内核。
- `papers.jsonl` 继续是 Seed Pack 论文事实的唯一权威文件。
- 已验证 PDF 和 MinerU 文件清单继续记录物理文件、字节和 SHA-256。
- SPC 不承担选题判断、论文评价或 CAPTCHA/MFA 绕过。

## 3. 命令树

核心命令按领域组织（实际命令树以 `spc --help` 为准）：

```text
spc version
spc doctor
spc schema [command]
spc system capabilities|preflight|source-status
spc paper search|graph|lookup|download|parse
spc seed-pack init|show|add|enrich
spc job list|show|wait|cancel
spc dataset ...
spc validate download
spc workflow ...
```

数据源和验收的旧顶层动词必须迁入所属领域。删除 `mcp`、`agent-guide`、
`job status`、`job watch` 和 `job result`。

## 4. 唯一公共结果

所有 JSON 命令输出 `spc.result.v2`。字段仅允许：

```text
schema status job_id data files results error
```

空的可选字段不输出。状态仅允许：

```text
queued running cancelling completed partial failed cancelled
```

`finished`、`orphaned` 和 `lifecycle` 不进入公共结果。内部 worker 消失对外表现为
`failed` 与 `error.code=job_process_disappeared`。

错误默认只包含 `code`、`message`、`stage` 和 `next`。`retryable` 仅在可稍后重试时出现。
hops、页面快照、浏览器种类、路由尝试、进程、metrics、audit 和 traceback 只进入显式调试记录。

## 5. 下载事实

论文下载结果必须保留：

```json
{
  "download": {
    "route": "europe_pmc",
    "access": "public",
    "identity_verified": true
  }
}
```

`route` 只表示本次最终成功且通过论文身份验证的途径，例如 `local`、`europe_pmc`、`pmc`、
`arxiv`、`publisher_api` 和 `public_http`。本地或全局缓存命中统一返回 `route=local` 和
`access=local`。

`paper download --route auto` 允许本安装中最佳的合法路线；`--route public` 只允许开放/公开
路线。paperfetch 不包含机构订阅路线。

`doctor` 只输出 `data.verdict`、`data.checks[]`、`data.blockers[]`。它回答配置和运行面，
不回答某篇论文的 PDF 是否可获取。

## 6. Job

`--detach` 返回 `status=queued` 与 `job_id`。`job show` 只返回紧凑快照；`job wait`
等待后直接返回原命令的最终 `spc.result.v2`；`job cancel` 幂等，并在 worker 与本任务
浏览器进程树全部退出后才返回 cancelled。

Job 内部状态更新必须有事务或版本比较，记录 PID、进程启动身份、process group、owner
token、heartbeat 和 deadline，禁止 cancel 与 worker 用旧记录覆盖对方终局。

## 7. stdout、stderr 与调试

- JSON 模式 stdout 恰好一个最终文档。
- 默认 stderr 为空。
- `help` 和 `version` 不生成 INFO 或终止事件。
- `-v` 才向 stderr 输出简短阶段进度。
- `--debug` 和 `--log-file` 保存完整诊断；默认不显示 traceback。
- 参数、环境、业务和内部错误都必须生成稳定 JSON；秘密始终脱敏。

网络类论文下载失败后，Skill 使用同一个 `doctor --probe-traffic-classes` 入口读取代理通路检查。
代理端点不可达和 407 认证失败可以确诊；通路检查 ok 只证明探针可达。

## 8. 单一命令树

每个命令只在所属领域的 argparse registrar 中注册一次，`build_parser()` 是唯一组装
入口。help、`spc schema`、Skill 命令契约测试和叶子命令快照都必须从这棵实时
parser 树产生。risk 和 execution mode 是 `spc schema` 对命令路径的薄投影；若增加新
命令类型，必须同提交更新该投影和契约测试。不再维护 MCP 工具表、Agent Guide
命令表或其他平行命令清单。

## 9. 发布门禁

- 所有叶子命令 `--help` 退出 0 且 stderr 为空。
- 默认 JSON 恰好一个可解析文档；失败也不例外。
- Job wait/cancel、worker 消失、PID 身份和并发终局通过 Linux integration 测试。
- Skill 中每条命令均由当前 parser 验证。
- 当前代码、依赖、插件和现行文档不存在 SPC MCP 入口。
- 发布 wheel 只从干净提交构建（见 `scripts/build_release.py`）。
