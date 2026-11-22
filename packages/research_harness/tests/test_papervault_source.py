"""Tests for the read-only PaperVault local metadata source."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from research_harness.paper_sources import SearchQuery
from research_harness.papervault_source import (
    PAPERVAULT_DB_ENV,
    PaperVaultProvider,
    _fts_match_query,
)


def _build_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " abstract TEXT, authors TEXT, venue TEXT, year INTEGER,"
        " pdf_url TEXT, code_url TEXT, arxiv_id TEXT)"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE papers_fts USING fts5(id UNINDEXED, title, abstract)"
    )
    for row in rows:
        conn.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row["title"],
                row.get("abstract", ""),
                json.dumps(row.get("authors", [])),
                row.get("venue", ""),
                row.get("year"),
                row.get("pdf_url", ""),
                row.get("code_url", ""),
                row.get("arxiv_id", ""),
            ),
        )
        conn.execute(
            "INSERT INTO papers_fts (id, title, abstract) VALUES (?, ?, ?)",
            (row["id"], row["title"], row.get("abstract", "")),
        )
    conn.commit()
    conn.close()


def _fixture_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "papervault.db"
    _build_db(
        db_path,
        [
            {
                "id": "pv1",
                "title": "Retrieval Augmented Generation Survey",
                "abstract": "A survey of RAG systems.",
                "authors": ["Ada Lovelace", "Alan Turing"],
                "venue": "ACL",
                "year": 2024,
                "pdf_url": "https://arxiv.org/pdf/2401.11111",
                "code_url": "https://github.com/ada/rag-survey",
                "arxiv_id": "2401.11111",
            },
            {
                "id": "pv2",
                "title": "Vision Transformers at Scale",
                "abstract": "Large ViT training.",
                "venue": "CVPR",
                "year": 2022,
            },
        ],
    )
    return db_path


def test_fts_query_is_tokenized_and_quoted():
    assert (
        _fts_match_query('rag "survey" OR 1;drop') == '"rag" "survey" "OR" "1" "drop"'
    )
    assert _fts_match_query("") == ""
    assert _fts_match_query("!!!") == ""


class TestProvider:
    def test_unconfigured_provider_is_unavailable(self, monkeypatch):
        monkeypatch.delenv(PAPERVAULT_DB_ENV, raising=False)
        provider = PaperVaultProvider()
        assert provider.available() is False
        assert provider.search(SearchQuery(query="rag")) == []

    def test_missing_file_is_unavailable(self, tmp_path):
        provider = PaperVaultProvider(tmp_path / "gone.db")
        assert provider.available() is False

    def test_search_maps_rows_to_records(self, tmp_path):
        provider = PaperVaultProvider(_fixture_db(tmp_path))

        records = provider.search(SearchQuery(query="retrieval augmented generation"))

        assert len(records) == 1
        record = records[0]
        assert record.provider == "papervault"
        assert record.title == "Retrieval Augmented Generation Survey"
        assert record.authors == ["Ada Lovelace", "Alan Turing"]
        assert record.venue == "ACL"
        assert record.arxiv_id == "2401.11111"
        assert (
            record.curation_signals["code_url"] == "https://github.com/ada/rag-survey"
        )
        assert record.source_refs[0]["source"] == "papervault"
        assert record.recall_hits[0]["source"] == "papervault"
        assert any(c.source_type == "arxiv_pdf" for c in record.pdf_candidates)

    def test_word_order_does_not_matter(self, tmp_path):
        provider = PaperVaultProvider(_fixture_db(tmp_path))

        records = provider.search(SearchQuery(query="generation retrieval survey"))

        assert len(records) == 1

    def test_year_filters_apply(self, tmp_path):
        provider = PaperVaultProvider(_fixture_db(tmp_path))

        records = provider.search(
            SearchQuery(query="retrieval augmented generation", year_from=2025)
        )

        assert records == []

    def test_hostile_query_does_not_raise(self, tmp_path):
        provider = PaperVaultProvider(_fixture_db(tmp_path))

        records = provider.search(SearchQuery(query='"; DROP TABLE papers; --'))

        assert isinstance(records, list)


class TestSuiteWiring:
    def test_provider_joins_suite_when_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv(PAPERVAULT_DB_ENV, str(_fixture_db(tmp_path)))
        from research_harness.paper_source_clients import build_provider_suite

        names = [provider.name for provider in build_provider_suite()]

        assert names[0] == "papervault"

    def test_provider_absent_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv(PAPERVAULT_DB_ENV, raising=False)
        from research_harness.paper_source_clients import build_provider_suite

        names = [provider.name for provider in build_provider_suite()]

        assert "papervault" not in names

    def test_spec_reports_configuration_state(self, monkeypatch):
        monkeypatch.delenv(PAPERVAULT_DB_ENV, raising=False)
        from research_harness.paper_source_clients import available_provider_specs

        spec = next(
            item for item in available_provider_specs() if item.name == "papervault"
        )

        assert spec.enabled is False
        assert "RESEARCH_HARNESS_PAPERVAULT_DB" in spec.reason
