"""Install and verify an SPC release wheel in a clean Linux virtualenv."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "spc.release-manifest.v1"
VERIFY_SCHEMA = "spc.release-install-verification.v1"


class ReleaseVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_release(manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ReleaseVerificationError("release manifest schema 不受支持")
    wheel_meta = manifest.get("wheel") or {}
    wheel = manifest_path.parent / str(wheel_meta.get("filename") or "")
    if not wheel.is_file():
        raise ReleaseVerificationError("release wheel 不存在")
    if _sha256(wheel) != wheel_meta.get("sha256"):
        raise ReleaseVerificationError("release wheel SHA-256 不匹配")
    if wheel.stat().st_size != wheel_meta.get("size_bytes"):
        raise ReleaseVerificationError("release wheel 字节数不匹配")
    return manifest, wheel


def _run_json(
    executable: Path, args: list[str], *, env: dict[str, str]
) -> dict[str, Any]:
    completed = subprocess.run(
        [str(executable), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return json.loads(completed.stdout)


def verify_release(manifest_path: Path, venv: Path) -> Path:
    if platform.system().lower() != "linux":
        raise ReleaseVerificationError("SPC release 只能在 Linux 验证")
    if sys.version_info[:2] != (3, 12):
        raise ReleaseVerificationError("SPC release 必须使用 Python 3.12 验证")
    manifest, wheel = load_release(manifest_path)
    if venv.exists():
        raise ReleaseVerificationError("验证 venv 已存在，拒绝复用非干净运行时")
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=120)
    python = venv / "bin" / "python"
    spc = venv / "bin" / "spc"
    subprocess.run(
        [str(python), "-m", "pip", "install", f"{wheel}[all]"],
        check=True,
        timeout=900,
    )
    runtime_env = os.environ.copy()
    runtime_env["SPC_LOG_MODE"] = "production"
    version_envelope = _run_json(spc, ["version", "--format", "json"], env=runtime_env)
    schema = _run_json(
        spc, ["schema", "paper", "download", "--format", "json"], env=runtime_env
    )
    capabilities = _run_json(
        spc,
        [
            "system",
            "capabilities",
            "--capability",
            "system.core",
            "--output-format",
            "json",
        ],
        env=runtime_env,
    )
    version = version_envelope.get("data", {})
    expected_sha = manifest["git_sha"]
    if version.get("git_sha") != expected_sha:
        raise ReleaseVerificationError("installed runtime Git SHA 与 manifest 不一致")
    if (
        version.get("install_mode") != "installed"
        or version.get("source_root") is not None
    ):
        raise ReleaseVerificationError("验证运行时不是独立 installed wheel")
    if version.get("python_version", "").split(".")[:2] != ["3", "12"]:
        raise ReleaseVerificationError("installed runtime Python 版本不符合 3.12")
    if schema.get("schema") != "spc.result.v2":
        raise ReleaseVerificationError("公共结果 schema 不兼容")
    if capabilities.get("status") != "completed":
        raise ReleaseVerificationError("system.core capability 未通过")
    report = {
        "schema_version": VERIFY_SCHEMA,
        "status": "completed",
        "git_sha": expected_sha,
        "wheel_sha256": manifest["wheel"]["sha256"],
        "venv": str(venv.resolve()),
        "runtime": {
            key: version.get(key)
            for key in (
                "version",
                "git_sha",
                "install_mode",
                "package_path",
                "source_root",
                "python_executable",
                "python_version",
                "platform",
            )
        },
        "public_result_schema": schema["schema"],
        "system_core_status": capabilities["status"],
    }
    report_path = manifest_path.parent / "install-verification.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在干净 Linux venv 验证 SPC release wheel"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_release(args.manifest.resolve(), args.venv.resolve())
    except (
        ReleaseVerificationError,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"status": "completed", "report_path": str(report)}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
