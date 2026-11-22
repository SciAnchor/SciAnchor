#!/usr/bin/env bash
# Record agent-session human feedback into Research Harness self-evolution.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/rh-agent-feedback-capture.sh --topic TOPIC --stage STAGE --feedback-file FILE [options]

Records human feedback as RH self-evolution experience. Intended for explicit use
or agent hooks that already know they are handling reusable feedback.

Options:
  --topic TOPIC           RH topic name.
  --stage STAGE           Workflow stage or surface.
  --section SECTION       Section/module/quality surface.
  --feedback-file FILE    Text or JSON feedback payload.
  --workspace-path PATH   Workspace path where feedback occurred. Defaults to $PWD.
  --agent NAME            Agent name, e.g. claude-code or codex.
  --trigger-class NAME    Defaults to human_feedback.
USAGE
}

TOPIC=""
STAGE=""
SECTION=""
FEEDBACK_FILE=""
WORKSPACE_PATH="$PWD"
AGENT_NAME=""
TRIGGER_CLASS="human_feedback"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --topic) shift; TOPIC="${1:-}" ;;
    --stage) shift; STAGE="${1:-}" ;;
    --section) shift; SECTION="${1:-}" ;;
    --feedback-file) shift; FEEDBACK_FILE="${1:-}" ;;
    --workspace-path) shift; WORKSPACE_PATH="${1:-}" ;;
    --agent) shift; AGENT_NAME="${1:-}" ;;
    --trigger-class) shift; TRIGGER_CLASS="${1:-}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ -z "$TOPIC" || -z "$STAGE" || -z "$FEEDBACK_FILE" ]]; then
  usage >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${RESEARCH_HARNESS_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if command -v rh >/dev/null 2>&1; then
  exec rh self-evolution record-human-feedback \
    --topic "$TOPIC" \
    --stage "$STAGE" \
    --section "$SECTION" \
    --feedback-file "$FEEDBACK_FILE" \
    --workspace-path "$WORKSPACE_PATH" \
    --agent "$AGENT_NAME" \
    --trigger-class "$TRIGGER_CLASS"
fi

exec "$PYTHON_BIN" -m research_harness.cli self-evolution record-human-feedback \
  --topic "$TOPIC" \
  --stage "$STAGE" \
  --section "$SECTION" \
  --feedback-file "$FEEDBACK_FILE" \
  --workspace-path "$WORKSPACE_PATH" \
  --agent "$AGENT_NAME" \
  --trigger-class "$TRIGGER_CLASS"
