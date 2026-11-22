from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from paperfetch.workflows.contracts import ContractError
from paperfetch.workflows.environment_identity import (
    conda_lock_digest,
    inspect_conda_environment,
    normalize_conda_packages,
)


def _packages(base_url: str = "https://mirror.example.invalid/conda-forge"):
    return [
        {
            "base_url": base_url,
            "build_number": 0,
            "build_string": "py311_0",
            "channel": "conda-forge",
            "dist_name": "demo-1.0-py311_0",
            "name": "demo",
            "platform": "linux-64",
            "version": "1.0",
        },
        {
            "base_url": "https://conda.anaconda.org/pypi",
            "build_number": 0,
            "build_string": "pypi_0",
            "channel": "pypi",
            "dist_name": "addon-2.0-pypi_0",
            "name": "addon",
            "platform": "pypi",
            "version": "2.0",
        },
    ]


def test_conda_lock_digest_is_order_and_mirror_independent():
    first = _packages()
    second = list(reversed(_packages("https://another.example.invalid/conda-forge")))

    assert conda_lock_digest(first) == conda_lock_digest(second)
    assert [item["name"] for item in normalize_conda_packages(first)] == [
        "addon",
        "demo",
    ]


def test_conda_lock_rejects_incomplete_records():
    with pytest.raises(ContractError, match="缺少字段"):
        normalize_conda_packages([{"name": "demo"}])


def test_conda_lock_rejects_invalid_identity_field_types():
    packages = _packages()
    packages[0]["build_number"] = True

    with pytest.raises(ContractError, match="无效字段类型"):
        normalize_conda_packages(packages)


def test_conda_lock_sort_uses_every_identity_field():
    packages = _packages()
    duplicate = dict(packages[0])
    duplicate["build_number"] = 1
    packages.append(duplicate)

    normalized = normalize_conda_packages(list(reversed(packages)))
    demo_builds = [
        item["build_number"] for item in normalized if item["name"] == "demo"
    ]

    assert demo_builds == [0, 1]


def test_inspect_conda_environment_uses_typed_argv(tmp_path, monkeypatch):
    conda = tmp_path / "conda.exe"
    conda.write_text("placeholder", encoding="utf-8")
    prefix = tmp_path / "env"
    prefix.mkdir()
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=json.dumps(_packages()), stderr="")

    monkeypatch.setattr(
        "paperfetch.workflows.environment_identity.subprocess.run",
        fake_run,
    )

    payload, digest = inspect_conda_environment(conda, prefix)

    assert observed["argv"] == [
        str(conda.resolve()),
        "list",
        "--json",
        "--prefix",
        str(prefix.resolve()),
    ]
    assert observed["kwargs"]["timeout"] == 60.0
    assert payload["schema_version"] == "spc.conda-environment-lock.v1"
    assert digest == conda_lock_digest(_packages())
