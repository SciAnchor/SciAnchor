"""Shared default-env loading for every Research Harness entrypoint.

The CLI has always auto-loaded local env files and macOS Keychain secrets
before running commands, but service/MCP entrypoints historically did not.
That made provider-readiness probes (for example figure-illustration backend
checks) answer differently depending on which surface invoked them: a CLI
command saw a configured provider while the same probe inside an MCP-served
gate saw nothing. This module is the single implementation both surfaces use.

Loading never overrides variables that are already set, honors the
``RESEARCH_HARNESS_AUTO_ENV`` / ``RESEARCH_HARNESS_AUTO_KEYCHAIN`` opt-outs,
and never logs secret values.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ENV_FALSE_VALUES = {"0", "false", "no", "off"}
KEYCHAIN_SECRET_NAMES = (
    "UNPAYWALL_EMAIL",
    "PUBMED_EMAIL",
    "FAL_KEY",
    "GOOGLE_API_KEY",
    "RESEARCH_HARNESS_FIGURE_MODEL",
    "RESEARCH_HARNESS_FIGURE_GEMINI_MODEL",
    "RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS",
    "ZOTERO_API_KEY",
    "ZOTERO_LIBRARY_ID",
    "ZOTERO_LIBRARY_TYPE",
    "MINERU_API_TOKEN",
)


def parse_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    name, raw_value = stripped.split("=", 1)
    name = name.strip()
    if not name or not all(ch == "_" or ch.isalnum() for ch in name):
        return None
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return name, value


def load_env_file(path: Path) -> list[str]:
    loaded: list[str] = []
    if not path.is_file():
        return loaded
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for line in lines:
        assignment = parse_env_assignment(line)
        if assignment is None:
            continue
        name, value = assignment
        if name in os.environ:
            continue
        os.environ[name] = value
        loaded.append(name)
    return loaded


def load_default_env_files() -> dict[str, list[str]]:
    """Load local RH env files and Keychain secrets without logging values."""

    if os.environ.get("RESEARCH_HARNESS_AUTO_ENV", "").strip().lower() in (
        ENV_FALSE_VALUES
    ):
        return {}

    candidates: list[Path] = []
    explicit = os.environ.get("RESEARCH_HARNESS_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    private_env = Path.home() / ".config" / "research-harness" / "private.env"
    candidates.append(private_env)
    root_env = discover_rh_root_env()
    if root_env is not None:
        candidates.append(root_env)
    candidates.append(Path.cwd() / ".env")

    loaded: dict[str, list[str]] = {}
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        names = load_env_file(path)
        if names:
            loaded[str(path)] = names
    keychain_names = load_keychain_env()
    if keychain_names:
        loaded["macos-keychain"] = keychain_names
    return loaded


def discover_rh_root_env() -> Path | None:
    root = os.environ.get("RESEARCH_HARNESS_ROOT", "").strip()
    if root:
        return Path(root).expanduser() / ".env"
    package_root = Path(__file__).resolve().parents[3]
    candidate = package_root / ".env"
    if candidate.is_file():
        return candidate
    return None


def load_keychain_env() -> list[str]:
    if os.environ.get("RESEARCH_HARNESS_AUTO_KEYCHAIN", "").strip().lower() in (
        ENV_FALSE_VALUES
    ):
        return []
    security = shutil.which("security")
    if not security:
        return []
    account = os.environ.get("USER", "").strip()
    if not account:
        try:
            account = os.getlogin()
        except OSError:
            return []
    keychain_path = os.environ.get("RH_KEYCHAIN_PATH", "").strip()
    loaded: list[str] = []
    for name in KEYCHAIN_SECRET_NAMES:
        if os.environ.get(name, "").strip():
            continue
        command = [
            security,
            "find-generic-password",
            "-a",
            account,
            "-s",
            f"research-harness:{name}",
            "-w",
        ]
        if keychain_path:
            command.append(keychain_path)
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        value = result.stdout.strip()
        if result.returncode == 0 and value:
            os.environ[name] = value
            loaded.append(name)
    return loaded


_ENSURED: dict[str, list[str]] | None = None


def ensure_default_env_loaded() -> dict[str, list[str]]:
    """Load default env files at most once per process.

    Readiness probes call this on every gate evaluation, so the underlying
    file/Keychain scan must not repeat; a stale negative would only occur if
    someone writes a new env file mid-process, which the CLI never supported
    either.
    """
    global _ENSURED
    if _ENSURED is None:
        _ENSURED = load_default_env_files()
    return _ENSURED


def reset_ensure_cache_for_tests() -> None:
    global _ENSURED
    _ENSURED = None
