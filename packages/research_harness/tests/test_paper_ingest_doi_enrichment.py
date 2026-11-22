"""C-48: `rh paper ingest --doi` wrote an empty row (title '', authors [], year NULL).

paper_ingest never called enrich_metadata; the real pool holds 63 DOI rows with no title.
The enrichment providers are stubbed here (network enrichment is `needs_network`).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.core.paper_pool import PaperPool
from research_harness.storage.db import Database


def _ingest(tmp_path, *args):
    db_path = tmp_path / "rh.db"
    runner = CliRunner()
    assert (
        runner.invoke(main, ["--db", str(db_path), "topic", "init", "demo"]).exit_code
        == 0
    )
    result = runner.invoke(
        main,
        ["--db", str(db_path), "--json", "paper", "ingest", *args, "--topic", "demo"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    conn = Database(db_path).connect()
    row = conn.execute(
        "SELECT title, authors, year FROM papers WHERE id = ?", (payload["paper_id"],)
    ).fetchone()
    conn.close()
    return payload, row


def test_a_doi_alone_is_resolved_into_a_titled_row(tmp_path, monkeypatch):
    from research_harness import paper_source_clients
    from research_harness.paper_sources import PaperRecord

    class ManagedProvider:
        name = "spc"

        def search(self, query):
            assert query.query == "10.1234/demo"
            return [
                PaperRecord(
                    title="A Resolved Title",
                    doi="10.1234/demo",
                    authors=["Ada Lovelace"],
                    year=2024,
                )
            ]

    monkeypatch.setattr(
        paper_source_clients, "build_provider_suite", lambda: [ManagedProvider()]
    )
    payload, row = _ingest(tmp_path, "--doi", "10.1234/demo")
    assert (
        payload["title"] == "A Resolved Title"
        and payload["metadata_enrichment"]["title"] == "A Resolved Title"
    )
    assert (row["title"], json.loads(row["authors"]), row["year"]) == (
        "A Resolved Title",
        ["Ada Lovelace"],
        2024,
    )


def test_an_unreachable_resolver_is_reported_not_fatal(tmp_path, monkeypatch):
    def down(self, paper_id):
        raise OSError("provider unreachable")

    monkeypatch.setattr(PaperPool, "enrich_metadata", down)
    payload, row = _ingest(tmp_path, "--doi", "10.1234/demo")
    assert "provider unreachable" in payload["metadata_enrichment"]["error"]


def test_a_given_title_is_not_looked_up(tmp_path, monkeypatch):
    monkeypatch.setattr(
        PaperPool,
        "enrich_metadata",
        lambda self, paper_id: (_ for _ in ()).throw(AssertionError),
    )
    payload, _ = _ingest(tmp_path, "--doi", "10.1234/demo", "--title", "Given")
    assert payload["metadata_enrichment"] == {}


def test_pubmed_fetch_by_doi_refuses_a_record_for_another_doi(monkeypatch):
    """Review: the fuzzy [AID] search's first record was returned whatever its DOI, and the ingest
    now reaches it: another paper's title and authors would land in this row."""
    from research_harness.paper_source_clients import PubMedProvider
    from research_harness.paper_sources import PaperRecord

    provider = PubMedProvider(api_key="", email="", tool="t")
    monkeypatch.setattr(provider, "_search_pmids", lambda query: ["1"])
    monkeypatch.setattr(
        provider,
        "_fetch_records",
        lambda ids: [PaperRecord(title="Another paper", doi="10.9999/other")],
    )
    assert provider.fetch_by_doi("10.1234/demo") is None
    monkeypatch.setattr(
        provider,
        "_fetch_records",
        lambda ids: [PaperRecord(title="This paper", doi="10.1234/DEMO")],
    )
    assert provider.fetch_by_doi("10.1234/demo").title == "This paper"


def test_a_pmid_without_a_title_is_enriched_too(tmp_path, monkeypatch):
    from research_harness.paper_sources import PaperRecord

    monkeypatch.setattr(
        "research_harness.cli_paper_acquisition._pubmed_provider",
        lambda: type(
            "P",
            (),
            {
                "fetch_by_pmid": staticmethod(
                    lambda pmid: PaperRecord(title="", pmid=pmid)
                )
            },
        )(),
    )
    calls = []
    monkeypatch.setattr(
        PaperPool,
        "enrich_metadata",
        lambda self, paper_id: calls.append(paper_id) or {},
    )
    _ingest(tmp_path, "--pmid", "12345678")
    assert calls
