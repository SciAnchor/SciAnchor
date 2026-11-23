<p align="center">
  <img src="docs/assets/scianchor-header.jpg" alt="SciAnchor — Every claim, anchored." width="100%"/>
</p>

<p align="center">
  <a href="README.md"><b>简体中文</b></a> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"/></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/MCP-compatible-orange.svg" alt="MCP"/>
</p>

<p align="center"><strong style="font-size:1.75rem;">做证据可信、过程可追、自主优化的长程自动化 AI 科研工具</strong></p>

<p align="center"><b>SciAnchor</b> 主仓库 · 内含开源核心引擎 <b>Research Harness</b>（客户端与网页即将推出）</p>

Research Harness 是科研 agent 的 harness 层：为 agent 提供证据状态、过程记录、工具接口和反馈回路，让检索、阅读、判断与写作成为可长期运行、可持续积累的自动化科研流程。

适用于 Codex、Claude Code、Gemini CLI、OpenCode、Cline、Cursor Agent、Kilo Code 等主流 AI 编程 agent；也支持通过 agent profile 接入 OpenClaw 等第三方 agent 工具。

当前子系统状态和公开工具面以 [docs/STATUS.md](docs/STATUS.md) 为准。
发布边界以 [docs/contracts/release-boundary.md](docs/contracts/release-boundary.md)
为准。

## 当前发布边界

RH 当前稳定承诺是本地 public CLI/MCP/skills 工作流；HTTP bridge 是
local/internal loopback 集成面，不是 stable external API release。Zotero
稳定范围仅限本地 `direction=push`, `dry_run=true` validation；fake/sandbox
pull/both 和 apply 证据只作为本地 gate evidence，real Zotero network
sync/apply 仍然 deferred。Benchmark/performance 证据只用于 private local
regression governance，不构成 public benchmark/performance claims。

## 3 分钟跑通

**① 安装 RH 本体**

```bash
git clone https://github.com/scianchor/scianchor.git
cd scianchor
./setup.sh
rh --json doctor            # 确认本机能跑起来（看 state_trees 指向同一个 pool.db）
```

可选：安装 paperfetch（自动获取并校验开放获取 PDF、解析全文；需要 Python 3.12）。装好后 RH 会自动识别 `spc` 命令并使用它：

```bash
pip install -e packages/paperfetch
```

**② 装到你的 agent**（Codex 与 Claude Code 都支持）

```bash
rh skill bootstrap          # 一条命令给 Codex + Claude Code 都装好 skills 并校验

# Codex：MCP 已由仓库内已签入的 .codex/config.toml 自动挂载，无需额外配置
# Claude Code：挂上 RH 的 MCP 工具面
claude mcp add research-harness \
  --env RESEARCH_HARNESS_DB_PATH="$PWD/.research-harness/pool.db" \
  -- python -m research_harness_mcp
```

> 完整部署步骤 + 对话式 human-in-the-loop 全流程操作实录（开题 → checkpoint 决策 →
> 继续 → 出稿 → 反馈返工）见 **[docs/deploy-and-hitl.zh.md](docs/deploy-and-hitl.zh.md)**。

**③ 交给 agent 起跑**

把这段交给 Codex、Claude Code 或其它已装好 RH 的 agent：

```text
先读 docs/AGENT_OPERATIONS.md（RH 的 L0 入口）。
用 checkpoint 交互模式，围绕「robust budget pacing for online advertising」
创建一个 research topic，检索近期论文，筛选有用论文入库，并生成第一版 literature map。
所有论文必须绑定 topic 入库，关键产出记录为 RH artifact；遇到关键决策点停下来问我。
```

没有 API key 也可以先完成安装检查、skills 安装、公共入口浏览和本地 demo story 阅读；需要 deep read、claim extraction、annotation 等模型能力时，再配置 LLM route。

## 为什么需要 RH

普通 agent 已经可以检索论文、总结 PDF、提取观点和生成草稿，但科研真正难的是让这些动作持续积累。一次对话结束后，paper、claim、gap、baseline、实验判断和草稿版本往往散落在聊天记录、临时文件和人的记忆里。Research Harness 解决的是这个断点：让科研过程从一次次回答，变成有证据、有轨迹、可接续、可优化的研究资产。

## 产品特点

| 特点 | 说明 |
|---|---|
| **证据可信** | 绑定论文、证据片段与来源链，减少无依据推断。 |
| **过程可追** | 记录判断、阶段、版本与门控结果，支持回放、审查和接续。 |
| **自主优化** | 沉淀失败、修正、矛盾和反馈，让后续轮次基于证据继续改进。 |
| **长程任务** | 支持跨会话、跨工具、跨 agent 的连续科研自动化。 |

## 五个公共入口

RH 的 public skills 现在按任务套件组织，`skills/manifest.json` 为每个 skill 暴露 `public_suite`、`task_type`、`data_access_level`、输入、输出、门控和预估耗时，方便 agent 或前端把复杂工具面折叠成少数可理解入口。

| 入口 | 适合做什么 | 代表 skills |
|---|---|---|
| **research** | 建 topic、搜论文、做文献地图、提取 claim、找 gap | `research-init`, `literature-search`, `literature-mapping`, `claim-extraction`, `gap-analysis` |
| **paper** | 起草章节、修图、组装投稿/评审包 | `paper-writing`, `section-drafting`, `figure-quality`, `publication-pack` |
| **review** | 查证论文身份、做证据门控、审计 provenance | `paper-verify`, `evidence-gating`, `provenance-review` |
| **zotero** | 同步 Zotero、本地 PDF 阅读、插件适配 | `paper-sync`, `paper-reading-annotation`, `rh-zotero-plugin-adapter` |
| **benchmark** | 评估最终 bundle、复盘运行契约、支持自优化 | `final-bundle-quality`, `task-taxonomy` |

## 核心能力

| 能力 | 说明 |
|---|---|
| 🔎 **论文池管理** | 围绕研究主题检索、筛选并入库论文，维护可持续扩展的主题级文献池。 |
| 🧾 **研究声明提取** | 从论文中提取研究声明、假设、局限、数据集、指标和可复现性风险。 |
| 🧭 **来源链追踪** | 记录论文、声明、证据、产出和阶段决策之间的关系，让关键结论可回查。 |
| 🧪 **空白与基线分析** | 识别研究空白、关键基线、方法矛盾和可推进的实验方向。 |
| 📝 **证据约束写作** | 生成实验 brief、proposal、related work 或章节草稿，并保留对应证据链。 |
| 🚦 **阶段编排与门控** | 通过阶段状态、门控检查、一致性检查和产出记录管理长程研究流程。 |
| 📦 **科研交付协议** | 以 RH 为事实源，覆盖 brief、proposal、experiment、review、paper、rebuttal 的科研交付协议。 |
| 🔁 **自主优化闭环** | 将失败原因、审查反馈、矛盾发现和修正记录写入研究状态，支持后续轮次持续改进。 |
| 📚 **Zotero 阅读工作流** | 以 Zotero 文献库、PDF 和阅读现场为入口，把本地阅读过程接入 RH 研究状态。 |
| 🔌 **多 agent 接入** | 支持主流 AI 编程 agent，并可通过 agent profile 接入第三方 agent 工具。 |

## 安装提示

先安装一个你常用的 AI 编程 agent。下面以 Codex 为例：

```bash
npm install -g @openai/codex
```

然后把下面这段交给 Codex：

```text
请为当前环境安装 SciAnchor（Research Harness 引擎）：

1. 克隆仓库：https://github.com/scianchor/scianchor.git
2. 进入项目目录并运行 ./setup.sh
3. 运行 rh --json doctor 验证安装
4. 为 Codex 安装 RH skills：rh skill install --agent codex
5. 运行 rh skill verify --agent codex 检查 skills 是否可用
6. 如果任何步骤失败，先诊断原因并修复，不要跳过失败步骤
```

手动安装、模型路径和 MCP 配置见：

- [Codex / Claude Code 部署 + 对话式 HITL 全流程](docs/deploy-and-hitl.zh.md)
- [中文快速开始](docs/quickstart.zh.md)
- [English Quickstart](docs/quickstart.md)
- [Demo story](docs/DEMO.md)
- [Showcase bundle](docs/showcase-bundle.md)

## 场景展示

下面提供的是可以直接交给 agent 的 prompt。RH 会把这些指令组织成 topic、paper pool、claim、gap、artifact 和 provenance 等结构化状态，而不是只生成一次性聊天回答。

**从零建立研究主题**

**Prompt**

```text
围绕「robust budget pacing for online advertising」创建一个研究 topic。
检索近期论文，筛选有用论文入库，并建立第一版 literature map。
```

**RH 如何执行**：创建 topic，检索并入库论文，维护 paper pool，并将 literature map 记录为可接续的研究产出。

---

**把阅读变成证据资产**

**Prompt**

```text
精读这个 topic 中最相关的论文。
提取研究声明、关键假设、局限、数据集、指标和可复现性风险。
```

**RH 如何执行**：调用论文精读和声明提取能力，把 claim、假设、局限和风险写入主题状态，并保留来源关系。

---

**从证据收敛到实验方向**

**Prompt**

```text
基于已记录证据识别 research gaps。
比较相关 baselines，并为最有潜力的方向生成 experiment brief。
```

**RH 如何执行**：基于已入库论文和声明识别 gap 与 baseline，将实验方向收敛为带证据约束的 experiment brief。

---

**生成可审查的写作草稿**

**Prompt**

```text
基于当前 topic 的 paper pool 和 claims，起草 related work。
每个关键结论都需要保留对应证据来源。
```

**RH 如何执行**：从 paper pool、claim 和 provenance 中组织写作材料，生成可审查、可追溯的章节草稿。

## 使用入口

| 入口 | 适合场景 | 文档 |
|---|---|---|
| **Zotero 侧边栏** | 以论文 / 文献库为中心的研究工作流 | [docs/zotero-rh-panel.md](docs/zotero-rh-panel.md) |
| **MCP / Agent 客户端** | Codex、Claude Code、Gemini CLI、OpenCode、Cline、Cursor Agent、Kilo Code 等 agent 工作流 | [docs/agent-guide.md](docs/agent-guide.md) |
| **CLI** | 本地终端、脚本、批处理、自动化 | [docs/quickstart.zh.md](docs/quickstart.zh.md) |
| **Python API** | Notebook、pipeline、程序化集成 | [docs/python-api.md](docs/python-api.md) |

## 开源维护与 Codex

SciAnchor 本身也使用 Codex 维护开源工作流：生成和审查测试、回放回归用例、检查 release hygiene、更新文档、复核 MCP / CLI / Zotero bridge 变更，并在合并前辅助进行安全检查。RH 的目标不是只让 agent 生成一次性答案，而是把维护过程中的判断、失败、修正和证据记录下来，沉淀为后续可复用的项目状态。

面向开源维护者，RH 提供一套可迁移的 agent 工作模式：Codex 负责执行与验证，RH 负责 paper、claim、artifact、gate、provenance 和长期任务状态，让复杂研究型项目在多轮、多工具、多会话中仍然可追踪、可恢复、可审查。

## 文档导航

- [文档首页](docs/index.md)
- [中文快速开始](docs/quickstart.zh.md)
- [Codex / Claude Code 部署 + 对话式 HITL](docs/deploy-and-hitl.zh.md)
- [Agent 使用手册](docs/agent-guide.md)
- [论文管理规范](docs/paper-management.zh.md)
- [MCP 工具与工作流](docs/mcp-tools.zh.md)
- [Zotero 集成](docs/zotero-integration.zh.md)
- [架构总览](docs/architecture.md)
- [RH 科研交付协议](docs/research-delivery-protocol.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [多工具支持矩阵](docs/tool-support.zh.md)
- [安全策略](SECURITY.md)

## License

[GNU AGPL-3.0](LICENSE)。个人、学术和机构内部使用不受限制；修改后分发，或基于 RH 对外提供网络服务时，必须以 AGPL-3.0 公开完整源代码。需要闭源或商业使用的，可以获取商业授权，见 [NOTICE](NOTICE)。第三方代码的许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
