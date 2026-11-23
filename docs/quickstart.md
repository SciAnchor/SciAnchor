# Quick Start Guide

## Shortest Useful Path

Use this path when you want to verify that RH can run locally and be discovered by an agent:

```bash
git clone https://github.com/scianchor/research-harness.git
cd research-harness
./setup.sh
rh --json doctor
rh skill install --agent codex
rh skill verify --agent codex
rh skill list --group-by-suite
```

If you use Claude Code, OpenCode, or Gemini CLI, replace `--agent codex` with the matching profile:

```bash
rh skill install --agent claude-code
rh skill install --agent opencode
rh skill install --agent gemini
```

Then give this prompt to your agent:

```text
Read docs/agent-guide.md and docs/PAPER_MANAGEMENT.md.
Create a research topic on "robust budget pacing for online advertising",
search recent papers, ingest the useful ones, and generate a first literature map.
Every paper must be ingested with a topic, and key outputs should be recorded
as RH artifacts.
```

Without an API key, you can still run doctor, install skills, inspect public entrypoints, and read the demo story. Configure an LLM route when you want deep read, claim extraction, annotation, or other model-backed primitives.

## Release Boundary

See [docs/contracts/release-boundary.md](contracts/release-boundary.md) for
the current pre-release boundary.

- Stable public/local CLI-MCP-skill workflow.
- Local/internal HTTP bridge only.
- Non-loopback HTTP binding is unsupported and not release-approved.
- Stable Zotero push dry-run validation only.
- Fake/sandbox Zotero pull/both and apply evidence is local-only.
- Private benchmark/performance regression governance only.
- Stable external API release: deferred.
- Real Zotero network sync/apply remains deferred.
- Public benchmark/performance claims remain deferred.

## Prerequisites

- Python 3.11+
- SQLite 3.35+ (bundled with macOS / most Linux distributions)
- For model-backed primitives, at least one workable LLM route:
  - a host CLI such as `codex` or `agent` (Cursor Agent)
  - an OpenAI-compatible / Anthropic-compatible endpoint
  - a direct provider API route such as OpenAI, Anthropic, or Kimi / Moonshot

## Installation

```bash
git clone https://github.com/scianchor/research-harness.git
cd research-harness
./setup.sh
```

`setup.sh` installs the core RH packages in editable mode, creates `.env` from
`.env.example`, and runs a smoke import test. It works with both `venv` and
`conda`.

### Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "packages/research_harness[dev]"
pip install -e "packages/research_harness_mcp[dev]"
cp .env.example .env
```

## Choose your LLM route

Only configure this if you want deep read, claim extraction, annotation, or
other model-backed primitives. `rh --json doctor` works without an API key when
you already have a usable host CLI route.

### Option A: host CLI

```bash
LLM_PROVIDER=codex
# CODEX_MODEL=gpt-5.4-high

# or

LLM_PROVIDER=cursor_agent
# CURSOR_AGENT_MODEL=composer-2.5-fast
```

### Option B: OpenAI-compatible endpoint

```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=<your-api-key>
OPENAI_MODEL=<your-model-id>
```

### Option C: direct provider API

```bash
OPENAI_API_KEY=<your-openai-key>
OPENAI_MODEL=gpt-4o-mini

# or
ANTHROPIC_API_KEY=<your-anthropic-key>
ANTHROPIC_MODEL=claude-sonnet-4-6

# or
KIMI_API_KEY=<your-kimi-key>
KIMI_MODEL=kimi-for-coding
```

`LLM_PROVIDER` is optional but recommended when you want RH to use a specific
route instead of falling back to auto-detection.

Paper search needs no keys: RH queries Semantic Scholar, OpenAlex, Crossref,
arXiv, PubMed and OpenReview through their public, keyless APIs (see
[paper search and acquisition](managed-paper-acquisition.md)). Recommended
contact metadata (free):

```bash
UNPAYWALL_EMAIL=you@example.com  # Unpaywall — free OA PDF lookup by DOI
```

For multi-machine setups, keep private RH runtime resources in one
machine-local file instead of scattering them across shell profiles:

```bash
mkdir -p ~/.config/research-harness
cp config/private.env.example ~/.config/research-harness/private.env
chmod 600 ~/.config/research-harness/private.env
```

`scripts/rh-env-keychain.sh` loads this file automatically before starting the
RH MCP server. On macOS it also keeps the older Keychain lookup path working.
Never commit the real `private.env`.

Keep scholarly-source contact metadata here (no API keys are used):

```bash
OPENALEX_MAILTO=you@example.com         # also used as Crossref polite fallback
CROSSREF_MAILTO=you@example.com         # optional explicit Crossref polite mailto
```

If you install the optional SPC component, it keeps its own project-local
configuration.

Optional (only if you want figure rendering):

```bash
FAL_KEY=...   # fal.ai — required by figure_generate for paper-ready diagrams
              # (skip unless you plan to render figures)

# Contract-driven illustration route for architecture/method figures
# (figure_generate model="illustration"). RH tries the configured public
# backends in order: Grok Imagine, GPT Image, native Gemini. RH stores only
# readiness/provenance booleans, never endpoint or key values.
RESEARCH_HARNESS_FIGURE_MODEL=illustration
GROK_API_KEY=...            # Grok Imagine (optional GROK_BASE_URL)
GPT_IMAGE_API_KEY=...       # GPT Image, OpenAI-compatible (optional GPT_IMAGE_BASE_URL)
GOOGLE_API_KEY=...          # native Gemini image generation
RESEARCH_HARNESS_FIGURE_GEMINI_MODEL=gemini-2.5-flash-image
RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS=900
```

Without `RESEARCH_HARNESS_FIGURE_MODEL`, `figure_generate` defaults to OpenAI
`gpt-image-2` (`OPENAI_API_KEY`); `recraft` / `flux` / `nano-banana` select
fal.ai (`FAL_KEY`). Use `model="illustration-fake"` for a deterministic,
no-network render in tests. Quantitative result figures never go through an
image model: they render deterministically from recorded data via
`figure_suite_render`.

### Tier-based LLM routing

Research Harness routes primitives to models by tier:

| Tier | Use case | Default |
|------|----------|---------|
| `light` | summarize, classify, format | cheapest configured model |
| `medium` | claim extraction, gap detection | balanced model |
| `heavy` | consistency check, adversarial review | highest-quality model |

Override routing with `LLM_ROUTE_{TIER}=provider:model`:

```bash
LLM_ROUTE_LIGHT=openai:gpt-4o-mini
LLM_ROUTE_MEDIUM=openai:gpt-4o
LLM_ROUTE_HEAVY=anthropic:claude-opus-4-5
```

See `.env.example` for the full list of optional variables.

## Verify Installation

```bash
rh --json doctor
# or equivalently: rhub --json doctor
```

The doctor output now reports the selected provider, route kind
(`host-cli`, `openai-compatible`, `anthropic-compatible`, `direct-api`), and
all currently detectable provider routes.

For deeper local troubleshooting, opt in to the runtime diagnostics preview:

```bash
rh --json doctor --runtime-diagnostics
```

This preview is read-only. It summarizes runtime health signals such as skill
manifest validity, generated skill-cache files, job-ledger state, event-source
integrity, artifact path writability, and showcase bundle path availability. It
does not write storage/provenance records or change orchestrator gates.

## Current tool support

| Tool / surface | Current status | Notes |
|---|---|---|
| Codex | Verified | Skill install profile and MCP workflow are ready |
| Claude Code | Verified as host surface | MCP + skills path is ready; CLI-provider path is not yet declared stable |
| Cline | Verified as host surface | `cline 3.0.13` completed a real one-shot run against an OpenAI-compatible endpoint; no repo-native RH profile is shipped yet |
| Cursor Agent | Verified | Local `agent` path is supported by RH |
| OpenCode | Verified as host surface | Native `~/.config/opencode/skills` profile is shipped and locally validated |
| Gemini CLI | Verified as host surface | Native `~/.gemini/skills` profile is shipped and locally validated |
| Kilo Code | Validated as a secondary surface | `kilo 7.3.12` completed `models` plus a real one-shot run against an OpenAI-compatible endpoint; no repo-native RH profile is shipped yet |

## Skills

`setup.sh` builds `skills/manifest.json` automatically. To make the shipped
skills available to your agent (Claude Code, Codex, OpenCode, Gemini CLI, and
similar skill-aware hosts), run one of:

```bash
# Use a built-in agent profile
rh skill install --agent claude-code
rh skill install --agent codex
rh skill install --agent opencode
rh skill install --agent gemini

# Or drop a .rh-agent.toml in the repo root and run install with no flags
cp skills/agent-profiles/claude-code.toml .rh-agent.toml
rh skill install

# Or install ad-hoc to any directory
rh skill install --target ~/.claude/skills
rh skill install --target ~/.agents/skills

# List shipped skills by public task suite
rh skill list --group-by-suite

# Or filter one suite
rh skill list --suite paper
```

Full design and how to add support for a new agent: see
[`docs/skills/`](skills/README.md).

Native host support is the primary claim:

- OpenCode: `~/.config/opencode/skills`
- Gemini CLI: `~/.gemini/skills`
- Codex: `~/.codex/skills`
- Claude Code: `~/.claude/skills`

Shared lower-cost option:

- `~/.agents/skills` works as a cross-agent alias for tools such as Gemini CLI
  and OpenCode when you prefer one shared install target

## Using with Claude Code

Add to `.claude/settings.json` (project-level) or `~/.claude/settings.json`
(global). **Use an absolute path to the installed `rh-mcp` launcher** so the
MCP server works regardless of which shell has your venv activated:

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/rh-mcp",
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/research-harness/.research-harness/pool.db"
      }
    }
  }
}
```

If you installed via conda, point `command` at the env's `rh-mcp` script
(`~/miniconda3/envs/research-harness/bin/rh-mcp` or similar).

Once configured, Claude Code sees the contracted public MCP surface. Internal
compatibility dispatch still supports legacy primitive names, but new agent
work should prefer the public tools listed in `research_harness_mcp.tool_surface`.

## First Research Topic

```bash
# 1. (Optional) Group related topics under a domain
rh domain init "auto-bidding"

# 2. Initialize a topic
rh topic init "my-research-topic" --domain auto-bidding

# 3. Search and ingest papers
rh paper search "my research query" --topic-id 1 --auto-ingest

# 4. Start the orchestrated workflow
rh orchestrator init --topic my-research-topic --mode standard

# 5. Check status
rh orchestrator status --topic my-research-topic

# 6. Advance through evidence-gated stages
rh orchestrator advance --topic my-research-topic
```

## Autonomous Mode

```bash
# Run with autonomous gate resolution (for well-defined tasks)
rh auto-runner start --topic-id 1 --mode standard \
  --direction "your research direction here"
```

## Start the local HTTP API bridge

The primary researcher-facing frontend is the Zotero side panel (see
[`docs/zotero-rh-panel.md`](zotero-rh-panel.md)). Start the local HTTP API
bridge when Zotero or another local integration needs an HTTP endpoint:

```bash
pip install -e "packages/research_harness_mcp[api]"
python -m research_harness_mcp.http_api
```

Then point the local client at <http://127.0.0.1:8000>. For agentic workflows,
prefer the MCP server or `rh` CLI so provenance and stage state remain explicit.

The HTTP bridge is loopback-first. Non-loopback binding is not release-approved;
reviewed local experiments must set `RESEARCH_HARNESS_HTTP_API_TOKEN`, and any
public deployment still needs a separate TLS/proxy, network allowlist, scoped
CORS, private/no-store cache, rollback, and monitoring gate.

## Run Tests

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
```

## Plugin Development

See [`docs/plugin-guide.md`](plugin-guide.md) for writing custom primitives.
The plugin manifest schema is at
`packages/research_harness/research_harness/plugin/manifest.py`.
