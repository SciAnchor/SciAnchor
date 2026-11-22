from __future__ import annotations

import json
import threading

from paperfetch.cli import datasets as dataset_cli
from paperfetch.cli import root as root_cli
from paperfetch.datasets.acquisition import AcquisitionBusy


def test_ncbi_validate_cli_dispatches_without_onboarding(monkeypatch):
    captured = {}

    def run(args):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr(dataset_cli, "run_ncbi_validate", run)
    assert (
        root_cli.main(
            [
                "dataset",
                "ncbi",
                "validate",
                "--accession",
                "NM_007294.4",
                "--requests-per-second",
                "2.5",
                "--output-format",
                "json",
            ]
        )
        == 0
    )
    assert captured["accession"] == "NM_007294.4"
    assert captured["requests_per_second"] == 2.5


def test_download_dryad_cli_reports_structured_auth_failure(
    monkeypatch, capsys, tmp_path
):
    class Store:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, *_args, **_kwargs):
            from paperfetch.datasets.dryad import DryadAuthenticationRequired

            raise DryadAuthenticationRequired("Dryad API 令牌需要刷新")

    monkeypatch.setattr(dataset_cli, "DryadDatasetStore", Store)
    code = root_cli.main(
        [
            "dataset",
            "dryad",
            "download",
            "10.5061/dryad.n02v6wx86",
            "--route",
            "api",
            "--output-dir",
            str(tmp_path),
            "--output-format",
            "json",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["error"]["code"] == "dryad_authentication_required"
    assert result["error"]["message"] == "Dryad API 令牌需要刷新"
    assert result["id"] == "10.5061/dryad.n02v6wx86"


def test_download_dryad_rejects_nonpositive_size_gate():
    assert (
        root_cli.main(
            [
                "dataset",
                "dryad",
                "download",
                "10.5061/dryad.n02v6wx86",
                "--max-size-gb",
                "0",
            ]
        )
        == 1
    )


def test_download_dryad_cli_processes_distinct_datasets_concurrently(
    monkeypatch,
    capsys,
    tmp_path,
):
    barrier = threading.Barrier(2)
    state = {"active": 0, "maximum": 0}
    lock = threading.Lock()

    class Store:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, doi, **_kwargs):
            with lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            barrier.wait(timeout=2)
            with lock:
                state["active"] -= 1
            return {
                "schema_version": "spc.dryad.command-result.v1",
                "doi": doi,
                "status": "complete",
                "route": "api",
                "files": {"complete": 1, "downloaded_bytes": 10},
            }

    monkeypatch.setattr(dataset_cli, "DryadDatasetStore", Store)
    dois = ["10.5061/dryad.n02v6wx86", "10.5061/dryad.abc123"]

    code = root_cli.main(
        [
            "dataset",
            "dryad",
            "download",
            *dois,
            "--dataset-concurrency",
            "2",
            "--output-dir",
            str(tmp_path),
            "--output-format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert state["maximum"] == 2
    assert [item["id"] for item in payload["results"]] == dois
    assert all(item["status"] == "completed" for item in payload["results"])


def test_download_dryad_cli_reports_resource_busy_with_stable_codes(
    monkeypatch,
    capsys,
    tmp_path,
):
    class Store:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def download(self, *_args, **_kwargs):
            raise AcquisitionBusy("资源正忙：数据集已由其他进程下载")

    monkeypatch.setattr(dataset_cli, "DryadDatasetStore", Store)

    code = root_cli.main(
        [
            "dataset",
            "dryad",
            "download",
            "10.5061/dryad.n02v6wx86",
            "--output-dir",
            str(tmp_path),
            "--output-format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]

    assert code == 3
    assert result["error"]["code"] == "resource_busy"
    assert result["error"]["message"].startswith("资源正忙")


def test_download_dryad_dry_run_preserves_requested_route(
    monkeypatch, capsys, tmp_path
):
    captured = {}

    class Store:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def plan(self, doi, filenames, *, route):
            captured.update({"doi": doi, "filenames": filenames, "route": route})
            return {
                "schema_version": "spc.dryad.plan.v1",
                "doi": doi,
                "totals": {"files": 1, "known_bytes": 10},
                "size_gate": {"blocked": False},
            }

    monkeypatch.setattr(dataset_cli, "DryadDatasetStore", Store)

    code = root_cli.main(
        [
            "dataset",
            "dryad",
            "download",
            "10.5061/dryad.n02v6wx86",
            "--route",
            "api",
            "--dry-run",
            "--output-dir",
            str(tmp_path),
            "--output-format",
            "json",
        ]
    )
    json.loads(capsys.readouterr().out)

    assert code == 0
    assert captured["route"] == "api"
