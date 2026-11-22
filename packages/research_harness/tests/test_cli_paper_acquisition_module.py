"""Shape-lock tests for the split CLI paper acquisition module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_paper_acquisition import (
    register,
    register_acquisition,
    register_ingest,
    register_metadata,
)


def test_cli_paper_acquisition_module_exports_register_functions() -> None:
    assert callable(register)
    assert callable(register_ingest)
    assert callable(register_metadata)
    assert callable(register_acquisition)
    paper_group = main.commands["paper"]
    for command in (
        "ingest",
        "enrich",
        "backfill-metadata",
        "backfill-pubmed",
        "acquire",
        "parse-mineru",
        "ingest-manual",
        "resolve-pdfs",
        "pmc-links",
        "audit-pdfs",
    ):
        assert command in paper_group.commands


def test_paper_acquisition_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        ("ingest",): ["--arxiv-id", "--pmid", "--topic", "--dry-run"],
        ("enrich",): ["PAPER_ID", "--topic", "--with-s2", "--missing"],
        ("backfill-metadata",): ["--missing", "--limit", "--dry-run"],
        ("backfill-pubmed",): ["--topic", "--limit", "--dry-run"],
        ("acquire",): ["TOPIC_ID", "--download-dir", "--artifacts-root"],
        ("parse-mineru",): ["--topic", "--paper-id", "--dry-run"],
        ("ingest-manual",): ["--manual-dir", "--artifacts-root"],
        ("resolve-pdfs",): ["--topic", "--dry-run"],
        ("pmc-links",): ["--topic"],
        ("audit-pdfs",): ["--topic"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["paper", *command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_parse_mineru_dry_run_reports_topic_pdfs(tmp_path) -> None:
    runner = CliRunner()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nbody")

    runner.invoke(main, ["topic", "init", "mineru-topic"])
    ingest = runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "MinerU Paper",
            "--pdf-path",
            str(pdf_path),
            "--topic",
            "mineru-topic",
        ],
    )
    assert ingest.exit_code == 0, ingest.output

    result = runner.invoke(
        main,
        [
            "--json",
            "paper",
            "parse-mineru",
            "--topic",
            "mineru-topic",
            "--dry-run",
            "--artifacts-root",
            str(tmp_path / "mineru"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["processed"] >= 1
    assert payload["skipped"] >= 1
    matching = [
        item for item in payload["results"] if Path(item["pdf_path"]) == pdf_path
    ]
    assert matching
    assert matching[0]["status"] == "would_parse"


def test_paper_acquisition_commands_keep_existing_registration_order() -> None:
    paper_commands = list(main.commands["paper"].commands)

    assert paper_commands.index("ingest") < paper_commands.index("list")
    assert paper_commands.index("update") < paper_commands.index("enrich")
    assert paper_commands.index("enrich") < paper_commands.index("backfill-metadata")
    assert paper_commands.index("backfill-metadata") < paper_commands.index("link")
    assert paper_commands.index("card") < paper_commands.index("acquire")
    assert paper_commands.index("acquire") < paper_commands.index("parse-mineru")
    assert paper_commands.index("parse-mineru") < paper_commands.index("ingest-manual")
    assert paper_commands.index("ingest-manual") < paper_commands.index("resolve-pdfs")
    assert paper_commands.index("resolve-pdfs") < paper_commands.index("move")


@pytest.mark.parametrize(
    "operation", ["ingest", "enrich", "backfill-metadata", "backfill-pubmed"]
)
def test_public_metadata_commands_fail_for_managed_source_errors(
    db, monkeypatch, operation
):
    from research_harness.acquisition.spc_bridge import SPCAcquisitionError
    from research_harness.core.paper_pool import PaperPool
    from research_harness.storage.models import Paper
    from research_harness import cli_paper_acquisition

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.path))
    conn = db.connect()
    try:
        pid = PaperPool(conn).ingest(Paper(title="Managed paper", doi="10.1234/fault"))
    finally:
        conn.close()

    def fail(*a, **k):
        raise SPCAcquisitionError(
            "lookup", {"error": {"code": "rate_limited", "retryable": True}}
        )

    monkeypatch.setattr(PaperPool, "enrich_metadata", fail)

    class FailedProvider:
        fetch_by_doi = fail
        fetch_by_pmid = fail

    monkeypatch.setattr(
        cli_paper_acquisition, "_pubmed_provider", lambda: FailedProvider()
    )
    args = {
        "ingest": ["--doi", "10.1234/fault"],
        "enrich": [str(pid), "--with-s2"],
        "backfill-metadata": ["--limit", "1"],
        "backfill-pubmed": ["--limit", "1"],
    }[operation]
    result = CliRunner().invoke(main, ["paper", operation, *args])
    assert result.exit_code != 0, result.output
    assert "rate_limited" in result.output
