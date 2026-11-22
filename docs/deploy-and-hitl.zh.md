# 在 Codex / Claude Code 部署 RH，并用对话做 Human-in-the-Loop 科研

> **这份文档解决什么。** 把「装到 Codex / Claude Code 上」和「之后怎么用对话一步步推进研究」
> 两件事，用一条可复制粘贴的路径 + 一个完整对话实录讲清楚。读完你能：
>
> 1. 在 Codex 和 Claude Code 里都挂上 RH 的 MCP 工具和 skills；
> 2. 用 `checkpoint` 交互模式，从一个题目一路对话到论文初稿，人来把关关键决策；
> 3. 拿到评审/导师反馈后，用对话做定向返工。
>
> 想深入某一步时再往下钻：主机无关的入口是 [`AGENT_OPERATIONS.md`](AGENT_OPERATIONS.md)，
> 状态模型是 [`TOPIC_LIFECYCLE.md`](TOPIC_LIFECYCLE.md)，Codex 专属细节是
> [`codex-workflow.md`](codex-workflow.md)。**修改 RH 本体**是另一回事，见文末第 5 节。

---

## 1. 一次性部署

RH 在每个 agent 里由两部分组成，都要装：

- **MCP 工具面** — `paper_search` / `paper_ingest` / `claim_extract` / `section_draft` /
  `topic_state` … 研究原语走 MCP，才能带上 provenance、门控和 artifact 版本。
- **Skills** — `/rh-write`、`/rh-status`、`/rh-continue`、`/rh-decide` 这些工作流入口。

### 1.1 先装 RH 本体

```bash
git clone https://github.com/research-harness/research-harness.git
cd research-harness
./setup.sh
rh --json doctor            # 确认本机能跑起来
```

`doctor` 里重点看 `state_trees`：当前 checkout 的规范状态树是
`<repo>/.research-harness/`（由 `.research-harness/config.json` 钉住）。**始终让所有 agent 指向同一个
`pool.db`**，否则会出现「多个数据库、状态对不上」的裂脑问题。

### 1.2 部署到 Claude Code

```bash
# (a) 挂 MCP 服务（项目作用域，指向仓库内的规范 DB）
claude mcp add research-harness \
  --env RESEARCH_HARNESS_DB_PATH="$PWD/.research-harness/pool.db" \
  -- python -m research_harness_mcp

# (b) 装 skills（把 skills/ 同步到 ~/.claude/skills/ 并校验）
scripts/sync-rh-to-claude-code.sh
#   等价于：rh skill install --agent claude-code && rh skill verify --agent claude-code
```

重启 Claude Code（或开新会话）后，输入 `/rh-` 应能补全出 `rh-write / rh-status / rh-continue / rh-decide`。

### 1.3 部署到 Codex

Codex 的 MCP 已经通过仓库内 **已签入的** `.codex/config.toml` 项目作用域配置好了——在仓库目录里启动
Codex 就会自动拉起 `research-harness` MCP 服务（凭据走 keychain，不入库）。你只需要装 skills：

```bash
scripts/sync-rh-to-codex.sh
#   等价于：rh skill install --agent codex && rh skill verify --agent codex

# 可选：装一次 git hook，本地 merge/checkout/rebase 后自动同步 Codex
scripts/install-codex-sync-hook.sh
```

> **Codex 的 skill 用 `$` 前缀调用**，不是 `/`。用 `/skills` 列出、`$rh-write ...` 调用。
> 自然语言也能触发（"用 rh-write 写一篇关于 X 的论文"），因为 Codex 会隐式匹配 skill 描述。

### 1.4 验证部署（两边一致）

```bash
rh skill bootstrap            # 一条命令给 Claude Code + Codex 都装好并校验
rh topic list                # MCP/CLI 能连上同一个 DB，说明打通了
```

Codex 侧改动前的本地门禁：`scripts/codex-check.sh --quick`（快校验）/ `--full`（提 PR 前）。

---

## 2. 对话式 HITL 的心智模型

只需记住 **3 种交互模式 × 4 个对话动作**。

**交互模式**（运行时可切换：`rh paper-production set-mode --topic <id> --mode <m>`）：

| 模式 | 行为 | 适合 |
|---|---|---|
| `checkpoint`（默认，**推荐做 HITL**） | 在结构化决策点暂停，等你拍板 | 你想审关键决策，其余自动 |
| `autonomous` | 自动采纳推荐，只有高风险项才停 | 你信任流程，想要初稿 |
| `interactive` | 在 checkpoint 基础上，AI 还会主动追问澄清 | 题目/约束还没定死 |

**四个对话动作**（对应文档里的 S1/S2/S3 场景）：

| 你想干什么 | 说什么 / 命令 | 背后 |
|---|---|---|
| 看现在到哪了、下一步做什么 | `/rh-status`（`$rh-status`） | `topic_state`，**永远先看这个**，别去猜 |
| 从零开题并跑起来 | `/rh-write "题目" <venue>` 或先 `rh topic init` 再 `paper-production start` | S1 |
| 回答一个待决策、然后继续 | `/rh-decide` → `/rh-continue` | S2 |
| 拿到反馈做定向返工 | `rh feedback add/plan/apply` → `/rh-continue` | S3 |

核心原则：**先 `topic_state`，信它给的 `next_action`，别因为状态看着乱就重开题目。**

---

## 3. 完整操作 case：从题目到初稿（checkpoint 模式对话实录）

场景：给 KDD 写一篇《Temporal Graph Neural Networks for Traffic Forecasting》，我想在
「方法路线」这类关键处把关，其余交给 agent。下面是**人 ↔ agent 的真实对话形态**（左侧是你输入，
`▷` 是 agent 大致会做/回的事）。

### 第 0 步 — 开题（controlled 起法，明确挂 checkpoint 模式）

> **你：** 用 checkpoint 模式给这个题目开一个 topic 并起跑：
> 《Temporal Graph Neural Networks for Traffic Forecasting》，目标会议 KDD。

```bash
rh topic init "tgnn-traffic-forecasting" --venue KDD
rh paper-production start --topic tgnn-traffic-forecasting \
  --target-venue KDD --interaction-mode checkpoint
```

> `▷` agent 创建 topic + run + checkpoint 状态，回你一个 topic id（假设是 42），并说明
> 现在处于检索/建库阶段。此后你**每一步都可以先 `/rh-status` 看它到哪了。**

### 第 1 步 — 检索、筛选、入库（agent 自动跑，你抽查）

> **你：** 检索近三年相关论文，筛掉无关的，有用的绑定 topic 42 入库，给我一版 literature map。

> `▷` agent 走 MCP：`paper_search` → 筛选 → `paper_ingest(topic_id=42)`（**所有论文必须绑 topic 入库，
> PDF 进 `.research-harness/downloads/`**）→ 产出 literature map 并 `orchestrator_record_artifact` 记录。
>
> **你随时可抽查：** `/rh-status`，或 `rh paper queue --topic 42` 看入库队列。

### 第 2 步 — 命中 checkpoint：关键决策要你拍板

跑到「方法路线」这类结构化决策点，checkpoint 模式会**暂停**，把选项摆给你：

> **你：** `/rh-status`
>
> `▷` `next_action = answer_pending_decision`：
> ```
> ⏸ 待决策 (topic 42) — 方法主线选择
>   A. 时空注意力 (ST-Attention) 主干 + 图扩散卷积
>   B. 纯 GNN + 时序自回归 (GRU-over-graph)
>   C. 连续时间图 ODE
> 推荐：A（证据覆盖最好，baseline 齐全）
> ```

你来定。可以直接用 skill，也可以走 MCP：

> **你：** `/rh-decide`，我选 A，理由：数据集上 ST-Attention 的 baseline 最完整，好对比。

```bash
# 等价的 MCP 调用
paper_production_decide(topic_id=42, choice="A",
    reasoning="ST-Attention baseline 最完整，便于公平对比")
```

> `▷` agent 记录决策到 decision log（可回溯），解除暂停。

### 第 3 步 — 继续推进到写作

> **你：** `/rh-continue`

> `▷` agent 从 checkpoint 恢复（`paper_production_resume`），带着你的决策继续：claim 抽取 →
> gap 分析 → 实验计划 → 分节起草（`section_draft`）。中途如果还有关键决策点，会再次暂停等你——
> 这就是 HITL 的循环：**跑 → 停在决策点 → 你拍板 → 继续。**
>
> 想换挡随时说：*"接下来切成 autonomous，一口气出初稿别再停我"* →
> `rh paper-production set-mode --topic 42 --mode autonomous`。

### 第 4 步 — 拿到初稿

> **你：** `/rh-status`
>
> `▷` `next_action` 显示已进入 write 完成态；初稿分节产出都在 artifact 里。
> 需要打包成 PDF/LaTeX 投稿包时走 `/publication-pack`。

### 第 5 步 — 反馈强化（导师/评审意见 → 定向返工，S3）

论文不是一次成型的。拿到意见后**不要重开题目**，用 feedback 做**受控的、只影响相关部分**的返工：

> **你：** 导师说 related work 里对连续时间图模型的对比太弱。帮我针对性补强。

```bash
rh feedback add --topic 42 --target-kind section --target related_work \
  --note "导师：对连续时间图模型 (graph ODE) 的对比太弱，需补充" --severity major
rh feedback plan  --topic 42            # 把反馈映射成返工计划
rh feedback apply --topic 42 --dry-run  # 预览会作废/重跑哪些产物
rh feedback apply --topic 42            # 定向 reset + 重新进入对应阶段
```

> **你：** `/rh-continue`
>
> `▷` agent 带着这条反馈重跑 related work（feedback 会注入到起草上下文）。反馈记录**在 reset 后仍存活**，
> 解决后被标记 `addressed`。target-kind 还可以是 `claim`/`evidence`（重进 analyze）或 `experiment`（重进实验）。

**这就是全流程 HITL 的闭环：** 开题 → agent 跑 → checkpoint 停下让你决策 → 继续 → 出稿 → 你给反馈 → 定向返工 → 再出稿。

---

## 4. 对话句式速查

在 Claude Code 用 `/`、在 Codex 用 `$`；也可以直接自然语言，agent 会匹配到对应 skill/工具。

| 意图 | 一句话说法 |
|---|---|
| 我到哪了 | 「看下 topic 42 现在什么状态、下一步做什么」→ `/rh-status` |
| 从零起跑 | 「用 checkpoint 模式给《…》起跑，目标 <venue>」 |
| 回答决策 | 「我选 B，因为 …」→ `/rh-decide` |
| 继续 | 「继续推进」→ `/rh-continue` |
| 换挡 | 「切 autonomous，一口气出稿」/「切 interactive，有不清楚就问我」 |
| 反馈返工 | 「<某节> 的 <某问题>，针对性返工」→ `rh feedback add/plan/apply` |
| 卡住了 | `rh paper-production preflight --topic 42`，按它列的 blocker 修，别重开 |

---

## 5. 如果你要修改 RH 本体（而不是用它做研究）

上面讲的是**用** RH 做科研的 HITL。如果你的任务是**改 RH 自己**（改工作流、加 skill、修 bug），
那是「自研模式」，入口不同：读仓库根的 [`AGENTS.md`](../AGENTS.md)，验证走
`scripts/codex-check.sh`，可复用的过程改进请开 GitHub Issue，
不要新建顶层报告文件。二者不要混：workflow skills 是 agent 面向的工作流包，evaluators 是
replay 门控的运行时候选，别当成一回事。
