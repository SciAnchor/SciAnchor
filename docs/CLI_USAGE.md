# Research Harness - CLI 完整使用指南

**三种方式，从零到论文，全程不离开 Claude Code / Codex**

---

## 🎯 快速开始

### 最简单方式（推荐）

在 **Claude Code** 或 **Codex** 中输入：

```bash
/rh-write "时序图神经网络在交通预测中的应用" NeurIPS
```

**就这么简单！** 1小时后得到完整论文。

---

## 📚 完整文档索引

| 文档 | 用途 | 适合人群 |
|---|---|---|
| **[ONE_COMMAND_QUICKSTART.md](docs/ONE_COMMAND_QUICKSTART.md)** ⭐ | 一条命令生成论文 | 所有人（最简单） |
| **[PURE_CLI_WORKFLOW.md](docs/PURE_CLI_WORKFLOW.md)** | 纯对话式完整示例 | 想要灵活控制的用户 |
| **[CLI_CAPABILITIES_SUMMARY.md](docs/CLI_CAPABILITIES_SUMMARY.md)** | 能力总结和对比 | 想了解全貌的用户 |
| **[NEW_RESEARCH_WORKFLOW.md](docs/NEW_RESEARCH_WORKFLOW.md)** | 传统 CLI 方式 | 喜欢命令行的用户 |
| **[RH_UPDATE_AND_RELOAD.md](docs/RH_UPDATE_AND_RELOAD.md)** | 更新和重载 | 开发者 |
| **[INTERACTION_MODE_GUIDE.md](docs/INTERACTION_MODE_GUIDE.md)** | 交互模式详解 | 高级用户 |
| **[QUICK_START.md](docs/QUICK_START.md)** | 快速开始总览 | 新用户 |

---

## 🚀 三种使用方式

### 方式 1: 一条命令（最简单） ⭐

```bash
/rh-write "研究主题" 目标会议 [语言] [模式]
```

**示例**：
```bash
/rh-write "Graph Neural Networks for Drug Discovery" NeurIPS
/rh-write "基于深度学习的图像分类" AAAI 中文
/rh-write "Temporal GNN for Traffic Prediction" ICML checkpoint
```

**特点**：
- ✅ 一条命令完成全流程
- ✅ 自动处理所有步骤
- ✅ 只在高风险决策时暂停
- ⏱️  约 1 小时完成

📖 **详见**: [ONE_COMMAND_QUICKSTART.md](docs/ONE_COMMAND_QUICKSTART.md)

---

### 方式 2: 纯对话式（灵活）

**你说**：
```
我想研究时序图神经网络在交通预测中的应用，目标 NeurIPS
```

**AI 自动执行**：
- 创建主题
- 启动工作流
- 展示决策选项（带 AI 推荐和置信度）
- 等待你选择
- 继续执行
- 导出论文

**特点**：
- ✅ 自然语言交互
- ✅ 每步都有 AI 推荐
- ✅ 完全掌控决策
- ⏱️  约 1-2 小时

📖 **详见**: [PURE_CLI_WORKFLOW.md](docs/PURE_CLI_WORKFLOW.md)

---

### 方式 3: 混合模式（传统）

部分终端，部分 Claude/Codex：

```bash
# 终端
rh topic init "时序图神经网络"
rh paper-production start --topic 1 --target-venue "NeurIPS"

# Claude/Codex
/rh-status
/rh-decide
/rh-continue
```

**特点**：
- ✅ 命令行控制
- ✅ Claude/Codex 辅助决策
- ⏱️  约 2-3 小时

📖 **详见**: [NEW_RESEARCH_WORKFLOW.md](docs/NEW_RESEARCH_WORKFLOW.md)

---

## 🔧 安装和配置

### 首次安装

```bash
cd /path/to/scianchor
./setup.sh
rh doctor
```

### MCP 服务器配置

**Claude Desktop** 会自动识别 MCP 服务器（如果已配置）

**Codex** 通过 HTTP API 连接（需要启动 HTTP 服务器）

---

## 🔄 代码更新后重载

### 快捷方式（推荐）

```bash
cd /path/to/scianchor
./scripts/reload-rh-mcp.sh
```

### 手动方式

```bash
# 重启 MCP 服务器
pkill -f research_harness_mcp

# 重启 Claude Desktop（如果需要新工具识别）
osascript -e 'quit app "Claude"'
open -a Claude
```

📖 **详见**: [RH_UPDATE_AND_RELOAD.md](docs/RH_UPDATE_AND_RELOAD.md)

---

## 📊 已实现功能

### MCP 工具（42 个）

#### 新增工作流工具（9 个）
- `topic_init` - 创建主题
- `paper_production_start` - 启动工作流
- `paper_production_status` - 查看状态
- `paper_production_pending_decisions` - 查看待决策
- `paper_production_decide` - 做决策
- `paper_production_resume` - 继续运行
- `paper_production_mode` - 查看模式
- `paper_production_set_mode` - 切换模式
- `paper_production_export` - 导出论文

#### 已有研究工具（32 个）
- 主题管理: `topic_list`, `topic_show`
- 论文管理: `paper_search`, `paper_ingest`, `paper_list`
- 研究原语: `claim_extract`, `gap_detect`, `baseline_identify`
- 论文写作: `section_draft`, `figure_generate`, `consistency_check`
- 工作流: `orchestrator_*` 系列
- 其他: `provenance_*`, `skill_*`, `zotero_sync` 等

### 斜杠命令（1 个）

- `/rh-write` - 一键生成论文

---

## 💡 使用示例

### 示例 1: 快速探索（自动模式）

```bash
/rh-write "Graph Attention Networks for Node Classification" NeurIPS
```

**过程**：
1. AI 自动创建主题
2. AI 自动获取文献
3. AI 自动分析
4. **你选择研究方向**（高风险决策）
5. AI 自动完成剩余步骤
6. 得到论文

**耗时**: ~1 小时

---

### 示例 2: 审慎研究（检查点模式）

```bash
/rh-write "Federated Learning with Privacy Preservation" ICML checkpoint
```

**过程**：
1. 每个关键决策都暂停
2. AI 展示选项和推荐
3. 你选择
4. 继续

**耗时**: ~2 小时（因为需要多次人工确认）

---

### 示例 3: 并行探索（多个方向）

```bash
# 同时探索 3 个方向
/rh-write "方向A：GNN for Image Classification" NeurIPS
/rh-write "方向B：TGNN for Time Series" NeurIPS
/rh-write "方向C：GNN for Recommendation" NeurIPS
```

1 小时后比较 3 篇论文，选择最佳方向深入。

---

## 🎓 学习路径

### 第 1 天: 了解基础

1. 阅读 [ONE_COMMAND_QUICKSTART.md](docs/ONE_COMMAND_QUICKSTART.md)
2. 运行一次：`/rh-write "测试主题" NeurIPS checkpoint`
3. 观察 AI 如何推荐

### 第 2-3 天: 实践使用

1. 用自己的研究方向运行一次
2. 尝试不同的会议格式
3. 理解决策逻辑

### 第 1 周: 熟练掌握

1. 切换到自动模式：`/rh-write "主题" NeurIPS`
2. 并行探索多个方向
3. 自定义决策策略

### 第 2 周: 高级技巧

1. 阅读 [INTERACTION_MODE_GUIDE.md](docs/INTERACTION_MODE_GUIDE.md)
2. 混合使用多种方式
3. 优化个人工作流

---

## ❓ 常见问题

### Q1: 不需要准备种子论文吗？

**A**: 不需要！AI 会自动搜索和获取相关文献。（如果你有推荐的论文，可以手动添加）

### Q2: 可以中途暂停吗？

**A**: 可以！按 Ctrl+C 中断，之后用 `/rh-continue` 继续。

### Q3: 论文质量不满意怎么办？

**A**: 
- 用 `checkpoint` 模式重新运行，人工把关每个决策
- 修改生成的 LaTeX 源文件
- 提供反馈：`/rh-feedback`

### Q4: 支持中文论文吗？

**A**: 支持！加上 `中文` 参数：
```bash
/rh-write "基于深度学习的图像分类" 中国计算机学会A类 中文
```

### Q5: 如何知道 RH 更新了？

**A**: 
```bash
git pull
./scripts/reload-rh-mcp.sh
```

---

## 🆘 获取帮助

- **文档**: 查看 `docs/` 目录
- **健康检查**: `rh doctor --verbose`
- **日志**: `~/.research-harness/logs/`
- **问题反馈**: GitHub Issues

---

## 📈 版本历史

### v2.0 (2026-07-05)

- ✅ 新增 9 个完整工作流 MCP 工具
- ✅ 新增 `/rh-write` 一键命令
- ✅ 完整纯 CLI 支持
- ✅ 自动重载脚本
- ✅ 7 份完整文档

### v1.0

- ✅ 基础 MCP 工具
- ✅ 传统 CLI 支持

---

## 🎯 立即开始

在 **Claude Code** 或 **Codex** 中输入：

```bash
/rh-write "你的研究主题" NeurIPS
```

或者说：

```
我想用 Research Harness 写一篇论文
```

**就这么简单！** AI 会引导你完成全流程。

---

**维护者**: SciAnchor Team  
**最后更新**: 2026-07-05  
**仓库**: `/path/to/scianchor`
