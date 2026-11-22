#!/usr/bin/env bash
# One full suite at a time (E1, 2026-09-28). mkdir is the lock.
#   full_suite_lock.sh acquire   # exit non-zero, naming the holder, if taken
#   full_suite_lock.sh release
set -euo pipefail
lock=${E1_SUITE_LOCK_DIR:-${TMPDIR:-/tmp}/e1-full-suite.lock}
case ${1:-} in
  acquire)
    if ! mkdir "$lock" 2>/dev/null; then
      echo "full suite already running: $(cat "$lock/holder" 2>/dev/null || echo "$lock")" >&2
      exit 1
    fi
    echo "pid=$$ cwd=$(pwd) at=$(date +%s)" > "$lock/holder"
    ;;
  release) rm -rf "$lock" ;;
  *) echo "usage: $0 acquire|release" >&2; exit 2 ;;
esac
