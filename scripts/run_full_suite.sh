#!/usr/bin/env bash
# Full suite, one at a time, parallel where it is safe (E1, 2026-09-28).
#   scripts/run_full_suite.sh            # -n 4, then the serial pass
#   scripts/run_full_suite.sh -- serial-only args go to pytest after --
# Time-sensitive tests (marker: serial) stay out of -n; they run second.
# --lf needs the cache this leaves behind. Do not add -n to default addopts.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
"$root/scripts/full_suite_lock.sh" acquire
trap '"$root/scripts/full_suite_lock.sh" release' EXIT
py=${PYTHON:-python3}
# The suite imports the worktree only when run from the package directory.
cd "$root/packages/research_harness"
"$py" -m pytest -m "not serial" -n 4 --dist loadfile --durations=30 "$@"
"$py" -m pytest -m serial --durations=30 "$@"
