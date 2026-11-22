"""BUG-003: ingest source normalization must recover identifiers from URLs and
SPC-style filenames and never store a filesystem path / raw URL as a title."""

from __future__ import annotations

from research_harness.primitives.impls import (
    _normalize_identifier_source,
    _paper_from_source,
)


def test_doi_recovered_from_doi_org_url() -> None:
    kind, value = _normalize_identifier_source("https://doi.org/10.3390/s23167275")
    assert kind == "doi"
    assert value == "10.3390/s23167275"


def test_doi_recovered_from_spc_underscore_filename() -> None:
    src = "/home/user/code/seed_pack/doi_10.1057_s41599-025-06126-7.pdf"
    kind, value = _normalize_identifier_source(src)
    assert kind == "doi"
    assert value == "10.1057/s41599-025-06126-7"


def test_arxiv_id_recovered_from_url() -> None:
    kind, value = _normalize_identifier_source("https://arxiv.org/abs/2412.00099")
    assert kind == "arxiv_id"
    assert value == "2412.00099"


def test_local_path_never_becomes_title() -> None:
    paper = _paper_from_source("/home/user/data/3d-clay-printing-higher-education.pdf")
    assert "/" not in paper.title
    assert not paper.title.endswith(".pdf")
    assert paper.title == "3d clay printing higher education"


def test_bare_web_url_leaves_title_empty() -> None:
    paper = _paper_from_source("https://openreview.net/forum?id=d4mZyZB5I9")
    assert paper.title == ""
    assert paper.url == "https://openreview.net/forum?id=d4mZyZB5I9"


def test_real_title_with_slash_is_preserved() -> None:
    # A title that happens to contain a slash must not be mistaken for a path.
    paper = _paper_from_source("TCP/IP congestion control")
    assert paper.title == "TCP/IP congestion control"
    assert not paper.doi
