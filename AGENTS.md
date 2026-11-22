## RH Self-Development Mode

Trigger this mode when the task is to modify, refactor, test, evaluate, or
document Research Harness itself.

In RH self-development mode:

- Keep changes scoped, tested, and consistent with the release boundary in
  `docs/contracts/release-boundary.md` and the guard scripts under `scripts/check-*.py`.
- Do not automatically read `docs/agent-guide.md`; that guide is for using RH
  on research projects, not for modifying RH itself.
- Do not load or invoke RH research workflow skills unless the task is to use RH
  for a research project or to edit that exact skill/tool.
- Stop and produce a review summary before changing the public MCP surface,
  touching storage/provenance/orchestrator gates, changing benchmark promotion
  claims, or adding dependencies.

## Research Harness 集成

本项目使用 Research Harness 进行科研流程管理。

### 系统位置

- Research Harness: project root
- Agent 入口手册（L0，先读这个）: `docs/AGENT_OPERATIONS.md`
- 深度参考（L2，按需读）: `docs/agent-guide.md`、`docs/TOPIC_LIFECYCLE.md`
- 数据库: `.research-harness/pool.db`（由 `.research-harness/config.json` 钉死）

### 必读

开始任何科研工作前，先读入口手册（约 4KB，覆盖新开/续推/反馈强化三个场景）：

```bash
cat docs/AGENT_OPERATIONS.md
```

不要默认全读 `docs/agent-guide.md`；只有入口手册指向它时才按需展开。

### Codex 上下文压缩规则

为避免 Codex 在接近上下文上限时自动压缩失败（例如 `Error running remote compact task: stream disconnected before completion`），必须采用主动压缩策略：

1. **40% 软阈值**：当可见 context 剩余不足 40%（或没有可见仪表但会话已经完成一个主要阶段/读取了大量文件/进行了大量工具调用）时，不要继续开启新的大型检索、批量读取或多文件改动，先进行一次 checkpoint。
2. **Checkpoint 内容**：压缩前先输出或保存简短状态摘要，包含当前目标、已完成事项、关键发现、未完成步骤、相关文件、需要保留的用户偏好/约束。
3. **主动压缩**：checkpoint 后主动建议/执行 Codex `/compact`；如果当前环境不能由 agent 直接执行 `/compact`，则明确提示用户执行 `/compact` 并附上 checkpoint 摘要。
4. **30% 硬阈值**：当 context 剩余不足 30% 时，只允许做收尾、记录状态或请求压缩；禁止继续启动长任务。
5. **失败兜底**：如果 `/compact` 或远程 compact 仍失败，立即把 checkpoint 摘要写入可持久位置（memory 或项目文档中已有合适位置），然后建议开启新会话并粘贴该摘要恢复。

### 三条铁律

1. 论文必须入库：通过 research-harness MCP 的 `paper_ingest` 或 `rh paper ingest` CLI 入库，不要把论文散放在项目目录
2. 产出必须记录：关键产出通过 `orchestrator_record_artifact` 记录到数据库
3. 经验必须反馈：工具不足、流程改进、bug 优先开 GitHub Issue 或进入项目正式 backlog；不要在公共仓库新增一次性调试日志/报告

### 稿件署名与 CRediT（全局，所有期刊/领域一律适用）

用户常设指令，见 `CLAUDE.md` 的 *Manuscript Byline and CRediT*，代码强制点在
`_workflow/execution/latex_compiler.py`（`PLACEHOLDER_AUTHOR_BLOCK` /
`credit_authorship_block`），回归测试 `test_credit_and_placeholder_byline.py`。

1. **署名占位**：固定 **3 作者 / 2 部门 / 第 3 位为通讯**（带随机生成邮箱），
   作者名用 `Author 1..3`，作者 1–2 同属 Department A，作者 3 属 Department B。
   **禁止输出 `Anonymous`。**
2. **CRediT 贡献声明**：每位作者一段，**加粗姓名 + 冒号 + 标准 CRediT 角色逗号
   列表 + 句号**，末尾统一一句 `All authors have read and agreed to the
   submitted version of the manuscript.`。角色后**不写散文说明**。
   角色分配**必须按该文实际内容调整**（无代码则不写 `Software`，纯设计稿不写
   `Data curation`）；代码里的默认切分只是起点。

### 文献检索与获取（RH ↔ SPC）

RH = 科研工作流大脑与唯一研究状态库；SPC（paperfetch）= 可选的文献获取与解析组件，装了 `spc` CLI 才启用。

- **检索走公开免 key 数据源**：`paper_source_clients.build_provider_suite` 是唯一决定检索源的地方（本地 PaperVault 缓存 + Semantic Scholar、OpenAlex、Crossref、arXiv、PubMed、OpenReview）。所有源一律不使用 API key，环境里的 key 也不读取；工作流入口不得绕过它直接构造 provider。SPC 安装时额外作为检索兜底、精确标识查询、引用图谱和 PDF 获取通道，缺失不算错误。详见 `docs/managed-paper-acquisition.md`。
- **失败不得静默**：单个源失败写入 `provider_errors`，保留其他源结果；所有源都没有应答时报错，不返回静默的空结果。源不可用或查不到不能证明论文不存在。
- **PDF 获取**使用 SPC `paper download`；RH `paper acquire` 负责调用、验证 PDF 身份并回填/标注。没有 SPC 时，PDF 改名 `<paper_id>_*.pdf` 后用 `rh paper ingest-manual` 入库。池管理、研究状态、阅读标注由 RH 负责。
- **回填桥**：`rh paper export-spc-wants <topic>` → SPC 履约 → `rh paper import-seed-pack`（不行则 PDF 改名 `<paper_id>_*.pdf` + `rh paper ingest-manual`）。禁止其它手工塞文件路径。
- **引文核验双通道**：稿件流水线内 = RH `citation_verify/citation_sanitize`；投稿前终审或需要与判决模型去相关的外部锚（`governance_gate` 语义）= SPC `verify`（需安装 SPC）。
- 复现审计（外部论文）、选刊与稿件排版均为独立于本基础仓的可选外部组件；RH 仅在配置可用时消费其输出。
- **检索通道次序铁律：学术检索先跑，Web Search 后补。** 任何先行工作 / 新颖性 / related work / 竞品 /「是不是已经有人做了」的问题，**第一手一律是 `paper_search`**（多数据源：本地 PaperVault 缓存、Semantic Scholar、OpenAlex、Crossref、arXiv、PubMed、OpenReview，装了 SPC 时再加 SPC）。**开局直接上 Web Search 是缺陷不是捷径**——web 结果欠采样决定新颖性判决的已索引文献，只凭它得出的 verdict 不成立。
- **Agent 自带 Web Search = 永久兜底与补充通道（全局铁律，Claude/Codex/子 agent 一体适用）**：凡 RH/SPC 检索覆盖不足（最新工作、冷门刊、特刊页面、投稿要求、机构/数据集事实核验），agent 应**主动**用自身 Web Search 补位，无需用户逐次授意；查得的论文仍须走正规入库通道（paper_ingest / SPC 履约），Web 证据须记来源。

### ⚠️ MCP 优先，CLI 只做数据管理

**所有 research primitive（gap_detect、claim_extract、baseline_identify、section_draft、consistency_check 等）必须通过 MCP 工具调用，不要用 `rh` / `rh` CLI 执行这些操作。**

原因：CLI 绕过了 provenance 追踪、orchestrator gate 检查和 artifact 版本管理。

| 场景 | 用 MCP 工具 | 禁止 |
|------|------------|------|
| 识别 baseline | `baseline_identify(topic_id=X)` | `rh baseline-identify ...` |
| 提取 claims | `claim_extract(paper_ids=[...])` | `rh claim-extract ...` |
| 起草章节 | `section_draft(section=..., topic_id=X)` | `rh section-draft ...` |
| 检测 gap | `gap_detect(topic_id=X)` | `rh gap-detect ...` |

`rh` / `rh` CLI 只用于：`topic list`、`paper list`、`paper ingest`、`orchestrator status` 等只读/入库操作。

### 可用工具（MCP research-harness）

- `paper_search`：多源论文搜索
- `paper_ingest`：论文入库（arxiv_id / DOI / PDF）
- `paper_summarize`：论文摘要
- `claim_extract`：提取研究声明
- `gap_detect`：研究空白分析
- `baseline_identify`：baseline 识别
- `section_draft`：章节起草
- `consistency_check`：一致性检查
- `orchestrator_resume`：**接管已有项目的首选入口**，自动从现有 artifact 推断当前阶段（不会从头开始）
- `orchestrator_status` / `orchestrator_advance` / `orchestrator_gate_check`：流程编排
- `adversarial_review`：**独立跨模型对抗审查**（Claude 环境自动调 Codex/GPT，Codex 环境自动调 Opus，保证 reviewer 独立性）
- `advisory_check` / `provenance_summary` / `provenance_export`：工作流建议与溯源审计

### Codex 中的 Research Harness Skills

如果已在 `~/.codex/skills/` 安装 Research Harness skills，优先按以下触发词理解：

- `research-harness`
- `research-init`
- `literature-search`
- `literature-mapping`
- `citation-trace`
- `claim-extraction`
- `gap-analysis`
- `evidence-gating`
- `section-drafting`
- `paper-verify`
- `provenance-review`

兼容输入写法：

- 直接写 skill 名称，如 `literature-search`
- 使用 Claude 风格前缀，如 `/literature-search`
- 入口分流，如 `/research-harness 帮我初始化一个新 topic`
- 在中文里明确说“用 literature-search skill”或“执行 /research-init”

注意：Codex 没有 Claude Code 那种原生 `/命令` 注册表。这里的 `/xxx` 是约定式触发词，不是 REPL 内建命令。

### 可用 Agents

- `literature-mapper`
- `proposer`
- `challenger`
- `adversarial-resolver`
- `synthesizer`

### 自由度

你可以按任意顺序、任意方式使用以上工具。6 阶段流程（init→build→analyze→propose→experiment→write，见 `docs/TOPIC_LIFECYCLE.md`）是参考框架，不是强制要求。人类研究员随时可以干预。

