"""Offline controls: synthesized HTML, not original captured HTTP responses."""

from __future__ import annotations

import io
import json
from email.message import Message

import pytest

from research_harness.acquisition import html_ingest
from research_harness.core.paper_pool import PaperPool
from research_harness.primitives.impls import paper_ingest
from research_harness.storage.models import Paper, PaperAnnotation

URL = "https://example.org/article"
CHALLENGE_TITLE = "Verifying your browser | OpenReview"
CHALLENGE_BODY = (
    "<h1>Verifying your browser</h1>"
    "<h2>Complete the check below to continue to OpenReview</h2>"
    "<p>Please complete the verification above.</p>"
)


def serve_html(
    monkeypatch, title=CHALLENGE_TITLE, body=CHALLENGE_BODY, content_type="text/html"
):
    calls = []

    def response(request, **kwargs):
        calls.append(request.full_url)
        result = io.BytesIO(
            f"<html><title>{title}</title><body>{body}</body></html>".encode()
        )
        result.headers = Message()
        result.headers["Content-Type"] = content_type
        result.status = 200
        return result

    monkeypatch.setattr("urllib.request.urlopen", response)
    return calls


@pytest.fixture(autouse=True)
def offline_metadata(monkeypatch):
    monkeypatch.setattr(PaperPool, "enrich_metadata", lambda self, paper_id: {})
    monkeypatch.setattr("time.sleep", lambda _: None)


@pytest.mark.parametrize(
    "title",
    [
        CHALLENGE_TITLE,
        "  VERIFYING YOUR BROWSER | OpenReview  ",
        "Checking your browser",
        "Just a moment...",
        "Attention Required! | Cloudflare",
        "Access Denied",
        "403 Forbidden",
        "404 Not Found",
        "502 Bad Gateway",
        "503 Service Unavailable",
    ],
)
def test_literal_challenge_and_error_titles(title):
    assert html_ingest.invalid_source_reason(title)


@pytest.mark.parametrize(
    ("title", "content"),
    [
        ("Browser verification for accessible clinical portals", "Brief report."),
        ("Formal verification of browser security", ""),
        ("Access denied: a study of authorization errors", "Results."),
        ("A short manual blog without a DOI", "One sentence."),
        ("", ""),
        (
            "An empirical paper",
            "The LLM summary calls this a browser-verification page.",
        ),
        (
            "Debugging challenges",
            "We observed the title Verifying your browser | OpenReview.",
        ),
        (
            "Browser measurement",
            "We recorded this page:\n# Verifying your browser\n"
            "## Complete the check below to continue to OpenReview\nPlease complete the verification above.",
        ),
    ],
)
def test_no_deterministic_invalid_page_evidence(title, content):
    assert html_ingest.invalid_source_reason(title, content) == ""


def test_page_signature_without_polluted_title(monkeypatch):
    serve_html(monkeypatch, title="")
    page = html_ingest.fetch_html_as_markdown(URL)
    assert page.http_status == 200
    assert not page.ok
    assert page.error == html_ingest.invalid_source_reason("", page.markdown)
    assert page.error


@pytest.mark.parametrize(
    ("title", "body", "reason"),
    [
        (
            "Just a moment...",
            "<p>Enable JavaScript and cookies to continue</p>",
            "source_challenge_page",
        ),
        (
            "",
            "<h1>Just a moment...</h1><p>Enable JavaScript and cookies to continue</p>",
            "source_challenge_page",
        ),
        ("503 Service Unavailable", "<p>Try again later.</p>", "source_error_page"),
    ],
)
def test_other_known_http_200_pages(monkeypatch, title, body, reason):
    serve_html(monkeypatch, title=title, body=body)
    page = html_ingest.fetch_html_as_markdown(URL)
    assert page.http_status == 200 and not page.ok
    assert page.error == reason


def test_fetched_page_constructor_rejects_polluted_title():
    page = html_ingest.FetchedPage(
        url=URL, title=CHALLENGE_TITLE, markdown="challenge text"
    )
    assert not page.ok
    assert page.error == html_ingest.invalid_source_reason(CHALLENGE_TITLE)
    supplied_error = html_ingest.FetchedPage(
        url=URL, title=CHALLENGE_TITLE, error="HTTP 429"
    )
    assert supplied_error.error == "HTTP 429"


@pytest.mark.parametrize("source_only", [False, True])
def test_ingest_rejects_http_200_challenge_without_losing_candidate(
    db, monkeypatch, source_only
):
    calls = serve_html(monkeypatch)
    result = paper_ingest(db=db, source=URL, **({} if source_only else {"url": URL}))
    assert calls == [URL]
    assert result.status == "new"  # Candidate is retained; retrieved text is not.
    assert result.html_ingest["fetched"] is False
    assert result.html_ingest["reason"]
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title, abstract, status, url FROM papers WHERE id = ?",
            (result.paper_id,),
        ).fetchone()
        assert not row["title"] and not row["abstract"]
        assert row["status"] == "meta_only" and row["url"] == URL
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM paper_annotations WHERE paper_id = ?",
                (result.paper_id,),
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


@pytest.mark.parametrize("abstract", ["", "Trusted abstract"])
def test_challenge_preserves_scholarly_metadata_and_annotations(
    db, monkeypatch, abstract
):
    conn = db.connect()
    try:
        pool = PaperPool(conn)
        paper_id = pool.ingest(
            Paper(
                title="Scholarly title", doi="10.1234/demo", abstract=abstract, url=URL
            )
        )
        pool.upsert_annotation(
            PaperAnnotation(
                paper_id=paper_id,
                section="summary",
                content="Trusted notes",
                source="manual",
            )
        )
        before = tuple(
            conn.execute(
                "SELECT title, abstract, status FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
        )
    finally:
        conn.close()
    serve_html(monkeypatch)
    result = paper_ingest(db=db, source="doi:10.1234/demo", url=URL)
    assert result.paper_id == paper_id
    assert result.title == "Scholarly title"
    assert result.html_ingest["fetched"] is False
    conn = db.connect()
    try:
        assert (
            tuple(
                conn.execute(
                    "SELECT title, abstract, status FROM papers WHERE id = ?",
                    (paper_id,),
                ).fetchone()
            )
            == before
        )
        assert [
            tuple(row)
            for row in conn.execute(
                "SELECT content, source FROM paper_annotations WHERE paper_id = ?",
                (paper_id,),
            )
        ] == [("Trusted notes", "manual")]
    finally:
        conn.close()


@pytest.mark.parametrize("source_only", [False, True])
def test_short_manual_blog_still_ingests(db, monkeypatch, source_only):
    serve_html(
        monkeypatch,
        title="Browser verification engineering notes",
        body="<p>One short note.</p>",
    )
    result = paper_ingest(
        db=db,
        source=URL if source_only else "Manual engineering blog title",
        **({} if source_only else {"url": URL}),
    )
    assert result.html_ingest["fetched"] is True
    assert result.title == (
        "Browser verification engineering notes"
        if source_only
        else "Manual engineering blog title"
    )
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT status, abstract, doi FROM papers WHERE id = ?", (result.paper_id,)
        ).fetchone()
        assert row["status"] == "text_only" and row["abstract"] == "One short note."
        assert not row["doi"]
    finally:
        conn.close()


def test_unknown_fetch_failure_is_not_invented_as_challenge(db, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("offline test failure")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    result = paper_ingest(db=db, source=URL, url=URL)
    assert result.html_ingest == {
        "fetched": False,
        "reason": "OSError: offline test failure",
    }


def test_empty_body_reports_failure(db, monkeypatch):
    serve_html(monkeypatch, title="An article", body="")
    result = paper_ingest(db=db, source=URL, url=URL)
    assert result.html_ingest["fetched"] is False
    assert result.html_ingest["reason"] == "no body"


def test_non_html_reports_existing_error(db, monkeypatch):
    serve_html(monkeypatch, content_type="application/pdf")
    result = paper_ingest(db=db, source=URL, url=URL)
    assert result.html_ingest == {
        "fetched": False,
        "reason": "non-HTML content-type: application/pdf",
    }


def test_public_python_api_source_only_preserves_failure(db, monkeypatch):
    from research_harness.api import ResearchAPI

    serve_html(monkeypatch)
    output = ResearchAPI(db.db_path).paper_ingest(source=URL)
    assert output.html_ingest["fetched"] is False
    assert output.html_ingest["reason"]


def test_public_cli_uses_shared_page_guard(db, monkeypatch):
    from click.testing import CliRunner
    from research_harness.cli import main

    serve_html(monkeypatch)
    result = CliRunner().invoke(
        main, ["--db", str(db.db_path), "--json", "paper", "ingest", "--url", URL]
    )
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["html_ingest"]["fetched"] is False
    assert output["html_ingest"]["reason"]
    assert output["title"] == ""


def test_public_mcp_source_only_preserves_failure(db, monkeypatch):
    from research_harness_mcp import tools

    serve_html(monkeypatch)
    monkeypatch.setattr(tools, "_resolve_db", lambda: db)
    result = tools.execute_tool("paper_ingest", {"source": URL})
    assert result["status"] == "success"  # Candidate admission succeeds, not retrieval.
    assert result["output"]["html_ingest"]["fetched"] is False
    assert result["output"]["html_ingest"]["reason"]
