#!/usr/bin/env bash
# Coverage baseline entrypoint. It records a pytest-cov report and checks it
# against the documented release coverage threshold decision.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${RESEARCH_HARNESS_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import pytest_cov  # noqa: F401
PY
then
  echo "SKIP: pytest-cov is not installed; coverage baseline not generated." >&2
  exit 0
fi

REPORT_DIR="${RESEARCH_HARNESS_COVERAGE_DIR:-"$ROOT/.tmp/coverage-baseline"}"
mkdir -p "$REPORT_DIR"
REPORT_DIR="$(cd "$REPORT_DIR" && pwd)"

CHECK_THRESHOLD="${RESEARCH_HARNESS_COVERAGE_CHECK:-1}"
TARGETS=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_THRESHOLD=1
      ;;
    --no-check)
      CHECK_THRESHOLD=0
      ;;
    *)
      TARGETS+=("$1")
      ;;
  esac
  shift
done

if [[ "${#TARGETS[@]}" -eq 0 ]]; then
  TARGETS=(
    "packages/research_harness/tests"
    "packages/research_harness_mcp/tests/test_http_paper_service_routing.py"
    "packages/research_harness_mcp/research_harness_mcp/tests/test_tools.py"
    "packages/research_harness_mcp/tests/test_http_boundary_auth.py"
    "packages/research_harness_mcp/tests/test_mcp_tool_boundary.py"
    "packages/research_harness_mcp/tests/test_topic_knowledge_refresh_http.py"
    "packages/research_harness_mcp/tests/test_topic_knowledge_status_http.py"
  )
fi

# Targets are repo-relative; pytest runs from the research_harness package
# directory, the only cwd its suite accepts (scripts/suite_preflight.py, E1).
ABS_TARGETS=()
for target in "${TARGETS[@]}"; do
  if [[ "$target" == /* ]]; then
    ABS_TARGETS+=("$target")
  else
    ABS_TARGETS+=("$ROOT/$target")
  fi
done

cd "$ROOT"
(cd "$ROOT/packages/research_harness" && "$PYTHON_BIN" -m pytest "${ABS_TARGETS[@]}" \
  --cov=research_harness \
  --cov=research_harness_mcp \
  --cov-report=term \
  --cov-report="json:$REPORT_DIR/coverage.json")

echo "Coverage baseline written to $REPORT_DIR/coverage.json"
if [[ "$CHECK_THRESHOLD" == "1" ]]; then
  "$PYTHON_BIN" scripts/check-coverage-threshold.py "$REPORT_DIR/coverage.json"
fi
