# Research Harness CLI 能力总结

**问题**: 能不能全程在 Claude Code / Codex CLI 中使用 Research Harness？

**答案**: ✅ **可以！现在完全支持。**

---

## ✅ 已实现的纯 CLI 能力

通过 **9 个新增 MCP 工具**，现在可以全程在 Claude Code / Codex 中完成：

### 1. 主题管理
- ✅ `topic_init` - 创建新研究主题
- ✅ `topic_list` - 列出所有主题（已有）
- ✅ `topic_show` - 查看主题详情（已有）

### 2. 论文管理
- ✅ `paper_ingest` - 添加论文（已有）
- ✅ `paper_search` - 搜索论文（已有）
- ✅ `paper_list` - 列出论文（已有）

### 3. Paper Production 完整工作流
- ✅ `paper_production_start` - 启动工作流
- ✅ `paper_production_status` - 查看状态
- ✅ `paper_production_pending_decisions` - 查看待决策
- ✅ `paper_production_decide` - 做决策
- ✅ `paper_production_resume` - 继续运行
- ✅ `paper_production_mode` - 查看交互模式
- ✅ `paper_production_set_mode` - 切换模式
- ✅ `paper_production_export` - 导出论文

### 4. 其他已有工具
- ✅ `orchestrator_status` - 详细状态（已有）
- ✅ `claim_extract`, `gap_detect`, `baseline_identify` 等 30+ 工具（已有）

**总计**: **42 个公开 MCP 工具**，覆盖完整研究工作流。

---

## 🎯 完整工作流示例

### 在 Claude Code / Codex 中的对话

```
你: "我想研究时序图神经网络，目标NeurIPS"

AI: 执行 rh.topic_init(name="时序图神经网络研究")
    ✅ 创建了主题 ID 5

AI: 执行 rh.paper_production_start(topic_id=5, target_venue="NeurIPS", interaction_mode="checkpoint")
    ✅ 已启动工作流

AI: 执行 rh.paper_production_status(topic_id=5)
    ⚠️  决策需求：种子论文不足
    
    选项：
    1. ⭐ 扩展搜索（推荐，85%）
    2. 手动添加（40%）
    3. 继续（15%）

你: "选第一个"

AI: 执行 rh.paper_production_decide(topic_id=5, choice="broaden_search", reasoning="...")
    ✅ 决策已记录

AI: 执行 rh.paper_production_resume(topic_id=5)
    ✅ 工作流继续，现在在 build 阶段

... (15分钟后)

你: "看看进展"

AI: 执行 rh.paper_production_status(topic_id=5)
    📊 当前：analyze 阶段
    ✅ 已完成：init, build
    ⏸️  等待方向选择...

你: "切换到自动模式，让AI自动决策"

AI: 执行 rh.paper_production_set_mode(topic_id=5, mode="autonomous")
    ✅ 已切换到自动模式

AI: 执行 rh.paper_production_resume(topic_id=5)
    ✅ 工作流自动推进中...

... (45分钟后)

你: "完成了吗？"

AI: 执行 rh.paper_production_status(topic_id=5)
    ✅ 全部完成！write 阶段已完成

AI: 执行 rh.paper_production_export(topic_id=5)
    📄 导出：
    - paper.tex
    - paper.pdf
    - 3个图表
    - 2个表格
    
    📂 位置：~/.research-harness/paper-production/topic_5
```

**总耗时**: ~1小时  
**人工干预**: 2次（方向选择前切换到自动）  
**切换到终端次数**: 0次

---

## 🔄 RH 更新后的重载方式

**问题**: 如果每次 RH 有更新，是否需要手动重新挂载到 Claude 或 Codex？

**答案**: ✅ **不需要！只需重启 MCP 服务器。**

### 操作方式

```bash
# 99% 情况只需这一行：
pkill -f research_harness_mcp

# MCP 会自动重启（如果配置了 auto_restart）
# 或者手动启动：
# python -m research_harness_mcp
```

### 详细说明

| 更新类型 | 重载方式 | 需要重启 Claude/Codex |
|---|---|---|
| Python 业务逻辑 | `pkill -f research_harness_mcp` | ❌ 不需要 |
| MCP 工具定义 | `pkill ...` + 重启 Claude/Codex | ✅ 需要 |
| 配置文件 | 无需操作 | ❌ 不需要 |
| Python 依赖 | `pip install -e .` + `pkill ...` | ❌ 不需要 |
| Skills（slash 命令） | 无需操作 | ❌ 不需要 |

**简化规则**：
- 代码更新 → `pkill -f research_harness_mcp`
- 新增 MCP 工具 → `pkill ...` + 重启 Claude Desktop
- 其他 → 通常不需要操作

详见：[`docs/RH_UPDATE_AND_RELOAD.md`](RH_UPDATE_AND_RELOAD.md)

---

## 📊 对比表：终端 vs. 纯CLI

| 功能 | 传统终端 CLI | 纯 Claude/Codex CLI（本方案） |
|---|---|---|
| **创建主题** | `rh topic init "..."` | 对话："创建一个关于XXX的主题" |
| **添加论文** | `rh paper ingest --arxiv-id ... --topic X` | 对话："添加arXiv:XXX" |
| **启动工作流** | `rh paper-production start --topic X --target-venue "..." --interaction-mode checkpoint` | 对话："启动paper production，目标NeurIPS，checkpoint模式" |
| **查看状态** | `rh paper-production status --topic X` | 对话："看看进展" |
| **做决策** | `rh paper-production decide --topic X --action ... --reasoning "..."` | 对话："选第一个，理由是..." |
| **切换模式** | `rh paper-production set-mode --topic X --mode autonomous` | 对话："切换到自动模式" |
| **导出论文** | `cp -r ~/.research-harness/paper-production/topic_X ...` | 对话："导出论文" |
| **上下文记忆** | ❌ 每次需要指定 topic ID | ✅ AI 记住你的项目 |
| **AI推荐** | ❌ 没有 | ✅ 每个决策都有AI建议和置信度 |
| **友好展示** | ❌ 原始 JSON | ✅ 格式化、带emoji、结构清晰 |
| **学习曲线** | ⚠️  需要记命令 | ✅ 自然语言交互 |

---

## 💡 使用建议

### 首次使用（推荐纯CLI）

1. 打开 Claude Code 或 Codex
2. 说："我想用Research Harness写一篇论文"
3. 跟随 AI 引导，观察决策推荐
4. 学习 RH 的工作流程

### 熟练使用（混合模式）

1. 终端：快速列出主题 `rh topic list`
2. Claude/Codex：启动和推进工作流
3. 终端：导出和编辑论文

### 高级使用（纯CLI + 自动化）

1. Claude/Codex：对话式完成全流程
2. 并行探索多个方向
3. 自定义决策策略

---

## 📚 完整文档导航

### 使用指南
1. **[纯 CLI 工作流](PURE_CLI_WORKFLOW.md)** ⭐ 最重要
   - 完整对话示例
   - 自然语言交互
   - 9个新增工具详解

2. **[新研究任务工作流](NEW_RESEARCH_WORKFLOW.md)**
   - 6阶段详解
   - 终端CLI方式
   - 常见问题

3. **[快速开始](QUICK_START.md)**
   - 两种方式对比
   - 5分钟上手

### 交互模式
4. **[交互模式快速参考](INTERACTION_MODE_QUICKREF.md)**
   - 一页纸速查
   - autonomous / checkpoint / interactive

5. **[交互模式完整指南](INTERACTION_MODE_GUIDE.md)**
   - CLI 命令详解
   - 配置文件
   - 最佳实践

### 维护
6. **[RH 更新和重载](RH_UPDATE_AND_RELOAD.md)**
   - MCP 服务器重启
   - 自动化脚本
   - 热重载配置

### 技术
7. **[HITL 实现总结](HITL_IMPLEMENTATION_SUMMARY.md)**
   - 架构设计
   - 决策注册机制

8. **[HITL CLI 设计](HITL_CLI_DESIGN.md)**
   - UI 集成
   - 斜杠命令

---

## 🎯 快速决策树

**我应该用哪种方式？**

```
是否熟悉命令行？
├─ 否 → 纯 CLI（Claude/Codex）
│       优势：自然语言，AI推荐，友好展示
│       文档：PURE_CLI_WORKFLOW.md
│
└─ 是 → 你喜欢打字还是对话？
        ├─ 对话 → 纯 CLI（Claude/Codex）
        │          优势：更快，有上下文
        │
        └─ 打字 → 混合模式
                   终端：topic/paper管理
                   Claude/Codex：workflow推进
                   文档：NEW_RESEARCH_WORKFLOW.md
```

**我应该用哪种交互模式？**

```
首次使用？
├─ 是 → checkpoint（默认）
│       学习AI如何决策
│
└─ 否 → 信任AI的判断？
        ├─ 是 → autonomous
        │       快速，AI自动决策
        │
        └─ 否 → checkpoint
                把关重要决策
```

---

## 🚀 立即开始

### 方式 1: 纯 CLI（5分钟）

1. 打开 Claude Code 或 Codex
2. 输入："我想用Research Harness写一篇关于[你的主题]的论文"
3. 跟随 AI 指引

### 方式 2: 终端 CLI（10分钟）

1. 打开终端
2. `rh topic init "你的主题"`
3. `rh paper-production start --topic 1 --target-venue "NeurIPS"`
4. 切换到 Claude/Codex 继续

---

## 📊 实现状态

| 功能模块 | 状态 | 可用工具数 |
|---|---|---|
| 主题管理 | ✅ 完整 | 3 |
| 论文管理 | ✅ 完整 | 4 |
| Paper Production | ✅ 完整 | 9 |
| 研究原语 | ✅ 完整 | 15 |
| 辅助工具 | ✅ 完整 | 10 |
| **总计** | **✅ 全部就绪** | **42** |

---

## ✅ 总结

1. **✅ 可以全程在 CLI 中完成** - 通过 42 个 MCP 工具
2. **✅ 自然语言交互** - 不需要记命令
3. **✅ AI 智能推荐** - 每个决策都有建议和置信度
4. **✅ 自动重载** - 代码更新只需 `pkill -f research_harness_mcp`
5. **✅ 友好展示** - 格式化输出，不是原始JSON
6. **✅ 上下文记忆** - AI 记住你的项目和进度

**开始使用**: [`docs/PURE_CLI_WORKFLOW.md`](PURE_CLI_WORKFLOW.md)

---

**最后更新**: 2026-07-05  
**新增工具**: 9 个（topic_init + 8 个 paper_production_* 工具）  
**总工具数**: 42 个公开 MCP 工具
