from __future__ import annotations

import json

from paperfetch.cli import run
from paperfetch.workflows.contracts import HostProfile, attach_content_digest


def _host_profile(tmp_path):
    env_root = tmp_path / "envs"
    data_root = tmp_path / "data"
    env_root.mkdir()
    data_root.mkdir()
    payload = attach_content_digest(
        {
            "schema_version": "spc.host-profile.v1",
            "host_id": "host:test-linux",
            "platform": "linux-x86_64",
            "conda_executable": str(tmp_path / "conda"),
            "allowed_environment_roots": [str(env_root)],
            "allowed_data_roots": [str(data_root)],
            "catalog_root": str(data_root / "catalog"),
            "environment_mappings": {
                "environment:npj-gene-r@1": str(env_root / "npj-gene-r"),
                "environment:npj-gene-py@1": str(env_root / "npj-gene-py"),
            },
            "dataset_mappings": {},
        }
    )
    HostProfile.model_validate(payload)
    path = tmp_path / "host-profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_workflow_check_and_status_cli_emit_machine_contract(tmp_path, capsys):
    profile = _host_profile(tmp_path)
    report = tmp_path / "workflow_ready.json"

    code = run(
        [
            "workflow",
            "check",
            "workflow:npj-gene.glioma@provisional-1",
            "--host-profile",
            str(profile),
            "--report-file",
            str(report),
            "--output-format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["schema"] == "spc.result.v2"
    assert payload["status"] == "failed"
    assert payload["data"]["resource_status"] == "blocked"
    assert report.is_file()
    assert "ENVIRONMENT_NOT_INSTALLED" in {
        item["code"] for item in payload["data"]["blockers"]
    }

    status_code = run(
        [
            "workflow",
            "status",
            "--report-file",
            str(report),
            "--max-age-seconds",
            "3600",
            "--output-format",
            "json",
        ]
    )
    status = json.loads(capsys.readouterr().out)

    assert status_code == 2
    assert status["data"]["status_observation"]["stale"] is False


def test_workflow_status_rejects_tampered_report(tmp_path, capsys):
    profile = _host_profile(tmp_path)
    report = tmp_path / "workflow_ready.json"
    run(
        [
            "workflow",
            "check",
            "workflow:npj-gene.glioma@provisional-1",
            "--host-profile",
            str(profile),
            "--report-file",
            str(report),
            "--output-format",
            "json",
        ]
    )
    capsys.readouterr()
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["resource_status"] = "ready"
    report.write_text(json.dumps(payload), encoding="utf-8")

    code = run(
        [
            "workflow",
            "status",
            "--report-file",
            str(report),
            "--output-format",
            "json",
        ]
    )
    error = json.loads(capsys.readouterr().out)

    assert code == 4
    assert error["error"]["code"] == "workflow_contract_invalid"
    assert "content_digest 不一致" in error["error"]["message"]


def test_workflow_prepare_cli_rejects_invalid_size_gate_before_network(
    tmp_path, capsys
):
    profile = _host_profile(tmp_path)

    code = run(
        [
            "workflow",
            "prepare",
            "workflow:npj-gene.glioma@provisional-1",
            "--host-profile",
            str(profile),
            "--max-size-gb",
            "0",
            "--output-format",
            "json",
        ]
    )
    error = json.loads(capsys.readouterr().out)

    assert code == 1
    assert error["schema"] == "spc.result.v2"
    assert error["error"]["code"] == "invalid_workflow_argument"
    assert "max_download_gb 必须大于 0" in error["error"]["message"]


def test_workflow_prepare_cli_validates_coordination_limits(tmp_path, capsys):
    profile = _host_profile(tmp_path)

    for option, value, expected in (
        ("--dataset-concurrency", "5", "数据集并发数必须在 1 到 4 之间"),
        ("--lock-timeout-seconds", "0", "数据集锁等待时间必须大于 0 秒"),
    ):
        code = run(
            [
                "workflow",
                "prepare",
                "workflow:npj-gene.glioma@provisional-1",
                "--host-profile",
                str(profile),
                option,
                value,
                "--output-format",
                "json",
            ]
        )
        error = json.loads(capsys.readouterr().out)
        assert code == 1
        assert expected in error["error"]["message"]


def test_workflow_environment_lock_matches_and_writes_lock_file(
    tmp_path,
    capsys,
    monkeypatch,
):
    profile = _host_profile(tmp_path)
    (tmp_path / "conda").write_text("test", encoding="utf-8")
    (tmp_path / "envs" / "npj-gene-r").mkdir()
    lock_payload = {
        "schema_version": "spc.conda-environment-lock.v1",
        "packages": [
            {
                "name": "r-base",
                "version": "4.3.3",
                "build_number": 0,
                "build_string": "h123_0",
                "channel": "conda-forge",
                "platform": "linux-64",
            }
        ],
    }
    expected_digest = (
        "sha256:bcaddc2c0e3aa04b76a8b7ada6d50a59c92530b27ca16eb18ead9e077e9df296"
    )
    monkeypatch.setattr(
        "paperfetch.cli.workflow.inspect_conda_environment",
        lambda executable, prefix: (lock_payload, expected_digest),
    )
    lock_file = tmp_path / "locks" / "npj-gene-r.lock.json"

    code = run(
        [
            "workflow",
            "environment-lock",
            "environment:npj-gene-r@1",
            "--host-profile",
            str(profile),
            "--lock-file",
            str(lock_file),
            "--output-format",
            "json",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["status"] == "completed"
    assert report["data"]["matches_definition"] is True
    assert report["data"]["lock_digest"] == expected_digest
    assert report["data"]["package_count"] == 1
    assert json.loads(lock_file.read_text(encoding="utf-8")) == lock_payload
    assert list(lock_file.parent.glob(f".{lock_file.name}.*.tmp")) == []


def test_workflow_environment_lock_digest_mismatch_returns_two(
    tmp_path,
    capsys,
    monkeypatch,
):
    profile = _host_profile(tmp_path)
    (tmp_path / "conda").write_text("test", encoding="utf-8")
    (tmp_path / "envs" / "npj-gene-py").mkdir()
    actual_digest = "sha256:" + "0" * 64
    monkeypatch.setattr(
        "paperfetch.cli.workflow.inspect_conda_environment",
        lambda executable, prefix: (
            {"schema_version": "spc.conda-environment-lock.v1", "packages": []},
            actual_digest,
        ),
    )

    code = run(
        [
            "workflow",
            "environment-lock",
            "environment:npj-gene-py@1",
            "--host-profile",
            str(profile),
            "--output-format",
            "json",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 2
    assert report["status"] == "failed"
    assert report["data"]["matches_definition"] is False
    assert report["data"]["lock_digest"] == actual_digest
    assert report["error"]["code"] == "environment_lock_mismatch"


def test_workflow_environment_lock_rejects_external_managed(tmp_path, capsys):
    profile = _host_profile(tmp_path)

    code = run(
        [
            "workflow",
            "environment-lock",
            "environment:npj-gene-geneformer@provisional-1",
            "--host-profile",
            str(profile),
            "--output-format",
            "json",
        ]
    )
    error = json.loads(capsys.readouterr().out)

    assert code == 1
    assert error["schema"] == "spc.result.v2"
    assert "environment-lock仅支持Conda环境" in error["error"]["message"]
