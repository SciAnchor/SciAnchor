#!/usr/bin/env bash
# Standard Codex verification entrypoint for research-harness.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/codex-check.sh [--quick|--full|--python|--mcp|--audit|--coverage]

Modes:
  --quick   Validate Codex/RH workflow metadata only (default).
  --full    Run quick checks plus RH_TEST_TIER=full Python tests and MCP smoke checks.
  --python  Run Python package tests when pytest is available.
  --mcp     Run lightweight Research Harness MCP wrapper checks.
  --audit   Run advisory dependency audit report if pip-audit is installed.
  --coverage Run pytest-cov coverage and enforce the release threshold decision.
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${RESEARCH_HARNESS_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

MODE="${1:---quick}"
case "$MODE" in
  --quick|--full|--python|--mcp|--audit|--coverage) ;;
  -h|--help) usage; exit 0 ;;
  *) echo "Unknown mode: $MODE" >&2; usage >&2; exit 2 ;;
esac

run_step() {
  local name="$1"
  shift
  printf '\n==> %s\n' "$name"
  "$@"
}

run_quick() {
  run_step "Codex/RH workflow metadata" "$PYTHON_BIN" scripts/codex_skill_manifest_check.py
  run_step "RH-to-Codex sync script syntax" bash -n scripts/sync-rh-to-codex.sh
  run_step "Codex sync hook installer syntax" bash -n scripts/install-codex-sync-hook.sh
  run_step "MCP public surface guard" "$PYTHON_BIN" scripts/check-mcp-public-surface.py
  run_step "Compatibility inventory guard" "$PYTHON_BIN" scripts/check-compatibility-inventory.py
  run_step "Service coverage guard" "$PYTHON_BIN" scripts/check-service-coverage.py
  run_step "Release docs consistency guard" "$PYTHON_BIN" scripts/check-release-doc-consistency.py
  run_step "Release gate guard" "$PYTHON_BIN" scripts/check-release-gates.py
  run_step "Transport service coverage guard" "$PYTHON_BIN" scripts/check-transport-service-coverage.py
  run_step "Untracked file inventory guard" "$PYTHON_BIN" scripts/worktree-inventory.py --check-only
  run_step "Architecture boundary metadata" "$PYTHON_BIN" scripts/check-architecture-boundaries.py
  run_step "SQLite schema documentation" "$PYTHON_BIN" scripts/dump-schema.py --check
}

run_in() {
  local dir="$1"
  shift
  (cd "$ROOT_DIR/$dir" && "$@")
}

ensure_pytest() {
  if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import pytest  # noqa: F401
PY
  then
    echo "SKIP: pytest is not importable in this Python environment" >&2
    return 1
  fi
  return 0
}

run_python() {
  ensure_pytest || return 0

  # Each package suite runs from its own directory: the research_harness
  # suite refuses any other cwd (scripts/suite_preflight.py, E1).
  run_step "Python smoke tests (research_harness)" \
    run_in packages/research_harness "$PYTHON_BIN" -m pytest tests/test_db.py -q --tb=short
  run_step "Python smoke tests (research_harness_mcp)" \
    run_in packages/research_harness_mcp "$PYTHON_BIN" -m pytest tests/test_routes.py -q --tb=short
}

run_python_full() {
  ensure_pytest || return 0

  local pkg
  local -a targets
  for pkg in llm_router paperindex research_harness research_harness_mcp; do
    targets=(tests)
    [[ "$pkg" == research_harness_mcp ]] && targets+=(research_harness_mcp/tests)
    run_step "Python full-tier tests ($pkg)" \
      run_in "packages/$pkg" env RH_TEST_TIER=full "$PYTHON_BIN" -m pytest "${targets[@]}" -q --tb=short
  done
}

run_mcp() {
  if [[ ! -x scripts/rh-mcp-keychain.sh ]]; then
    echo "FAIL: scripts/rh-mcp-keychain.sh is missing or not executable" >&2
    return 1
  fi

  run_step "Research Harness MCP import smoke" \
    "$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

if importlib.util.find_spec("research_harness_mcp") is None:
    print("SKIP: research_harness_mcp is not importable in this Python environment", file=sys.stderr)
    raise SystemExit(0)

print("research_harness_mcp importable")
PY
}

run_dependency_audit() {
  run_step "Dependency audit report (advisory)" bash scripts/dependency-audit-report.sh --advisory
}

run_coverage_baseline() {
  run_step "Critical path coverage guard" "$PYTHON_BIN" scripts/check-critical-path-coverage.py
  run_step "Coverage baseline threshold" bash scripts/coverage-baseline.sh "$@"
}

case "$MODE" in
  --quick)
    run_quick
    ;;
  --python)
    run_quick
    run_python
    ;;
  --mcp)
    run_quick
    run_mcp
    ;;
  --audit)
    run_dependency_audit
    ;;
  --coverage)
    shift || true
    run_coverage_baseline "$@"
    ;;
  --full)
    run_quick
    run_python_full
    run_mcp
    run_dependency_audit
    ;;
esac

printf '\nCodex check completed: %s\n' "$MODE"
