# 快速开始

本页是 Research Harness 中文快速上手指南。整体介绍可先看仓库根目录的 [`README.md`](../README.md)；英文首页见 [`README.en.md`](../README.en.md)，英文快速开始见 [`docs/quickstart.md`](quickstart.md)。

## 最短可用路径

这条路径用于第一次确认 RH 能在本机被 agent 使用：

```bash
git clone https://github.com/scianchor/research-harness.git
cd research-harness
./setup.sh
rh --json doctor
rh skill install --agent codex
rh skill verify --agent codex
rh skill list --group-by-suite
```

如果你使用 Claude Code、OpenCode 或 Gemini CLI，把 `--agent codex` 换成对应 profile：

```bash
rh skill install --agent claude-code
rh skill install --agent opencode
rh skill install --agent gemini
```

完成后，把下面这段交给 agent：

```text
请阅读 docs/agent-guide.md 和 docs/PAPER_MANAGEMENT.md。
围绕「robust budget pacing for online advertising」创建一个 research topic，
检索近期论文，筛选有用论文入库，并生成第一版 literature map。
所有论文必须绑定 topic 入库，关键产出要记录为 RH artifact。
```

没有 API key 也可以先完成 doctor、skills 安装、公共入口浏览和 demo story 阅读；需要 deep read、claim extraction、annotation 等模型能力时，再配置 LLM route。

## 发布边界

当前发布边界见 [docs/contracts/release-boundary.md](contracts/release-boundary.md)。
RH 稳定承诺是本地 public CLI/MCP/skills 工作流；HTTP bridge 仅是
local/internal loopback 集成面。非 loopback HTTP 绑定不受支持，也未获
release approval。Zotero 稳定范围仅限本地 `direction=push`,
`dry_run=true` validation；fake/sandbox pull/both 和 apply 证据只作为本地
gate evidence。Stable external API release：deferred。Real Zotero network
sync/apply 仍然 deferred。Public benchmark/performance claims 仍然 deferred。

## 前置要求

- Python 3.11+
- SQLite 3.35+（macOS 与大多数 Linux 发行版已内置）
- 如果要跑 deep read、claim extraction、annotation 等模型能力，需要至少一条可行的 LLM route：
  - 宿主 / 本机 CLI，例如 `codex`、`agent`（Cursor Agent）
  - OpenAI-compatible / Anthropic-compatible endpoint
  - 直接供应商 API，例如 OpenAI、Anthropic、Kimi / Moonshot
- 如果要让 Codex / Claude Code 调用 RH，需要配置 MCP server

## 安装

```bash
git clone https://github.com/scianchor/research-harness.git
cd research-harness
./setup.sh
```

`setup.sh` 会创建虚拟环境、安装核心 package、复制 `.env.example`，并执行基础 smoke check。

### 手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "packages/research_harness[dev]"
pip install -e "packages/research_harness_mcp[dev]"
cp .env.example .env
```

## 选择 LLM route

只有在你要启用 deep read、claim extraction、annotation 等模型能力时，
才需要配这一段。如果本机已经有可用的宿主 CLI 路径，`rh --json doctor`
本身不要求 API key。

### 方案 A：宿主 / 本机 CLI

```bash
LLM_PROVIDER=codex
# CODEX_MODEL=gpt-5.4-high

# 或

LLM_PROVIDER=cursor_agent
# CURSOR_AGENT_MODEL=composer-2.5-fast
```

### 方案 B：OpenAI-compatible endpoint

```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=<your-api-key>
OPENAI_MODEL=<your-model-id>
```

### 方案 C：直接供应商 API

```bash
OPENAI_API_KEY=<your-openai-key>
OPENAI_MODEL=gpt-4o-mini

# 或
ANTHROPIC_API_KEY=<your-anthropic-key>
ANTHROPIC_MODEL=claude-sonnet-4-6

# 或
KIMI_API_KEY=<your-kimi-key>
KIMI_MODEL=kimi-for-coding
```

`LLM_PROVIDER` 不是强制项，但如果你希望 RH 明确走某条路由，而不是依赖自动探测，建议显式设置。

论文检索不需要任何 key：RH 通过 Semantic Scholar、OpenAlex、Crossref、arXiv、PubMed、
OpenReview 的公开免 key 接口检索（见 [论文检索与获取](managed-paper-acquisition.md)）。推荐但非必需的联系信息：

```bash
PUBMED_EMAIL=you@example.com     # PubMed 批量检索建议填写，便于 NCBI 联系工具维护者
UNPAYWALL_EMAIL=you@example.com  # Unpaywall，用 DOI 查 OA PDF
```

多机器使用时，建议把 RH 私有运行资源统一放在一个用户级文件里，而不是分散写在
shell profile、项目 `.env` 或不同 agent 配置中：

```bash
mkdir -p ~/.config/research-harness
cp config/private.env.example ~/.config/research-harness/private.env
chmod 600 ~/.config/research-harness/private.env
```

`scripts/rh-env-keychain.sh` 启动 RH MCP 时会自动读取这个文件；在 macOS 上也会继续兼容
原来的 Keychain 读取方式。真实 `private.env` 只保存在本机，不能提交进仓库。

学术源的联系邮箱建议放在这里（不使用任何 API key）：

```bash
OPENALEX_MAILTO=you@example.com         # 同时作为 Crossref polite fallback
CROSSREF_MAILTO=you@example.com         # 可选：显式 Crossref polite mailto
```

如果安装了可选组件 SPC，它使用自己项目内的配置。

架构图/方法图可以走 contract 驱动的 illustration 路由（`figure_generate`
的 `model="illustration"`）。RH 按顺序尝试已配置的公开后端：Grok Imagine、
GPT Image、原生 Gemini。RH 只记录 set/missing readiness 和 provenance，不记录
endpoint 或 key 值：

```bash
RESEARCH_HARNESS_FIGURE_MODEL=illustration
GROK_API_KEY=...            # Grok Imagine（可选 GROK_BASE_URL）
GPT_IMAGE_API_KEY=...       # GPT Image，OpenAI-compatible（可选 GPT_IMAGE_BASE_URL）
GOOGLE_API_KEY=...          # 原生 Gemini 图像生成
RESEARCH_HARNESS_FIGURE_GEMINI_MODEL=gemini-2.5-flash-image
RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS=900
```

未设置 `RESEARCH_HARNESS_FIGURE_MODEL` 时，`figure_generate` 默认用 OpenAI
`gpt-image-2`（`OPENAI_API_KEY`）；`recraft` / `flux` / `nano-banana` 走
fal.ai（`FAL_KEY`）。测试中可用 `model="illustration-fake"` 做无网络的确定性渲染。
定量结果图从不走图像模型，而是由 `figure_suite_render` 基于已记录数据确定性渲染。

医学/PubMed 常用入口：

```bash
rh paper ingest --pmid 12345678 --topic "medical-topic"
rh paper backfill-pubmed --topic "medical-topic" --limit 100
rh search pubmed-screen --query "climate change maternal child health" --limit 100
rh paper pmc-links --topic "medical-topic"
rh paper audit-pdfs --topic "medical-topic"
```

`pubmed-screen` 的期刊分区字段只表示 `needs_external_verification`。
一区/二区筛选需要接入 JCR、CAS 或 Scimago 等外部分区数据后再确认。

## 验证安装

```bash
rh --json doctor
# 或
rhub --json doctor
```

`doctor` 现在会显示当前选中的 provider、route kind
（`host-cli`、`openai-compatible`、`anthropic-compatible`、`direct-api`），
以及本机当前能探测到的 provider 路径。

如果需要更深入的本地排障，可以显式打开 runtime diagnostics preview：

```bash
rh --json doctor --runtime-diagnostics
```

这个预览是只读的，会汇总 skill manifest、生成缓存、job ledger、
event source、artifact 路径可写性和 showcase bundle 路径等运行时健康信号。
它不会写 storage/provenance，也不会改变 orchestrator gate。

运行测试：

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
```

## 创建第一个研究 topic

```bash
rh topic init "my-research-topic"
rh paper search "my research query" --topic-id 1 --auto-ingest
rh orchestrator init --topic my-research-topic --mode standard
rh orchestrator status --topic my-research-topic
```

## 配置 Agent Skills

下面这些命令会把 RH 自带 skills 安装到对应 agent 的可发现目录中。

```bash
# 安装给 Claude Code
rh skill install --agent claude-code

# 安装给 Codex
rh skill install --agent codex

# 安装给 OpenCode / Gemini CLI
rh skill install --agent opencode
rh skill install --agent gemini

# 或安装到共享兼容目录
rh skill install --target ~/.agents/skills

# 按公共任务套件查看 RH 自带 skills
rh skill list --group-by-suite

# 或只筛选一个套件
rh skill list --suite paper
```

原生宿主目录优先用于对外宣称支持：

- OpenCode: `~/.config/opencode/skills`
- Gemini CLI: `~/.gemini/skills`
- Codex: `~/.codex/skills`
- Claude Code: `~/.claude/skills`

如果你想用一个共享目录给多个 agent CLI 复用，`~/.agents/skills`
可以作为低成本选项。

## 当前多工具支持状态

| 工具 / 接入面 | 当前状态 | 说明 |
|---|---|---|
| Codex | 已验证 | skills 安装 profile 与 MCP 工作流可用 |
| Claude Code | 宿主接入已验证 | MCP + skills 路径可用；CLI provider 路径暂不宣称稳定 |
| Cline | 宿主接入已验证 | `cline 3.0.13` 已对 OpenAI-compatible endpoint 完成真实单轮运行；仓库暂未内置原生 RH profile |
| Cursor Agent | 已验证 | 本机 `agent` 路径可用 |
| OpenCode | 宿主接入已验证 | 原生 `~/.config/opencode/skills` profile 已随仓库提供并完成本机验证 |
| Gemini CLI | 宿主接入已验证 | 原生 `~/.gemini/skills` profile 已随仓库提供并完成本机验证 |
| Kilo Code | 已验证，定位为次一级入口 | `kilo 7.3.12` 已完成 `models` 与真实单轮运行；仓库暂未内置原生 RH profile |

## 配置 MCP Server

MCP 配置的关键是使用**绝对路径**，避免不同 shell / venv 下找不到 Python。
现在更推荐直接指向安装后的 `rh-mcp` launcher。

示例：

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/rh-mcp",
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/research-harness/.research-harness/pool.db"
      }
    }
  }
}
```

配置完成后，Agent 就可以调用 RH 的 paper、claim、gap、orchestrator、artifact 等工具。

## 启动本地 HTTP API bridge（可选）

当前主推的研究者前端是 Zotero 侧边栏插件（见
[`docs/zotero-rh-panel.md`](zotero-rh-panel.md)）。当 Zotero 或其他本地集成
需要 HTTP endpoint 时，启动本地 HTTP API bridge：

```bash
pip install -e "packages/research_harness_mcp[api]"
python -m research_harness_mcp.http_api
```

本地客户端指向：<http://127.0.0.1:8000>

HTTP bridge 默认只面向 loopback。本地审查实验如果绑定 non-loopback，必须设置
`RESEARCH_HARNESS_HTTP_API_TOKEN`；任何公网部署仍需要单独通过 TLS/proxy、
network allowlist、scoped CORS、private/no-store cache、rollback 和 monitoring
gate。

论文知识库只读 HTTP beta endpoint 见
[`docs/knowledge-http-api.md`](knowledge-http-api.md)。受控 beta 使用时请设置
`RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN`，并用
`RESEARCH_HARNESS_CORS_ORIGINS` 限定允许访问的本地前端来源。

Agent 工作流优先使用 MCP server 或 `rh` CLI，以便 provenance 与阶段状态保持明确。

## 下一步

阅读 [Demo story](DEMO.md) 了解如何展示完整产品路径，或把下面这段交给你的 Agent 开始真实研究：

```text
请阅读 docs/agent-guide.md 和 docs/PAPER_MANAGEMENT.md，
然后围绕我的研究方向创建 topic、检索论文、筛选入库，
并给我一份可审查的 literature map 初稿。
```
