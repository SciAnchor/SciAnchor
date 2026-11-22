import json
from argparse import Namespace
from pathlib import Path

import pytest

from paperfetch.downloaders.pdf_common import PDFDownloadResult
from paperfetch.downloaders.validation import (
    ValidationGate,
    _load_suite,
    _select_samples,
    run_download_validation,
)
from paperfetch.cli.download_validation import (
    project_download_validation_result,
    run_download_validation_command,
)


def test_builtin_download_validation_suite_has_stable_profiles():
    suite = _load_suite(None)

    smoke = _select_samples(suite, profile="smoke", publishers=None, sample_ids=None)
    assert [item["id"] for item in smoke] == [
        "arxiv_attention",
        "plos_medical",
    ]
    biomedical_oa = _select_samples(
        suite,
        profile="biomedical_oa",
        publishers=None,
        sample_ids=None,
    )
    assert [item["id"] for item in biomedical_oa] == [
        "plos_medical",
        "frontiers_medical",
        "mdpi_medical",
    ]
    full = _select_samples(suite, profile="full", publishers=None, sample_ids=None)
    assert len(full) >= 4
    assert all(item.get("access") == "open" for item in full)


def test_download_validation_filters_publishers_and_samples():
    suite = _load_suite(None)

    selected = _select_samples(
        suite,
        profile="oa",
        publishers=["plos"],
        sample_ids=["plos_medical"],
    )

    assert [item["id"] for item in selected] == ["plos_medical"]


@pytest.mark.asyncio
async def test_download_validation_runs_isolated_rounds_and_enforces_gates(
    tmp_path, monkeypatch
):
    calls = []

    async def fake_download_many(self, papers):
        calls.append(str(self.cache.root))
        for paper in papers:
            status = paper.fulltext_status
            status.download_attempted = True
            status.download_status = "downloaded"
            status.successful_route = "public_http"
            status.magic_pdf = True
            status.identity_verified = True
            status.identity_status = "verified_doi"
            status.identity_confidence = "high"
            source = (
                "arxiv"
                if paper.arxiv_id
                else "plos_rule"
                if str(paper.doi).startswith("10.1371/")
                else "elsevier_api"
            )
            status.normalized_resources = [{"sources": [source]}]
            status.download_attempts = [
                {
                    "route": "public_http",
                    "duration_ms": 120,
                    "proxy_mode": "no-proxy",
                    "skipped": False,
                }
            ]
            status.verification = {"duration_ms": 5, "identity_verified": True}

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "paperfetch.downloaders.validation.PDFDownloadManager.download_many",
        fake_download_many,
    )
    monkeypatch.setattr(
        "paperfetch.downloaders.validation.PDFDownloadManager.close",
        fake_close,
    )

    report = await run_download_validation(
        profile="smoke",
        rounds=3,
        output_dir=str(tmp_path),
        gate=ValidationGate(maximum_phase1_p95_ms=500),
    )

    assert report["validation_ok"] is True
    assert report["passed"] == 6
    assert report["failed"] == 0
    assert report["performance"]["phase1_p95_ms"] == 120
    assert len(set(calls)) == 3
    assert all(f"round_{index}" in calls[index - 1] for index in range(1, 4))
    assert (tmp_path / "validation_report.json").exists()
    assert (tmp_path / "round_1" / "run_report.json").exists()


@pytest.mark.asyncio
async def test_download_validation_reports_identity_failure(tmp_path, monkeypatch):
    suite = {
        "suite_version": "paperfetch.download-suite.v1",
        "profiles": {"smoke": ["one"]},
        "samples": [
            {
                "id": "one",
                "doi": "10.1000/example",
                "title": "Expected title",
                "publisher": "Example",
                "expected_status": "downloaded",
            }
        ],
    }
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    async def fake_download_many(self, papers):
        status = papers[0].fulltext_status
        status.download_attempted = True
        status.download_status = "failed"
        status.failure_taxonomy = "metadata_poisoned"
        status.identity_status = "mismatch"

    async def fake_close(self):
        return None

    monkeypatch.setattr(
        "paperfetch.downloaders.validation.PDFDownloadManager.download_many",
        fake_download_many,
    )
    monkeypatch.setattr(
        "paperfetch.downloaders.validation.PDFDownloadManager.close",
        fake_close,
    )

    report = await run_download_validation(
        suite_path=str(suite_path),
        profile="smoke",
        rounds=1,
        output_dir=str(tmp_path / "out"),
    )

    assert report["validation_ok"] is False
    assert report["gate_failures"][0]["actual"] == "metadata_poisoned"


def test_pdf_download_result_initializes_diagnostics():
    result = PDFDownloadResult(path="paper.pdf", resolved_url=None, source="test")

    assert result.diagnostics == {}


def test_download_validation_projects_public_command_result(tmp_path):
    report_path = tmp_path / "validation_report.json"
    report = {
        "validation_ok": True,
        "success_rate": 1.0,
        "gate_failures": [],
        "performance": {
            "phase1_p50_ms": 100,
            "phase1_p95_ms": 120,
            "phase1_max_ms": 140,
        },
        "round_reports": [
            {
                "round": 1,
                "entries": [
                    {
                        "sample_id": "oa",
                        "doi": "10.1000/example",
                        "publisher": "example",
                        "expected_status": "downloaded",
                        "passed": True,
                        "actual": "downloaded",
                        "download_status": "downloaded",
                        "successful_route": "public_http",
                        "identity_verified": True,
                        "identity_status": "verified_doi",
                        "pdf_path": str(tmp_path / "paper.pdf"),
                        "pdf_size_bytes": 1234,
                        "pdf_sha256": "b" * 64,
                        "discovery_sources": ["official"],
                    }
                ],
            }
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = project_download_validation_result(
        report, output_dir=str(tmp_path), elapsed_ms=456
    ).model_dump(mode="json")

    assert result["schema_version"] == "spc.command-result.v1"
    assert result["command"] == "download.validate"
    assert result["status"] == "completed"
    assert result["summary"]["selected"] == 1
    assert result["items"][0]["data"]["successful_route"] == "public_http"
    assert result["items"][0]["data"]["download"]["route"] == "public_http"
    assert result["items"][0]["data"]["download"]["status"] == "available"
    assert result["items"][0]["artifacts"][0]["sha256"] == "b" * 64
    assert "browser_processes_remaining" not in result["metrics"]
    assert result["artifacts"][0]["kind"] == "validation_report"


def test_download_validation_gate_failure_is_stable_public_error(tmp_path):
    report = {
        "validation_ok": False,
        "success_rate": 0.0,
        "gate_failures": [{"gate": "success_rate"}],
        "performance": {},
        "round_reports": [
            {
                "round": 1,
                "entries": [
                    {
                        "sample_id": "failed",
                        "passed": False,
                        "actual": "timeout",
                        "download_status": "failed",
                    }
                ],
            }
        ],
    }
    (tmp_path / "validation_report.json").write_text("{}", encoding="utf-8")

    result = project_download_validation_result(
        report, output_dir=str(tmp_path), elapsed_ms=1
    )

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "download_validation_gate_failed"
    assert result.items[0].error is not None
    assert result.items[0].error.error_class == "timeout"


def test_download_validation_command_outputs_public_contract(
    tmp_path, monkeypatch, capsys
):
    async def fake_run(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True)
        report = {
            "validation_ok": True,
            "success_rate": 1.0,
            "gate_failures": [],
            "performance": {},
            "round_reports": [
                {
                    "round": 1,
                    "entries": [
                        {
                            "sample_id": "one",
                            "passed": True,
                            "actual": "downloaded",
                            "download_status": "downloaded",
                        }
                    ],
                }
            ],
        }
        (output / "validation_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return report

    monkeypatch.setattr(
        "paperfetch.cli.download_validation.run_download_validation",
        fake_run,
    )
    args = Namespace(
        suite=None,
        profile="smoke",
        rounds=1,
        output_dir=str(tmp_path / "out"),
        publisher=None,
        sample=None,
        minimum_success_rate=1.0,
        maximum_phase1_p95_ms=12500,
        maximum_phase1_paper_ms=47000,
        output_format="json",
    )

    exit_code = run_download_validation_command(args)
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["schema_version"] == "spc.command-result.v1"
    assert payload["command"] == "download.validate"
