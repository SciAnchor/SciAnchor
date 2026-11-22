import tomllib
from pathlib import Path

from paperfetch import runtime_info
from paperfetch.runtime_info import collect_runtime_info


def _project_version() -> str:
    payload = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    return str(payload["project"]["version"])


def test_runtime_info_uses_release_metadata_without_credentials(monkeypatch):
    monkeypatch.setattr(runtime_info, "BUILD_GIT_SHA", None)
    monkeypatch.setattr(runtime_info, "BUILD_TIME", None)
    monkeypatch.setenv("SPC_BUILD_GIT_SHA", "abcdef1234567890")
    monkeypatch.setenv("SPC_BUILD_TIME", "2026-07-28T10:00:00+08:00")
    monkeypatch.setenv("ELSEVIER_API_KEY", "must-not-leak")

    result = collect_runtime_info()

    assert result["package"] == "paperfetch"
    assert result["version"] == _project_version()
    assert result["installed_version"]
    assert isinstance(result["version_mismatch"], bool)
    assert result["git_sha"] == "abcdef1234567890"
    assert result["build_time"] == "2026-07-28T10:00:00+08:00"
    assert result["install_mode"] in {"editable", "installed"}
    assert "must-not-leak" not in str(result)


def test_runtime_info_has_required_deployment_identity(monkeypatch):
    monkeypatch.delenv("SPC_BUILD_GIT_SHA", raising=False)
    monkeypatch.delenv("SPC_BUILD_TIME", raising=False)

    result = collect_runtime_info()

    assert result["version"]
    assert result["package_path"]
    assert result["python_executable"]
    assert result["python_version"]
    assert result["platform"]


def test_runtime_info_uses_identity_embedded_in_wheel(monkeypatch):
    monkeypatch.setenv("SPC_BUILD_GIT_SHA", "stale-environment-sha")
    monkeypatch.setenv("SPC_BUILD_TIME", "2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(runtime_info, "BUILD_GIT_SHA", "embedded-sha")
    monkeypatch.setattr(runtime_info, "BUILD_TIME", "2026-07-28T09:00:00+00:00")
    monkeypatch.setattr(runtime_info, "_git_sha", lambda _path: "checkout-sha")

    result = collect_runtime_info()

    assert result["git_sha"] == "embedded-sha"
    assert result["build_time"] == "2026-07-28T09:00:00+00:00"
