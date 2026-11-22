"""Build the one immutable SPC wheel and its release manifest on Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any


MANIFEST_SCHEMA = "spc.release-manifest.v1"
REQUIRED_WHEEL_MEMBERS = (
    "paperfetch/downloaders/download_validation_samples.json",
    "paperfetch/data/reference/ccf_ranks_2026.json",
    "paperfetch/data/workflow/schemas/workflow-ready.v1.schema.json",
)
FORBIDDEN_MEMBER_PARTS = (
    "/.env",
    "secrets.env",
    "storage-state",
    "cookies.json",
)


class ReleaseBuildError(RuntimeError):
    pass


def _run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        [*args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_clean_source(root: Path, git_sha: str, destination: Path) -> None:
    """Materialize only files tracked by the requested commit.

    Setuptools can reuse ``build/lib`` from a long-lived checkout and silently
    package files deleted from the current commit.  A Git archive makes the
    release input independent from ignored caches and previous builds.
    """

    destination.mkdir(parents=True)
    archive_path = destination.parent / "source.tar"
    with archive_path.open("wb") as archive_handle:
        subprocess.run(
            ["git", "archive", "--format=tar", git_sha],
            cwd=root,
            check=True,
            stdout=archive_handle,
            timeout=120,
        )
    with tarfile.open(archive_path, "r") as archive:
        archive.extractall(destination, filter="data")


def inspect_wheel(wheel: Path, git_sha: str) -> dict[str, Any]:
    """Verify release identity, required package data, and secret exclusions."""
    with zipfile.ZipFile(wheel) as archive:
        members = sorted(archive.namelist())
        missing = [name for name in REQUIRED_WHEEL_MEMBERS if name not in members]
        forbidden = [
            name
            for name in members
            if any(
                part.casefold() in f"/{name}".casefold()
                for part in FORBIDDEN_MEMBER_PARTS
            )
        ]
        build_info_names = [
            name for name in members if name == "paperfetch/_build_info.py"
        ]
        build_info = (
            archive.read(build_info_names[0]).decode("utf-8")
            if len(build_info_names) == 1
            else ""
        )
    if missing:
        raise ReleaseBuildError(f"wheel 缺少必需运行文件：{', '.join(missing)}")
    if forbidden:
        raise ReleaseBuildError("wheel 包含禁止发布的私有配置文件")
    if len(build_info_names) != 1 or git_sha not in build_info:
        raise ReleaseBuildError("wheel 未嵌入唯一 Git SHA")
    return {
        "member_count": len(members),
        "required_members_verified": list(REQUIRED_WHEEL_MEMBERS),
        "build_identity_verified": True,
        "private_config_absent": True,
    }


def build_release(root: Path, output_root: Path) -> Path:
    if platform.system().lower() != "linux":
        raise ReleaseBuildError("SPC wheel 只能在 Linux 上构建")
    if sys.version_info[:2] != (3, 12):
        raise ReleaseBuildError("SPC wheel 必须使用 Python 3.12 构建")
    if _run(root, "git", "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseBuildError("Git 工作树不干净，拒绝构建 release wheel")
    git_sha = _run(root, "git", "rev-parse", "HEAD")
    build_time = _run(root, "git", "show", "-s", "--format=%cI", "HEAD")
    output_root = output_root.resolve()
    release_dir = output_root / git_sha
    staging_dir = output_root / f".staging-{git_sha}-{os.getpid()}"
    if release_dir.exists():
        raise ReleaseBuildError(f"release 目录已存在，拒绝覆盖：{release_dir}")
    if staging_dir.exists():
        raise ReleaseBuildError(f"release staging 目录已存在：{staging_dir}")
    staging_dir.mkdir(parents=True)
    environment = os.environ.copy()
    environment["SPC_BUILD_GIT_SHA"] = git_sha
    environment["SPC_BUILD_TIME"] = build_time
    # The commit time makes archive timestamps stable for a given source commit.
    environment["SOURCE_DATE_EPOCH"] = _run(
        root, "git", "show", "-s", "--format=%ct", "HEAD"
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".source-{git_sha}-", dir=output_root
        ) as temporary_source:
            clean_root = Path(temporary_source) / "repo"
            export_clean_source(root, git_sha, clean_root)
            project = tomllib.loads(
                (clean_root / "pyproject.toml").read_text(encoding="utf-8")
            )["project"]
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--outdir",
                    str(staging_dir),
                ],
                cwd=clean_root,
                env=environment,
                check=True,
                timeout=600,
            )
        wheels = list(staging_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise ReleaseBuildError("构建必须只产生一个 wheel")
        wheel = wheels[0]
        inspection = inspect_wheel(wheel, git_sha)
        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "package": str(project["name"]),
            "version": str(project["version"]),
            "git_sha": git_sha,
            "build_time": build_time,
            "build_platform": "linux",
            "python_version": platform.python_version(),
            "wheel": {
                "filename": wheel.name,
                "sha256": _sha256(wheel),
                "size_bytes": wheel.stat().st_size,
            },
            "inspection": inspection,
        }
        manifest_path = staging_dir / "release-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging_dir.rename(release_dir)
        return release_dir / manifest_path.name
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 SPC 2.0 唯一 Linux wheel")
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-root", type=Path, default=Path("dist/releases"))
    args = parser.parse_args()
    try:
        manifest = build_release(args.root.resolve(), args.output_root)
    except (
        ReleaseBuildError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"status": "completed", "manifest_path": str(manifest)}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
