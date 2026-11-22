"""Sanitized SPC runtime and CLI-schema preflight for the Codex plugin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PUBLIC_SCHEMA = "spc.result.v2"


def _expected_python(profile: str, production_root: str | None = None) -> Path:
    if profile == "production":
        root = (
            Path(production_root).expanduser()
            if production_root
            else Path.home() / ".local" / "share" / "paperfetch-production"
        )
        return root / "current" / "venv" / "bin" / "python"
    return Path(sys.executable)


def _spc_executable(profile: str, python_path: Path) -> Path:
    return python_path.parent / "spc"


def _run_json(prefix: list[str], args: list[str]) -> tuple[int, dict[str, Any] | None]:
    completed = subprocess.run(
        [*prefix, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    return completed.returncode, payload


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    production_root = getattr(args, "production_root", None)
    expected_python = (
        _expected_python(args.runtime_profile, production_root).expanduser().absolute()
    )
    actual_python = Path(sys.executable).expanduser().absolute()
    spc_executable = _spc_executable(args.runtime_profile, expected_python)
    module_prefix = [str(expected_python), "-m", "paperfetch"]
    env_file = Path(args.env_file).resolve() if args.env_file else None
    checks: dict[str, Any] = {
        "python_matches_profile": actual_python == expected_python,
        "python_exists": expected_python.is_file(),
        "spc_executable_exists": spc_executable.is_file(),
        "env_file_supplied": env_file is not None,
        "env_file_exists": env_file.is_file() if env_file else None,
    }
    report: dict[str, Any] = {
        "schema_version": "spc.codex-plugin-preflight.v1",
        "runtime_profile": args.runtime_profile,
        "production_root": production_root
        if args.runtime_profile == "production"
        else None,
        "checks": checks,
        "ready": False,
    }
    if not checks["python_matches_profile"] or not checks["python_exists"]:
        report["error_code"] = "runtime_python_mismatch"
        return report
    if not checks["spc_executable_exists"]:
        report["error_code"] = "spc_executable_missing"
        return report
    if env_file is not None and not checks["env_file_exists"]:
        report["error_code"] = "env_file_missing"
        return report

    version_code, version = _run_json(
        module_prefix, ["version", "--output-format", "json"]
    )
    schema_code, schema = _run_json(
        module_prefix, ["schema", "paper", "download", "--format", "json"]
    )
    doctor_args = ["doctor", "--output-format", "json"]
    if env_file:
        doctor_args.extend(["--env-file", str(env_file)])
    doctor_code, doctor = _run_json(module_prefix, doctor_args)

    version_envelope = version or {}
    version = (
        version_envelope.get("data")
        if isinstance(version_envelope.get("data"), dict)
        else {}
    )
    schema = schema or {}
    checks.update(
        {
            "version_command_ok": version_code == 0,
            "doctor_command_ok": doctor_code == 0 and doctor is not None,
            "schema_command_ok": schema_code == 0,
            "public_schema_compatible": schema.get("schema") == PUBLIC_SCHEMA,
            "git_sha_present": bool(version.get("git_sha")),
            "expected_git_sha_matches": (
                version.get("git_sha") == args.expected_git_sha
                if args.expected_git_sha
                else None
            ),
            "expected_source_root_matches": (
                Path(version.get("source_root", "")).resolve()
                == Path(args.expected_source_root).resolve()
                if args.expected_source_root
                else None
            ),
        }
    )
    report["runtime"] = {
        "version": version.get("version"),
        "git_sha": version.get("git_sha"),
        "install_mode": version.get("install_mode"),
        "python_matches_version_report": (
            Path(version.get("python_executable", "")).expanduser().absolute()
            == expected_python
        ),
    }
    required = [
        "version_command_ok",
        "doctor_command_ok",
        "schema_command_ok",
        "public_schema_compatible",
        "git_sha_present",
    ]
    if args.expected_git_sha:
        required.append("expected_git_sha_matches")
    if args.expected_source_root:
        required.append("expected_source_root_matches")
    report["ready"] = (
        all(checks[name] for name in required)
        and report["runtime"]["python_matches_version_report"]
    )
    if not report["ready"]:
        report["error_code"] = "spc_preflight_failed"
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check SPC without exposing configuration values."
    )
    parser.add_argument(
        "--runtime-profile",
        choices=["development", "production"],
        default="development",
    )
    parser.add_argument(
        "--production-root",
        default=None,
        help="Release root containing current/venv; defaults to ~/.local/share/paperfetch-production",
    )
    parser.add_argument("--env-file")
    parser.add_argument("--expected-git-sha")
    parser.add_argument("--expected-source-root")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = build_report(parse_args(argv))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
