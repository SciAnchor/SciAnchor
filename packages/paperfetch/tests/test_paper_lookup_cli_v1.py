"""SPC 1.0 `paper lookup` 的真实 parser/CLI 契约。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from paperfetch.cli.root import main
from paperfetch.papers.lookup import LookupRequest, PaperLookupError, PaperLookupService
from paperfetch.papers.models import (
    BibliographicMetadata,
    FieldProvenance,
    IdentifierSet,
    MetadataProvenance,
    PaperRecord,
    SourceSnapshot,
    new_paper_id,
)


pytestmark = [pytest.mark.contract, pytest.mark.integration]


def _record() -> PaperRecord:
    now = datetime.now(timezone.utc)
    return PaperRecord(
        paper_id=new_paper_id(),
        identifiers=IdentifierSet(
            doi="10.3390/curroncol29090518",
            pubmed_id="36135087",
            pmc_id="PMC9498154",
        ),
        bibliographic=BibliographicMetadata(
            title="Example biomedical article",
            paper_type="journal_article",
            publication_date="2022-09-14",
        ),
        provenance=MetadataProvenance(
            sources=[
                SourceSnapshot(
                    source_id="europe-pmc-1",
                    source="europe_pmc",
                    record_id="PMC9498154",
                    payload_sha256="a" * 64,
                )
            ],
            fields=[
                FieldProvenance(field="identifiers.doi", source_ids=["europe-pmc-1"]),
                FieldProvenance(
                    field="identifiers.pubmed_id", source_ids=["europe-pmc-1"]
                ),
                FieldProvenance(
                    field="identifiers.pmc_id", source_ids=["europe-pmc-1"]
                ),
                FieldProvenance(
                    field="bibliographic.title", source_ids=["europe-pmc-1"]
                ),
            ],
        ),
        created_at=now,
        updated_at=now,
    )


def test_paper_lookup_outputs_compact_v2_result(monkeypatch, capsys):
    async def fake_lookup(_self, request):
        assert request == LookupRequest(
            identifier_type="doi", value="10.3390/curroncol29090518"
        )
        return _record()

    monkeypatch.setattr(PaperLookupService, "lookup", fake_lookup)
    assert (
        main(
            [
                "paper",
                "lookup",
                "--doi",
                "10.3390/curroncol29090518",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "spc.result.v2"
    assert payload["status"] == "completed"
    paper = payload["data"]["paper"]
    assert {key: paper[key] for key in ("doi", "pubmed_id", "pmc_id")} == {
        "doi": "10.3390/curroncol29090518",
        "pubmed_id": "36135087",
        "pmc_id": "PMC9498154",
    }
    assert paper["title"] == "Example biomedical article"
    assert "download" not in paper
    serialized = json.dumps(payload)
    assert "legacy_output" not in serialized
    assert "pdf_candidates" not in serialized
    assert "available_files" not in serialized
    assert "payload_sha256" not in serialized
    assert "field_sources" not in serialized
    assert "metadata_transport" not in serialized


def test_paper_lookup_supports_detached_reliable_wait(monkeypatch, capsys):
    captured = {}

    def fake_detach(arguments, *, cwd):
        captured["arguments"] = arguments
        captured["cwd"] = cwd
        return {
            "schema_version": "spc.job.v1",
            "job_id": "a" * 32,
            "command": "paper.lookup",
            "lifecycle": "queued",
            "command_ref": "/tmp/command.json",
            "event_ref": "/tmp/events.jsonl",
            "stderr_ref": "/tmp/stderr.log",
        }

    monkeypatch.setattr("paperfetch.jobs.detach", fake_detach)
    assert (
        main(
            [
                "paper",
                "lookup",
                "--doi",
                "10.1000/reliable",
                "--detach",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["job_id"] == "a" * 32
    assert captured["arguments"][:3] == ["paper", "lookup", "--doi"]


def test_paper_lookup_has_one_stable_error(monkeypatch, capsys):
    async def fake_lookup(_self, _request):
        raise PaperLookupError(
            "metadata_not_resolved",
            "resource_not_found",
            "官方元数据源未找到该论文标识",
            retryable=False,
        )

    monkeypatch.setattr(PaperLookupService, "lookup", fake_lookup)
    assert (
        main(
            [
                "paper",
                "lookup",
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
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "metadata_not_resolved"
    assert "primary_failure_class" not in json.dumps(payload)


def test_paper_download_metadata_failure_does_not_create_output_directory(
    monkeypatch, tmp_path, capsys
):
    async def fake_lookup(_self, _request):
        raise PaperLookupError(
            "metadata_not_resolved",
            "resource_not_found",
            "官方元数据源未找到该论文标识",
            retryable=False,
        )

    output_dir = tmp_path / "single-paper"
    monkeypatch.setattr(PaperLookupService, "lookup", fake_lookup)
    assert (
        main(
            [
                "paper",
                "download",
                "--doi",
                "10.1000/missing",
                "--output-dir",
                str(output_dir),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "metadata_not_resolved"
    assert not output_dir.exists()


@pytest.mark.asyncio
async def test_metadata_lookup_fuses_europe_pmc_and_crossref_without_route_payloads():
    responses = {
        "europepmc": {
            "resultList": {
                "result": [
                    {
                        "doi": "10.3390/curroncol29090518",
                        "pmid": "36135087",
                        "pmcid": "PMC9498154",
                        "title": "Example biomedical article",
                        "pubYear": "2022",
                        "journalTitle": "Current Oncology",
                        "authorList": {
                            "author": [
                                {
                                    "fullName": "Ada Example",
                                    "lastName": "Example",
                                    "firstName": "Ada",
                                }
                            ]
                        },
                    }
                ]
            },
        },
        "crossref": {
            "message": {
                "DOI": "10.3390/curroncol29090518",
                "title": ["Example biomedical article"],
                "type": "journal-article",
                "publisher": "MDPI AG",
                "container-title": ["Current Oncology"],
                "published": {"date-parts": [[2022, 9, 14]]},
                "author": [{"given": "Ada", "family": "Example"}],
            },
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ebi.ac.uk":
            return httpx.Response(200, json=responses["europepmc"])
        return httpx.Response(200, json=responses["crossref"])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        record = await PaperLookupService(client).lookup(
            LookupRequest.normalize("doi", "10.3390/curroncol29090518")
        )
    assert record.identifiers.pubmed_id == "36135087"
    assert record.identifiers.pmc_id == "PMC9498154"
    assert record.bibliographic.publisher == "MDPI AG"
    assert record.bibliographic.paper_type == "journal_article"
    assert {item.source for item in record.provenance.sources} == {
        "europe_pmc",
        "crossref",
    }
    assert "bibliographic.publisher" in {
        item.field for item in record.provenance.fields
    }


_ARXIV_ATOM = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T17:57:34Z</published>
    <summary>The dominant sequence transduction models...</summary>
    <author><name>Ashish Vaswani</name></author>
  </entry>
</feed>"""


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", ["1706.03762", "1706.03762v7", "1706.03762v3"])
async def test_arxiv_lookup_matches_across_versions_and_keeps_requested_id(requested):
    # The arXiv API always answers with the versioned entry id (here v7).
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "export.arxiv.org"
        return httpx.Response(200, text=_ARXIV_ATOM)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        record = await PaperLookupService(client).lookup(
            LookupRequest.normalize("arxiv_id", requested)
        )
    assert record.bibliographic.title == "Attention Is All You Need"
    assert record.identifiers.arxiv_id == requested


@pytest.mark.asyncio
async def test_arxiv_lookup_still_rejects_a_different_paper():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_ARXIV_ATOM)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PaperLookupError) as caught:
            await PaperLookupService(client).lookup(
                LookupRequest.normalize("arxiv_id", "1706.03763")
            )
    assert caught.value.code == "metadata_not_resolved"


@pytest.mark.asyncio
async def test_explicit_not_found_is_not_misclassified_as_network_error():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PaperLookupError) as caught:
            await PaperLookupService(client).lookup(
                LookupRequest.normalize("doi", "10.1000/missing")
            )
    assert caught.value.code == "metadata_not_resolved"
    assert caught.value.error_class == "resource_not_found"
