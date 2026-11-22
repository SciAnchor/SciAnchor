"""SPC 1.0 release wheel manifest contract."""

from __future__ import annotations

import zipfile
import json
import subprocess
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _load_module():
    import importlib.util

    path = Path(__file__).parents[1] / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("spc_build_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_verify_module():
    import importlib.util

    path = Path(__file__).parents[1] / "scripts" / "verify_release.py"
    spec = importlib.util.spec_from_file_location("spc_verify_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wheel(
    path: Path,
    *,
    git_sha: str,
    missing: str | None = None,
    secret: bool = False,
):
    module = _load_module()
    with zipfile.ZipFile(path, "w") as archive:
        for member in module.REQUIRED_WHEEL_MEMBERS:
            if member != missing:
                archive.writestr(member, b"test")
        archive.writestr(
            "paperfetch/_build_info.py",
            f"BUILD_GIT_SHA = {git_sha!r}\nBUILD_TIME = '2026-08-14T00:00:00Z'\n",
        )
        if secret:
            archive.writestr("paperfetch/secrets.env", b"TOKEN=hidden")


def test_release_wheel_inspection_requires_identity_and_runtime_data(tmp_path):
    module = _load_module()
    sha = "a" * 40
    wheel = tmp_path / "spc.whl"
    _wheel(wheel, git_sha=sha)

    result = module.inspect_wheel(wheel, sha)

    assert result["build_identity_verified"] is True
    assert result["private_config_absent"] is True
    assert result["required_members_verified"] == list(module.REQUIRED_WHEEL_MEMBERS)


def test_release_wheel_rejects_missing_runtime_data(tmp_path):
    module = _load_module()
    sha = "b" * 40
    wheel = tmp_path / "spc.whl"
    _wheel(wheel, git_sha=sha, missing=module.REQUIRED_WHEEL_MEMBERS[0])

    with pytest.raises(module.ReleaseBuildError, match="缺少必需运行文件"):
        module.inspect_wheel(wheel, sha)


def test_release_wheel_rejects_private_configuration(tmp_path):
    module = _load_module()
    sha = "c" * 40
    wheel = tmp_path / "spc.whl"
    _wheel(wheel, git_sha=sha, secret=True)

    with pytest.raises(module.ReleaseBuildError, match="私有配置"):
        module.inspect_wheel(wheel, sha)


def test_release_builder_exports_only_committed_source(tmp_path):
    module = _load_module()
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "spc-test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "SPC Test"], cwd=root, check=True)
    (root / "tracked.txt").write_text("current", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    stale = root / "build" / "lib" / "paperfetch"
    stale.mkdir(parents=True)
    (stale / "deleted_backend.py").write_text("stale", encoding="utf-8")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    destination = tmp_path / "clean"

    module.export_clean_source(root, sha, destination)

    assert (destination / "tracked.txt").read_text(encoding="utf-8") == "current"
    assert not (destination / "build").exists()


def test_release_verifier_accepts_matching_manifest(tmp_path):
    module = _load_verify_module()
    wheel = tmp_path / "spc.whl"
    wheel.write_bytes(b"wheel")
    digest = module._sha256(wheel)
    manifest = {
        "schema_version": module.MANIFEST_SCHEMA,
        "git_sha": "d" * 40,
        "wheel": {"filename": wheel.name, "sha256": digest, "size_bytes": 5},
    }
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded, loaded_wheel = module.load_release(manifest_path)

    assert loaded["git_sha"] == "d" * 40
    assert loaded_wheel == wheel


def test_release_verifier_rejects_hash_mismatch(tmp_path):
    module = _load_verify_module()
    wheel = tmp_path / "spc.whl"
    wheel.write_bytes(b"wheel")
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": module.MANIFEST_SCHEMA,
                "wheel": {"filename": wheel.name, "sha256": "0" * 64, "size_bytes": 5},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ReleaseVerificationError, match="SHA-256"):
        module.load_release(manifest_path)
