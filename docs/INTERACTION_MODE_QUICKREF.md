# 交互模式快速参考卡

> **已并入 `docs/HITL_QUICK_START.md`（唯一 HITL 快速参考），本文件保留为历史速查卡。**

## 🎯 一句话选择

- **我想让 AI 全自动运行** → `--interaction-mode autonomous`
- **我想在关键决策时把关** → `--interaction-mode checkpoint` (默认，推荐)
- **我需要和 AI 双向沟通** → `--interaction-mode interactive`

---

## ⚡ 最常用命令

### 启动时指定模式

```bash
# 完全自动（AI 自动决策，高风险除外）
rh paper-production start \
  --topic "你的研究主题" \
  --target-venue "NeurIPS" \
  --interaction-mode autonomous

# 检查点模式（在决策点暂停，默认）
rh paper-production start \
  --topic "你的研究主题" \
  --target-venue "NeurIPS" \
  --interaction-mode checkpoint

# 不指定，使用默认（checkpoint）
rh paper-production start \
  --topic "你的研究主题" \
  --target-venue "NeurIPS"
```

### 运行时查看/切换模式

```bash
# 查看当前模式
rh paper-production mode --topic 1

# 切换模式
rh paper-production set-mode --topic 1 --mode autonomous
rh paper-production set-mode --topic 1 --mode checkpoint

# 临时用自动模式继续一次（不改设置）
rh paper-production resume --topic 1 --auto-approve
```

---

## 📋 三种模式对比

| | autonomous | checkpoint | interactive |
|---|---|---|---|
| **AI 决策** | 自动应用推荐 | 暂停等人 | 暂停等人 |
| **高风险决策** | 仍需人工 | 需要人工 | 需要人工 |
| **AI 可提问** | ❌ | ❌ | ✅ |
| **适合场景** | 快速迭代 | 关键决策把关 | 复杂研究 |
| **速度** | 最快 | 中等 | 较慢 |

---

## 🎨 Claude Code / Codex 斜杠命令

```bash
# 查看状态（自动显示当前模式）
/rh-status

# 交互式决策（自动检测模式）
/rh-decide

# 智能继续（根据模式自动/交互）
/rh-continue

# 强制自动模式继续一次
/rh-continue --auto
```

---

## 💡 推荐用法

### 首次使用
```bash
# 用默认 checkpoint 模式，观察 AI 如何推荐
rh paper-production start --topic "..." --target-venue "..."

# 在 /rh-decide 时观察推荐
# 如果 AI 推荐都合理 → 下次可以用 autonomous
```

### 熟练用户
```bash
# 启动自动模式
rh paper-production start --interaction-mode autonomous

# 遇到不满意的自动决策时切换
rh paper-production set-mode --topic 1 --mode checkpoint
```

### 混合策略
```bash
# 早期阶段自动
rh paper-production start --interaction-mode autonomous

# 到分析阶段切换人工
rh paper-production set-mode --topic 1 --mode checkpoint
```

---

## 📊 决策行为示例

### 场景：种子论文不足（3/10）

**autonomous 模式**:
```
⚡ Auto-decision: 扩展到外部提供商
   Reason: AI 推荐（置信度 85%）
   → Continuing workflow...
```

**checkpoint 模式**:
```
⚠️  Decision required: 种子论文不足

[AskUserQuestion 或 CLI 选项展示]
1. ⭐ 扩展到外部提供商 (推荐, 85%)
2. 手动添加论文 (40%)
3. 停止工作流 (10%)

等待用户选择...
```

---

## 🔧 实现状态

| 功能 | 状态 |
|---|---|
| `--interaction-mode` 参数 | ✅ 已实现 |
| `mode` 命令查看 | ✅ 代码就绪 |
| `set-mode` 运行时切换 | ✅ 代码就绪 |
| `resume --auto` 临时自动 | ⏳ 待集成 |
| `/rh-status` 技能 | ✅ 文档就绪 |
| `/rh-decide` 技能 | ✅ 文档就绪 |
| `/rh-continue` 技能 | ✅ 文档就绪 |
| AskUserQuestion 集成 | ⏳ 待测试 |

---

## 📖 详细文档

- **完整指南**: `docs/INTERACTION_MODE_GUIDE.md`
- **CLI 设计**: `docs/HITL_CLI_DESIGN.md`
- **技术实现**: `docs/HITL_IMPLEMENTATION_SUMMARY.md`
- **快速入门**: `docs/HITL_QUICK_START.md`

---

**最后更新**: 2026-07-05
