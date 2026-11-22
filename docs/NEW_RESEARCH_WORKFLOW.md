# 新科研任务完整工作流

> **场景 S1 — 新 topic 从零开始（分步控制路径，适合 HITL）。** 一键版见
> `ONE_COMMAND_QUICKSTART.md`；agent 分层入口见 `docs/AGENT_OPERATIONS.md`。

从零开始，用 Research Harness 完成一个新的研究任务。

---

## 🎯 场景：我有一个新的科研想法

假设你想研究：**"时序图神经网络在城市交通预测中的应用"**

目标会议：NeurIPS 2026

---

## 📋 完整步骤

### Step 0: 确认环境就绪

```bash
# 检查 RH 安装和配置
rh doctor

# 预期输出：
# ✅ Database: ~/.research-harness/pool.db
# ✅ MCP server: running
# ✅ API keys: configured
# ✅ PDF storage: ~/.research-harness/pdfs
```

如果有问题，运行：
```bash
./setup.sh
```

---

### Step 1: 创建研究主题

```bash
# 初始化主题
rh topic init "时序图神经网络-交通预测"

# 查看主题 ID（假设得到 topic_id=5）
rh topic list
```

**输出示例**:
```
Topic ID: 5
Name: 时序图神经网络-交通预测
Created: 2026-07-05 10:30:00
Papers: 0
Status: initialized
```

---

### Step 2: 添加种子论文（可选但推荐）

有两种方式：

#### 方式 A: 从已知论文开始（推荐）

```bash
# 添加你已知的相关论文
rh paper ingest --arxiv-id 2106.15012 --topic 5  # 某篇 TGNN 论文
rh paper ingest --arxiv-id 2203.12345 --topic 5  # 某篇交通预测论文
rh paper ingest --doi "10.1145/3534678.3539234" --topic 5
```

#### 方式 B: 从搜索开始

```bash
# 搜索并添加
rh search arxiv "temporal graph neural networks traffic" --topic 5 --limit 5
rh search semantic-scholar "urban traffic prediction GNN" --topic 5 --limit 5
```

**建议**：至少准备 **5-10 篇**高质量种子论文，覆盖：
- 核心方法论文（TGNN）
- 应用领域论文（交通预测）
- 相关基线论文（静态 GNN、LSTM）

---

### Step 3: 启动 Paper Production 工作流

#### 🔰 首次使用：用默认检查点模式

```bash
rh paper-production start \
  --topic 5 \
  --target-venue "NeurIPS" \
  --interaction-mode checkpoint
```

**说明**：
- `checkpoint` 模式会在关键决策点暂停，让你把关
- 你会看到 AI 的推荐和置信度，最终由你决定
- 适合学习 RH 的决策逻辑

#### ⚡ 熟练后：用自动模式加速

```bash
rh paper-production start \
  --topic 5 \
  --target-venue "NeurIPS" \
  --interaction-mode autonomous
```

**说明**：
- AI 自动应用推荐决策（高风险除外）
- 显著加速流程
- 你可以随时切换回 checkpoint 模式

---

### Step 4: 在 Claude Code / Codex 中交互推进

启动后，在 Claude Code 或 Codex 中：

#### 4.1 查看状态

```bash
/rh-status
```

**输出示例**:
```
📊 RESEARCH HARNESS STATUS

Topic: 时序图神经网络-交通预测
Current Stage: init
Stage Status: in_progress

⚠️  PENDING DECISION:
   insufficient_seed_papers
   
Options:
1. ⭐ 扩展到外部提供商 (推荐, 85%)
   启用 semantic_scholar 和 OpenReview
   
2. 手动添加论文 (40%)
   你自己找更多论文

3. 继续当前配置 (30%)
   用现有 8 篇论文继续

💡 Next action: /rh-decide
```

#### 4.2 做决策

```bash
/rh-decide
```

这会弹出原生选择界面（Claude Code 用 AskUserQuestion，Codex 用交互式选项）。

或者直接用 CLI：
```bash
rh paper-production decide \
  --topic 5 \
  --action broaden_search \
  --reasoning "需要更全面的文献覆盖，覆盖 TGNN 和交通预测两个子领域"
```

#### 4.3 继续工作流

```bash
/rh-continue
```

这个命令会：
1. 检查是否有待决策 → 有则展示选项
2. 决策完成后自动 resume
3. 推进到下一阶段

---

### Step 5: 逐阶段推进（6 个阶段）

#### 阶段 1: **Init** - 初始化

- 检查种子论文数量
- 配置文献源
- 设置预算和目标

**常见决策**：
- `insufficient_seed_papers` → 扩展文献源 / 手动添加

---

#### 阶段 2: **Build** - 构建文献池

- 从种子论文扩展相关文献
- 下载 PDF
- 解析摘要和元数据

**常见决策**：
- `too_many_results` → 调整相关性阈值
- `download_failures` → 切换 PDF 源

**监控**：
```bash
rh paper list --topic 5 --count
# 输出: 45 papers acquired
```

---

#### 阶段 3: **Analyze** - 分析文献

- 提取方法、数据集、结果
- 识别研究 gap
- 生成方向提案

**常见决策**：
- `multiple_directions_available` → 选择研究方向（**关键决策**）
  - 方向 1: TGNN + 时空注意力
  - 方向 2: TGNN + 因果推理
  - 方向 3: TGNN + 联邦学习

**这是最重要的决策**，即使在 autonomous 模式下也会暂停。

**建议**：
- 仔细阅读各方向的 gap 分析
- 考虑数据集可得性
- 评估创新性 vs. 可行性

选择后：
```bash
rh paper-production decide \
  --topic 5 \
  --action select_direction_0 \
  --reasoning "时空注意力机制更成熟，数据集充足，适合 NeurIPS timeline"
```

---

#### 阶段 4: **Propose** - 生成提案

- 细化方法设计
- 选择基线方法
- 规划实验

**常见决策**：
- `baseline_selection` → 选择对比基线
- `dataset_selection` → 选择评估数据集

**检查**：
```bash
# 查看生成的提案文档
rh orchestrator status --topic 5 --json | jq '.stage.artifacts'

# 输出包括:
# - direction_proposal.md
# - baseline_matrix.json
# - experiment_plan.json
```

---

#### 阶段 5: **Experiment** - 执行实验

- 运行实验，或导入已完成实验的结果
- 用实际结果创建结果表格和图表
- 满足最低内容要求：
  - ≥ 8 页
  - ≥ 2 个图表
  - ≥ 1 个结果表

没有完成的实验结果时：提示用户先准备实验，不要用预期值代替。

---

#### 阶段 6: **Write** - 撰写论文

- 生成完整 LaTeX 论文
- 包含：摘要、引言、方法、实验、结论
- 符合目标会议格式

**常见决策**：
- `paper_quality_check` → 接受 / 修订 / 重新生成
- `citation_conflicts` → 解决引用问题

**最终接受**：
```bash
rh paper-production decide \
  --topic 5 \
  --action accept_paper \
  --reasoning "论文结构完整，实验充分，符合 NeurIPS 标准"
```

---

### Step 6: 获取产出

#### 6.1 查看最终状态

```bash
rh orchestrator status --topic 5
```

**输出示例**:
```
Current Stage: write
Stage Status: complete
Gate Decision: passed

Artifacts:
✅ paper.tex
✅ paper.pdf
✅ bibliography.bib
✅ figures/ (3 figures)
✅ tables/ (2 tables)

Estimated cost: $45.30
```

#### 6.2 导出论文

```bash
# 查找生成的文件
ls ~/.research-harness/paper-production/topic_5/

# 输出:
# paper.tex
# paper.pdf
# references.bib
# figures/
# tables/
# experiment_results.json

# 复制到你的工作目录
cp -r ~/.research-harness/paper-production/topic_5/ ~/my-neurips-paper/
```

#### 6.3 查看生成报告

```bash
rh orchestrator report --topic 5 --format markdown > research_report.md
```

包含：
- 文献综述
- Gap 分析
- 方法设计
- 实验计划
- 结果总结

---

## 🔄 中断和恢复

### 中途暂停

```bash
# 查看当前状态
/rh-status

# 输出:
# Current Stage: analyze
# Stage Status: in_progress
# 可以随时中断，状态会保存
```

### 恢复工作

```bash
# 下次启动 Claude Code / Codex
/rh-status   # 查看上次到哪了
/rh-continue # 继续推进
```

---

## 🎨 模式切换策略

### 推荐：混合模式

```bash
# 启动时用自动模式（快速通过早期阶段）
rh paper-production start --interaction-mode autonomous --topic 5 --target-venue "NeurIPS"

# 到 analyze 阶段切换到检查点（重要决策人工把关）
rh paper-production set-mode --topic 5 --mode checkpoint

# 方向选择后，切回自动
rh paper-production set-mode --topic 5 --mode autonomous
```

### 完全自动（适合熟练用户）

```bash
rh paper-production start --interaction-mode autonomous --topic 5 --target-venue "NeurIPS"

# 后台运行，定期检查
/rh-status
```

### 完全人工（适合新手学习）

```bash
rh paper-production start --interaction-mode checkpoint --topic 5 --target-venue "NeurIPS"

# 每个决策点都会暂停
/rh-decide  # 逐个决策
/rh-continue
```

---

## 📊 实战案例时间线

### 快速模式（自动 + 熟练用户）

| 时间 | 阶段 | 操作 |
|---|---|---|
| T+0min | 准备 | `rh topic init` + 添加 10 篇种子论文 |
| T+5min | Init | 启动 autonomous 模式 |
| T+10min | Build | 自动扩展到 50 篇论文 |
| T+20min | Analyze | 暂停，人工选择方向（5 min） |
| T+30min | Propose | 自动生成提案 |
| T+40min | Experiment | Dream 模式生成结果 |
| T+60min | Write | 生成完整论文 |

**总耗时**：~1 小时（实际时间取决于 API 速度）

### 审慎模式（检查点 + 新手）

| 时间 | 阶段 | 操作 |
|---|---|---|
| T+0min | 准备 | 初始化 + 种子论文 |
| T+15min | Init | 决策文献源（人工选择） |
| T+30min | Build | 监控文献获取进度 |
| T+60min | Analyze | 详细评估 3 个研究方向 |
| T+90min | Propose | 调整基线和数据集选择 |
| T+120min | Experiment | Dream 模式 |
| T+150min | Write | 审查论文质量，可能修订 |

**总耗时**：2.5-3 小时

---

## 🛠️ 高级技巧

### 1. 批量处理多个方向

```bash
# 创建多个主题，并行探索
rh topic init "TGNN-交通-时空注意力"  # topic 5
rh topic init "TGNN-交通-因果推理"    # topic 6
rh topic init "TGNN-交通-联邦学习"    # topic 7

# 同时启动（不同终端或后台）
rh paper-production start --topic 5 --interaction-mode autonomous &
rh paper-production start --topic 6 --interaction-mode autonomous &
rh paper-production start --topic 7 --interaction-mode autonomous &

# 比较结果
rh orchestrator status --topic 5
rh orchestrator status --topic 6
rh orchestrator status --topic 7
```

### 2. 重用文献池

```bash
# 第一个主题建立文献池
rh paper-production start --topic 5 ...

# 第二个主题复用部分文献
rh paper clone --from-topic 5 --to-topic 6 --filter "temporal graph"
```

### 3. 导出中间产物

```bash
# 导出文献综述（analyze 阶段后）
rh orchestrator export-artifact --topic 5 --artifact literature_review --format markdown

# 导出 gap 分析
rh orchestrator export-artifact --topic 5 --artifact gap_analysis --format json

# 导出实验计划
rh orchestrator export-artifact --topic 5 --artifact experiment_plan --format yaml
```

---

## ⚠️ 常见问题

### Q1: 种子论文太少怎么办？

**A**: RH 会在 init 阶段提示你：
```bash
⚠️  Decision: insufficient_seed_papers (3/10)

Options:
1. ⭐ 扩展到外部提供商 → 推荐
2. 手动添加论文
3. 继续（风险高）
```

**建议**：选择选项 1，让 RH 自动扩展。

### Q2: 不喜欢生成的研究方向？

**A**: 在 analyze 阶段可以：
```bash
# 方法 1: 拒绝所有方向，重新分析
rh paper-production decide --topic 5 --action regenerate_directions

# 方法 2: 手动编辑方向提案
rh orchestrator edit-artifact --topic 5 --artifact direction_proposal

# 方法 3: 添加更多约束
rh paper-production set-constraint --topic 5 --key "focus_area" --value "causal inference"
```

### Q3: 论文质量不满意？

**A**: 在 write 阶段：
```bash
# 拒绝接受，提供反馈
rh paper-production decide \
  --topic 5 \
  --action revise_paper \
  --reasoning "引言部分创新性不足，需要强化与现有 TGNN 方法的对比"

# RH 会重新生成
```

### Q4: 预算超限？

**A**: 监控和调整：
```bash
# 查看当前花费
rh orchestrator status --topic 5 --json | jq '.cost'

# 设置预算上限
rh paper-production set-budget --topic 5 --max-cost 50.0

# RH 会在超限前暂停请求确认
```

---

## 📚 相关文档

- **交互模式选择**: `docs/INTERACTION_MODE_GUIDE.md`
- **快速参考**: `docs/INTERACTION_MODE_QUICKREF.md`
- **HITL 实现**: `docs/HITL_IMPLEMENTATION_SUMMARY.md`
- **Paper Management**: `docs/PAPER_MANAGEMENT.md`

---

## 🎯 下一步

1. **立即开始**：选一个你感兴趣的研究方向，运行 Step 1-3
2. **学习决策**：在 checkpoint 模式下观察 AI 推荐逻辑
3. **提供反馈**：用 `/rh-feedback` 告诉 RH 哪些决策好 / 不好
4. **优化流程**：熟练后切换到 autonomous 模式加速

---

**最后更新**: 2026-07-05  
**预计阅读时间**: 15 分钟  
**预计首次完整流程时间**: 1-3 小时
