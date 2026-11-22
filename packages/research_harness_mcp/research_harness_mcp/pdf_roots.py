"""Private helpers for local PDF root trust configuration."""

from __future__ import annotations

import os
from pathlib import Path


def default_pdf_roots() -> list[Path]:
    """Return trusted local roots for stored paper PDF paths."""
    candidates = [
        Path.home() / ".research-harness",
        Path(__file__).resolve().parents[3] / ".research-harness",
        # Legacy location for users who upgraded from the pre-OSS layout.
        Path.home() / "code" / "research-harness" / ".research-harness",
    ]
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            root = candidate.expanduser().resolve()
        except OSError:
            continue
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def configured_pdf_roots(env_value: str | None = None) -> list[Path]:
    raw_env_value = (
        os.environ.get("RESEARCH_HARNESS_PDF_ROOTS") if env_value is None else env_value
    )
    if raw_env_value:
        return [
            Path(path).expanduser().resolve()
            for path in raw_env_value.split(":")
            if path
        ]
    return default_pdf_roots()
