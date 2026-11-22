# -*- coding: utf-8 -*-

from pathlib import Path

import pytest

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache
from paperfetch.downloaders.pipeline.resolver import PDFResolver
from paperfetch.downloaders.routing.classifier import PDFDatabaseClassifier
from paperfetch.downloaders.routing.router import PDFDatabaseRouter
from paperfetch.downloaders.base import DownloadRunContext


def _run_context() -> DownloadRunContext:
    return DownloadRunContext()


def test_database_classifier_identifies_sciencedirect_by_doi_prefix():
    matches = PDFDatabaseClassifier().classify(
        PaperRecord(
            paper_id="spc:sd", doi="10.1016/j.cities.2023.104510", title="ScienceDirect"
        )
    )

    assert matches[0].key == "sciencedirect"
    assert matches[0].reason == "doi_prefix_match"
    assert matches[0].confidence >= 90


def test_database_classifier_identifies_nature_and_science_prefixes():
    classifier = PDFDatabaseClassifier()

    nature = classifier.classify(
        PaperRecord(
            paper_id="spc:nature", doi="10.1038/s41586-020-2649-2", title="Nature"
        )
    )
    science = classifier.classify(
        PaperRecord(
            paper_id="spc:science", doi="10.1126/science.169.3946.635", title="Science"
        )
    )

    assert nature[0].key == "nature"
    assert science[0].key == "science"


def test_database_classifier_identifies_taylor_prefix():
    matches = PDFDatabaseClassifier().classify(
        PaperRecord(
            paper_id="spc:taylor", doi="10.1080/01621459.2023.2183129", title="Taylor"
        )
    )

    assert matches[0].key == "taylor"
    assert matches[0].reason == "doi_prefix_match"


@pytest.mark.parametrize(
    "doi",
    (
        "10.1002/rob.22010",
        "10.1111/ruso.12424",
        "10.1034/example",
        "10.1046/j.1365-2923.1998.00210.x",
    ),
)
def test_database_classifier_identifies_wiley_prefix(doi):
    matches = PDFDatabaseClassifier().classify(
        PaperRecord(paper_id="spc:wiley", doi=doi, title="Wiley")
    )

    assert matches[0].key == "wiley"
    assert matches[0].reason == "doi_prefix_match"


def test_database_router_only_plans_official_publisher_api_routes(monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    router = PDFDatabaseRouter(_run_context(), lambda doi: (doi or "").lower())

    elsevier = router.plan(
        PaperRecord(
            paper_id="spc:sd", doi="10.1016/j.cities.2023.104510", title="ScienceDirect"
        )
    )
    ieee = router.plan(
        PaperRecord(paper_id="spc:ieee", doi="10.1109/example", title="IEEE")
    )
    unknown = router.plan(
        PaperRecord(paper_id="spc:unknown", doi="10.9999/example", title="Unknown")
    )

    assert [candidate.route for candidate in elsevier.candidates] == ["elsevier_api"]
    assert ieee.matches[0].key == "ieee"
    assert ieee.candidates == []
    assert unknown.candidates == []


def test_resolver_plans_only_cache_and_api_routes(tmp_path):
    resolver = PDFResolver(
        PDFGlobalCache(root=tmp_path / "cache"),
        run_context=_run_context(),
        no_cache=True,
    )
    paper = PaperRecord(
        paper_id="spc:taylor-route-order",
        doi="10.1080/23802359.2024.2368208",
        title="Taylor route order",
    )
    paper.fulltext_status.pdf_url = (
        "https://www.tandfonline.com/doi/pdf/10.1080/23802359.2024.2368208"
    )

    candidates = resolver.resolve(paper, str(tmp_path / "pdf"))

    assert candidates == []
