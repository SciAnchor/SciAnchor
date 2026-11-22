# Research Harness 快速开始

**5 分钟上手，完整端到端科研工作流。**

---

## 🎯 三种使用方式

### 方式 A: 一条命令（最简单，推荐新手） ⭐

**一行搞定，从零到论文！**

```bash
/rh-write "你的研究主题" 目标会议
```

👉 **直接跳转**: [`docs/ONE_COMMAND_QUICKSTART.md`](ONE_COMMAND_QUICKSTART.md)

**示例**:
```bash
/rh-write "时序图神经网络在交通预测中的应用" NeurIPS
```

**结果**: 1小时后得到完整 NeurIPS 格式论文

- ✅ 自动创建主题
- ✅ 自动获取文献
- ✅ 自动分析和设计
- ✅ 自动生成论文
- ⚠️  只在关键决策（如研究方向）时暂停

---

### 方式 B: 纯 CLI 对话（灵活，适合熟练用户）

**完全不需要打开终端！** 所有操作通过 MCP 工具在 Claude/Codex 中完成。

👉 **直接跳转**: [`docs/PURE_CLI_WORKFLOW.md`](PURE_CLI_WORKFLOW.md)

**示例对话**:
```
你: "我想研究时序图神经网络，帮我开始一个RH项目"

Claude/Codex: 
✅ 已创建主题 "时序图神经网络研究"（ID: 5）
需要添加一些种子论文吗？

你: "添加arXiv:2106.15012"

Claude/Codex:
✅ 已添加论文
现在启动paper production吗？目标会议是？

你: "NeurIPS，用checkpoint模式"

Claude/Codex:
✅ 已启动工作流
⚠️  需要决策：种子论文不足...
[展示选项和AI推荐]
```

---

### 方式 C: 混合模式（CLI + MCP 工具）

部分操作在终端，部分在 Claude/Codex。适合喜欢命令行的用户。

---

## 🚀 方式 C: 混合模式使用

### Step 1: 安装和配置

```bash
cd /path/to/research-harness

# 安装
./setup.sh

# 验证
rh doctor
```

**预期输出**:
```
✅ Database: connected
✅ MCP server: running
✅ API keys: configured
✅ Ready to use!
```

### Step 2: 创建你的第一个研究任务

```bash
# 初始化主题
rh topic init "时序图神经网络-交通预测"

# 添加几篇种子论文（可选）
rh paper ingest --arxiv-id 2106.15012 --topic 1
rh paper ingest --arxiv-id 2203.12345 --topic 1
```

### Step 3: 启动 Paper Production

```bash
# 使用默认检查点模式（推荐新手）
rh paper-production start \
  --topic 1 \
  --target-venue "NeurIPS"
```

### Step 4: 在 Claude Code / Codex 中交互

启动 Claude Code 或 Codex，然后：

```bash
# 查看状态
/rh-status

# 做决策
/rh-decide

# 继续推进
/rh-continue
```

重复 status → decide → continue，直到论文生成完成。

---

## ⚡ 熟练用户：快速模式

```bash
# 一键启动自动模式
rh paper-production start \
  --topic <your-topic-id> \
  --target-venue "NeurIPS" \
  --interaction-mode autonomous

# 后台监控
/rh-status  # 定期检查进度
```

AI 会自动完成大部分决策，只在关键点暂停（如研究方向选择）。

---

## 📚 核心文档导航

### 使用指南
- **[新研究任务完整工作流](NEW_RESEARCH_WORKFLOW.md)** ⭐ 最重要
  - 从创建主题到生成论文的完整步骤
  - 6 个阶段详解
  - 实战案例和时间线
  - 常见问题解答

- **[交互模式快速参考](INTERACTION_MODE_QUICKREF.md)**
  - 一页纸版本，最常用命令
  - 三种模式对比
  - 斜杠命令使用

- **[交互模式完整指南](INTERACTION_MODE_GUIDE.md)**
  - CLI 命令详解
  - 模式切换策略
  - 配置文件和最佳实践

### 维护和更新
- **[RH 更新和重载指南](RH_UPDATE_AND_RELOAD.md)**
  - 代码更新后如何重载
  - MCP 服务器重启
  - 自动化脚本
  - 热重载配置

### 技术实现
- **[HITL 实现总结](HITL_IMPLEMENTATION_SUMMARY.md)**
  - 架构设计
  - 决策点注册机制
  - 扩展指南

- **[HITL CLI 设计](HITL_CLI_DESIGN.md)**
  - UI 集成方案
  - 斜杠命令设计
  - 典型工作流

- **[Paper Management](PAPER_MANAGEMENT.md)**
  - 论文数据库管理
  - 获取和摄入协议

---

## 🎯 典型工作流

### 工作流 1: 审慎研究（新手推荐）

```bash
# 1. 创建主题
rh topic init "你的研究主题"

# 2. 添加 5-10 篇种子论文
rh paper ingest --arxiv-id ... --topic 1

# 3. 启动检查点模式
rh paper-production start --topic 1 --target-venue "NeurIPS" --interaction-mode checkpoint

# 4. 在 Claude/Codex 中逐步推进
/rh-status       # 查看当前状态
/rh-decide       # 做决策（AI 会给推荐）
/rh-continue     # 继续

# 重复 4，直到完成
```

**耗时**：2-3 小时  
**优点**：学习 RH 决策逻辑，完全掌控

### 工作流 2: 快速迭代（熟练用户）

```bash
# 1-2. 同上

# 3. 启动自动模式
rh paper-production start --topic 1 --target-venue "NeurIPS" --interaction-mode autonomous

# 4. 偶尔检查
/rh-status  # 每 15 分钟检查一次

# 5. 在关键决策点介入（自动模式也会暂停高风险决策）
/rh-decide  # 只在 AI 要求时
```

**耗时**：1 小时  
**优点**：快速，适合探索多个方向

### 工作流 3: 混合模式（推荐）

```bash
# 启动自动模式
rh paper-production start --topic 1 --interaction-mode autonomous

# 到关键阶段切换
rh paper-production set-mode --topic 1 --mode checkpoint

# 在 analyze 阶段人工选择研究方向
/rh-decide

# 方向确定后切回自动
rh paper-production set-mode --topic 1 --mode autonomous
```

**耗时**：1.5 小时  
**优点**：平衡速度和控制

---

## 🛠️ 常用命令速查

### 主题管理
```bash
rh topic list                        # 列出所有主题
rh topic init "主题名"                # 创建新主题
rh topic show --topic 1              # 查看主题详情
```

### 论文管理
```bash
rh paper ingest --arxiv-id 2106.15012 --topic 1     # 添加论文
rh paper list --topic 1                              # 列出论文
rh paper search "temporal GNN" --topic 1             # 搜索论文
```

### Paper Production
```bash
rh paper-production start --topic 1 --target-venue "NeurIPS"  # 启动
rh paper-production status --topic 1                           # 查看状态
rh paper-production mode --topic 1                             # 查看模式
rh paper-production set-mode --topic 1 --mode autonomous       # 切换模式
rh paper-production resume --topic 1                           # 恢复运行
```

### 斜杠命令（Claude Code / Codex）
```bash
/rh-status          # 查看状态
/rh-decide          # 做决策
/rh-continue        # 智能继续
/rh-continue --auto # 强制自动模式一次
```

### 系统维护
```bash
rh doctor                    # 健康检查
rh --version                 # 版本信息
pkill -f research_harness_mcp  # 重启 MCP 服务器
```

---

## ⚙️ 配置

### 最小配置（必需）

```yaml
# ~/.research-harness/config.yaml
api_keys:
  anthropic: "sk-ant-..."
  openai: "sk-..."
  
database:
  path: "~/.research-harness/pool.db"
```

### 推荐配置

```yaml
# ~/.research-harness/config.yaml
api_keys:
  anthropic: "sk-ant-..."
  openai: "sk-..."
  semantic_scholar: "your-key"  # 可选，提高速率限制

database:
  path: "~/.research-harness/pool.db"

paper_production:
  default_interaction_mode: "checkpoint"  # autonomous / checkpoint / interactive
  default_budget: 100.0  # USD
  
  stage_modes:
    init: "autonomous"      # 初始化自动
    build: "autonomous"     # 文献获取自动
    analyze: "checkpoint"   # 分析暂停
    propose: "checkpoint"   # 提案暂停
    experiment: "checkpoint"
    write: "checkpoint"

storage:
  pdf_dir: "~/.research-harness/pdfs"
  output_dir: "~/.research-harness/paper-production"

logging:
  level: "INFO"
  file: "~/.research-harness/logs/rh.log"
```

---

## 🔧 故障排除

### MCP 服务器连接失败

```bash
# 检查 MCP 进程
ps aux | grep research_harness_mcp

# 如果没有，手动启动
python -m research_harness_mcp

# 查看日志
tail -f ~/.research-harness/logs/mcp_server.log
```

### "Topic not found" 错误

```bash
# 检查主题列表
rh topic list

# 如果是新环境，初始化数据库
rh doctor --init-db
```

### 论文下载失败

```bash
# 检查 PDF 下载源配置
rh doctor --check-sources

# 尝试手动下载
rh paper ingest --arxiv-id 2106.15012 --topic 1 --force
```

### 代码更新后行为未变

```bash
# 重启 MCP 服务器
pkill -f research_harness_mcp

# 如果还不行，重启 Claude Desktop
osascript -e 'quit app "Claude"'
open -a Claude

# 详见: docs/RH_UPDATE_AND_RELOAD.md
```

---

## 📖 深入学习路径

1. **第一周**：跟着 [新研究任务工作流](NEW_RESEARCH_WORKFLOW.md) 完成一个完整项目
2. **第二周**：阅读 [交互模式指南](INTERACTION_MODE_GUIDE.md)，尝试不同模式
3. **第三周**：探索高级功能，阅读 [HITL 实现](HITL_IMPLEMENTATION_SUMMARY.md)
4. **持续**：提供反馈，优化个人工作流

---

## 🎓 示例项目

### 示例 1: 小规模探索

```bash
# 10 篇种子论文，快速生成 draft
rh topic init "TGNN-小规模探索"
# 添加 10 篇论文...
rh paper-production start --topic 1 --interaction-mode autonomous
```

**耗时**: 30 分钟  
**成本**: ~$15  
**产出**: 初步 draft，用于评估方向可行性

### 示例 2: 完整研究项目

```bash
# 50+ 篇文献，深入分析，完整论文
rh topic init "TGNN-完整项目"
# 添加 10 篇高质量种子论文...
rh paper-production start --topic 1 --interaction-mode checkpoint
```

**耗时**: 2-3 小时  
**成本**: ~$50  
**产出**: 符合会议标准的完整论文

### 示例 3: 多方向并行探索

```bash
# 同时探索 3 个研究方向
rh topic init "TGNN-方向A"
rh topic init "TGNN-方向B"
rh topic init "TGNN-方向C"

# 并行启动
rh paper-production start --topic 1 --interaction-mode autonomous &
rh paper-production start --topic 2 --interaction-mode autonomous &
rh paper-production start --topic 3 --interaction-mode autonomous &

# 比较结果，选择最佳方向
```

**耗时**: 1.5 小时（并行）  
**成本**: ~$45  
**产出**: 3 个方向的对比分析，选择最优路径

---

## 💡 最佳实践

1. **种子论文质量 > 数量**：5-10 篇高质量比 50 篇低质量好
2. **善用检查点模式**：第一次用新领域时，用 checkpoint 学习
3. **定期 /rh-status**：了解当前进度和花费
4. **保存中间产物**：export artifacts 用于其他用途
5. **提供反馈**：告诉 RH 哪些决策好 / 不好，帮助优化

---

## 🆘 获取帮助

- **文档**: `docs/` 目录下的所有 `.md` 文件
- **健康检查**: `rh doctor --verbose`
- **查看日志**: `~/.research-harness/logs/`
- **问题反馈**: GitHub Issues

---

## 🎯 下一步

**新手**: 立即运行 [新研究任务工作流](NEW_RESEARCH_WORKFLOW.md) 中的 Step 1-3

**熟练用户**: 阅读 [交互模式指南](INTERACTION_MODE_GUIDE.md) 优化你的工作流

**开发者**: 查看 [HITL 实现](HITL_IMPLEMENTATION_SUMMARY.md) 了解架构

---

**最后更新**: 2026-07-05  
**预计阅读时间**: 10 分钟
