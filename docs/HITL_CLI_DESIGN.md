## Research Harness HITL CLI 端设计方案

> **设计记录。** 日常使用请读 `docs/HITL_QUICK_START.md`（唯一 HITL 快速参考）。

**目标**: 让 Claude Code 和 Codex CLI 用户无缝使用 HITL 功能  
**原则**: 充分利用原生 UI 能力，最小化用户输入步骤  
**日期**: 2026-07-05

---

## 🎯 设计目标

1. **原生 UI 优先**: 使用 Claude Code `AskUserQuestion` 和 Codex 选择界面
2. **零学习成本**: 斜杠命令语义清晰，类似 `/help`、`/clear`
3. **智能默认**: 自动检测 topic、自动推荐、自动恢复
4. **可视化增强**: 推荐标记（⭐）、偏好分可视化、预期效果提示
5. **快速通道**: 一个命令完成"检查→决策→恢复"全流程

---

## 📋 核心斜杠命令

| 命令 | 用途 | 典型场景 |
|---|---|---|
| `/rh-status` | 显示当前状态 | "我们在哪一步了？" |
| `/rh-decide` | 交互式决策 | "让我选择下一步" |
| `/rh-continue` | 智能继续 | "继续运行" (最常用) |
| `/rh-feedback` | 收集反馈 | 阶段完成后 |

---

## 🔧 技术实现

### 1. 决策渲染模块 (`decision_ui.py`)

**核心函数**:

```python
# Claude Code 原生 UI 格式
format_decision_for_ask_user_question(decision) → AskUserQuestion format

# Codex/终端 CLI 格式
format_decision_for_cli_display(decision, colorize=True) → colored text

# 从 AskUserQuestion 提取选择
extract_action_from_selection(answers, options) → action_id

# 生成决策摘要
build_decision_summary(decision, choice, reasoning) → summary text

# 格式化状态显示
format_status_display(status, pending_decision) → status text
```

**视觉增强**:
- ⭐ 标记推荐选项
- [Default] 标记自动模式默认值
- 偏好分可视化：`████████████████░░░░ 85%`
- 预期效果提示：`→ May find 7+ additional papers`

### 2. 斜杠命令技能

#### `/rh-status` - 状态诊断

**输入**: `topic_id` (可选，自动检测)  
**输出**:
```
======================================================================
📊 RESEARCH HARNESS STATUS
======================================================================

Topic: Temporal Graph Neural Networks
Current Stage: analyze
Stage Status: in_progress
Gate Decision: needs_approval
⏸️  Cannot advance yet

Missing artifacts:
  - direction_proposal

⚠️  PENDING DECISION: multiple_directions_available
   Run /rh-decide to make a choice

======================================================================

💡 Next action: /rh-decide to make a choice
```

**关键特性**:
- 自动检测待决策
- 显示缺失产物
- 建议下一步操作
- 支持 `--compact` 和 `--json` 模式

#### `/rh-decide` - 交互式决策

**流程**:
1. 自动检测 topic (从上下文或最近活跃)
2. 获取待决策：`paper_production_pending_decisions(topic_id)`
3. **Claude Code**: 使用 `AskUserQuestion` 原生渲染
4. **Codex**: 显示彩色 CLI 格式，等待用户输入
5. 可选：询问决策理由（审计和学习）
6. 应用决策：`paper_production_decide(topic_id, choice, reasoning)`
7. 显示摘要和下一步

**AskUserQuestion 示例**:
```python
{
  "questions": [{
    "question": "Found 3 seed papers, need 10. How should we acquire more?",
    "header": "Evidence",
    "options": [
      {
        "label": "⭐ Expand to external providers (Recommended) [Default]",
        "description": "Enable semantic_scholar and pasa...\n\n→ May find 7+ papers\n\nAI confidence: 85%"
      },
      {
        "label": "Add papers manually",
        "description": "Provide local papers...\n\nAI confidence: 40%"
      },
      {
        "label": "Stop workflow",
        "description": "Halt and require manual intervention\n\nAI confidence: 10%"
      }
    ],
    "multiSelect": false
  }]
}
```

**Codex CLI 示例**:
```
======================================================================
🤔 DECISION REQUIRED
======================================================================

Found 3 seed papers, need 10. How should we acquire more?

Mode: checkpoint

Available options:

⭐ 1. Expand to external providers [RECOMMENDED] [Default]
   Enable semantic_scholar and pasa (requires network)
   → May find 7+ additional papers
   AI confidence: ████████████████░░░░ 85%

2. Add papers manually
   Provide local papers or specific DOI/arXiv IDs
   → Workflow pauses until papers are added
   AI confidence: ████████░░░░░░░░░░░░ 40%

3. Stop workflow
   Halt and require manual intervention
   AI confidence: ██░░░░░░░░░░░░░░░░░░ 10%

======================================================================

Enter your choice (1-3):
```

#### `/rh-continue` - 智能继续（🌟 最常用）

**这是最重要的命令** —— 一键完成全流程。

**逻辑**:
```
检查状态
  ↓
有待决策？
  ├─ Yes → 展示选项 → 收集选择 → 应用
  └─ No  → 直接继续
  ↓
检查 gate
  ├─ 可以推进 → advance 到下一阶段
  └─ 不能推进 → 显示阻塞原因
  ↓
报告结果
```

**支持模式**:
- **交互模式** (默认): 遇到决策点时使用 AskUserQuestion
- **自动模式** (`--auto`): 应用推荐默认值，不询问

**使用示例**:
```bash
# 交互模式（默认）
/rh-continue

# 自动模式
/rh-continue --auto

# 指定 topic
/rh-continue --topic 5
```

**输出示例**:
```
📊 Current stage: init

⚠️  Decision required: insufficient_seed_papers
[Shows AskUserQuestion]

✅ Decision recorded: Expand to external providers

▶️  Resuming workflow...
✅ Workflow resumed: build stage
   Advancing to next stage...
   → Now in build stage

💡 Workflow is running. Use /rh-status to check progress.
```

#### `/rh-feedback` - 收集反馈

**触发时机**:
- 阶段完成后
- gate 通过时
- 用户主动调用

**AskUserQuestion 格式**:
```python
{
  "questions": [{
    "question": "The analyze stage completed successfully. Any feedback?",
    "header": "Feedback",
    "options": [
      {"label": "No feedback needed", "description": "Worked as expected"},
      {"label": "Performance issue", "description": "Took too long"},
      {"label": "Quality concern", "description": "Output could improve"},
      {"label": "Process suggestion", "description": "I have a suggestion"},
      {"label": "Other (please explain)", "description": "Custom feedback"}
    ]
  }]
}
```

**记录**: 调用现有 `rh self-evolution record-human-feedback` 流程

---

## 🎨 Claude Code 特定优化

### 1. AskUserQuestion 深度集成

**完整流程示例**:

```python
# Agent 检测到需要决策
if workflow_status == "paused":
    # 调用 MCP 工具
    decisions = tools.paper_production_pending_decisions(topic_id=1)

    if decisions["has_pending"]:
        # 格式化为 AskUserQuestion
        from research_harness.auto_runner.decision_ui import (
            format_decision_for_ask_user_question
        )

        auq_format = format_decision_for_ask_user_question(
            decisions["decision"]
        )

        # Claude Code 原生渲染
        answers = AskUserQuestion(
            questions=auq_format["questions"],
            metadata=auq_format["metadata"]
        )

        # 提取选择
        from research_harness.auto_runner.decision_ui import (
            extract_action_from_selection
        )

        choice = extract_action_from_selection(
            answers,
            decisions["decision"]["options"]
        )

        # 应用决策
        tools.paper_production_decide(
            topic_id=1,
            choice=choice,
            reasoning="User selected via Claude Code UI"
        )
```

### 2. 自动 Topic 检测

```python
def auto_detect_topic():
    """从对话上下文自动检测 topic_id"""
    # 1. 检查最近的命令输出
    # 2. 调用 topic_list 获取最近活跃
    topics = tools.topic_list()
    if len(topics) == 1:
        return topics[0]["id"]

    # 3. 多个 topic：用 AskUserQuestion 让用户选
    options = [
        {
            "label": f"{t['name']} (#{t['id']})",
            "description": t.get('description', '')[:100]
        }
        for t in topics[:5]
    ]

    answer = AskUserQuestion(questions=[{
        "question": "Which topic?",
        "header": "Topic",
        "options": options,
        "multiSelect": False
    }])

    # 从答案提取 topic_id
    # ...
```

### 3. 进度更新

```python
# 长时间运行时显示进度
print("▶️  Resuming workflow...")

# Claude Code 会实时显示这些更新
print("  • Checking gate status...")
print("  • Loading artifacts...")
print("  • Advancing to next stage...")
print("✅ Now in build stage")
```

---

## 🖥️ Codex 特定优化

### 1. 彩色 CLI 输出

```python
from research_harness.auto_runner.decision_ui import (
    format_decision_for_cli_display
)

# 生成彩色 ANSI 输出
cli_output = format_decision_for_cli_display(
    decision,
    colorize=True  # ANSI color codes
)
print(cli_output)
```

**ANSI 颜色方案**:
- **黄色**: 标题和重要提示
- **绿色**: 推荐选项、成功消息
- **蓝色**: 信息和模式指示
- **灰色**: 次要信息

### 2. 输入收集

```python
# 显示选项后等待输入
cli_output = format_decision_for_cli_display(decision)
print(cli_output)

# Codex 原生输入
choice_idx = input("Enter your choice (1-3): ")

# 转换为 action
try:
    idx = int(choice_idx) - 1
    choice = decision["options"][idx]["action"]
except (ValueError, IndexError):
    print("❌ Invalid choice")
```

### 3. MCP 调用示例

```typescript
// Codex TypeScript/JavaScript 环境
const decisions = await mcp.call("paper_production_pending_decisions", {
  topic_id: 1
});

if (decisions.has_pending) {
  // 渲染到 Codex UI
  renderDecisionUI(decisions.decision);

  // 收集用户选择
  const choice = await getUserChoice();

  // 记录决策
  const result = await mcp.call("paper_production_decide", {
    topic_id: 1,
    choice: choice,
    reasoning: "User selected in Codex UI"
  });

  showNotification("Decision recorded", "success");
}
```

---

## 🔄 典型工作流

### 场景 1: 首次运行遇到决策点

```
User: 开始论文生产

Agent: 正在启动...
[Runs: rh paper-production start --topic "..." --target-venue "..."]

Agent: 工作流已启动。现在自动继续...
[Internally calls /rh-continue]

Agent: ⚠️  需要做一个决策：种子论文不足
[Shows AskUserQuestion with 3 options]

User: [Selects "Expand to external providers"]

Agent: ✅ 决策已记录，继续运行...
      ▶️  现在进入 build 阶段

Agent: 🎯 工作流正在运行。我会在下一个决策点通知你。
```

### 场景 2: 检查状态后继续

```
User: 我们现在到哪一步了？

Agent: [Calls /rh-status]

📊 RESEARCH HARNESS STATUS
Topic: Temporal GNN
Current Stage: analyze
Gate Decision: needs_approval
⚠️  PENDING DECISION: multiple_directions_available

💡 Next action: /rh-decide

User: 帮我决策

Agent: [Calls /rh-decide, shows 3 research directions with scores]

User: [Selects direction 1]

Agent: ✅ 已选择方向 1: Temporal Graph Attention
      📋 接下来：基线识别将开始

User: 继续

Agent: [Calls /rh-continue]
      ✅ 工作流继续，进入 propose 阶段
```

### 场景 3: 完全自动模式

```
User: 用自动模式运行，AI 自己决定就行

Agent: 好的，启动自动模式...
[Runs: rh paper-production start --interaction-mode autonomous]

Agent: ▶️  工作流运行中（自动模式）
      • init 阶段：自动扩展证据搜索 ✓
      • build 阶段：正在获取论文...

[Later, at high-risk decision]
Agent: ⚠️  遇到高风险决策：研究方向选择
      自动模式下仍需人工确认
[Shows AskUserQuestion]
```

---

## 📊 UI 组件库

### 决策选项卡片（AskUserQuestion）

```
┌─────────────────────────────────────────────────────┐
│ ⭐ Expand to external providers [RECOMMENDED]       │
│                                                     │
│ Enable semantic_scholar and pasa for broader       │
│ coverage (requires network access)                 │
│                                                     │
│ → May find 7+ additional papers                    │
│                                                     │
│ AI confidence: ████████████████░░░░ 85%            │
└─────────────────────────────────────────────────────┘
```

### 状态面板

```
┌──────────────── 📊 RH STATUS ─────────────────┐
│ Topic: Temporal GNN                           │
│ Stage: analyze → propose                      │
│ Gate:  ⏸️  needs_approval                     │
│ Next:  /rh-decide                             │
└───────────────────────────────────────────────┘
```

### 进度指示

```
▶️  Workflow Progress:
  ✅ init     (completed)
  ✅ build    (completed)
  ⏺️  analyze  (in progress)
  ⏸️  propose  (waiting)
  ⬜ experiment
  ⬜ write
```

---

## 🎓 用户引导

### 首次使用

```
User: [首次启动 paper-production]

Agent: 👋 检测到这是首次使用 Research Harness！

几个有用的命令：
• /rh-status  - 查看当前状态
• /rh-decide  - 做出决策
• /rh-continue - 智能继续（最常用）

现在启动工作流...
```

### 上下文帮助

```
User: /rh-decide

Agent: [No pending decision]

ℹ️  当前没有待决策。

提示：
• 使用 /rh-status 查看工作流状态
• 使用 /rh-continue 继续运行
• 决策点会自动出现在需要时
```

---

## ⚙️ 配置和定制

### 用户偏好设置

```python
# ~/.research-harness/ui-preferences.json
{
  "decision_ui": {
    "show_preference_scores": true,
    "show_expected_effects": true,
    "colorize_terminal": true,
    "auto_detect_topic": true,
    "ask_reasoning": "optional"  # always | optional | never
  },
  "continue_behavior": {
    "auto_advance": true,
    "pause_after_decision": false,
    "show_progress": true
  }
}
```

### 技能元数据

每个斜杠命令技能包含：
- `trigger`: 触发关键词
- `inputs`: 参数（自动检测或必填）
- `outputs`: 输出格式
- `estimated_runtime`: 预估时间

---

## 📈 成功指标

| 指标 | 目标 | 测量方式 |
|---|---|---|
| 决策完成时间 | < 2分钟 | 从展示到应用 |
| 自动检测准确率 | > 95% | topic_id 检测 |
| 用户满意度 | > 4.5/5 | 反馈评分 |
| 命令使用频率 | /rh-continue 占 60%+ | 使用日志 |

---

## 🚀 实施路线图

### Phase 1: 核心功能（已完成）
- ✅ decision_ui.py 渲染模块
- ✅ /rh-decide 技能
- ✅ /rh-status 技能  
- ✅ /rh-continue 技能

### Phase 2: Claude Code 集成（下一步）
- ⏳ AskUserQuestion 完整流程测试
- ⏳ 自动 topic 检测实现
- ⏳ 技能注册到 Claude Code 技能系统

### Phase 3: Codex 集成
- ⏳ MCP 调用测试
- ⏳ Codex UI 渲染适配
- ⏳ TypeScript/JavaScript 示例

### Phase 4: 优化和扩展
- ⏳ 用户偏好设置
- ⏳ 更多决策点
- ⏳ 反馈闭环
- ⏳ 分析仪表板

---

## 📚 相关文档

- `docs/HITL_IMPLEMENTATION_SUMMARY.md` - 技术实施总结
- `docs/HITL_QUICK_START.md` - 快速入门
- `skills/rh-decide/SKILL.md` - /rh-decide 详细文档
- `skills/rh-status/SKILL.md` - /rh-status 详细文档
- `skills/rh-continue/SKILL.md` - /rh-continue 详细文档

---

**设计者**: Claude (Fable 5)  
**审核状态**: ✅ 设计完成，ready for implementation  
**最后更新**: 2026-07-05
