import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_module_entrypoint_emits_clean_version_json():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "paperfetch",
            "version",
            "--output-format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["schema"] == "spc.result.v2"
    assert envelope["status"] == "completed"
    payload = envelope["data"]
    assert payload["package"] == "paperfetch"
    assert payload["python_executable"] == sys.executable
