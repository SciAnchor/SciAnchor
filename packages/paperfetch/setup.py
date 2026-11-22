"""Setuptools hooks for embedding immutable wheel build identity."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


def _git_sha() -> str | None:
    configured = os.getenv("SPC_BUILD_GIT_SHA", "").strip()
    if configured:
        return configured[:128]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _build_time() -> str:
    configured = os.getenv("SPC_BUILD_TIME", "").strip()
    if configured:
        return configured[:128]
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BuildPyWithIdentity(build_py):
    """Write release identity into the build tree, never the source tree."""

    def run(self) -> None:
        super().run()
        target = Path(self.build_lib) / "paperfetch" / "_build_info.py"
        target.write_text(
            "# Generated during wheel build; do not edit.\n"
            f"BUILD_GIT_SHA = {_git_sha()!r}\n"
            f"BUILD_TIME = {_build_time()!r}\n",
            encoding="utf-8",
        )


setup(cmdclass={"build_py": BuildPyWithIdentity})
