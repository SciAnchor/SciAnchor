#!/usr/bin/env bash
# Install local git hooks that sync RH Codex skills after successful git updates.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/install-codex-sync-hook.sh [--force]

Installs git hooks into the active hooks path for this clone:
  - post-merge
  - post-checkout
  - post-rewrite

The hooks run scripts/sync-rh-to-codex.sh after successful local updates so
Codex sees merged RH skill/workflow changes promptly.

If core.hooksPath is configured, Git executes hooks from that configured path;
this installer follows the same path. Hooks installed into a shared hooksPath
silently skip repositories that do not contain scripts/sync-rh-to-codex.sh.
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FORCE=0
case "${1:-}" in
  "")
    ;;
  --force)
    FORCE=1
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

HOOK_DIR="$(git rev-parse --git-path hooks)"
mkdir -p "$HOOK_DIR"

install_hook() {
  local hook_name="$1"
  local target="$HOOK_DIR/$hook_name"

  if [[ -e "$target" && "$FORCE" -ne 1 ]]; then
    if grep -q "RH_CODEX_SYNC_HOOK" "$target" 2>/dev/null; then
      echo "already installed: $target"
      return
    fi
    echo "refusing to overwrite existing hook: $target" >&2
    echo "rerun with --force after reviewing the existing hook" >&2
    return 1
  fi

  cat > "$target" <<'HOOK'
#!/usr/bin/env bash
# RH_CODEX_SYNC_HOOK
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SYNC_SCRIPT="$ROOT_DIR/scripts/sync-rh-to-codex.sh"

if [[ ! -x "$SYNC_SCRIPT" ]]; then
  exit 0
fi

LOG_DIR="$ROOT_DIR/.git/rh"
LOG_FILE="$LOG_DIR/codex-sync.log"
mkdir -p "$LOG_DIR"

{
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] sync after git hook $(basename "$0")"
  "$SYNC_SCRIPT" --preserve-manifest
} >>"$LOG_FILE" 2>&1 || {
  echo "Research Harness Codex sync failed; see $LOG_FILE" >&2
  exit 0
}
HOOK
  chmod +x "$target"
  echo "installed: $target"
}

install_hook post-merge
install_hook post-checkout
install_hook post-rewrite

echo "Codex sync hooks installed for $ROOT_DIR"
