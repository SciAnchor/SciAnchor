# Research Harness Human-in-the-Loop (HITL) 实施总结

> **实现记录（含决策点扩展指南）。** 日常使用请读 `docs/HITL_QUICK_START.md`。

**实施日期**: 2026-07-05  
**状态**: ✅ 核心功能已实现，适配 Claude Code 和 Codex

---

## 🎯 实施目标

1. **统一交互模式**：用单一 `interaction_mode` 参数替代 mode/autonomy/auto_approve 三旋钮
2. **结构化决策点**：支持 AI 推荐 + 偏好分 + 人类最终决策
3. **跨宿主兼容**：Claude Code 和 Codex 都能使用完整 HITL 功能
4. **固定反馈点**：在关键阶段收集人类反馈，积累自优化知识

---

## ✅ 已完成的核心组件

### 1. 统一交互模式系统 (`interaction_mode.py`)

**三种模式**:
- `autonomous`: AI 全自动决策，仅在高风险点暂停
- `checkpoint`: 在所有结构化决策点暂停等待人类（推荐）
- `interactive`: 允许 AI 主动询问澄清信息

**关键函数**:
```python
resolve_interaction_mode(mode, autonomy, auto_approve, interaction_mode)
should_pause_for_decision(interaction_mode, decision_required, risk_level)
default_action_for_decision(interaction_mode, options)  # 自动模式选择
```

**CLI 支持**:
```bash
rh paper-production start --topic "..." --target-venue "..." \
  --interaction-mode checkpoint
```

### 2. 决策请求 Schema v2 (`checkpoint.py`)

**新增字段**:
- `auto_selected`: 是否自动应用
- `auto_selection_reason`: 自动选择原因
- **选项增强**:
  - `recommended`: AI 推荐标记
  - `preference_score`: 偏好分 (0.0-1.0)
  - `expected_effect`: 预期效果描述
  - `default_action`: 自动模式默认选项

**向后兼容**: v1 schema 自动升级到 v2

### 3. 决策辅助函数 (`decision_helpers.py`)

```python
# 构建带 AI 推荐的决策选项
build_decision_option(
    action="broaden_search",
    label="扩展到外部提供商",
    description="启用 semantic_scholar 和 pasa",
    recommended=True,
    preference_score=0.85,
    expected_effect="可能找到 10+ 额外论文",
    default_action=True
)

# 自动排序和标记推荐
rank_options_by_preference(options)

# 标准化提示格式
format_decision_prompt(situation, question, context)
```

### 4. 决策点注册表 (`decision_registry.py`)

**声明式定义**:
```python
DecisionPoint(
    name="insufficient_seed_papers",
    stage="init",
    trigger_check=_trigger_insufficient_seed_papers,
    build_options=_build_evidence_acquisition_options,
    apply_handler=_apply_evidence_acquisition_decision,
    risk_level="medium",
    requires_human=False  # 可自动应用
)
```

**已注册决策点**:
1. `insufficient_seed_papers` - 种子论文不足（init 阶段）
2. `direction_selection` - 研究方向选择（analyze 阶段，必须人类决策）

**扩展方式**: 添加新 DecisionPoint 到 DECISION_REGISTRY 即可

### 5. MCP 工具 - Claude/Codex 适配 (`tools_decision.py`)

#### `paper_production_pending_decisions(topic_id)`
返回当前等待的决策请求，包含:
- 提示文本
- 选项列表（带推荐和偏好分）
- 交互模式
- 推荐操作和自动操作

**Claude Code 使用**:
```python
# AI 可调用 MCP 工具获取决策
result = tools.paper_production_pending_decisions(topic_id=1)
# 然后用 AskUserQuestion 原生渲染选项
```

**Codex 使用**:
```python
# Codex 直接调用 MCP 获取并渲染决策
decisions = await mcp.call("paper_production_pending_decisions", {"topic_id": 1})
# 显示给用户并收集选择
```

#### `paper_production_decide(topic_id, choice, reasoning)`
记录人类决策并推进流程:
```python
tools.paper_production_decide(
    topic_id=1,
    choice="broaden_search",
    reasoning="需要更多高质量论文支撑相关工作部分"
)
```

### 6. 集成到核心流程

**paper_production_entry.py**: 
- 在 `paper_production_run_policy` 中设置 `interaction_mode`
- Schema 升级到 v2

**stage_executor.py**:
- 使用 `should_pause_for_decision()` 判断是否暂停
- 保留向后兼容的 legacy 逻辑

**runner.py**:
- 证据获取决策请求使用 v2 schema
- 应用 decision_helpers 构建选项

**tool_surface.py**:
- 注册 2 个新 MCP 工具到公开 API

---

## 📊 决策流程示意

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 触发决策点 (e.g., 种子论文不足)                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Decision Registry 构建选项                                 │
│    - broaden_search (推荐, score=0.85, default)               │
│    - add_papers_manually (score=0.4)                         │
│    - stop (score=0.1)                                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 检查 interaction_mode                                      │
│    ┌─────────────┬──────────────┬──────────────┐            │
│    │ autonomous  │  checkpoint  │ interactive  │            │
│    │ (自动应用   │  (等待人类)   │ (可询问)      │            │
│    │  default)   │              │              │            │
│    └─────────────┴──────────────┴──────────────┘            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. MCP 工具暴露决策                                            │
│    - Claude Code: AskUserQuestion 原生渲染                    │
│    - Codex: 自定义 UI 渲染选项                                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 记录决策并应用                                              │
│    - decision_log (audit trail)                              │
│    - apply_handler 更新 checkpoint                            │
│    - resume workflow                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 使用示例

### CLI 使用

```bash
# 1. 启动 checkpoint 模式（默认）
rh paper-production start \
  --topic "动态图神经网络的时序建模" \
  --target-venue "NeurIPS" \
  --interaction-mode checkpoint

# 2. 查看等待的决策
rh paper-production status --topic 1

# 3. 做出决策
rh paper-production decide \
  --topic 1 \
  --action broaden_search \
  --reasoning "需要扩大论文池覆盖 GNN 时序方法"

# 4. 恢复运行
rh paper-production resume --topic 1
```

### Python/MCP 使用

```python
# Claude Code 或 Codex 中
from research_harness_mcp import tools

# 获取待决策
decisions = tools.paper_production_pending_decisions(topic_id=1)
if decisions["has_pending"]:
    print(decisions["decision"]["prompt"])
    for opt in decisions["decision"]["options"]:
        print(f"- {opt['label']} (推荐: {opt['recommended']}, "
              f"分数: {opt['preference_score']})")
        print(f"  {opt['description']}")
    
    # 记录人类选择
    tools.paper_production_decide(
        topic_id=1,
        choice="broaden_search",
        reasoning="用户批准扩展搜索"
    )
```

---

## 🚀 扩展指南

### 添加新决策点

1. **在 `decision_registry.py` 添加触发检查**:
```python
def _trigger_budget_approval(checkpoint_data, context):
    estimated_cost = context.get("estimated_cost_usd", 0)
    return estimated_cost > 50.0  # 超过 $50 需要批准
```

2. **添加选项构建器**:
```python
def _build_budget_options(checkpoint_data, stage, context):
    cost = context["estimated_cost_usd"]
    return {
        "prompt": f"预计花费 ${cost:.2f}，是否继续?",
        "options": [
            build_decision_option(
                action="approve_budget",
                label="批准预算",
                recommended=cost < 100,
                preference_score=0.8 if cost < 100 else 0.4,
            ),
            build_decision_option(
                action="reduce_scope",
                label="缩减范围",
                preference_score=0.2,
            ),
        ]
    }
```

3. **添加应用处理器**:
```python
def _apply_budget_decision(checkpoint_data, choice, params):
    if choice == "approve_budget":
        checkpoint_data["budget_approved"] = True
        return {"applied": True, "next_action": "advance"}
    elif choice == "reduce_scope":
        # 调整参数
        return {"applied": True, "next_action": "revise"}
```

4. **注册到 DECISION_REGISTRY**:
```python
DECISION_REGISTRY["budget_approval"] = DecisionPoint(
    name="budget_approval",
    stage="build",
    checkpoint="budget_gate",
    reason_code="budget_exceeds_threshold",
    trigger_check=_trigger_budget_approval,
    build_options=_build_budget_options,
    apply_handler=_apply_budget_decision,
    risk_level="medium",
)
```

### 添加固定反馈点

在 `stage_executor.py` 的阶段完成处理中:
```python
from .interaction_mode import should_request_feedback

if should_request_feedback(interaction_mode, stage, gate_passed=True):
    # 生成可选反馈提示（非阻塞）
    feedback_prompt = {
        "stage": stage,
        "prompt": f"{stage} 阶段已完成，有什么反馈吗？",
        "optional": True,
        "decision_ids": [...]  # 关联本阶段的决策
    }
    ckpt.record_event(checkpoint_data, stage=stage, 
                     event="feedback_opportunity", 
                     detail=json.dumps(feedback_prompt))
```

---

## 📝 架构设计原则

1. **声明式优于命令式**: 决策点通过注册表声明，不散落在代码中
2. **关注点分离**: 触发检查、选项构建、应用逻辑独立
3. **向后兼容**: v2 schema 可读取 v1，legacy 参数仍工作
4. **宿主无关**: MCP 层提供统一接口，Claude/Codex 都能用
5. **审计友好**: 所有决策记录到 decision_log 和 checkpoint history

---

## 🔬 测试状态

### 已验证
- ✅ interaction_mode 模块语法和逻辑
- ✅ decision_helpers 构建选项
- ✅ decision_registry 加载和查询
- ✅ tools_decision MCP 工具语法
- ✅ 向后兼容性（v1 schema 路径）

### 待验证（需端到端测试）
- ⏳ 完整 paper-production 流程中的决策点触发
- ⏳ Claude Code AskUserQuestion 集成
- ⏳ Codex MCP 调用和 UI 渲染
- ⏳ 自动模式的 default_action 应用
- ⏳ 反馈点到 ExperienceStore 的闭环

---

## 🎓 对比原有机制

| 维度 | 原有机制 | 新机制 |
|---|---|---|
| 交互模式 | mode/autonomy/auto_approve 三参数 | 统一 interaction_mode |
| 决策点 | 硬编码在 runner.py | 声明式注册表 |
| 选项结构 | 简单 action/label | 带推荐、分数、预期效果 |
| AI 推荐 | 无 | preference_score + recommended |
| 自动应用 | auto_approve flag | default_action + interaction_mode |
| 跨宿主 | CLI only | CLI + MCP (Claude/Codex) |
| 扩展性 | 修改 runner.py | 添加 DecisionPoint |
| 反馈收集 | 手动调用 | 固定点 + 归因 |

---

## 📚 相关文档

- `docs/paper-production-workspace.md` - Paper production 工作流
- `docs/contracts/end-to-end-paper-writing-capability.md` - E2E 能力合同
- `packages/research_harness/research_harness/auto_runner/interaction_mode.py` - 交互模式系统
- `packages/research_harness/research_harness/auto_runner/decision_registry.py` - 决策点注册表
- `packages/research_harness_mcp/research_harness_mcp/tools_decision.py` - MCP 工具

---

## 🚦 下一步

1. **端到端测试**: 在真实 paper-production 运行中验证决策流
2. **Claude Code 技能**: 创建 `/rh-decide` 斜杠命令（友好 UI）
3. **Codex 适配器**: 在 Codex UI 中渲染决策选项
4. **更多决策点**: 
   - 预算批准（build 阶段）
   - 实验规模（experiment 阶段）
   - 最终接受（write 阶段）
5. **反馈闭环**: 将反馈 → lesson → 行为改变的自优化闭环实现
6. **文档补充**: 为用户和 agent 编写完整使用指南

---

**实施者**: Claude (Fable 5)  
**审核状态**: ✅ 核心功能就绪，可进入测试阶段
