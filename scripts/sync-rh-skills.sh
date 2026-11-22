#!/usr/bin/env bash
# Sync Research Harness skills into supported local agent skill surfaces.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/sync-rh-skills.sh [--dry-run] [--preserve-manifest] [--agent claude-code|codex]

Synchronizes the current Research Harness checkout to local agent skill surfaces.
By default, syncs both Claude Code and Codex.

Options:
  --dry-run            Show what would be installed without writing agent state.
  --preserve-manifest  Do not rewrite skills/manifest.json.
  --agent NAME         Sync one agent only. May be repeated.
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DRY_RUN=0
PRESERVE_MANIFEST=0
AGENTS=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --preserve-manifest)
      PRESERVE_MANIFEST=1
      ;;
    --agent)
      shift
      [[ "$#" -gt 0 ]] || { echo "--agent requires a value" >&2; exit 2; }
      AGENTS+=("$1")
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

if [[ "${#AGENTS[@]}" -eq 0 ]]; then
  AGENTS=(claude-code codex)
fi

args=()
[[ "$DRY_RUN" -eq 1 ]] && args+=(--dry-run)
[[ "$PRESERVE_MANIFEST" -eq 1 ]] && args+=(--preserve-manifest)

for agent in "${AGENTS[@]}"; do
  case "$agent" in
    claude-code|claude)
      scripts/sync-rh-to-claude-code.sh "${args[@]}"
      ;;
    codex)
      scripts/sync-rh-to-codex.sh "${args[@]}"
      ;;
    *)
      echo "Unsupported agent: $agent" >&2
      exit 2
      ;;
  esac
done
