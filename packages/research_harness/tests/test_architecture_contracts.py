from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
REPO_ROOT = next(
    p for p in HERE.parents if (p / "skills").is_dir() and (p / "setup.sh").is_file()
)


def test_architecture_boundary_metadata_is_current() -> None:
    subprocess.run(
        [sys.executable, "scripts/check-architecture-boundaries.py"],
        cwd=REPO_ROOT,
        check=True,
    )


def test_storage_schema_doc_is_current() -> None:
    subprocess.run(
        [sys.executable, "scripts/dump-schema.py", "--check"],
        cwd=REPO_ROOT,
        check=True,
    )
