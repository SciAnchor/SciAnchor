# 多工具支持矩阵

更新时间：2026-05-27

这份表区分三件事：

1. 该工具官方是否提供 RH 需要的接入面（skills / extensions / MCP / agent config）。
2. 我们当前仓库是否已经给出对应包装。
3. 这台机器上是否已经真实安装并验证。

## 支持工具总览

以下卡片用于公开展示当前支持面。详细证据、验证命令和 caveat 仍以下面的矩阵与路径说明为准。

<div class="tool-card-section">
  <div class="tool-card-grid">
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/codex.png" alt="Codex logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Codex
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">CLI + skills + composable commands</p>
        <p>OpenAI coding CLI，适合终端优先的 agent 工作流。</p>
        <p class="tool-card__note">RH 已内置原生 skill profile 与 MCP 路径。</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/claude-code.png" alt="Claude Code logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Claude Code
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">skills + plugins + MCP</p>
        <p>Anthropic 官方 AI 编程 CLI，适合技能驱动与 MCP 工作流。</p>
        <p class="tool-card__note">RH 已内置原生 skill profile；当前以宿主 / MCP 接入为主。</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/cline.png" alt="Cline logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Cline
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">CLI + IDE + MCP</p>
        <p>面向 VS Code / CLI 的 agent 宿主，适合审批式执行路径。</p>
        <p class="tool-card__note">已完成真实宿主运行验证；后续再补原生 RH profile。</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/cursor-agent.svg" alt="Cursor logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Cursor Agent
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">local agent CLI route</p>
        <p>本机 agent CLI 路径，可直接作为 RH 的宿主 route 使用。</p>
        <p class="tool-card__note">当前重点是 CLI route，可被 RH 直接探测。</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/opencode.png" alt="OpenCode logo" height="24" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        OpenCode
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">native skills + MCP + ACP</p>
        <p>开源、本地优先的 agent 编辑器，适合原生技能目录安装。</p>
        <p class="tool-card__note">RH 已内置 `~/.config/opencode/skills` profile。</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/gemini-cli.png" alt="Gemini CLI logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Gemini CLI
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">native skills + MCP + extensions</p>
        <p>Google agent CLI，适合原生 skills / extensions 组合方式。</p>
        <p class="tool-card__note">RH 已内置 `~/.gemini/skills` profile。</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/SciAnchor/SciAnchor/main/docs/assets/tool-logos/kilo-code.svg" alt="Kilo Code logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Kilo Code
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">CLI + IDE + MCP</p>
        <p>编码 agent 工具链已实测可跑通，但当前不作为第一优先对外承诺。</p>
        <p class="tool-card__note">宿主运行路径已验证；原生 RH profile 仍待补齐。</p>
      </div>
    </div>
  </div>
</div>

## 对外支持层级

| 工具 | 官方接入面 | RH 当前包装 | 本机验证结论 | 对外定位 |
|---|---|---|---|---|
| Codex | skills、CLI、可组合命令 | 已内置原生 RH skill profile + MCP | `codex 0.133.0`；`rh skill install --agent codex` 与 `verify` 已通过 | 主支持面 |
| Claude Code | skills、plugins、MCP | 已内置原生 RH skill profile + MCP | `Claude Code 2.1.150`；`rh skill install --agent claude-code` 与 `verify` 已通过 | 主支持面 |
| Cline | CLI、IDE、MCP | 仓库暂未内置原生 RH profile；当前通过 MCP / 宿主配置接入 | `cline 3.0.13`；在隔离目录中完成 `auth`，并对 OpenAI-compatible endpoint 成功跑通真实单轮 `Reply with exactly OK.` | 主支持面 |
| Cursor Agent | 本机 CLI 路径 | RH 内置宿主 CLI route | `agent 2026.05.24-dda726e` 在 PATH，可被 RH 探测 | 主支持面 |
| OpenCode | 原生 skills、MCP、agents、ACP | 已内置原生 RH skill profile + MCP | `opencode 1.15.10`；`rh skill install --agent opencode` 与 `verify` 已通过；`opencode debug skill` 已在干净工作区发现 `~/.config/opencode/skills` 下的 RH skills | 主支持面 |
| Gemini CLI | 原生 skills、MCP servers、extensions | 已内置原生 RH skill profile + MCP | `gemini 0.43.0`；`rh skill install --agent gemini` 与 `verify` 已通过；`gemini skills list --all` 已显示 `~/.gemini/skills` 下的 RH skills | 主支持面 |
| Kilo Code | CLI、IDE、MCP | 仓库暂未内置原生 RH profile；当前通过 MCP / 宿主配置接入 | `kilo 7.3.12`；在隔离目录中完成 `kilo models mimo` 与真实单轮 `Reply with exactly OK.` | 已验证，次一级入口 |

## “主支持面” 与 “次一级入口” 的区别

- **主支持面**：我们今天愿意在 README 和公开支持说明里直接点名的工具。
- **次一级入口**：运行路径已经真实验证，但 RH 还没有为它补齐更原生的安装 profile
  或更完整的产品化接入叙事。

当前的拆分是：

- **已内置原生 RH 包装**：Codex、Claude Code、OpenCode、Gemini CLI
- **宿主 / 运行路径已验证，但包装仍偏轻**：Cline、Kilo Code

## 已实测通过的路径

### 1. Codex 原生宿主路径

- RH skills 已真实安装到 `~/.codex/skills`
- `rh skill verify --agent codex` 结果为 `ok=22`
- `rh-mcp` console script 已安装，可作为 MCP server 入口

### 2. Claude Code 原生宿主路径

- RH skills 已真实安装到 `~/.claude/skills`
- `rh skill verify --agent claude-code` 结果为 `ok=22`
- 当前推荐把 Claude Code 视为 RH 的宿主 / MCP 消费方，而不是提前承诺它已经是稳定的 RH Claude CLI provider

### 3. Cline 宿主运行路径

- 已在隔离 data dir 中完成 `cline auth`
- `cline --json "Reply with exactly OK."` 已对 OpenAI-compatible endpoint 成功完成真实运行
- 这说明 Cline 作为 RH 邻接宿主 / 运行面是成立的，只是仓库暂未随附专门的 Cline skill profile

### 4. Cursor Agent provider 路径

- 本机 `agent` 二进制已存在，可被 RH 探测
- RH 可以把它作为宿主 CLI route 使用，而不要求默认必须配置 API key

### 5. OpenCode 原生宿主路径

- RH skills 已安装到 `~/.config/opencode/skills`
- `rh skill verify --agent opencode` 返回 `ok=22`
- 在一个干净的临时工作区中，`opencode debug skill` 明确返回了来自
  `~/.config/opencode/skills` 的 RH skills

### 6. Gemini 原生宿主路径

- RH skills 已安装到 `~/.gemini/skills`
- `rh skill verify --agent gemini` 返回 `ok=22`
- `gemini skills list --all` 已显示位置位于 `~/.gemini/skills` 的 RH skills

### 7. Kilo Code 宿主运行路径

- `kilo models mimo` 已返回 `mimo/mimo-v2.5-pro`
- `kilo run --format json --model mimo/mimo-v2.5-pro "Reply with exactly OK."`
  已成功完成
- 这说明 Kilo 作为真实宿主 / 运行路径可成立，但仓库暂未随附专门的 Kilo install profile

## 更低成本的模型路径

这些路径很有用，但它们本身不应该被写成“工具支持”承诺：

- 宿主 CLI 路径，例如 Codex 或 Cursor Agent
- OpenAI-compatible endpoint
- 直接供应商 API，例如 OpenAI、Anthropic、Kimi / Moonshot

## Kilo 在部分 npm 镜像下的安装注意事项

这次本地验证暴露出一个值得明确写下来的安装 caveat：

- 这台机器的 `npm` 默认 registry 是 `https://registry.npmmirror.com`
- 在 `2026-05-27`，`@kilocode/cli` 已解析到 `7.3.12`
- 但同一镜像上的 `@kilocode/cli-darwin-arm64` 仍是 `7.3.1`
- 这个版本不一致会直接导致 `darwin-arm64` 上的 Kilo postinstall 失败
- 本次验证改用官方 npm registry `https://registry.npmjs.org` 后已成功

这不是 RH 的 bug，但它会直接影响发布说明，尤其是对默认不走官方 npm 源的用户。

## 官方文档依据

- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Claude Code plugins / skills: https://code.claude.com/docs/en/plugins-reference
- Codex use cases（skills / CLI 组合能力）: https://developers.openai.com/codex/use-cases
- Cline 安装文档: https://docs.cline.bot/getting-started/installing-cline
- Cline CLI 概览: https://docs.cline.bot/cline-cli/overview
- Gemini CLI agent skills: https://geminicli.com/docs/cli/using-agent-skills/
- Gemini CLI CLI reference（`skills install|link|list`）: https://geminicli.com/docs/cli/cli-reference/
- Kilo Code 安装文档: https://kilo.ai/docs/getting-started/installing
- OpenCode skills: https://opencode.ai/docs/skills/
- OpenCode ACP / MCP support: https://opencode.ai/docs/acp/
