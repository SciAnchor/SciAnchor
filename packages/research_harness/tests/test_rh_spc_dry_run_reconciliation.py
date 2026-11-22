from __future__ import annotations

import hashlib
import sqlite3

import pytest

from research_harness._selfdev.rh_spc_dry_run_reconciliation import (
    ReconciliationObservation,
    reconcile_observations,
)
from research_harness._selfdev.rh_spc_dry_run_reconciliation import (
    ReconciliationError,
    _hash_for_record,
    _load_rh_observations,
    _load_spc_observations,
    _pdf_hashes,
    _resolve_rh_pdf,
)


def _obs(key: str, **overrides: object) -> ReconciliationObservation:
    values = {
        "source": "rh",
        "source_key": key,
        "title": "A study of forecasting",
        "year": 2024,
        "doi": None,
        "arxiv_id": None,
        "content_hash": None,
    }
    values.update(overrides)
    return ReconciliationObservation(**values)


def test_reconcile_classifies_same_by_unique_doi() -> None:
    report = reconcile_observations(
        (_obs("rh:1", doi="10.1000/ABC"),),
        (_obs("spc:1", source="spc", doi="doi:10.1000/abc"),),
    )

    assert report.outcomes[0].relation == "same"
    assert report.outcomes[0].evidence == ("doi_exact",)


def test_reconcile_classifies_conflicting_strong_identifier() -> None:
    report = reconcile_observations(
        (_obs("rh:1", doi="10.1000/abc"),),
        (
            _obs(
                "spc:1",
                source="spc",
                doi="10.1000/abc",
                title="A contradictory title",
            ),
        ),
    )

    assert report.outcomes[0].relation == "conflict"
    assert "doi_exact" in report.outcomes[0].evidence
    assert "title_conflict" in report.outcomes[0].evidence


def test_reconcile_keeps_title_year_match_as_related() -> None:
    report = reconcile_observations(
        (_obs("rh:1"),),
        (_obs("spc:1", source="spc"),),
    )

    assert report.outcomes[0].relation == "related"
    assert report.outcomes[0].evidence == ("title_year_match",)


def test_reconcile_keeps_ambiguous_and_unmatched_observations_visible() -> None:
    report = reconcile_observations(
        (
            _obs("rh:1", doi="10.1000/abc"),
            _obs("rh:2", doi=None, title="unmatched"),
        ),
        (
            _obs("spc:1", source="spc", doi="10.1000/abc"),
            _obs("spc:2", source="spc", doi="10.1000/abc"),
            _obs("spc:3", source="spc", title="only spc"),
        ),
    )

    assert [outcome.relation for outcome in report.outcomes] == [
        "manual_review",
        "manual_review",
        "manual_review",
    ]
    visible_keys = {
        key
        for outcome in report.outcomes
        for key in (outcome.left_key, *outcome.right_keys)
        if key is not None
    }
    assert visible_keys == {"rh:1", "rh:2", "spc:1", "spc:2", "spc:3"}
    assert report.conservation_total == 5
    assert report.counts["manual_review"] == 3


def test_reconcile_classifies_incompatible_duplicate_strong_matches_as_conflict() -> (
    None
):
    report = reconcile_observations(
        (_obs("rh:1", doi="10.1000/abc"),),
        (
            _obs("spc:1", source="spc", doi="10.1000/abc"),
            _obs(
                "spc:2",
                source="spc",
                doi="10.1000/abc",
                title="A different study",
            ),
        ),
    )

    assert report.outcomes[0].relation == "conflict"
    assert "incompatible_strong_matches" in report.outcomes[0].evidence


def test_reconcile_portable_report_has_no_persistent_write() -> None:
    report = reconcile_observations((_obs("rh:1"),), (_obs("spc:1", source="spc"),))

    portable = report.to_portable()
    assert portable["persistent_write"] is False
    assert portable["conservation_total"] == 2


def test_reconcile_rejects_wrong_or_duplicate_source_keys() -> None:
    with pytest.raises(ReconciliationError, match="left_source"):
        reconcile_observations((_obs("x:1", source="other"),), ())
    with pytest.raises(ReconciliationError, match="right_source"):
        reconcile_observations((), (_obs("x:1"),))
    with pytest.raises(ReconciliationError, match="source_keys"):
        reconcile_observations((_obs("same"),), (_obs("same", source="spc"),))


def test_reconcile_covers_hash_and_ambiguous_title_year_paths() -> None:
    content_hash = "a" * 64
    report = reconcile_observations(
        (
            _obs("rh:hash", title="hash", content_hash=content_hash),
            _obs("rh:ambiguous", title="same", year=2024),
            _obs("rh:bad", title="none", year=2020),
        ),
        (
            _obs(
                "spc:hash",
                source="spc",
                title="different",
                content_hash=content_hash,
            ),
            _obs("spc:title-a", source="spc", title="same", year=2024),
            _obs("spc:title-b", source="spc", title="same", year=2024),
        ),
    )

    assert [outcome.relation for outcome in report.outcomes[:3]] == [
        "manual_review",
        "manual_review",
        "manual_review",
    ]
    assert report.outcomes[0].evidence == ("content_hash_exact", "title_conflict")
    assert report.outcomes[1].evidence == ("ambiguous_title_year",)


def test_reconcile_loaders_read_only_and_resolve_only_download_pdfs(tmp_path) -> None:
    state = tmp_path / ".research-harness"
    downloads = state / "downloads"
    downloads.mkdir(parents=True)
    (downloads / "paper.pdf").write_bytes(b"rh-pdf")
    database = state / "pool.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE papers (id INTEGER, title TEXT, year INTEGER, doi TEXT, "
        "arxiv_id TEXT, pdf_hash TEXT, pdf_path TEXT);"
        "INSERT INTO papers VALUES (1, 'RH title', 2024, NULL, "
        "'arXiv:1234.5678v2', NULL, 'downloads/paper.pdf');"
        "INSERT INTO papers VALUES (2, 'Known hash', 2023, NULL, NULL, '"
        + hashlib.sha256(b"known").hexdigest()
        + "', NULL);"
    )
    connection.commit()
    connection.close()

    observations = _load_rh_observations(tmp_path)
    assert observations[0].content_hash == hashlib.sha256(b"rh-pdf").hexdigest()
    assert observations[1].content_hash == hashlib.sha256(b"known").hexdigest()
    assert _resolve_rh_pdf(tmp_path, state, downloads, "../outside.pdf") is None
    assert _resolve_rh_pdf(tmp_path, state, downloads, None) is None


def test_reconcile_spc_loader_associates_safe_filenames_and_rejects_symlinks(
    tmp_path,
) -> None:
    pack = tmp_path / "pack"
    pdf_dir = pack / "pdf"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "doi_10_1000_test.pdf").write_bytes(b"doi-pdf")
    (pdf_dir / "arxiv_1234_5678.pdf").write_bytes(b"arxiv-pdf")
    (pack / "seed_papers.jsonl").write_text(
        '{"recorded_facts":{"doi":"10.1000/test","title":"DOI","year":2024}}\n'
        '{"arxiv_id":"1234.5678v2","title":"Arxiv","year":2023}\n',
        encoding="utf-8",
    )

    observations = _load_spc_observations(tmp_path)
    assert len(observations) == 2
    assert observations[0].content_hash == hashlib.sha256(b"doi-pdf").hexdigest()
    assert observations[1].content_hash == hashlib.sha256(b"arxiv-pdf").hexdigest()
    assert _hash_for_record({}, "", "") is None
    assert _pdf_hashes(tmp_path / "missing") == {}

    link = pdf_dir / "linked.pdf"
    link.symlink_to(pdf_dir / "doi_10_1000_test.pdf")
    with pytest.raises(ReconciliationError, match="spc_pdf_symlink"):
        _pdf_hashes(pdf_dir)
