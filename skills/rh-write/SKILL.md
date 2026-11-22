---
name: rh-write
description: One-command paper generation - creates topic, runs workflow, handles decisions, exports paper. Simplest way to use Research Harness.
trigger: Use when user types /rh-write or wants to "write a paper about X"
public_suite: paper
task_type: end-to-end
data_access_level: local-files
inputs: research topic, target venue, optional language and mode
outputs: complete research paper (LaTeX + PDF)
gates: none (handles internally)
artifact_schemas: topic_brief, paper_plan, draft_pack, final_bundle, publication_pack
estimated_runtime: 1-2 hours
---

# RH Write - 一键生成论文

最简单的 Research Harness 使用方式。一条命令完成从零到论文的全流程。

## Purpose

将复杂的 6 阶段工作流简化为一个斜杠命令，自动处理：
- ✅ 创建主题
- ✅ 启动 Paper Production
- ✅ 智能决策（使用 AI 推荐）
- ✅ 进度监控
- ✅ 导出论文

## When to Use

- 用户想快速生成论文，不想了解细节
- 首次使用 Research Harness
- 探索性研究，快速验证想法

## Usage

### 基础用法

```bash
/rh-write "时序图神经网络在交通预测中的应用" NeurIPS
```

### 完整用法

```bash
/rh-write <研究主题> <目标会议> [语言] [模式]
```

**参数**：
- `<研究主题>`: 论文主题（必需）
- `<目标会议>`: 目标会议/期刊，如 NeurIPS, ICML, CVPR（必需）
- `[语言]`: 论文语言，中文/英文（可选，默认英文）
- `[模式]`: autonomous/checkpoint（可选，默认 autonomous）

### 示例

```bash
# 英文论文，自动模式
/rh-write "Graph Neural Networks for Drug Discovery" NeurIPS

# 中文论文，自动模式
/rh-write "基于图神经网络的药物发现" 中国计算机学会A类 中文

# 英文论文，检查点模式（在关键决策时暂停）
/rh-write "Temporal GNN for Traffic Prediction" ICML checkpoint

# 完整参数
/rh-write "联邦学习与隐私保护" AAAI 中文 checkpoint
```

## Implementation

```python
from research_harness_mcp import tools as rh
import time

def rh_write(
    topic: str,
    venue: str,
    language: str = "英文",
    mode: str = "autonomous"
):
    """
    One-command paper generation.
    
    Args:
        topic: Research topic
        venue: Target venue (e.g., "NeurIPS", "ICML")
        language: "中文" or "英文"
        mode: "autonomous" or "checkpoint"
    """
    
    print(f"🚀 启动 Research Harness 论文生成")
    print(f"   主题：{topic}")
    print(f"   目标：{venue}")
    print(f"   语言：{language}")
    print(f"   模式：{mode}")
    print()
    
    # Step 1: Create topic
    print("📝 [1/6] 创建研究主题...")
    topic_result = rh.topic_init(
        name=topic,
        description=f"Research on {topic}, target venue: {venue}",
        tags=extract_tags_from_topic(topic)
    )
    topic_id = topic_result["output"]["topic_id"]
    print(f"   ✅ 主题已创建（ID: {topic_id}）")
    print()
    
    # Step 2: Start paper production
    print("🏃 [2/6] 启动 Paper Production 工作流...")
    
    # Determine paper_mode based on language
    paper_mode = "main"  # For now, always use main mode
    
    start_result = rh.paper_production_start(
        topic_id=topic_id,
        target_venue=venue,
        interaction_mode=mode,
        paper_mode=paper_mode
    )
    print(f"   ✅ 工作流已启动")
    print()
    
    # Step 3: Monitor and handle decisions
    print("⚙️  [3/6] 工作流执行中...")
    if mode == "autonomous":
        print("   使用自动模式，AI 将自动处理大部分决策")
        print("   （高风险决策如研究方向选择仍需人工确认）")
    else:
        print("   使用检查点模式，关键决策将暂停等待确认")
    print()
    
    # Main workflow loop
    iteration = 0
    last_stage = None
    
    while True:
        iteration += 1
        
        # Get status
        status = rh.paper_production_status(topic_id=topic_id)
        current_stage = status["output"]["orchestrator"]["run"]["current_stage"]
        stage_status = status["output"]["orchestrator"]["run"]["stage_status"]
        
        # Show progress if stage changed
        if current_stage != last_stage:
            stage_emoji = {
                "init": "🔧",
                "build": "📚",
                "analyze": "🔍",
                "propose": "💡",
                "experiment": "🧪",
                "write": "✍️"
            }
            emoji = stage_emoji.get(current_stage, "▶️")
            print(f"   {emoji} 当前阶段：{current_stage}")
            last_stage = current_stage
        
        # Check for pending decisions
        decisions = status["output"].get("pending_decisions", {})
        
        if decisions.get("has_pending"):
            decision = decisions["decision"]
            reason = decision.get("reason_code")
            
            print(f"\n   ⚠️  需要决策：{reason}")
            
            if mode == "autonomous":
                # Auto-apply in autonomous mode
                recommended = decision.get("recommended_action")
                default = decision.get("default_action")
                choice = recommended or default
                
                if choice:
                    # Check if it's a high-risk decision
                    high_risk = is_high_risk_decision(reason)
                    
                    if high_risk:
                        # Show options and ask user
                        print("\n   🛑 这是高风险决策，需要人工确认：\n")
                        show_decision_options(decision)
                        
                        # Use AskUserQuestion
                        from research_harness.auto_runner.decision_ui import (
                            format_decision_for_ask_user_question
                        )
                        auq_format = format_decision_for_ask_user_question(decision)
                        answer = AskUserQuestion(questions=auq_format["questions"])
                        
                        # Extract choice from answer
                        from research_harness.auto_runner.decision_ui import (
                            extract_action_from_selection
                        )
                        choice = extract_action_from_selection(
                            answer, decision["options"]
                        )
                    else:
                        # Auto-apply for low-risk
                        print(f"   🤖 自动选择：{choice}")
                        print(f"      （AI 推荐，置信度：{decision.get('preference_score', 0)*100:.0f}%）")
                    
                    # Apply decision
                    rh.paper_production_decide(
                        topic_id=topic_id,
                        choice=choice,
                        reasoning="Auto-applied via /rh-write"
                    )
                    print(f"   ✅ 决策已应用，继续执行...\n")
                    
                    # Resume
                    rh.paper_production_resume(topic_id=topic_id)
                    
            else:
                # Checkpoint mode - always ask user
                print("\n   可选操作：\n")
                show_decision_options(decision)
                
                from research_harness.auto_runner.decision_ui import (
                    format_decision_for_ask_user_question,
                    extract_action_from_selection
                )
                
                auq_format = format_decision_for_ask_user_question(decision)
                answer = AskUserQuestion(questions=auq_format["questions"])
                choice = extract_action_from_selection(answer, decision["options"])
                
                rh.paper_production_decide(
                    topic_id=topic_id,
                    choice=choice,
                    reasoning="User selection via /rh-write"
                )
                print(f"   ✅ 决策已记录\n")
                
                rh.paper_production_resume(topic_id=topic_id)
        
        # Check if complete
        if current_stage == "write" and stage_status == "complete":
            break
        
        # Check if stuck
        if stage_status == "failed":
            print(f"   ❌ 工作流失败，阶段：{current_stage}")
            print(f"   请使用 /rh-status 查看详细错误信息")
            return
        
        # Wait before next check
        if iteration % 5 == 0:
            print(f"   ⏳ 仍在运行...（已等待 {iteration * 10} 秒）")
        
        time.sleep(10)  # Check every 10 seconds
    
    print("   ✅ 工作流完成！")
    print()
    
    # Step 4: Export paper
    print("📦 [4/6] 导出论文...")
    export_result = rh.paper_production_export(
        topic_id=topic_id,
        format="both",
        include_artifacts=True
    )
    
    output_dir = export_result["output"]["output_directory"]
    files = export_result["output"]["files"]
    
    print(f"   ✅ 论文已导出")
    print()
    
    # Step 5: Show summary
    print("📊 [5/6] 生成摘要...")
    
    # Get final status for cost info
    final_status = rh.paper_production_status(topic_id=topic_id)
    
    print()
    print("═" * 70)
    print("✅ 论文生成完成！")
    print("═" * 70)
    print()
    print(f"📂 输出目录：{output_dir}")
    print()
    print("📄 生成的文件：")
    
    if files.get("latex"):
        print(f"   LaTeX: {', '.join([f.split('/')[-1] for f in files['latex']])}")
    if files.get("pdf"):
        print(f"   PDF: {', '.join([f.split('/')[-1] for f in files['pdf']])}")
    if files.get("figures"):
        print(f"   图表: {len(files['figures'])} 个")
    if files.get("tables"):
        print(f"   表格: {len(files['tables'])} 个")
    
    print()
    print("💡 下一步：")
    print(f"   1. 查看论文：open {output_dir}/paper.pdf")
    print(f"   2. 编辑源文件：{output_dir}/paper.tex")
    print(f"   3. 复制到工作目录：cp -r {output_dir} ~/my-paper/")
    print()
    print("═" * 70)


def extract_tags_from_topic(topic: str) -> list[str]:
    """Extract potential tags from topic string."""
    # Simple keyword extraction
    keywords = []
    
    if "图神经网络" in topic or "GNN" in topic.upper() or "Graph Neural" in topic:
        keywords.append("graph-neural-networks")
    if "时序" in topic or "temporal" in topic.lower() or "time" in topic.lower():
        keywords.append("temporal-modeling")
    if "交通" in topic or "traffic" in topic.lower():
        keywords.append("traffic-prediction")
    if "推荐" in topic or "recommendation" in topic.lower():
        keywords.append("recommender-systems")
    if "联邦学习" in topic or "federated" in topic.lower():
        keywords.append("federated-learning")
    if "药物" in topic or "drug" in topic.lower():
        keywords.append("drug-discovery")
    
    return keywords or ["machine-learning", "deep-learning"]


def is_high_risk_decision(reason_code: str) -> bool:
    """Check if a decision is high-risk and requires human confirmation."""
    high_risk_codes = [
        "multiple_directions_available",  # Research direction selection
        "direction_selection",
        "final_acceptance",  # Final paper acceptance
        "major_revision_required",
    ]
    return reason_code in high_risk_codes


def show_decision_options(decision: dict):
    """Show decision options in a friendly format."""
    options = decision.get("options", [])
    
    for i, opt in enumerate(options, 1):
        label = opt.get("label", "")
        desc = opt.get("description", "")
        recommended = opt.get("recommended", False)
        score = opt.get("preference_score", 0)
        
        marker = "⭐" if recommended else "  "
        print(f"   {marker} {i}. {label}")
        print(f"      {desc}")
        if score > 0:
            print(f"      置信度：{score*100:.0f}%")
        print()
```

## Output Examples

### Example 1: Successful run (autonomous mode)

```
User: /rh-write "时序图神经网络在交通预测中的应用" NeurIPS

🚀 启动 Research Harness 论文生成
   主题：时序图神经网络在交通预测中的应用
   目标：NeurIPS
   语言：英文
   模式：autonomous

📝 [1/6] 创建研究主题...
   ✅ 主题已创建（ID: 5）

🏃 [2/6] 启动 Paper Production 工作流...
   ✅ 工作流已启动

⚙️  [3/6] 工作流执行中...
   使用自动模式，AI 将自动处理大部分决策
   （高风险决策如研究方向选择仍需人工确认）

   🔧 当前阶段：init
   
   ⚠️  需要决策：insufficient_seed_papers
   🤖 自动选择：broaden_search
      （AI 推荐，置信度：85%）
   ✅ 决策已应用，继续执行...

   📚 当前阶段：build
   ⏳ 仍在运行...（已等待 50 秒）
   
   🔍 当前阶段：analyze
   
   ⚠️  需要决策：multiple_directions_available
   
   🛑 这是高风险决策，需要人工确认：

   ⭐ 1. TGNN + 时空注意力机制
      现有TGNN未充分利用交通网络的空间局部性
      置信度：82%

     2. TGNN + 因果推理
      交通预测中因果关系未被建模
      置信度：70%

     3. TGNN + 联邦学习
      多城市数据隐私问题
      置信度：55%

[AskUserQuestion 弹出选择框]

   ✅ 决策已应用，继续执行...

   💡 当前阶段：propose
   🧪 当前阶段：experiment
   ✍️ 当前阶段：write
   ✅ 工作流完成！

📦 [4/6] 导出论文...
   ✅ 论文已导出

📊 [5/6] 生成摘要...

══════════════════════════════════════════════════════════════════════
✅ 论文生成完成！
══════════════════════════════════════════════════════════════════════

📂 输出目录：~/.research-harness/paper-production/topic_5

📄 生成的文件：
   LaTeX: paper.tex, neurips_2026.sty
   PDF: paper.pdf
   图表: 3 个
   表格: 2 个

💡 下一步：
   1. 查看论文：open ~/.research-harness/paper-production/topic_5/paper.pdf
   2. 编辑源文件：~/.research-harness/paper-production/topic_5/paper.tex
   3. 复制到工作目录：cp -r ~/.research-harness/paper-production/topic_5 ~/my-paper/

══════════════════════════════════════════════════════════════════════
```

### Example 2: With language option

```
User: /rh-write "基于深度学习的图像分类" 中国计算机学会A类 中文

🚀 启动 Research Harness 论文生成
   主题：基于深度学习的图像分类
   目标：中国计算机学会A类
   语言：中文
   模式：autonomous

[工作流程...]
```

## Best Practices

1. **首次使用建议用 checkpoint 模式**：
   ```bash
   /rh-write "你的主题" NeurIPS checkpoint
   ```
   可以观察 AI 如何决策

2. **熟练后用 autonomous 模式**：
   ```bash
   /rh-write "你的主题" ICML
   ```
   快速生成，只在高风险决策时暂停

3. **主题描述要具体**：
   - ❌ "图神经网络"（太宽泛）
   - ✅ "图神经网络在推荐系统中的应用"（具体）

4. **选择合适的目标会议**：
   - 影响论文风格和长度
   - NeurIPS/ICML: 8-9 页
   - AAAI/IJCAI: 7 页

## Integration

与其他技能的关系：
- 替代：`/rh-status` + `/rh-decide` + `/rh-continue` 的手动循环
- 互补：可以在执行中随时 Ctrl+C 中断，切换到手动模式
- 扩展：生成后可以用 `/rh-feedback` 提供反馈

## Skill Metadata

- **Frequency**: High (主要入口)
- **Criticality**: Very High (端到端流程)
- **User satisfaction**: Very High (最简单方式)
- **Automation potential**: Very High (几乎全自动)
