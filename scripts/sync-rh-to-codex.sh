#!/usr/bin/env bash
# Sync Research Harness skills and Codex-facing workflow surfaces into Codex.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/sync-rh-to-codex.sh [--dry-run] [--preserve-manifest]

Synchronizes the current Research Harness checkout to the local Codex skill
surface by rebuilding or validating the RH skill manifest and running:

  rh skill install --agent codex
  rh skill verify --agent codex

This script is safe to run repeatedly. It does not push, publish, or modify
remote resources.

Options:
  --dry-run            Show what would be installed without writing Codex state.
  --preserve-manifest  Do not rewrite skills/manifest.json. Intended for git
                       hooks so checkout/merge sync does not dirty the tree.
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DRY_RUN=0
PRESERVE_MANIFEST=0
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --preserve-manifest)
      PRESERVE_MANIFEST=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

PYTHON_BIN="${RESEARCH_HARNESS_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

run_rh() {
  if command -v rh >/dev/null 2>&1; then
    rh "$@"
    return
  fi
  "$PYTHON_BIN" -m research_harness.cli "$@"
}

echo "==> Research Harness to Codex sync"
echo "repo: $ROOT_DIR"
echo "python: $PYTHON_BIN"

if [[ "$DRY_RUN" -eq 1 ]]; then
  run_rh skill index --skills-root "$ROOT_DIR" --no-write >/dev/null
  run_rh skill install --skills-root "$ROOT_DIR" --agent codex --dry-run
  exit 0
fi

if [[ "$PRESERVE_MANIFEST" -eq 1 ]]; then
  run_rh skill index --skills-root "$ROOT_DIR" --no-write >/dev/null
else
  run_rh skill index --skills-root "$ROOT_DIR"
fi
run_rh skill install --skills-root "$ROOT_DIR" --agent codex
run_rh skill verify --skills-root "$ROOT_DIR" --agent codex

echo "Codex sync completed."
