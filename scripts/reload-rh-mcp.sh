#!/bin/bash
# Research Harness MCP 重载脚本
# 用于在代码更新后重新加载最新能力到 Claude Desktop 和 Codex

set -e

echo "════════════════════════════════════════════════════════════"
echo "Research Harness MCP 重载脚本"
echo "════════════════════════════════════════════════════════════"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "📍 工作目录: $SCRIPT_DIR"
echo ""

# Step 1: 验证新工具
echo "步骤 1/4: 验证新增工具..."
echo "────────────────────────────────────────────────────────────"

.venv/bin/python << 'PYEOF'
from research_harness_mcp.tools import list_tool_definitions
tools = list_tool_definitions()
workflow_tools = [t.name for t in tools if 'production' in t.name or t.name == 'topic_init']

print(f"✅ 检测到 {len(workflow_tools)} 个工作流工具")
print(f"✅ 总共 {len(tools)} 个公开 MCP 工具")

if len(workflow_tools) < 9:
    print(f"⚠️  警告：预期 9 个工作流工具，实际只有 {len(workflow_tools)} 个")
    exit(1)

print("\n新增工具列表：")
for name in sorted(workflow_tools):
    print(f"  • {name}")
PYEOF

echo ""

# Step 2: 重启 MCP 服务器
echo "步骤 2/4: 重启 MCP 服务器..."
echo "────────────────────────────────────────────────────────────"

# 查找现有 MCP 进程
MCP_PIDS=$(pgrep -f "python.*research_harness_mcp" | grep -v http_api || true)

if [ -n "$MCP_PIDS" ]; then
    echo "找到运行中的 MCP 服务器进程："
    echo "$MCP_PIDS" | while read pid; do
        echo "  PID $pid"
    done
    echo ""
    echo "正在终止..."
    pkill -f "python.*research_harness_mcp" || true
    echo "✅ MCP 服务器已停止"
else
    echo "⚠️  未找到运行中的 MCP 服务器"
fi

echo ""

# Step 3: 重启 Claude Desktop（如果已安装）
echo "步骤 3/4: 重启 Claude Desktop..."
echo "────────────────────────────────────────────────────────────"

if [ -d "/Applications/Claude.app" ]; then
    echo "检测到 Claude Desktop，正在重启..."

    osascript -e 'quit app "Claude"' 2>/dev/null || true
    sleep 2

    echo "✅ Claude Desktop 已退出"
    echo ""
    echo "📱 请手动重新打开 Claude Desktop"
    echo "   或执行: open -a Claude"
    echo ""
else
    echo "⚠️  未检测到 Claude Desktop"
    echo "   如果使用 Claude Desktop，请手动重启应用"
    echo ""
fi

# Step 4: HTTP API 信息（用于 Codex）
echo "步骤 4/4: HTTP API 状态（用于 Codex）..."
echo "────────────────────────────────────────────────────────────"

HTTP_PIDS=$(pgrep -f "research_harness_mcp.http_api" || true)

if [ -n "$HTTP_PIDS" ]; then
    echo "✅ HTTP API 服务器正在运行："
    echo "$HTTP_PIDS" | while read pid; do
        echo "  PID $pid"
    done
    echo ""
    echo "如需重启 HTTP API："
    echo "  pkill -f 'research_harness_mcp.http_api'"
    echo "  .venv/bin/python -m research_harness_mcp.http_api &"
else
    echo "⚠️  HTTP API 服务器未运行"
    echo ""
    echo "如需启动 HTTP API（用于 Codex）："
    echo "  .venv/bin/python -m research_harness_mcp.http_api &"
fi

echo ""

# 完成
echo "════════════════════════════════════════════════════════════"
echo "✅ 重载完成！"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📋 后续步骤："
echo ""
echo "1. 如果使用 Claude Desktop："
echo "   - 重新打开 Claude Desktop"
echo "   - 在对话中输入：\"列出所有 paper_production 工具\""
echo "   - 验证新工具可用"
echo ""
echo "2. 如果使用 Codex："
echo "   - Codex 会自动识别新工具"
echo "   - 直接测试即可"
echo ""
echo "3. 测试新功能："
echo "   /rh-write \"测试主题\" NeurIPS"
echo ""
echo "📚 完整文档："
echo "   docs/ONE_COMMAND_QUICKSTART.md  - 一条命令使用"
echo "   docs/PURE_CLI_WORKFLOW.md       - 纯对话式工作流"
echo "   docs/RH_UPDATE_AND_RELOAD.md    - 更新重载详解"
echo ""
