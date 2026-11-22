#!/usr/bin/env bash
# Dependency audit entrypoint.
#
# CI uses advisory mode: missing pip-audit or findings are reported without
# failing the job. Local release closure can use --require-report to make a
# generated pip-audit JSON report mandatory without adding pip-audit to project
# package dependencies.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/dependency-audit-report.sh [--advisory|--require-report] [--fail-on-findings] [REPORT_DIR]

Modes:
  --advisory         Report findings, skip cleanly if pip-audit is unavailable.
  --require-report   Fail if pip-audit is unavailable or no JSON report is written.
  --fail-on-findings Fail when pip-audit reports vulnerabilities.

pip-audit is intentionally an external local audit tool; keep it out of
project package dependencies.
USAGE
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${RESEARCH_HARNESS_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

MODE="advisory"
FAIL_ON_FINDINGS=0
REPORT_DIR="$ROOT/.tmp/dependency-audit"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --advisory)
      MODE="advisory"
      ;;
    --require-report)
      MODE="require-report"
      ;;
    --fail-on-findings)
      FAIL_ON_FINDINGS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      REPORT_DIR="$1"
      ;;
  esac
  shift
done

mkdir -p "$REPORT_DIR"
REPORT_PATH="$REPORT_DIR/pip-audit-report.json"
REPORT_TMP="$REPORT_PATH.tmp.$$"

if ! "$PYTHON_BIN" -m pip_audit --version >/dev/null 2>&1; then
  echo "SKIP: pip-audit is not installed; dependency audit not generated." >&2
  echo "Install it outside project dependencies with: $PYTHON_BIN -m pip install pip-audit" >&2
  if [[ "$MODE" == "require-report" ]]; then
    exit 1
  fi
  exit 0
fi

rm -f "$REPORT_TMP"

set +e
"$PYTHON_BIN" -m pip_audit \
  --progress-spinner off \
  --format=json \
  --output "$REPORT_TMP"
AUDIT_STATUS=$?
set -e

REPORT_GENERATED=0
if [[ -s "$REPORT_TMP" ]]; then
  mv "$REPORT_TMP" "$REPORT_PATH"
  REPORT_GENERATED=1
else
  rm -f "$REPORT_TMP"
fi

if [[ "$AUDIT_STATUS" -eq 0 ]]; then
  if [[ "$REPORT_GENERATED" -ne 1 ]]; then
    echo "FAIL: required dependency audit report was not generated: $REPORT_PATH" >&2
    if [[ "$MODE" == "require-report" || "$FAIL_ON_FINDINGS" -eq 1 ]]; then
      exit 1
    fi
    echo "Advisory mode: dependency audit did not write a fresh report." >&2
    exit 0
  fi
  echo "Dependency audit report passed: $REPORT_PATH"
else
  if [[ "$REPORT_GENERATED" -ne 1 ]]; then
    echo "FAIL: required dependency audit report was not generated: $REPORT_PATH" >&2
    if [[ "$MODE" == "require-report" || "$FAIL_ON_FINDINGS" -eq 1 ]]; then
      exit "$AUDIT_STATUS"
    fi
    echo "Advisory mode: dependency audit failed before writing a fresh report." >&2
    exit 0
  fi
  echo "Dependency audit report has findings: $REPORT_PATH" >&2
  if [[ "$FAIL_ON_FINDINGS" -eq 1 ]]; then
    exit "$AUDIT_STATUS"
  fi
  echo "Advisory findings mode: generated report without failing." >&2
fi

if [[ "$MODE" == "require-report" && "$REPORT_GENERATED" -ne 1 ]]; then
  echo "FAIL: required dependency audit report was not generated: $REPORT_PATH" >&2
  exit 1
fi

exit 0
