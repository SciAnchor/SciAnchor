from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.paper_sources import PaperRecord
from research_harness.storage.db import Database


def _write_text_pdf(path: Path, text: str) -> None:
    """Write a tiny but well-formed single-page PDF whose page carries ``text``.

    Real extractors (PyMuPDF/pypdf/pdftotext) return nothing for a bare
    ``%PDF`` header followed by plain text, which would exercise the
    "no extractable PDF text" branch instead of the identity mismatch.
    """
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Root 1 0 R /Size %d >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    path.write_bytes(bytes(out))


class StubPubMedProvider:
    def __init__(self) -> None:
        self.by_pmid = {
            "12345678": PaperRecord(
                title="Climate change and pregnancy outcomes.",
                authors=["Ada Lovelace"],
                year=2025,
                venue="Environmental Health Perspectives",
                abstract="Heat exposure increased preterm birth risk.",
                doi="10.1289/example",
                pmid="12345678",
                pmcid="PMC1234567",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                provider="pubmed",
                concepts=[
                    {
                        "source": "pubmed",
                        "kind": "publication_type",
                        "display_name": "Systematic Review",
                    },
                    {
                        "source": "pubmed",
                        "kind": "mesh",
                        "display_name": "Pregnancy Outcome",
                        "major_topic": True,
                    },
                ],
            )
        }
        self.by_doi = {"10.1289/example": self.by_pmid["12345678"]}

    def fetch_by_pmid(self, pmid: str) -> PaperRecord | None:
        return self.by_pmid.get(pmid)

    def fetch_by_doi(self, doi: str) -> PaperRecord | None:
        return self.by_doi.get(doi)

    def search(self, query):
        del query
        return list(self.by_pmid.values())


def _read_one_paper(db_path: Path) -> dict:
    db = Database(db_path)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM papers ORDER BY id LIMIT 1").fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def test_paper_ingest_accepts_pmid_and_persists_pubmed_fields(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "rh.db"
    monkeypatch.setattr(
        "research_harness.cli_paper_acquisition._pubmed_provider",
        lambda: StubPubMedProvider(),
    )
    runner = CliRunner()

    init = runner.invoke(main, ["--db", str(db_path), "topic", "init", "medical"])
    assert init.exit_code == 0, init.output

    result = runner.invoke(
        main,
        [
            "--db",
            str(db_path),
            "--json",
            "paper",
            "ingest",
            "--pmid",
            "12345678",
            "--topic",
            "medical",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["paper_id"] == 1
    row = _read_one_paper(db_path)
    assert row["title"] == "Climate change and pregnancy outcomes."
    assert row["pmid"] == "12345678"
    assert row["pmcid"] == "PMC1234567"
    assert row["doi"] == "10.1289/example"


def test_paper_backfill_pubmed_updates_missing_fields_from_doi(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "rh.db"
    monkeypatch.setattr(
        "research_harness.cli_paper_acquisition._pubmed_provider",
        lambda: StubPubMedProvider(),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            main, ["--db", str(db_path), "topic", "init", "medical"]
        ).exit_code
        == 0
    )
    ingest = runner.invoke(
        main,
        [
            "--db",
            str(db_path),
            "paper",
            "ingest",
            "--doi",
            "10.1289/example",
            "--title",
            "doi:10.1289/example",
            "--topic",
            "medical",
        ],
    )
    assert ingest.exit_code == 0, ingest.output

    result = runner.invoke(
        main,
        [
            "--db",
            str(db_path),
            "--json",
            "paper",
            "backfill-pubmed",
            "--topic",
            "medical",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] == 1
    row = _read_one_paper(db_path)
    assert row["title"] == "Climate change and pregnancy outcomes."
    assert row["pmid"] == "12345678"
    assert row["pmcid"] == "PMC1234567"
    assert row["venue"] == "Environmental Health Perspectives"


def test_paper_pmc_links_reports_manual_download_queue(tmp_path) -> None:
    db_path = tmp_path / "rh.db"
    runner = CliRunner()
    assert (
        runner.invoke(
            main, ["--db", str(db_path), "topic", "init", "medical"]
        ).exit_code
        == 0
    )
    db = Database(db_path)
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, pmid, pmcid, doi)
            VALUES ('PMC paper', '12345678', 'PMC1234567', '10.1289/example')
            """
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(
        main,
        ["--db", str(db_path), "--json", "paper", "pmc-links", "--topic", "medical"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/"
    assert item["manual_required"] is True
    assert item["treat_as_direct_pdf"] is False


def test_paper_audit_pdfs_marks_wrong_pdf_as_suspect(tmp_path) -> None:
    db_path = tmp_path / "rh.db"
    wrong_pdf = tmp_path / "wrong.pdf"
    _write_text_pdf(wrong_pdf, "EPA climate adaptation plan for infrastructure.")
    runner = CliRunner()
    assert (
        runner.invoke(
            main, ["--db", str(db_path), "topic", "init", "medical"]
        ).exit_code
        == 0
    )
    db = Database(db_path)
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, doi, pmid, pdf_path)
            VALUES (?, ?, ?, ?)
            """,
            (
                "Climate change and pregnancy outcomes.",
                "10.1289/example",
                "12345678",
                str(wrong_pdf),
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(
        main,
        ["--db", str(db_path), "--json", "paper", "audit-pdfs", "--topic", "medical"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["suspect"] == 1
    item = payload["items"][0]
    assert item["status"] == "suspect"
    assert "no title/DOI/PMID signal" in item["reason"]


def test_search_pubmed_screen_outputs_medical_screening_fields(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "rh.db"
    monkeypatch.setattr(
        "research_harness.cli_search._pubmed_provider",
        lambda: StubPubMedProvider(),
    )
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "--db",
            str(db_path),
            "--json",
            "search",
            "pubmed-screen",
            "--query",
            "heat pregnancy",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    row = payload["rows"][0]
    assert row["pmid"] == "12345678"
    assert row["pmcid"] == "PMC1234567"
    assert "pregnancy" in row["life_stage_tags"]
    assert row["evidence_type"] == "systematic_review"
    assert row["journal_quartile_status"] == "needs_external_verification"
