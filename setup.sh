#!/usr/bin/env bash
set -euo pipefail

# Research Harness — first-time setup
# Usage: ./setup.sh
#
# Installs the core RH packages in editable mode, creates .env if missing.
# Supports both pip (venv) and conda workflows.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Research Harness Setup ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Check Python version
# ---------------------------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not found."
  echo "Install Python 3.11+ from https://www.python.org/downloads/"
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
  echo "Error: Python 3.11+ required, found $PYTHON_VERSION"
  exit 1
fi

echo "Found Python $PYTHON_VERSION"

# ---------------------------------------------------------------------------
# 2. Choose install method
# ---------------------------------------------------------------------------

# If already inside a conda env, use it directly
if [ -n "${CONDA_DEFAULT_ENV:-}" ] && [ "${CONDA_DEFAULT_ENV}" != "base" ]; then
  echo "Active conda environment detected: $CONDA_DEFAULT_ENV"
  PYTHON="python3"
  PIP="pip3"
  echo "Using existing conda environment."
elif command -v conda >/dev/null 2>&1; then
  echo ""
  echo "conda detected. Choose setup method:"
  echo "  1) conda  — create/activate 'research-harness' conda env (recommended)"
  echo "  2) venv   — create .venv in this directory"
  echo ""
  read -r -p "Enter 1 or 2 [default: 1]: " CHOICE
  CHOICE="${CHOICE:-1}"

  if [ "$CHOICE" = "1" ]; then
    if conda env list | grep -q "^research-harness "; then
      echo "Conda env 'research-harness' already exists, reusing it."
    else
      echo "Creating conda env 'research-harness' (Python 3.11)..."
      conda create -n research-harness python=3.11 -y
    fi
    # shellcheck disable=SC1091
    eval "$(conda shell.bash hook)"
    conda activate research-harness
    PYTHON="python"
    PIP="pip"
  else
    if [ ! -d "$REPO_ROOT/.venv" ]; then
      echo "Creating .venv..."
      python3 -m venv "$REPO_ROOT/.venv"
    fi
    PYTHON="$REPO_ROOT/.venv/bin/python"
    PIP="$REPO_ROOT/.venv/bin/pip"
    echo ""
    echo "Note: activate with:  source .venv/bin/activate"
  fi
else
  # No conda — use venv
  if [ ! -d "$REPO_ROOT/.venv" ]; then
    echo "Creating .venv..."
    python3 -m venv "$REPO_ROOT/.venv"
  fi
  PYTHON="$REPO_ROOT/.venv/bin/python"
  PIP="$REPO_ROOT/.venv/bin/pip"
  echo ""
  echo "Note: activate with:  source .venv/bin/activate"
fi

# ---------------------------------------------------------------------------
# 3. Upgrade pip
# ---------------------------------------------------------------------------

echo ""
echo "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

# ---------------------------------------------------------------------------
# 4. Install packages (editable)
# ---------------------------------------------------------------------------

echo "Installing llm_router..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/llm_router[all]"

echo "Installing paperindex..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/paperindex"

echo "Installing research_harness..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/research_harness[dev]"

echo "Installing research_harness_mcp..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/research_harness_mcp[dev]"

# ---------------------------------------------------------------------------
# 5. Environment file
# ---------------------------------------------------------------------------

if [ ! -f "$REPO_ROOT/.env" ]; then
  if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo ""
    echo "Created .env from .env.example"
    echo "  -> Choose one LLM route in .env before model-backed workflows:"
    echo "     host CLI (Codex / Cursor Agent), OpenAI-compatible endpoint, or direct API key."
  else
    echo ""
    echo "Warning: .env.example not found. Create .env manually with your LLM route."
  fi
else
  echo ""
  echo ".env already exists, skipping."
fi

# ---------------------------------------------------------------------------
# 6. Smoke test
# ---------------------------------------------------------------------------

echo ""
echo "Verifying installation..."
"$PYTHON" -c "import llm_router; import paperindex; import research_harness; import research_harness_mcp; print('All packages importable.')"

# ---------------------------------------------------------------------------
# 7. Build skill manifest (always) and offer skill install
# ---------------------------------------------------------------------------

echo ""
echo "Indexing skills..."
"$PYTHON" -m research_harness.cli skill index --skills-root "$REPO_ROOT" >/dev/null
SKILL_COUNT=$(ls -d "$REPO_ROOT/skills/"*/ 2>/dev/null | grep -v agent-profiles | wc -l | tr -d ' ')
echo "  $SKILL_COUNT skills indexed at $REPO_ROOT/skills/manifest.json"

if [ -f "$REPO_ROOT/.rh-agent.toml" ] || [ -n "${RH_AGENT_CONFIG:-}" ]; then
  echo "Found .rh-agent.toml; installing skills into the agent's expected location..."
  "$PYTHON" -m research_harness.cli skill install --skills-root "$REPO_ROOT" || true
else
  echo ""
  echo "Skills not auto-installed: no .rh-agent.toml found in this repo."
  echo "To install for an agent, either:"
  echo "  * drop a .rh-agent.toml in this directory (templates: skills/agent-profiles/)"
  echo "  * or run:  rh skill install --agent claude-code"
  echo "  * or run:  rh skill install --agent codex   (or opencode / gemini)"
  echo "  * or run:  rh skill install --target ~/.claude/skills"
fi

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and choose an LLM route:"
echo "     host CLI (Codex / Cursor Agent), OpenAI-compatible endpoint, or direct API key"
echo "  2. Install skills:    rh skill install --agent claude-code   (or codex / opencode / gemini)"
echo "  3. Run tests:         python -m pytest packages/ -q"
echo "  4. Health check:      rh --json doctor    (alias: rhub)"
echo "  5. Initialize topic:  rh topic init \"my-research-topic\""
echo "  6. Start MCP server:  rh-mcp"
echo "  7. Start local API:   python -m research_harness_mcp.http_api"
echo "     Endpoint:          http://127.0.0.1:8000"
echo ""
echo "Using Claude Code? CLAUDE.md has all the context."
echo "Using Codex?       AGENTS.md has agent integration instructions."
echo ""
echo "MCP server config for Claude Code (.claude/settings.json):"
echo '  {'
echo '    "mcpServers": {'
echo '      "research-harness": {'
echo '        "command": "rh-mcp"'
echo '      }'
echo '    }'
echo '  }'
