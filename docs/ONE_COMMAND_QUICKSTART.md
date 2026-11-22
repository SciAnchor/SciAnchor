# Research Harness - 一条命令生成论文

> **场景 S1 — 新 topic 从零开始（最简路径）。** 分步控制版见
> `NEW_RESEARCH_WORKFLOW.md`；agent 分层入口见 `docs/AGENT_OPERATIONS.md`。

**最简单的使用方式** - 一条斜杠命令，从零到论文。

---

## 🚀 极简用法

在 **Claude Code** 或 **Codex** 中输入：

```bash
/rh-write "你的研究主题" 目标会议
```

**就这么简单！** 1-2小时后得到完整论文。

---

## 📋 完整格式

```bash
/rh-write <研究主题> <目标会议> [语言] [模式]
```

### 参数说明

| 参数 | 必需? | 说明 | 示例 |
|---|---|---|---|
| `研究主题` | ✅ 必需 | 你的研究方向 | "时序图神经网络在交通预测中的应用" |
| `目标会议` | ✅ 必需 | 投稿目标 | NeurIPS, ICML, AAAI, CVPR |
| `语言` | ⭕ 可选 | 中文/英文 | 默认：英文 |
| `模式` | ⭕ 可选 | autonomous/checkpoint | 默认：autonomous（自动） |

---

## 💡 使用示例

### 示例 1: 最简单（默认英文，自动模式）

```bash
/rh-write "Graph Neural Networks for Drug Discovery" NeurIPS
```

**结果**: 1小时后得到英文 NeurIPS 格式论文

---

### 示例 2: 中文论文

```bash
/rh-write "基于图神经网络的药物发现" 中国计算机学会A类 中文
```

**结果**: 中文论文

---

### 示例 3: 检查点模式（想参与决策）

```bash
/rh-write "Temporal GNN for Traffic Prediction" ICML checkpoint
```

**结果**: 在关键决策点暂停，让你选择

---

### 示例 4: 完整参数

```bash
/rh-write "联邦学习与隐私保护" AAAI 中文 checkpoint
```

**结果**: 中文 AAAI 论文，关键决策时暂停

---

## 🎬 完整流程演示

### 你只需要输入：

```
/rh-write "时序图神经网络在交通预测中的应用" NeurIPS
```

### AI 会自动完成：

```
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

   🔧 当前阶段：init
   ⚠️  需要决策：种子论文不足
   🤖 自动选择：扩展搜索（AI 推荐，置信度：85%）
   ✅ 决策已应用

   📚 当前阶段：build（文献获取）
   
   🔍 当前阶段：analyze（文献分析）
   ⚠️  需要决策：研究方向选择
   
   🛑 这是高风险决策，需要人工确认：
   
   ⭐ 1. TGNN + 时空注意力机制（推荐，82%）
      创新点：时空解耦注意力
   
     2. TGNN + 因果推理（70%）
      创新点：因果图注意力
   
     3. TGNN + 联邦学习（55%）
      创新点：分布式TGNN训练
```

**此时会弹出选择框，你选择一个方向**

```
   ✅ 决策已应用，继续执行

   💡 当前阶段：propose（方法设计）
   
   🧪 当前阶段：experiment（实验执行）
   
   ✍️ 当前阶段：write（论文撰写）
   
   ✅ 工作流完成！

📦 [4/6] 导出论文...
   ✅ 论文已导出

══════════════════════════════════════════════════════════════════
✅ 论文生成完成！
══════════════════════════════════════════════════════════════════

📂 输出目录：~/.research-harness/paper-production/topic_5

📄 生成的文件：
   LaTeX: paper.tex
   PDF: paper.pdf
   图表: 3 个
   表格: 2 个

💡 下一步：
   1. 查看论文：open ~/.research-harness/paper-production/topic_5/paper.pdf
   2. 编辑源文件：~/.research-harness/paper-production/topic_5/paper.tex
   3. 复制到工作目录：cp -r ~/.research-harness/paper-production/topic_5 ~/my-paper/

══════════════════════════════════════════════════════════════════
```

**总耗时**: 约 1 小时  
**你的操作**: 输入 1 条命令 + 选择 1 次方向

---

## 🎯 两种模式对比

### autonomous 模式（默认，推荐）

```bash
/rh-write "你的主题" NeurIPS
```

**特点**:
- ✅ 最快，几乎全自动
- ✅ AI 自动处理大部分决策
- ⚠️  高风险决策（如研究方向）仍会暂停

**适合**: 快速迭代，信任 AI 判断

---

### checkpoint 模式

```bash
/rh-write "你的主题" NeurIPS checkpoint
```

**特点**:
- ⏸️  在每个关键决策点暂停
- 👤 你掌控所有决策
- 🎓 可以学习 AI 的推荐逻辑

**适合**: 首次使用，想了解决策过程

---

## 🎓 推荐学习路径

### 第一次使用（用 checkpoint）

```bash
/rh-write "你感兴趣的主题" NeurIPS checkpoint
```

观察 AI 如何推荐，了解决策逻辑。

---

### 第二次使用（用 autonomous）

```bash
/rh-write "另一个主题" ICML
```

让 AI 自动处理，体验全自动流程。

---

### 熟练使用（autonomous + 并行）

```bash
# 同时探索 3 个方向
/rh-write "方向A：GNN图像分类" NeurIPS
/rh-write "方向B：TGNN时序预测" NeurIPS  
/rh-write "方向C：GNN推荐系统" NeurIPS

# 1小时后比较 3 篇论文，选择最佳方向深入
```

---

## 🔧 常见问题

### Q1: 可以中途暂停吗？

**A**: 可以！按 Ctrl+C 中断，然后用：

```bash
/rh-status  # 查看状态
/rh-continue  # 继续运行
```

### Q2: 想修改 AI 的决策怎么办？

**A**: 使用 checkpoint 模式，或中途切换：

```bash
# 先自动模式启动
/rh-write "主题" NeurIPS

# 中途切换到人工模式
/rh-status  # 看到当前 topic_id
rh.paper_production_set_mode(topic_id=5, mode="checkpoint")
```

### Q3: 论文质量不满意？

**A**: 可以：
1. 用 checkpoint 模式重新运行，人工把关每个决策
2. 修改生成的 LaTeX 源文件
3. 提供反馈：`/rh-feedback`

### Q4: 支持哪些会议/期刊？

**A**: 支持所有主流会议：
- AI: NeurIPS, ICML, ICLR, AAAI, IJCAI
- CV: CVPR, ICCV, ECCV
- NLP: ACL, EMNLP, NAACL
- 中文: 中国计算机学会A/B/C类

### Q5: 需要准备种子论文吗？

**A**: 不需要！AI 会自动搜索和获取相关文献。

（如果你有推荐的论文，可以用 `/rh-status` 查看 topic_id，然后手动添加）

---

## 📊 与其他方式对比

| 方式 | 命令数 | 耗时 | 复杂度 | 适合人群 |
|---|---|---|---|---|
| **`/rh-write`** | **1条** | **1小时** | **极简** | **所有人（推荐）** |
| 纯 CLI 对话 | 多次对话 | 1-2小时 | 简单 | 喜欢对话的用户 |
| 传统 CLI | 10+ 条命令 | 2-3小时 | 中等 | 熟悉命令行的用户 |

---

## 🚀 立即开始

### 在 Claude Code 或 Codex 中输入：

```bash
/rh-write "你的研究主题" NeurIPS
```

### 或者用自然语言：

```
我想写一篇关于时序图神经网络的 NeurIPS 论文
```

AI 会自动调用 `/rh-write` 完成。

---

## 📚 进阶学习

想了解更多？查看：

- **完整对话式工作流**: `docs/PURE_CLI_WORKFLOW.md`
- **传统 CLI 方式**: `docs/NEW_RESEARCH_WORKFLOW.md`
- **交互模式详解**: `docs/INTERACTION_MODE_GUIDE.md`

---

**最后更新**: 2026-07-05  
**一条命令**: `/rh-write <主题> <会议> [语言] [模式]`  
**平均耗时**: 1-2 小时  
**人工操作**: 1-2 次决策选择
