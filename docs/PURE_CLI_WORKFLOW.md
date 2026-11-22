# 纯 CLI 工作流 - 全程在 Claude Code / Codex 中完成

> **宿主变体 — 无终端、纯 MCP 环境。** 覆盖 S1 新开与 S2 续推两个场景的 MCP 等价
> 调用；agent 分层入口见 `docs/AGENT_OPERATIONS.md`。

**不需要切换到终端！** 所有操作都可以通过 MCP 工具在 Claude Code 或 Codex 中完成。

---

## ✅ 能力确认

现在 Research Harness 提供了 **9 个完整工作流 MCP 工具**，让你可以：

1. ✅ 创建研究主题
2. ✅ 添加论文
3. ✅ 启动 Paper Production
4. ✅ 查看状态和决策
5. ✅ 做决策
6. ✅ 切换交互模式
7. ✅ 继续工作流
8. ✅ 导出论文

**全程无需打开终端！**

---

## 🚀 完整示例：从零到论文

以下是在 **Claude Code** 或 **Codex** 中的完整对话示例。

### Step 1: 创建研究主题

**你（在 Claude/Codex 中）**:
```
我想研究"时序图神经网络在城市交通预测中的应用"，帮我创建一个新的RH主题
```

**Claude/Codex** 会调用：
```python
rh.topic_init(
    name="时序图神经网络-城市交通预测",
    description="研究TGNN在城市交通流量预测中的应用，目标会议：NeurIPS 2026",
    tags=["graph-neural-networks", "traffic-prediction", "temporal-modeling"]
)
```

**返回**:
```json
{
  "status": "success",
  "summary": "Created topic '时序图神经网络-城市交通预测' with ID 5",
  "output": {
    "topic_id": 5,
    "name": "时序图神经网络-城市交通预测",
    "description": "研究TGNN在城市交通流量预测中的应用，目标会议：NeurIPS 2026",
    "tags": ["graph-neural-networks", "traffic-prediction", "temporal-modeling"]
  },
  "next_actions": [
    "Add seed papers: paper_ingest(..., topic_id=5)",
    "Start workflow: paper_production_start(topic_id=5, target_venue='...')"
  ]
}
```

---

### Step 2: 添加种子论文

**你**:
```
帮我添加几篇相关论文作为种子：
- arXiv:2106.15012 (一篇TGNN论文)
- arXiv:2203.12345 (一篇交通预测论文)
```

**Claude/Codex** 会调用：
```python
rh.paper_ingest(
    arxiv_id="2106.15012",
    topic_id=5
)
rh.paper_ingest(
    arxiv_id="2203.12345",
    topic_id=5
)
```

---

### Step 3: 启动 Paper Production

**你**:
```
好的，现在启动paper production工作流，目标NeurIPS，用checkpoint模式（我想在关键决策时把关）
```

**Claude/Codex** 会调用：
```python
rh.paper_production_start(
    topic_id=5,
    target_venue="NeurIPS",
    interaction_mode="checkpoint",
    paper_mode="main"
)
```

**返回**:
```json
{
  "status": "success",
  "summary": "Started paper production for topic 5 (mode: checkpoint, venue: NeurIPS)",
  "output": {
    "topic_id": 5,
    "target_venue": "NeurIPS",
    "interaction_mode": "checkpoint",
    "paper_mode": "main",
    "current_stage": "init"
  },
  "next_actions": [
    "Check status: paper_production_status(topic_id=5)",
    "If decision pending: paper_production_decide(...)",
    "Continue workflow: paper_production_resume(topic_id=5)"
  ]
}
```

---

### Step 4: 查看状态

**你**:
```
看看现在进展到哪了
```

**Claude/Codex** 会调用：
```python
rh.paper_production_status(topic_id=5)
```

**返回**:
```json
{
  "status": "success",
  "summary": "Status for topic 5",
  "output": {
    "orchestrator": {
      "current_stage": "init",
      "stage_status": "paused",
      "gate": {
        "decision": "needs_approval",
        "can_advance": false
      }
    },
    "pending_decisions": {
      "has_pending": true,
      "decision": {
        "reason_code": "insufficient_seed_papers",
        "reason_message": "Only 2 seed papers, recommended minimum is 10",
        "options": [
          {
            "action": "broaden_search",
            "label": "扩展到外部提供商",
            "description": "启用 semantic_scholar 和 OpenReview",
            "recommended": true,
            "preference_score": 0.85,
            "expected_effect": "获取 30-50 篇相关论文"
          },
          {
            "action": "manual_add",
            "label": "手动添加论文",
            "description": "你自己继续添加更多论文",
            "recommended": false,
            "preference_score": 0.40
          },
          {
            "action": "continue",
            "label": "继续当前配置",
            "description": "用现有 2 篇论文继续（不推荐）",
            "recommended": false,
            "preference_score": 0.15
          }
        ]
      }
    },
    "interaction_mode": "checkpoint",
    "mode_description": "Pause at decision points for human approval"
  },
  "next_actions": [
    "Make decision: paper_production_decide(...)"
  ]
}
```

**Claude/Codex 会友好地展示**:
```
📊 当前状态：

阶段：init（初始化）
状态：暂停

⚠️  需要决策：种子论文不足

当前只有 2 篇种子论文，推荐至少 10 篇。我有以下建议：

1. ⭐ 扩展到外部提供商（推荐，置信度 85%）
   → 启用 semantic_scholar 和 OpenReview
   → 预计获取 30-50 篇相关论文

2. 手动添加论文（置信度 40%）
   → 你自己继续添加更多论文

3. 继续当前配置（不推荐，置信度 15%）
   → 用现有 2 篇论文继续

你想选择哪个？
```

---

### Step 5: 做决策

**你**:
```
我选第一个，扩展搜索。我希望文献覆盖全面一点。
```

**Claude/Codex** 会调用：
```python
rh.paper_production_decide(
    topic_id=5,
    choice="broaden_search",
    reasoning="希望文献覆盖全面，包括TGNN和交通预测两个子领域"
)
```

**返回**:
```json
{
  "status": "success",
  "summary": "Decision recorded and workflow will resume",
  "output": {
    "topic_id": 5,
    "decision_accepted": true,
    "next_stage": "build"
  },
  "next_actions": [
    "Resume workflow: paper_production_resume(topic_id=5)"
  ]
}
```

---

### Step 6: 继续工作流

**你**:
```
继续推进
```

**Claude/Codex** 会调用：
```python
rh.paper_production_resume(topic_id=5)
```

**工作流自动运行...**

---

### Step 7: 后续决策（自动循环）

工作流会在关键点再次暂停，例如：

**在 analyze 阶段**（最重要的决策）:

**Claude/Codex** 调用 `rh.paper_production_status(topic_id=5)` 后展示：

```
📊 当前状态：

阶段：analyze（分析）
状态：暂停

⚠️  需要决策：多个研究方向可选

我识别出了 3 个潜在研究方向：

1. ⭐ TGNN + 时空注意力机制（推荐，置信度 82%）
   → Gap: 现有TGNN未充分利用交通网络的空间局部性
   → 创新点：设计时空解耦注意力
   → 数据集：METR-LA, PeMS-Bay可用
   → 实验难度：中等

2. TGNN + 因果推理（置信度 70%）
   → Gap: 交通预测中因果关系未被建模
   → 创新点：因果图注意力
   → 数据集：需要标注因果关系
   → 实验难度：较高

3. TGNN + 联邦学习（置信度 55%）
   → Gap: 多城市数据隐私问题
   → 创新点：分布式TGNN训练
   → 数据集：需要多个城市数据
   → 实验难度：高

你想选择哪个方向？
```

**你**:
```
选第一个，时空注意力。理由是数据集容易获取，而且实验可行性高，适合NeurIPS的timeline。
```

**Claude/Codex** 调用：
```python
rh.paper_production_decide(
    topic_id=5,
    choice="select_direction_0",
    reasoning="时空注意力机制更成熟，数据集充足，适合NeurIPS timeline"
)
```

---

### Step 8: 切换到自动模式（可选）

如果你信任后续的决策，可以切换到自动模式：

**你**:
```
方向定了之后，剩下的决策我相信AI的判断，切换到自动模式吧
```

**Claude/Codex** 调用：
```python
rh.paper_production_set_mode(
    topic_id=5,
    mode="autonomous"
)
```

**返回**:
```json
{
  "status": "success",
  "summary": "Changed mode from checkpoint to autonomous",
  "output": {
    "topic_id": 5,
    "old_mode": "checkpoint",
    "new_mode": "autonomous",
    "description": "AI auto-decides (except high-risk decisions)"
  }
}
```

**Claude/Codex 继续**:
```python
rh.paper_production_resume(topic_id=5)
```

之后工作流会自动推进，只在高风险决策时暂停。

---

### Step 9: 定期检查进度

**你（15分钟后）**:
```
看看进展
```

**Claude/Codex** 调用：
```python
rh.paper_production_status(topic_id=5)
```

**可能的返回**:
```json
{
  "output": {
    "orchestrator": {
      "current_stage": "propose",
      "stage_status": "in_progress",
      "completed_stages": ["init", "build", "analyze"]
    },
    "pending_decisions": {
      "has_pending": false
    },
    "interaction_mode": "autonomous"
  }
}
```

**Claude/Codex 展示**:
```
📊 进展顺利！

✅ 已完成阶段：
  - init（初始化）
  - build（文献池构建）- 获取了 47 篇论文
  - analyze（分析）- 选择了时空注意力方向

🔄 当前阶段：propose（提案生成）
   正在生成方法设计和实验计划...

模式：自动模式（AI自动决策）

预计还需 15-20 分钟完成全流程。
```

---

### Step 10: 导出最终论文

**你（工作流完成后）**:
```
论文生成完了吗？导出给我看看
```

**Claude/Codex** 调用：
```python
rh.paper_production_export(
    topic_id=5,
    format="both",
    include_artifacts=True
)
```

**返回**:
```json
{
  "status": "success",
  "summary": "Exported paper for topic 5",
  "output": {
    "output_directory": "~/.research-harness/paper-production/topic_5",
    "files": {
      "latex": ["paper.tex", "neurips_2026.sty"],
      "pdf": ["paper.pdf"],
      "figures": [
        "figures/architecture.pdf",
        "figures/results_metr_la.pdf",
        "figures/results_pems_bay.pdf"
      ],
      "tables": [
        "tables/comparison.tex",
        "tables/ablation.tex"
      ],
      "artifacts": [
        "direction_proposal.md",
        "baseline_matrix.json",
        "experiment_plan.json",
        "gap_analysis.md"
      ]
    }
  },
  "next_actions": [
    "Copy files from: ~/.research-harness/paper-production/topic_5",
    "Review paper.tex and paper.pdf"
  ]
}
```

**Claude/Codex 展示**:
```
✅ 论文已生成！

📂 输出目录：
~/.research-harness/paper-production/topic_5

📄 生成的文件：
  - paper.tex（LaTeX源文件）
  - paper.pdf（编译后的PDF）
  
📊 图表：
  - architecture.pdf（模型架构图）
  - results_metr_la.pdf（METR-LA数据集结果）
  - results_pems_bay.pdf（PeMS-Bay数据集结果）
  
📑 表格：
  - comparison.tex（与基线对比）
  - ablation.tex（消融实验）

📚 中间产物：
  - direction_proposal.md（研究方向提案）
  - gap_analysis.md（文献gap分析）
  - experiment_plan.json（实验计划）

你可以用以下命令复制到你的工作目录：
```bash
cp -r ~/.research-harness/paper-production/topic_5 ~/my-neurips-paper/
```
```

---

## 🎯 纯CLI命令速查表

### 基础操作

| 操作 | MCP 工具调用 |
|---|---|
| 创建主题 | `rh.topic_init(name="...", description="...")` |
| 查看主题列表 | `rh.topic_list()` |
| 添加论文 | `rh.paper_ingest(arxiv_id="...", topic_id=X)` |
| 搜索论文 | `rh.paper_search(query="...", topic_id=X)` |

### Paper Production

| 操作 | MCP 工具调用 |
|---|---|
| 启动工作流 | `rh.paper_production_start(topic_id=X, target_venue="...", interaction_mode="checkpoint")` |
| 查看状态 | `rh.paper_production_status(topic_id=X)` |
| 查看待决策 | `rh.paper_production_pending_decisions(topic_id=X)` |
| 做决策 | `rh.paper_production_decide(topic_id=X, choice="...", reasoning="...")` |
| 继续运行 | `rh.paper_production_resume(topic_id=X)` |
| 查看模式 | `rh.paper_production_mode(topic_id=X)` |
| 切换模式 | `rh.paper_production_set_mode(topic_id=X, mode="autonomous")` |
| 导出论文 | `rh.paper_production_export(topic_id=X)` |

---

## 💡 自然语言使用示例

你不需要记住这些函数名！只需用自然语言和 Claude/Codex 对话：

### 示例 1: 启动新项目

**你说**:
> "我想研究图神经网络在推荐系统中的应用，帮我开始一个RH项目"

**Claude/Codex 理解并执行**:
1. `rh.topic_init(name="GNN推荐系统", ...)`
2. 提示你添加种子论文
3. 询问是否现在启动 paper production

### 示例 2: 检查进度

**你说**:
> "我的那个GNN项目现在怎么样了？"

**Claude/Codex**:
1. `rh.topic_list()` 找到你的项目
2. `rh.paper_production_status(topic_id=...)` 获取状态
3. 用友好的方式展示给你

### 示例 3: 快速决策

**你说**:
> "刚才那个决策，选第一个推荐的"

**Claude/Codex**:
1. 从上下文中记住待决策的选项
2. `rh.paper_production_decide(topic_id=..., choice=..., reasoning="选择推荐选项")`
3. 自动 resume

### 示例 4: 切换模式

**你说**:
> "后面的决策让AI自动处理吧，我不想每次都确认"

**Claude/Codex**:
1. `rh.paper_production_set_mode(topic_id=..., mode="autonomous")`
2. `rh.paper_production_resume(topic_id=...)`

---

## 🔧 高级技巧

### 技巧 1: 并行探索多个方向

**你说**:
> "我有3个研究想法，帮我同时探索一下，看看哪个最有潜力"

**Claude/Codex** 会：
```python
# 创建3个主题
topic_a = rh.topic_init(name="想法A - GNN图像分类")
topic_b = rh.topic_init(name="想法B - TGNN时序预测")
topic_c = rh.topic_init(name="想法C - GNN推荐系统")

# 并行启动（自动模式，快速探索）
for topic in [topic_a, topic_b, topic_c]:
    rh.paper_production_start(
        topic_id=topic["output"]["topic_id"],
        target_venue="NeurIPS",
        interaction_mode="autonomous"
    )

# 等待30分钟后比较
for topic in [topic_a, topic_b, topic_c]:
    status = rh.paper_production_status(topic_id=...)
    # 展示gap分析质量、数据集可得性、创新性评分
```

### 技巧 2: 中途调整方向

**你说**:
> "我看了文献分析，发现当前方向数据集很难获取，能不能换到第二个方向？"

**Claude/Codex** 会：
```python
# 回退到analyze阶段
rh.orchestrator_reset_to_stage(topic_id=5, stage="analyze")

# 重新选择方向
rh.paper_production_decide(
    topic_id=5,
    choice="select_direction_1",  # 第二个方向
    reasoning="第一个方向数据集难以获取，改为第二方向"
)

# 继续
rh.paper_production_resume(topic_id=5)
```

### 技巧 3: 导出中间产物

**你说**:
> "我想看看RH生成的文献gap分析，不想等论文全部完成"

**Claude/Codex** 会：
```python
status = rh.paper_production_status(topic_id=5)

# 找到gap分析artifact
gap_analysis_path = status["output"]["artifacts"].find("gap_analysis")

# 读取并展示
with open(gap_analysis_path) as f:
    print(f.read())
```

---

## ⚡ 完全自动模式示例

如果你完全信任AI，可以用最简化的流程：

**你只需要说**:
> "我想研究时序图神经网络，目标NeurIPS，全程自动，完成后通知我"

**Claude/Codex** 会：
```python
# 1. 创建主题
topic = rh.topic_init(name="时序图神经网络研究")

# 2. 启动自动模式
rh.paper_production_start(
    topic_id=topic["output"]["topic_id"],
    target_venue="NeurIPS",
    interaction_mode="autonomous"  # 全自动
)

# 3. 定期检查（每15分钟）
while True:
    status = rh.paper_production_status(...)
    if status["output"]["orchestrator"]["current_stage"] == "write" and \
       status["output"]["orchestrator"]["stage_status"] == "complete":
        break
    time.sleep(900)

# 4. 完成后通知你
print("✅ 论文生成完成！")
rh.paper_production_export(topic_id=...)
```

**你只需要等待，AI 会在 1-2 小时内完成整个流程**（除非遇到高风险决策）。

---

## 📊 与传统CLI对比

| 操作 | 传统 CLI | 纯 MCP 工具（本方案） |
|---|---|---|
| 创建主题 | `rh topic init "..."` | `rh.topic_init(name="...")` |
| 添加论文 | `rh paper ingest --arxiv-id ... --topic X` | `rh.paper_ingest(arxiv_id="...", topic_id=X)` |
| 启动工作流 | `rh paper-production start --topic X --target-venue "..."` | `rh.paper_production_start(topic_id=X, target_venue="...")` |
| 查看状态 | `rh paper-production status --topic X` | `rh.paper_production_status(topic_id=X)` |
| 做决策 | `rh paper-production decide --topic X --action ...` | `rh.paper_production_decide(topic_id=X, choice=...)` |
| 切换模式 | `rh paper-production set-mode --topic X --mode ...` | `rh.paper_production_set_mode(topic_id=X, mode=...)` |

**关键优势**：
- ✅ 无需记忆命令行参数
- ✅ 自然语言交互
- ✅ AI 理解上下文（记住你的topic_id）
- ✅ 友好的结果展示（不是原始JSON）
- ✅ 智能决策建议
- ✅ 全程不离开 Claude/Codex

---

## 🎓 学习路径

### 第一次使用（30分钟）

1. 对 Claude/Codex 说：**"我想用Research Harness写一篇论文，帮我开始"**
2. 跟随 AI 的引导，了解整个流程
3. 在关键决策点观察 AI 的推荐逻辑

### 熟练使用（1周后）

1. 直接说：**"启动一个关于XXX的研究，目标XXX会议，用自动模式"**
2. 定期检查进度
3. 只在必要时介入决策

### 高级使用（2周后）

1. 并行探索多个方向
2. 导出和重用中间产物
3. 自定义决策策略
4. 与团队协作（共享topic）

---

## 📚 相关文档

- **新研究任务工作流**: `docs/NEW_RESEARCH_WORKFLOW.md`
- **交互模式指南**: `docs/INTERACTION_MODE_GUIDE.md`
- **快速参考**: `docs/INTERACTION_MODE_QUICKREF.md`
- **更新和重载**: `docs/RH_UPDATE_AND_RELOAD.md`

---

## 💡 最佳实践

1. **首次使用用 checkpoint 模式**：观察 AI 如何决策
2. **熟练后用 autonomous 模式**：加速流程
3. **关键阶段切回 checkpoint**：如研究方向选择
4. **定期 `status` 检查**：了解进度和花费
5. **善用自然语言**：不需要记住函数名

---

**最后更新**: 2026-07-05  
**已验证工具数**: 9 个完整工作流 MCP 工具  
**总 MCP 工具数**: 42 个
