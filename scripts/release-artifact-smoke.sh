#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${1:-"$ROOT/.tmp/release-artifact-smoke"}"
DIST_DIR="$BUILD_ROOT/dist"
VENV_DIR="$BUILD_ROOT/venv"
PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.11 python3 python; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    candidate_path="$(command -v "$candidate")"
    if "$candidate_path" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    then
      PYTHON_BIN="$candidate_path"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "No Python >=3.11 interpreter found. Set PYTHON=/path/to/python." >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$DIST_DIR"

"$PYTHON_BIN" -m pip install --upgrade build >/dev/null

for package in llm_router paperindex research_harness research_harness_mcp; do
  "$PYTHON_BIN" -m build --sdist --wheel --outdir "$DIST_DIR" "$ROOT/packages/$package"
done

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
llm_router_wheels=("$DIST_DIR"/scianchor_llm_router-*.whl)
paperindex_wheels=("$DIST_DIR"/scianchor_paperindex-*.whl)
research_harness_wheels=("$DIST_DIR"/scianchor-[0-9]*.whl)
research_harness_mcp_wheels=("$DIST_DIR"/scianchor_mcp-*.whl)

"$VENV_DIR/bin/python" -m pip install \
  "${llm_router_wheels[0]}[all]" \
  "${paperindex_wheels[0]}" \
  "${research_harness_wheels[0]}" \
  "${research_harness_mcp_wheels[0]}[api]"

# CLI smoke
"$VENV_DIR/bin/rh" --help >/dev/null
"$VENV_DIR/bin/paperindex" --help >/dev/null

"$VENV_DIR/bin/python" - <<'PY'
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from research_harness._core.storage.db import MIGRATIONS_DIR
from research_harness.storage.db import Database
import research_harness_mcp.server  # noqa: F401
import research_harness_mcp.tools  # noqa: F401

sql_files = sorted(Path(MIGRATIONS_DIR).glob("*.sql"))
if len(sql_files) < 60:
    raise SystemExit(f"expected packaged migrations, found {len(sql_files)} in {MIGRATIONS_DIR}")

db_path = Path(tempfile.mkdtemp(prefix="rh-release-smoke-")) / "pool.db"
db = Database(db_path)
db.migrate()

conn = sqlite3.connect(str(db_path))
try:
    applied = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
finally:
    conn.close()

if applied != len(sql_files):
    raise SystemExit(f"migration replay mismatch: applied={applied} files={len(sql_files)}")


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "rh-release-smoke"})
    with urllib.request.urlopen(request, timeout=2) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def _assert_direct_asgi_non_loopback_rejected(env: dict[str, str]) -> None:
    guard_env = dict(env)
    guard_env.pop("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", None)
    guard_env.pop("RESEARCH_HARNESS_HTTP_API_TOKEN", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.argv = ['uvicorn', 'research_harness_mcp.http_api:app', "
                "'--host', '0.0.0.0']; "
                "from research_harness_mcp import http_api"
            ),
        ],
        env=guard_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        raise SystemExit("direct ASGI non-loopback import unexpectedly succeeded")
    if "Non-loopback HTTP binding is unsupported" not in result.stderr:
        raise SystemExit(
            "direct ASGI non-loopback import failed without the expected boundary "
            f"message: {result.stderr[-1000:]}"
        )


port = _reserve_loopback_port()
env = os.environ.copy()
env["RESEARCH_HARNESS_DB_PATH"] = str(db_path)
env["RESEARCH_HARNESS_HTTP_HOST"] = "127.0.0.1"
env.pop("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", None)
_assert_direct_asgi_non_loopback_rejected(env)

process = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "research_harness_mcp.http_api:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ],
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.PIPE,
    text=True,
)

try:
    base_url = f"http://127.0.0.1:{port}"
    topics_payload = None
    last_error: Exception | None = None
    for _ in range(80):
        if process.poll() is not None:
            break
        try:
            topics_payload = _get_json(f"{base_url}/api/topics")
            break
        except Exception as exc:  # noqa: BLE001 - smoke reports last startup error.
            last_error = exc
            time.sleep(0.25)

    if topics_payload is None:
        stderr = process.communicate(timeout=2)[1] if process.poll() is not None else ""
        raise SystemExit(
            "HTTP release smoke failed to start /api/topics"
            f"; last_error={last_error}; stderr={stderr[-2000:]}"
        )

    papers_payload = _get_json(f"{base_url}/api/papers")
    for route, payload in (
        ("/api/topics", topics_payload),
        ("/api/papers", papers_payload),
    ):
        if not isinstance(payload, (dict, list)):
            raise SystemExit(f"HTTP release smoke returned non-JSON collection for {route}")
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
PY
