# Research Harness 更新和重载指南

当 RH 代码更新后，如何让 Claude Code / Codex 使用最新版本？

---

## 🎯 核心答案

**大多数情况下不需要手动重新挂载**，只需重启 MCP 服务器。

但需要根据**更新类型**选择正确的重载方式：

| 更新类型 | 重载方式 | 操作 |
|---|---|---|
| Python 业务逻辑 | 重启 MCP 服务器 | `pkill -f research_harness_mcp` |
| MCP 工具定义 | 重启 Claude/Codex | 关闭并重新打开应用 |
| 配置文件 | 无需重启 | 修改立即生效 |
| Python 依赖 | 重装 + 重启 MCP | `pip install -e .` |
| 技能（slash 命令） | 无需重启 | 下次调用时自动加载 |

---

## 📋 详细场景

### 场景 1: 更新了 Python 业务逻辑

**示例**：
- 修改了 `research_harness/auto_runner/runner.py`
- 优化了 `research_harness/_workflow/orchestrator/service.py`
- 改进了论文分析算法

**操作**：
```bash
# 方法 A: 重启 MCP 服务器进程
pkill -f "research_harness_mcp"

# MCP 会自动重启（如果配置了 auto-restart）
# 或者手动启动：
python -m research_harness_mcp
```

**验证**：
```bash
# 在 Claude Code / Codex 中
/rh-status

# 如果能正常返回，说明 MCP 已重新加载
```

---

### 场景 2: 新增或修改了 MCP 工具

**示例**：
- 在 `research_harness_mcp/tool_surface.py` 中新增工具
- 修改了某个工具的参数定义
- 改变了工具的返回格式

**操作**：
```bash
# Step 1: 重启 MCP 服务器
pkill -f "research_harness_mcp"
python -m research_harness_mcp

# Step 2: 重启 Claude Desktop / Codex
# macOS:
osascript -e 'quit app "Claude"'
open -a Claude

# 或者直接手动关闭并重新打开
```

**验证**：
```bash
# 在 Claude Code 中，检查工具是否可见
# （Claude 会在启动时重新读取 MCP 工具列表）

# 或者在 Codex 中：
rh doctor --check-mcp
```

---

### 场景 3: 修改了配置文件

**示例**：
- 更新了 `.research-harness/config.yaml`
- 修改了 `~/.research-harness/preferences.yaml`
- 改变了 API keys 或路径配置

**操作**：
```bash
# 无需重启，配置文件是运行时动态读取的
# 直接使用即可

# 验证配置生效：
rh doctor --verbose
```

---

### 场景 4: 更新了 Python 依赖

**示例**：
- `pyproject.toml` 中添加了新依赖
- 升级了某个包版本
- `requirements.txt` 变化

**操作**：
```bash
# Step 1: 重新安装依赖
cd /path/to/scianchor
pip install -e "packages/research_harness[dev]"
pip install -e packages/research_harness_mcp

# Step 2: 重启 MCP 服务器
pkill -f "research_harness_mcp"
python -m research_harness_mcp

# Step 3: 验证
rh doctor
```

---

### 场景 5: 更新了 Skills（斜杠命令）

**示例**：
- 修改了 `skills/rh-status/SKILL.md`
- 新增了 `skills/rh-new-command/`
- 改进了 skill 实现逻辑

**操作**：
```bash
# Skills 是动态加载的，无需重启
# 下次调用时自动使用最新版本

# 可选：清理 skill 缓存（如果有）
rm -rf ~/.research-harness/skill_cache

# 验证新 skill 可用：
rh skill list
```

---

## 🔄 推荐：自动化重载脚本

创建一个便捷脚本：

```bash
#!/bin/bash
# rh-reload.sh - Research Harness 更新重载脚本

set -e

echo "🔄 Reloading Research Harness..."

# 1. 拉取最新代码
cd /path/to/scianchor
git pull

# 2. 重新安装（如果有依赖变化）
pip install -e "packages/research_harness[dev]" -q
pip install -e packages/research_harness_mcp -q

# 3. 重启 MCP 服务器
echo "📡 Restarting MCP server..."
pkill -f "research_harness_mcp" || true
sleep 1

# MCP 会自动重启（如果配置了自动重启）
# 或手动启动：
# python -m research_harness_mcp &

echo "✅ MCP server restarted"

# 4. 检查健康状态
echo "🏥 Running health check..."
rh doctor

echo ""
echo "✅ Research Harness reloaded successfully!"
echo "💡 If you added new MCP tools, restart Claude Desktop / Codex"
```

**使用**：
```bash
chmod +x rh-reload.sh
./rh-reload.sh
```

---

## 🤖 MCP 自动重启配置

### Claude Desktop 配置

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "python",
      "args": ["-m", "research_harness_mcp"],
      "env": {
        "PYTHONPATH": "/path/to/scianchor/packages"
      },
      "auto_restart": true,
      "restart_delay": 1000
    }
  }
}
```

**关键参数**：
- `auto_restart: true` - 进程崩溃时自动重启
- `restart_delay: 1000` - 重启延迟（毫秒）

### Codex 配置

编辑 `~/.config/codex/mcp_servers.json`:

```json
{
  "research-harness": {
    "command": ["python", "-m", "research_harness_mcp"],
    "env": {
      "PYTHONPATH": "/path/to/scianchor/packages"
    },
    "restart_policy": "always"
  }
}
```

---

## 🔍 调试：如何确认更新生效

### 方法 1: 版本检查

在代码中添加版本号：

```python
# packages/research_harness/research_harness/__init__.py
__version__ = "0.5.1"  # 每次更新递增

# packages/research_harness_mcp/research_harness_mcp/__init__.py
def get_version():
    from research_harness import __version__
    return __version__
```

添加 MCP 工具：

```python
# packages/research_harness_mcp/research_harness_mcp/tool_surface.py
def rh_version():
    """Get Research Harness version."""
    from research_harness import __version__
    return {"version": __version__}
```

在 Claude / Codex 中调用：
```bash
# 通过 MCP 工具
rh.version()

# 或通过 CLI
rh --version
```

### 方法 2: 时间戳检查

```bash
# 检查 MCP 进程启动时间
ps aux | grep research_harness_mcp

# 输出：
# user    12345  0.5  0.1 ... 10:30AM python -m research_harness_mcp
#                               ^^^^^^^^ 启动时间

# 如果时间在你重启之后，说明加载了新代码
```

### 方法 3: 日志检查

```bash
# 查看 MCP 服务器日志
tail -f ~/.research-harness/logs/mcp_server.log

# 重启后应该看到：
# [2026-07-05 10:35:00] MCP server started
# [2026-07-05 10:35:01] Loaded 25 tools from tool_surface
```

### 方法 4: 功能测试

在更新中添加一个简单的测试工具：

```python
# tools_debug.py (临时)
def rh_test_update():
    """Test that latest code is loaded."""
    return {
        "status": "updated",
        "message": "This tool only exists in the latest version",
        "timestamp": datetime.now().isoformat()
    }
```

在 Claude / Codex 中调用：
```bash
rh.rh_test_update()

# 如果能调用，说明新代码已加载
```

---

## ⚡ 快速操作备忘

### 最常用：重启 MCP

```bash
pkill -f research_harness_mcp && sleep 1 && python -m research_harness_mcp &
```

### 完全重载（包括 Claude/Codex）

```bash
# 重启 MCP
pkill -f research_harness_mcp

# 重启 Claude Desktop (macOS)
osascript -e 'quit app "Claude"' && sleep 1 && open -a Claude

# 或重启 Codex
pkill -f codex && sleep 1 && codex
```

### 验证是否需要重启 Claude/Codex

```bash
# 检查 MCP 工具列表是否有变化
diff \
  <(git show HEAD~1:packages/research_harness_mcp/research_harness_mcp/tool_surface.py | grep "def ") \
  <(cat packages/research_harness_mcp/research_harness_mcp/tool_surface.py | grep "def ")

# 如果有差异，需要重启 Claude/Codex
# 如果没有差异，只重启 MCP 即可
```

---

## 🎯 最佳实践

### 1. 开发中：使用 `--reload` 模式

如果频繁修改代码，可以启用热重载：

```bash
# 使用 uvicorn/watchfiles 实现热重载
pip install watchfiles

# 启动 MCP 服务器（开发模式）
watchmedo auto-restart \
  --directory packages/research_harness \
  --directory packages/research_harness_mcp \
  --pattern "*.py" \
  --recursive \
  -- python -m research_harness_mcp
```

修改代码后自动重启 MCP，无需手动 kill。

### 2. 生产环境：使用 supervisor

```bash
# 安装 supervisor
pip install supervisor

# 配置文件: /etc/supervisor/conf.d/rh_mcp.conf
[program:rh_mcp]
command=python -m research_harness_mcp
directory=/path/to/scianchor
autostart=true
autorestart=true
stderr_logfile=/var/log/rh_mcp.err.log
stdout_logfile=/var/log/rh_mcp.out.log

# 启动
supervisorctl start rh_mcp

# 重载
supervisorctl restart rh_mcp
```

### 3. 版本控制：Git hooks

```bash
# .git/hooks/post-merge
#!/bin/bash
# 自动在 git pull 后重启 MCP

echo "🔄 Code updated, reloading RH MCP..."
pkill -f research_harness_mcp
sleep 1
echo "✅ MCP server will auto-restart"
```

```bash
chmod +x .git/hooks/post-merge
```

现在每次 `git pull` 后自动重启 MCP。

---

## 📊 更新检查清单

拉取新代码后，按此清单操作：

- [ ] **检查 CHANGELOG.md**：了解更新内容
- [ ] **检查 `git diff` 中是否修改了**：
  - [ ] `tool_surface.py` → 需要重启 Claude/Codex
  - [ ] `*.py` 业务逻辑 → 只需重启 MCP
  - [ ] `config.yaml` → 无需重启
  - [ ] `pyproject.toml` → 需要 `pip install -e .`
- [ ] **运行测试**：`pytest packages/ -q`
- [ ] **运行健康检查**：`rh doctor`
- [ ] **验证 MCP 连接**：在 Claude/Codex 中运行 `/rh-status`

---

## ❓ FAQ

### Q1: 我更新了代码，但 Claude 还是用旧逻辑？

**A**: 
1. 确认 MCP 服务器已重启（检查进程启动时间）
2. 如果修改了工具定义，重启 Claude Desktop
3. 检查 PYTHONPATH 是否指向正确的代码目录

### Q2: MCP 服务器启动失败？

**A**:
```bash
# 查看详细错误
python -m research_harness_mcp --verbose

# 常见问题：
# - 端口占用：pkill -f research_harness_mcp
# - 依赖缺失：pip install -e "packages/research_harness[dev]"
# - 配置错误：rh doctor --fix
```

### Q3: 如何确认使用的是最新代码？

**A**:
```bash
# 方法 1: 检查模块路径
python -c "import research_harness; print(research_harness.__file__)"
# 应该指向你的开发目录，不是 site-packages

# 方法 2: 添加日志
# 在你修改的函数中加一行：
print(f"DEBUG: Using updated code at {__file__}")

# 方法 3: 检查 git commit
cd packages/research_harness
git log -1 --oneline
# 确认是你最新提交的版本
```

### Q4: 每次都要手动重启太麻烦？

**A**: 使用上面的**热重载方案**或 **Git hooks**。

---

## 🎯 总结

| 你的操作 | 需要做的 | 命令 |
|---|---|---|
| `git pull` 拉取代码 | 重启 MCP | `pkill -f research_harness_mcp` |
| 修改 Python 业务逻辑 | 重启 MCP | 同上 |
| 新增 MCP 工具 | 重启 MCP + Claude/Codex | + `osascript -e 'quit app "Claude"'` |
| 修改配置文件 | 无需操作 | 直接生效 |
| 更新依赖 | 重装 + 重启 MCP | `pip install -e .` + 重启 |
| 更新 skill | 无需操作 | 下次调用自动加载 |

**一句话**：99% 的情况只需 `pkill -f research_harness_mcp`。

---

**最后更新**: 2026-07-05  
**相关文档**: `docs/NEW_RESEARCH_WORKFLOW.md`
