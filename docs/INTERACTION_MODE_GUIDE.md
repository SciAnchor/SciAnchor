# Research Harness 交互模式使用指南

> **设计/详解记录。** 日常使用请读 `docs/HITL_QUICK_START.md`（唯一 HITL 快速参考）。

## 🎯 三种交互模式

| 模式 | 说明 | 适用场景 | 决策行为 |
|---|---|---|---|
| **autonomous** | 完全自动 | 快速迭代、信任 AI | 自动应用推荐/默认选项 |
| **checkpoint** | 检查点暂停 | 关键决策把关（推荐） | 在决策点暂停等待 |
| **interactive** | 交互式 | 复杂研究、需要澄清 | 允许 AI 主动询问信息 |

---

## 🚀 CLI 使用方式

### 方式 1: 启动时指定（推荐）

```bash
# 完全自动模式
rh paper-production start \
  --topic "时序图神经网络" \
  --target-venue "NeurIPS" \
  --interaction-mode autonomous

# 检查点模式（默认，也可显式指定）
rh paper-production start \
  --topic "时序图神经网络" \
  --target-venue "NeurIPS" \
  --interaction-mode checkpoint

# 交互模式
rh paper-production start \
  --topic "时序图神经网络" \
  --target-venue "NeurIPS" \
  --interaction-mode interactive
```

### 方式 2: 使用传统 mode 参数（自动映射）

```bash
# 自动映射到 autonomous
rh paper-production start --mode demo

# 自动映射到 checkpoint  
rh paper-production start --mode standard

# 自动映射到 checkpoint（更严格的检查）
rh paper-production start --mode strict
```

**映射规则**:
- `demo` / `autonomous` → `autonomous` 模式
- `standard` → `checkpoint` 模式
- `strict` → `checkpoint` 模式

### 方式 3: 运行时查看当前模式

```bash
# 查看当前交互模式
rh paper-production status --topic 1 --json | jq '.run.interaction_mode'

# 或使用新命令
rh paper-production mode --topic 1
```

### 方式 4: 运行时切换模式

```bash
# 切换到自动模式
rh paper-production set-mode --topic 1 --mode autonomous

# 切换回检查点模式
rh paper-production set-mode --topic 1 --mode checkpoint

# 临时使用自动模式继续（不修改设置）
rh paper-production resume --topic 1 --auto
```

---

## 📋 完整命令示例

### 场景 1: 快速原型（完全自动）

```bash
# 1. 启动自动模式
rh paper-production start \
  --topic "动态图表示学习" \
  --target-venue "ICLR" \
  --interaction-mode autonomous \
  --local-only

# 2. 工作流自动运行，AI 自动决策
# （除了高风险决策，如研究方向选择）

# 3. 检查进度
rh paper-production status --topic 1

# 输出:
# Current Stage: analyze
# Mode: autonomous (auto-applying decisions)
# ⚡ Auto-decision applied: broaden_search
```

### 场景 2: 审慎研究（检查点模式）

```bash
# 1. 启动检查点模式（默认）
rh paper-production start \
  --topic "因果图神经网络" \
  --target-venue "NeurIPS"

# 2. 工作流在每个决策点暂停
# Current Stage: init
# Status: paused
# Reason: insufficient_seed_papers

# 3. 使用 /rh-decide 做决策
rh paper-production decide --topic 1 \
  --action broaden_search \
  --reasoning "需要更全面的文献覆盖"

# 4. 继续运行
rh paper-production resume --topic 1
```

### 场景 3: 混合模式（启动自动，遇到问题切换）

```bash
# 1. 启动自动模式
rh paper-production start \
  --interaction-mode autonomous \
  --topic "..." --target-venue "..."

# 2. 发现 AI 做了不理想的决策
# （例如：自动扩展搜索但获取了太多低质量论文）

# 3. 切换到检查点模式
rh paper-production set-mode --topic 1 --mode checkpoint

# 4. 之后的决策都会暂停等待人工确认
```

---

## 🔧 新增 CLI 命令实现

### 1. `rh paper-production mode` - 查看当前模式

```python
# cli_paper_production.py
@paper_production_group.command("mode")
@click.option("--topic", type=int, required=True)
@click.pass_context
def paper_production_mode(ctx: click.Context, topic: int):
    """Show current interaction mode for a topic."""
    from .auto_runner import checkpoint as ckpt
    from .config import find_workspace_root

    ws = find_workspace_root()
    base_dir = ws / ".research-harness" if ws else Path.home() / ".research-harness"
    ckpt_path = ckpt.checkpoint_path(base_dir, topic)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)

    if not checkpoint_data:
        echo(ctx, {"error": "No checkpoint found"}, "No checkpoint found")
        return

    run_policy = checkpoint_data.get("paper_production_run_policy", {})
    mode = run_policy.get("interaction_mode", "checkpoint")

    from .auto_runner.interaction_mode import interaction_mode_description

    result = {
        "topic_id": topic,
        "interaction_mode": mode,
        "description": interaction_mode_description(mode),
        "can_auto_decide": mode == "autonomous",
    }

    if ctx.obj.get("json"):
        echo(ctx, result, "")
    else:
        echo(ctx, result, f"Mode: {mode}\n{result['description']}")
```

### 2. `rh paper-production set-mode` - 运行时切换

```python
# cli_paper_production.py
@paper_production_group.command("set-mode")
@click.option("--topic", type=int, required=True)
@click.option(
    "--mode",
    type=click.Choice(["autonomous", "checkpoint", "interactive"]),
    required=True,
)
@click.pass_context
def paper_production_set_mode(
    ctx: click.Context,
    topic: int,
    mode: str,
):
    """Change interaction mode for a running workflow."""
    from .auto_runner import checkpoint as ckpt
    from .config import find_workspace_root
    from .auto_runner.interaction_mode import interaction_mode_description

    ws = find_workspace_root()
    base_dir = ws / ".research-harness" if ws else Path.home() / ".research-harness"
    ckpt_path = ckpt.checkpoint_path(base_dir, topic)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)

    if not checkpoint_data:
        echo(ctx, {"error": "No checkpoint found"}, "No checkpoint found")
        return

    # Update mode in checkpoint
    old_mode = checkpoint_data.get("paper_production_run_policy", {}).get(
        "interaction_mode", "checkpoint"
    )

    run_policy = checkpoint_data.setdefault("paper_production_run_policy", {})
    run_policy["interaction_mode"] = mode
    run_policy["autonomous_completion"] = mode == "autonomous"

    # Record the change
    ckpt.record_event(
        checkpoint_data,
        stage=checkpoint_data.get("current_stage", "unknown"),
        event="interaction_mode_changed",
        detail=f"{old_mode} → {mode}",
    )

    ckpt.save_checkpoint(ckpt_path, checkpoint_data)

    result = {
        "topic_id": topic,
        "old_mode": old_mode,
        "new_mode": mode,
        "description": interaction_mode_description(mode),
    }

    echo(
        ctx,
        result,
        f"✅ Mode changed: {old_mode} → {mode}\n{result['description']}"
    )
```

### 3. `resume --auto` 临时自动模式

```python
# cli_paper_production.py 中的 resume 命令添加 --auto 选项
@paper_production_group.command("resume")
@click.option("--topic", type=int, required=True)
@click.option(
    "--auto",
    is_flag=True,
    default=False,
    help="Temporarily use autonomous mode for this resume (doesn't change saved mode)",
)
@click.pass_context
def paper_production_resume(
    ctx: click.Context,
    topic: int,
    auto: bool,
):
    """Resume a paused paper-production workflow."""
    from .auto_runner.runner import resume_topic
    from .config import find_workspace_root

    ws = find_workspace_root()
    base_dir = ws / ".research-harness" if ws else Path.home() / ".research-harness"

    # If --auto, temporarily apply auto-decision
    if auto:
        from .auto_runner import checkpoint as ckpt

        ckpt_path = ckpt.checkpoint_path(base_dir, topic)
        checkpoint_data = ckpt.load_checkpoint(ckpt_path)

        if checkpoint_data:
            # Check for pending decision and auto-apply
            decision = checkpoint_data.get("human_decision", {})
            if decision.get("requested"):
                from .auto_runner.interaction_mode import default_action_for_decision

                options = decision.get("options", [])
                choice = default_action_for_decision("autonomous", options)

                if choice:
                    from .auto_runner.runner import decide_human_checkpoint

                    decide_result = decide_human_checkpoint(
                        topic_id=topic,
                        choice=choice,
                        reasoning="Auto-applied via --auto flag",
                        base_dir=base_dir,
                    )
                    echo(ctx, decide_result, f"🤖 Auto-applied: {choice}")

    # Normal resume
    result = resume_topic(topic_id=topic, base_dir=base_dir)
    echo(ctx, result, f"Resumed topic {topic}")
```

---

## 🎨 斜杠命令中的模式控制

### `/rh-continue` 的模式感知

```python
# skills/rh-continue/implementation.py
def rh_continue(topic_id: int, force_auto: bool = False):
    """
    Smart continuation with mode awareness.
    
    Args:
        topic_id: Topic to continue
        force_auto: Temporarily use auto mode even if checkpoint mode
    """
    # Get current mode
    checkpoint_data = load_checkpoint(...)
    run_policy = checkpoint_data.get("paper_production_run_policy", {})
    current_mode = run_policy.get("interaction_mode", "checkpoint")
    
    # Override if force_auto
    effective_mode = "autonomous" if force_auto else current_mode
    
    # Check pending decisions
    decisions = rh.paper_production_pending_decisions(topic_id)
    
    if decisions.get("has_pending"):
        decision = decisions["decision"]
        
        if effective_mode == "autonomous":
            # Auto-apply
            choice = decision.get("recommended_action") or decision.get("default_action")
            print(f"🤖 Auto-applying: {choice} (mode: {effective_mode})")
            
        else:
            # Interactive
            print(f"⚠️  Decision required (mode: {effective_mode})")
            # Show AskUserQuestion...
```

### 用户调用方式

```bash
# Claude Code / Codex 中

# 默认：遵循设置的模式
/rh-continue

# 临时自动模式
/rh-continue --auto

# 检查当前模式
/rh-mode

# 切换模式
/rh-set-mode autonomous
```

---

## 📊 模式对比表

| 决策场景 | autonomous | checkpoint | interactive |
|---|---|---|---|
| 种子论文不足 | 🤖 自动扩展搜索 | ⏸️ 等待人类选择 | ⏸️ 等待 + 可询问更多信息 |
| 研究方向选择 | ⏸️ 高风险必须人工 | ⏸️ 等待人类选择 | ⏸️ 等待 + AI 可澄清各选项 |
| 预算超限 | 🤖 自动批准（低风险） | ⏸️ 等待确认 | ⏸️ 等待 + 可询问预算分配 |
| 数据集选择 | 🤖 自动选推荐 | ⏸️ 等待选择 | ⏸️ 等待 + 可询问数据集细节 |
| 实验规模 | 🤖 自动选默认 | ⏸️ 等待确认 | ⏸️ 等待 + 可询问资源需求 |
| 最终接受 | ⏸️ 高风险必须人工 | ⏸️ 等待人类接受 | ⏸️ 等待 + 可讨论改进点 |

---

## 🎯 推荐使用策略

### 初学者
```bash
# 第一次使用：检查点模式（默认）
rh paper-production start --topic "..." --target-venue "..."

# 学习决策模式
/rh-decide  # 看看 AI 如何推荐
```

### 熟练用户
```bash
# 日常使用：自动模式加速
rh paper-production start --interaction-mode autonomous

# 关键决策时切换
rh paper-production set-mode --topic 1 --mode checkpoint
```

### 高级用户
```bash
# 分阶段控制
# Init-Build: 自动
rh paper-production start --interaction-mode autonomous

# Analyze-Propose: 切换到检查点
rh paper-production set-mode --topic 1 --mode checkpoint

# Experiment-Write: 切换到交互
rh paper-production set-mode --topic 1 --mode interactive
```

---

## ⚙️ 配置文件支持

### 项目级默认模式

```yaml
# .research-harness/config.yaml
paper_production:
  default_interaction_mode: checkpoint
  
  # 按阶段覆盖
  stage_modes:
    init: autonomous      # 初始化自动
    build: autonomous     # 文献获取自动
    analyze: checkpoint   # 分析暂停
    propose: checkpoint   # 提案暂停
    experiment: checkpoint
    write: checkpoint
```

### 用户级偏好

```yaml
# ~/.research-harness/preferences.yaml
interaction:
  preferred_mode: checkpoint
  auto_advance_on_low_risk: true
  ask_reasoning: optional
  
  # 自动模式白名单决策点
  auto_approve_decisions:
    - insufficient_seed_papers
    - small_budget_increase
  
  # 永远需要人工的决策点
  always_manual_decisions:
    - direction_selection
    - final_acceptance
```

---

## 🔍 调试和监控

### 查看决策历史

```bash
# 查看所有决策记录
rh orchestrator decisions --topic 1

# 输出示例：
# Decision History for Topic 1:
# 1. insufficient_seed_papers → broaden_search (auto, 2026-07-05 10:23)
# 2. direction_selection → select_direction_0 (manual, 2026-07-05 10:45)
# 3. budget_approval → approve_budget (manual, 2026-07-05 11:12)
```

### 审计自动决策

```bash
# 只看自动决策
rh orchestrator decisions --topic 1 --auto-only

# 输出：
# Auto Decisions:
# - broaden_search (confidence: 85%, reason: recommended_default)
# - approve_small_budget (confidence: 92%, reason: low_risk_threshold)
```

---

## 💡 最佳实践

1. **默认检查点**: 不确定时用 checkpoint，安全可控
2. **信任建立**: 观察几次 AI 推荐后再切换 autonomous
3. **分阶段切换**: 初期自动，关键阶段人工
4. **记录理由**: 即使自动模式，也保存 auto_selection_reason
5. **定期审计**: 查看自动决策历史，优化白名单

---

## 📚 相关文档

- `docs/HITL_IMPLEMENTATION_SUMMARY.md` - 技术实现
- `docs/HITL_CLI_DESIGN.md` - CLI 设计
- `packages/research_harness/research_harness/auto_runner/interaction_mode.py` - 代码实现

---

**最后更新**: 2026-07-05  
**版本**: v2.0
