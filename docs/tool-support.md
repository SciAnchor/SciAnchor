# Tool Support Matrix

Updated: 2026-05-27

This matrix separates three questions:

1. Does the host tool officially expose the integration surface RH needs
   (skills, extensions, MCP, agent config)?
2. Does this repo already package RH for that surface?
3. Was it actually installed and validated on this machine?

## Supported tools at a glance

These cards are the public-facing summary. The matrix and validation notes
below remain the source of truth for exact evidence, caveats, and command-level
proof.

<div class="tool-card-section">
  <div class="tool-card-grid">
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/codex.png" alt="Codex logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Codex
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">CLI + skills + composable commands</p>
        <p>OpenAI's coding CLI, well suited to terminal-first agent workflows.</p>
        <p class="tool-card__note">RH ships a native skill profile plus MCP path.</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/claude-code.png" alt="Claude Code logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Claude Code
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">skills + plugins + MCP</p>
        <p>Anthropic's official coding CLI for skill-driven and MCP-heavy flows.</p>
        <p class="tool-card__note">RH ships a native skill profile; host / MCP is the main supported path.</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/cline.png" alt="Cline logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Cline
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">CLI + IDE + MCP</p>
        <p>An agent host for VS Code and terminal workflows with approval-first execution.</p>
        <p class="tool-card__note">Real host/runtime path validated; native RH profile can come later.</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/cursor-agent.svg" alt="Cursor logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Cursor Agent
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">local agent CLI route</p>
        <p>A local agent CLI route that RH can detect and use directly.</p>
        <p class="tool-card__note">The current support claim is the host CLI route, not extra proxy-specific setup.</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/opencode.png" alt="OpenCode logo" height="24" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        OpenCode
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">native skills + MCP + ACP</p>
        <p>An open-source, local-first agent editor with a clean native skill directory.</p>
        <p class="tool-card__note">RH ships the native `~/.config/opencode/skills` profile.</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/gemini-cli.png" alt="Gemini CLI logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Gemini CLI
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">native skills + MCP + extensions</p>
        <p>Google's agent CLI with a native skills / extensions consumption model.</p>
        <p class="tool-card__note">RH ships the native `~/.gemini/skills` profile.</p>
      </div>
    </div>
    <div class="tool-card">
      <h3 class="tool-card__title" style="margin:0 0 0.75rem;font-size:1.25rem;line-height:2rem;font-weight:600;">
        <img class="tool-card__logo" src="https://raw.githubusercontent.com/research-harness/research-harness/main/docs/assets/tool-logos/kilo-code.svg" alt="Kilo Code logo" height="28" style="vertical-align:middle;margin-right:0.65rem;background:#fff;border:1px solid rgba(15,23,42,.08);border-radius:0.6rem;padding:0.2rem 0.35rem;">
        Kilo Code
      </h3>
      <div class="tool-card__body">
        <p class="tool-card__surface">CLI + IDE + MCP</p>
        <p>A real, validated coding-agent host path, but not yet a first-tier RH public claim.</p>
        <p class="tool-card__note">Runtime path is validated; a native RH profile is still pending.</p>
      </div>
    </div>
  </div>
</div>

## Public support tiers

| Tool | Official surface | RH packaging today | Local validation | Public position |
|---|---|---|---|---|
| Codex | skills, CLI, composable commands | Native RH skill profile + MCP | `codex 0.133.0`; `rh skill install --agent codex` and `verify` passed | Primary |
| Claude Code | skills, plugins, MCP | Native RH skill profile + MCP | `Claude Code 2.1.150`; `rh skill install --agent claude-code` and `verify` passed | Primary |
| Cline | CLI, IDE, MCP | No repo-native RH profile yet; use MCP / direct host config | `cline 3.0.13`; isolated `auth` plus a real one-shot `Reply with exactly OK.` run against an OpenAI-compatible endpoint succeeded | Primary |
| Cursor Agent | local CLI route | Built-in host CLI route in RH | `agent 2026.05.24-dda726e` is on PATH and detected by RH | Primary |
| OpenCode | native skills, MCP, agents, ACP | Native RH skill profile + MCP | `opencode 1.15.10`; `rh skill install --agent opencode` and `verify` passed; `opencode debug skill` discovered RH skills from `~/.config/opencode/skills` in a clean workspace | Primary |
| Gemini CLI | native skills, MCP servers, extensions | Native RH skill profile + MCP | `gemini 0.43.0`; `rh skill install --agent gemini` and `verify` passed; `gemini skills list --all` showed RH skills from `~/.gemini/skills` | Primary |
| Kilo Code | CLI, IDE, MCP | No repo-native RH profile yet; use MCP / direct host config | `kilo 7.3.12`; isolated `kilo models mimo` and a real one-shot `Reply with exactly OK.` run against an OpenAI-compatible endpoint succeeded | Secondary validated |

## What “primary” vs “secondary” means

- **Primary** means we are comfortable naming the tool in public RH support
  claims today.
- **Secondary validated** means the runtime path is real and locally verified,
  but RH does not yet ship a native install profile or a stronger productized
  integration story for that host.

Today that split is:

- **Native RH packaging shipped**: Codex, Claude Code, OpenCode, Gemini CLI
- **Runtime / host path validated, packaging still thinner**: Cline, Kilo Code

## Paths validated end to end

### 1. Codex native host path

- RH skills were actually installed into `~/.codex/skills`
- `rh skill verify --agent codex` returned `ok=22`
- `rh-mcp` is installed as a real console script

### 2. Claude Code native host path

- RH skills were actually installed into `~/.claude/skills`
- `rh skill verify --agent claude-code` returned `ok=22`
- The recommended production path today is to treat Claude Code as an RH host
  and MCP consumer, not to over-claim a stable RH Claude CLI provider before it
  is fully validated

### 3. Cline runtime host path

- `cline auth` was configured in an isolated data directory
- `cline --json "Reply with exactly OK."` completed successfully against an
  OpenAI-compatible endpoint
- This validates Cline as a real RH-adjacent host/runtime surface, even though
  RH does not yet ship a dedicated Cline skill profile

### 4. Cursor Agent provider path

- The local `agent` binary is present and detectable by RH
- RH can use it as a host CLI route without requiring a default API key

### 5. OpenCode native host path

- RH skills were installed into `~/.config/opencode/skills`
- `rh skill verify --agent opencode` returned `ok=22`
- In a clean temporary workspace, `opencode debug skill` surfaced RH skills
  from the native OpenCode directory

### 6. Gemini native host path

- RH skills were installed into `~/.gemini/skills`
- `rh skill verify --agent gemini` returned `ok=22`
- `gemini skills list --all` showed RH skills with locations under
  `~/.gemini/skills`

### 7. Kilo Code runtime path

- `kilo models mimo` returned `mimo/mimo-v2.5-pro` from an isolated config
- `kilo run --format json --model mimo/mimo-v2.5-pro "Reply with exactly OK."`
  completed successfully
- This validates Kilo as a real host/runtime path, but RH does not yet ship a
  native Kilo-specific install profile

## Lower-cost model routes

These are useful, but they are not a public “tool support” claim by
themselves:

- Host CLI routes such as Codex or Cursor Agent
- OpenAI-compatible endpoints
- Direct provider APIs such as OpenAI, Anthropic, or Kimi / Moonshot

## Kilo install caveat on some npm mirrors

The local Kilo validation exposed a packaging caveat worth documenting:

- On this machine, `npm` defaulted to `https://registry.npmmirror.com`
- On `2026-05-27`, `@kilocode/cli` resolved to `7.3.12`, but the mirror still
  served `@kilocode/cli-darwin-arm64` as `7.3.1`
- That version mismatch breaks Kilo's postinstall step on `darwin-arm64`
- The validation succeeded after installing from the official npm registry:
  `https://registry.npmjs.org`

This is not an RH bug, but it matters for release guidance, especially for
users whose global npm registry is not the official upstream registry.

## Official references

- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Claude Code plugins / skills: https://code.claude.com/docs/en/plugins-reference
- Codex use cases (skills / CLI composition): https://developers.openai.com/codex/use-cases
- Cline install guide: https://docs.cline.bot/getting-started/installing-cline
- Cline CLI overview: https://docs.cline.bot/cline-cli/overview
- Gemini CLI agent skills: https://geminicli.com/docs/cli/using-agent-skills/
- Gemini CLI CLI reference (`skills install|link|list`): https://geminicli.com/docs/cli/cli-reference/
- Kilo Code install guide: https://kilo.ai/docs/getting-started/installing
- OpenCode skills: https://opencode.ai/docs/skills/
- OpenCode ACP / MCP support: https://opencode.ai/docs/acp/
