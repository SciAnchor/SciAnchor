# Research Harness HITL 快速入门

> **HITL / 交互模式的唯一快速参考。** 其余 HITL 文档
> （`INTERACTION_MODE_GUIDE.md`、`HITL_CLI_DESIGN.md`、`HITL_IMPLEMENTATION_SUMMARY.md`、
> `INTERACTION_MODE_QUICKREF.md`）是设计与实现记录，日常使用只需要本文件。
> 会话入口见 `docs/AGENT_OPERATIONS.md`。

## 为 Claude Code 用户

### 查看待决策

在 paper-production 运行中，如果遇到决策点，使用 MCP 工具：

```python
# 获取待决策（自动暴露给 Claude）
result = tools.paper_production_pending_decisions(topic_id=1)

# Claude 会看到：
# - 提示问题
# - 选项列表（带推荐标记和偏好分）
# - 推荐的默认操作
```

### 做出决策

```python
# 方式 1: 通过 MCP 工具
tools.paper_production_decide(
    topic_id=1,
    choice="broaden_search",
    reasoning="用户批准扩展搜索以获取更多高质量论文"
)

# 方式 2: 通过 CLI（如果 Claude 用 Bash 工具）
!rh paper-production decide --topic 1 --action broaden_search \
  --reasoning "扩展到外部提供商"
```

### 设置交互模式

```bash
# 启动时指定模式
!rh paper-production start \
  --topic "你的研究主题" \
  --target-venue "NeurIPS" \
  --interaction-mode checkpoint  # autonomous | checkpoint | interactive
```

---

## 为 Codex 用户

### 查看待决策

```python
# Codex 调用 MCP
decisions = await mcp.call("paper_production_pending_decisions", {
    "topic_id": 1
})

if decisions["has_pending"]:
    decision = decisions["decision"]
    print(f"问题: {decision['prompt']}")
    
    # 显示选项（可以渲染为 UI 按钮）
    for opt in decision["options"]:
        recommended = "⭐" if opt["recommended"] else ""
        score = opt.get("preference_score", 0)
        print(f"{recommended} {opt['label']} (分数: {score:.2f})")
        print(f"   {opt['description']}")
        print(f"   预期效果: {opt.get('expected_effect', 'N/A')}")
```

### 记录决策

```python
# Codex 调用 MCP 记录用户选择
result = await mcp.call("paper_production_decide", {
    "topic_id": 1,
    "choice": "broaden_search",  # 用户选中的 action
    "reasoning": "需要更多论文支撑相关工作"
})

print(result["next_steps"])  # 显示下一步操作
```

---

## 三种交互模式对比

| 模式 | 行为 | 适用场景 |
|---|---|---|
| **autonomous** | AI 自动选择默认操作，只在高风险点暂停 | 完全信任 AI，快速迭代 |
| **checkpoint** | 在所有结构化决策点暂停等待人类 | 需要掌控关键决策（推荐） |
| **interactive** | 允许 AI 主动询问澄清信息 | 复杂研究，需要双向沟通 |

### 运行时查看/切换模式

```bash
rh paper-production mode --topic 1                       # 查看当前模式
rh paper-production set-mode --topic 1 --mode autonomous # 切换
rh paper-production resume --topic 1 --auto-approve      # 临时自动继续一次（不改设置）
```

---

## 当前可用决策点

1. **种子论文不足** (`insufficient_seed_papers`)
   - **触发**: init 阶段，种子论文 < 10 篇
   - **选项**: 扩展搜索 | 手动添加 | 停止
   - **默认**: 扩展搜索（autonomous 模式）

2. **研究方向选择** (`direction_selection`)
   - **触发**: analyze 阶段，发现多个候选方向
   - **选项**: 每个方向（带新颖性和可行性分数）
   - **默认**: 无（必须人类选择）

更多决策点正在开发中...

---

## 典型工作流

```
1. 启动 paper-production
   ↓
2. AI 执行到决策点（例如：种子论文不足）
   ↓
3. 调用 paper_production_pending_decisions
   ↓
4. 显示选项给用户（Claude: AskUserQuestion, Codex: UI）
   ↓
5. 用户选择 → 调用 paper_production_decide
   ↓
6. checkpoint 更新，workflow 继续
   ↓
7. 在关键阶段收集可选反馈（非阻塞）
```

---

## FAQ

**Q: 如何跳过某个决策点？**  
A: 使用 `autonomous` 模式，AI 会自动应用 default_action

**Q: 如何查看历史决策？**  
A: `rh orchestrator status --topic <id>` 会显示 decision_log

**Q: 决策记录在哪里？**  
A: 1) checkpoint 文件 2) orchestrator decision_log 表 3) human_feedback_record artifact（如果提供反馈）

**Q: 如何添加自定义决策点？**  
A: 参见 `docs/HITL_IMPLEMENTATION_SUMMARY.md` 的扩展指南

---

**更多信息**: 
- 完整实施文档: `docs/HITL_IMPLEMENTATION_SUMMARY.md`
- 代码位置: `packages/research_harness/research_harness/auto_runner/decision_*.py`
- MCP 工具: `packages/research_harness_mcp/research_harness_mcp/tools_decision.py`
