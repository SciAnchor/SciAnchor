"""SPC 1.0 `seed-pack enrich` 原子状态与部分成功契约。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperfetch import jobs
from paperfetch.fulltext.workflow import PaperFileOutcome, PaperFileWorkflow
from paperfetch.artifacts.models import ArtifactProducer
from paperfetch.artifacts.store import materialize_artifact
from paperfetch.cli.root import main
from paperfetch.core.contracts_v1 import ErrorInfo
from paperfetch.papers.models import (
    BibliographicMetadata,
    FieldProvenance,
    IdentifierSet,
    IdentityVerification,
    MetadataProvenance,
    PaperRecord,
    SourceSnapshot,
    new_paper_id,
)
from paperfetch.seedpacks.repository import SeedPackRepository


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def _paper() -> PaperRecord:
    now = datetime.now(timezone.utc)
    return PaperRecord(
        paper_id=new_paper_id(),
        identifiers=IdentifierSet(doi="10.1000/example"),
        bibliographic=BibliographicMetadata(title="Example article"),
        provenance=MetadataProvenance(
            sources=[SourceSnapshot(source_id="src-1", source="test")],
            fields=[
                FieldProvenance(field="identifiers.doi", source_ids=["src-1"]),
                FieldProvenance(field="bibliographic.title", source_ids=["src-1"]),
            ],
        ),
        created_at=now,
        updated_at=now,
    )


def _pdf_pointer(
    repository: SeedPackRepository, paper: PaperRecord, tmp_path: Path, make_pdf_bytes
):
    source = tmp_path / "source.pdf"
    source.write_bytes(
        make_pdf_bytes(title=paper.bibliographic.title, doi=paper.identifiers.doi)
    )
    return materialize_artifact(
        repository.root,
        paper_id=paper.paper_id,
        kind="paper_pdf",
        files={"article_pdf": source},
        producer=ArtifactProducer(name="test"),
    )


def test_pdf_success_parse_failure_is_partial_and_persisted(
    monkeypatch, tmp_path: Path, make_pdf_bytes, capsys
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    pdf = _pdf_pointer(repository, paper, tmp_path, make_pdf_bytes)
    parse_error = ErrorInfo(
        code="artifact_tls_error",
        error_class="artifact_tls_error",
        stage="artifact_download",
        retryable=True,
        message="MinerU 正文 ZIP 下载失败",
    )

    async def fake_run(_self, **kwargs):
        return PaperFileOutcome(
            paper_id=paper.paper_id,
            pdf=pdf,
            identity=IdentityVerification(
                method="doi",
                target=paper.identifiers.doi,
                observed=paper.identifiers.doi,
            ),
            fulltext=None,
            successful_route="europe_pmc",
            attempted=(
                {"route": "europe_pmc", "outcome": "succeeded", "error_class": None},
            ),
            pdf_error=None,
            parse_error=parse_error,
            audit_refs=(".spc/audit/example/mineru-parse.json",),
        )

    monkeypatch.setattr(PaperFileWorkflow, "run", fake_run)
    assert (
        main(
            [
                "seed-pack",
                "enrich",
                "--seed-pack",
                str(repository.root),
                "--doi",
                paper.identifiers.doi,
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "partial"
    assert result["error"]["code"] == "artifact_tls_error"
    assert result["files"][0]["sha256"]
    assert result["files"][0]["size"] > 0
    [persisted] = repository.load().papers
    assert persisted.fulltext.pdf.status == "available"
    assert persisted.fulltext.parse.status == "failed"
    assert result["data"]["download"] == {
        "route": "europe_pmc",
        "access": "public",
        "identity_verified": True,
    }
    assert persisted.fulltext.pdf.route == "europe_pmc"


def test_parse_only_without_verified_pdf_rejects_before_workflow(
    monkeypatch, tmp_path: Path, capsys
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    before = repository.papers_path.read_bytes()

    async def forbidden(_self, **_kwargs):
        raise AssertionError("workflow must not run")

    monkeypatch.setattr(PaperFileWorkflow, "run", forbidden)
    assert (
        main(
            [
                "seed-pack",
                "enrich",
                "--seed-pack",
                str(repository.root),
                "--doi",
                paper.identifiers.doi,
                "--parse-only",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["error"]["code"] == "verified_pdf_required"
    assert repository.papers_path.read_bytes() == before


def test_completed_record_is_skipped_without_revision_change(
    tmp_path: Path, make_pdf_bytes, capsys
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    pdf = _pdf_pointer(repository, paper, tmp_path, make_pdf_bytes)
    layout = tmp_path / "layout.json"
    layout.write_text("{}", encoding="utf-8")
    content = tmp_path / "content.json"
    content.write_text("[]", encoding="utf-8")
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    md = tmp_path / "full.md"
    md.write_text("# Example", encoding="utf-8")
    archive = tmp_path / "raw.zip"
    archive.write_bytes(b"PK")
    fulltext = materialize_artifact(
        repository.root,
        paper_id=paper.paper_id,
        kind="mineru_fulltext",
        files={
            "document_markdown": (md, "document.md"),
            "layout": (layout, "layout.json"),
            "content_list": (content, "content-list.json"),
            "model": (model, "model.json"),
            "raw_archive": (archive, "raw/mineru-result.zip"),
        },
        producer=ArtifactProducer(name="mineru"),
        source_artifact_id=pdf.artifact_id,
    )
    from paperfetch.papers.models import FulltextState, ParseTerminal, PdfTerminal

    ready = paper.model_copy(
        update={
            "revision": 2,
            "updated_at": datetime.now(timezone.utc),
            "fulltext": FulltextState(
                pdf=PdfTerminal(
                    status="available",
                    artifact=pdf,
                    identity=IdentityVerification(
                        method="doi",
                        target=paper.identifiers.doi,
                        observed=paper.identifiers.doi,
                    ),
                ),
                parse=ParseTerminal(status="available", artifact=fulltext),
            ),
        }
    )
    repository.replace([PaperRecord.model_validate(ready.model_dump())])
    assert (
        main(
            [
                "seed-pack",
                "enrich",
                "--seed-pack",
                str(repository.root),
                "--doi",
                paper.identifiers.doi,
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert repository.load().papers[0].revision == 2


def test_detached_enrich_result_projects_reloaded_pdf_and_markdown_files(
    monkeypatch, tmp_path: Path, make_pdf_bytes
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    pdf = _pdf_pointer(repository, paper, tmp_path, make_pdf_bytes)
    layout = tmp_path / "layout.json"
    layout.write_text("{}", encoding="utf-8")
    content = tmp_path / "content.json"
    content.write_text("[]", encoding="utf-8")
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    markdown = tmp_path / "full.md"
    markdown.write_text("# Example", encoding="utf-8")
    archive = tmp_path / "raw.zip"
    archive.write_bytes(b"PK")
    fulltext = materialize_artifact(
        repository.root,
        paper_id=paper.paper_id,
        kind="mineru_fulltext",
        files={
            "document_markdown": (markdown, "document.md"),
            "layout": (layout, "layout.json"),
            "content_list": (content, "content-list.json"),
            "model": (model, "model.json"),
            "raw_archive": (archive, "raw/mineru-result.zip"),
        },
        producer=ArtifactProducer(name="mineru"),
        source_artifact_id=pdf.artifact_id,
    )

    async def fake_run(_self, **_kwargs):
        return PaperFileOutcome(
            paper_id=paper.paper_id,
            pdf=pdf,
            identity=IdentityVerification(
                method="doi",
                target=paper.identifiers.doi,
                observed=paper.identifiers.doi,
            ),
            fulltext=fulltext,
            successful_route="europe_pmc",
            attempted=(
                {"route": "europe_pmc", "outcome": "succeeded", "error_class": None},
            ),
            pdf_error=None,
            parse_error=None,
            audit_refs=(".spc/audit/example/mineru-parse.json",),
        )

    monkeypatch.setattr(PaperFileWorkflow, "run", fake_run)
    monkeypatch.setenv("SPC_JOB_ROOT", str(tmp_path / "jobs"))

    class FakeProcess:
        pid = 4321

    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    state = jobs.detach(
        [
            "seed-pack",
            "enrich",
            "--seed-pack",
            str(repository.root),
            "--doi",
            paper.identifiers.doi,
            "--detach",
            "--output-format",
            "json",
        ],
        cwd=str(tmp_path),
    )
    assert jobs._worker(state["job_id"]) == 0
    result = jobs.result(state["job_id"])
    [persisted] = repository.load().papers

    assert result["status"] == "completed"
    assert result["job_id"] == state["job_id"]
    assert result["items"][0]["data"]["fulltext"] == {
        "pdf_status": "available",
        "pdf_identity_verified": True,
        "pdf_identity_method": "doi",
        "pdf_route": "europe_pmc",
        "parse_status": "available",
    }
    assert result["items"][0]["data"]["download"]["route"] == "europe_pmc"
    assert {item["kind"] for item in result["items"][0]["artifacts"]} == {
        "paper_pdf",
        "mineru_fulltext",
    }
    assert all(Path(item["path"]).is_file() for item in result["items"][0]["artifacts"])
    assert all(
        item["sha256"] and item["size_bytes"] > 0
        for item in result["items"][0]["artifacts"]
    )
    assert result["artifacts"] == []
    assert result["items"][0]["data"][
        "identifiers"
    ] == persisted.identifiers.model_dump(mode="json", exclude_none=True)
    assert not (tmp_path / "jobs" / state["job_id"] / "stdout.txt").exists()
