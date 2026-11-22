"""SPC 1.0 `seed-pack` 的真实 parser/CLI 和 detached 结果。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperfetch import jobs
from paperfetch.cli.root import main
from paperfetch.papers.lookup import PaperLookupService
from paperfetch.papers.models import (
    BibliographicMetadata,
    FieldProvenance,
    IdentifierSet,
    MetadataProvenance,
    PaperRecord,
    SourceSnapshot,
    new_paper_id,
)
from paperfetch.seedpacks.repository import SeedPackRepository


pytestmark = [pytest.mark.contract, pytest.mark.integration]


def _record(doi: str = "10.1000/example") -> PaperRecord:
    now = datetime.now(timezone.utc)
    return PaperRecord(
        paper_id=new_paper_id(),
        identifiers=IdentifierSet(doi=doi),
        bibliographic=BibliographicMetadata(title="Example article"),
        provenance=MetadataProvenance(
            sources=[
                SourceSnapshot(source_id="crossref-1", source="crossref", record_id=doi)
            ],
            fields=[
                FieldProvenance(field="identifiers.doi", source_ids=["crossref-1"]),
                FieldProvenance(field="bibliographic.title", source_ids=["crossref-1"]),
            ],
        ),
        created_at=now,
        updated_at=now,
    )


def test_seed_pack_init_show_and_add_use_grouped_cli(
    monkeypatch, tmp_path: Path, capsys
):
    root = tmp_path / "pack"
    assert (
        main(
            [
                "seed-pack",
                "init",
                "--seed-pack",
                str(root),
                "--name",
                "Test",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["schema"] == "spc.result.v2"
    assert initialized["data"]["paper_count"] == 0

    async def fake_lookup(_self, _request):
        return _record()

    monkeypatch.setattr(PaperLookupService, "lookup", fake_lookup)
    assert (
        main(
            [
                "seed-pack",
                "add",
                "--seed-pack",
                str(root),
                "--doi",
                "10.1000/example",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["status"] == "completed"
    assert "legacy_output" not in json.dumps(added)
    [persisted] = SeedPackRepository(root).load().papers
    assert added["data"]["paper"]["doi"] == persisted.identifiers.doi

    assert (
        main(
            [
                "seed-pack",
                "show",
                "--seed-pack",
                str(root),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    data = status["data"]
    assert data["paper_count"] == 1
    assert data["verified_pdf_count"] == 0
    assert data["mineru_markdown_count"] == 0
    assert "artifact_count" not in data


def test_seed_pack_add_batch_failure_is_zero_write(monkeypatch, tmp_path: Path, capsys):
    root = tmp_path / "pack"
    SeedPackRepository.initialize(root)

    async def fake_lookup(_self, request):
        if request.value == "10.1000/missing":
            from paperfetch.papers.lookup import PaperLookupError

            raise PaperLookupError(
                "metadata_not_resolved",
                "resource_not_found",
                "未找到论文",
                retryable=False,
            )
        return _record(request.value)

    monkeypatch.setattr(PaperLookupService, "lookup", fake_lookup)
    assert (
        main(
            [
                "seed-pack",
                "add",
                "--seed-pack",
                str(root),
                "--doi",
                "10.1000/one",
                "--doi",
                "10.1000/missing",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "atomic_metadata_batch_failed"
    assert all(item["status"] == "failed" for item in payload["results"])
    assert SeedPackRepository(root).load().papers == ()


def test_seed_pack_rejects_legacy_layout_via_real_cli(tmp_path: Path, capsys):
    root = tmp_path / "legacy"
    root.mkdir()
    (root / "seed_papers.jsonl").write_text("{}\n", encoding="utf-8")
    assert (
        main(
            [
                "seed-pack",
                "show",
                "--seed-pack",
                str(root),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "unsupported_legacy_seed_pack"


def test_detached_seed_pack_add_result_is_the_reloaded_fact_projection(
    monkeypatch, tmp_path: Path
):
    root = tmp_path / "pack"
    SeedPackRepository.initialize(root)
    monkeypatch.setenv("SPC_JOB_ROOT", str(tmp_path / "jobs"))

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    state = jobs.detach(
        [
            "seed-pack",
            "add",
            "--seed-pack",
            str(root),
            "--doi",
            "10.1000/example",
            "--detach",
            "--output-format",
            "json",
        ],
        cwd=str(tmp_path),
    )

    async def fake_lookup(_self, _request):
        return _record()

    monkeypatch.setattr(PaperLookupService, "lookup", fake_lookup)
    assert jobs._worker(state["job_id"]) == 0
    result = jobs.result(state["job_id"])
    [persisted] = SeedPackRepository(root).load().papers
    assert result["schema_version"] == "spc.command-result.v1"
    assert result["job_id"] == state["job_id"]
    assert result["run_id"] == jobs._load_record(state["job_id"]).run_id
    assert result["items"][0]["data"]["paper_id"] == persisted.paper_id
    assert result["items"][0]["data"][
        "identifiers"
    ] == persisted.identifiers.model_dump(mode="json", exclude_none=True)
    assert "legacy_output" not in json.dumps(result)
