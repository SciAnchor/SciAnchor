from paperfetch.core.models import FulltextStatus
from paperfetch.downloaders.pipeline.outcome import finalize_download_outcome


def test_download_outcome_uses_actionable_failures_and_discovered_resource():
    status = FulltextStatus(
        download_attempted=True,
        download_status="failed",
        candidate_pdf_urls=[{"route": "elsevier_api", "url": "https://doi.org/x"}],
        download_attempts=[
            {"route": "local_cache", "error_class": "missing_file"},
            {
                "route": "elsevier_api",
                "error_class": "subscription_required",
                "status_code": 200,
            },
            {"route": "public_browser", "error_class": "publisher_challenge"},
        ],
    )

    finalize_download_outcome(status)

    assert status.primary_failure_class == "subscription_required"
    assert status.last_failure_class == "publisher_challenge"
    assert status.failure_taxonomy == "publisher_challenge"
    assert status.resource_outcome == "resource_discovered_but_transfer_failed"
    assert len(status.attempted_route_summary) == 3


def test_download_outcome_preserves_not_attempted_and_downloaded_states():
    untouched = FulltextStatus()
    finalize_download_outcome(untouched)
    assert untouched.resource_outcome == "not_attempted"

    downloaded = FulltextStatus(
        download_attempted=True,
        download_status="downloaded",
        failure_taxonomy="html_landing",
        download_attempts=[
            {"route": "public_http", "error_class": "html_landing"},
            {"route": "public_browser", "error_class": None},
        ],
    )
    finalize_download_outcome(downloaded)
    assert downloaded.resource_outcome == "downloaded"
    assert downloaded.primary_failure_class is None
    assert downloaded.last_failure_class is None
    assert downloaded.failure_taxonomy is None
    assert downloaded.attempted_route_summary[0]["error_class"] == "html_landing"


def test_download_outcome_classifies_terminal_resource_not_discovered():
    status = FulltextStatus(
        download_attempted=True,
        download_status="failed",
    )

    finalize_download_outcome(status)

    assert status.resource_outcome == "resource_not_discovered"
    assert status.primary_failure_class == "pdf_resource_not_discovered"
    assert status.last_failure_class == "pdf_resource_not_discovered"
    assert status.failure_taxonomy == "pdf_resource_not_discovered"


def test_download_outcome_replaces_generic_no_result_but_preserves_specific_failure():
    generic = FulltextStatus(
        download_attempted=True,
        download_status="failed",
        failure_taxonomy="no_result",
    )
    specific = FulltextStatus(
        download_attempted=True,
        download_status="failed",
        failure_taxonomy="metadata_poisoned",
    )

    finalize_download_outcome(generic)
    finalize_download_outcome(specific)

    assert generic.primary_failure_class == "pdf_resource_not_discovered"
    assert generic.last_failure_class == "pdf_resource_not_discovered"
    assert generic.failure_taxonomy == "pdf_resource_not_discovered"
    assert specific.primary_failure_class == "metadata_poisoned"
    assert specific.last_failure_class == "metadata_poisoned"
    assert specific.failure_taxonomy == "metadata_poisoned"
