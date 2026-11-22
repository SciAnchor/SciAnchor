"""URL-level PDF plausibility checks.

Identity audit verifies file content, but a supplement or figure PDF often
contains the paper title and passes it. These checks catch the class of
false positive the content audit cannot: URLs whose *path* says the file is
not the manuscript. Applied when planning native route candidates and when
accepting externally acquired PDFs at the import boundary.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

# URL path fragments that publishers use for figures, supplements, and other
# non-manuscript PDF assets. Conservative on purpose: a false skip loses one
# candidate URL; a false accept poisons the paper record.
NON_PDF_URL_PATTERNS = (
    "article/figure",
    "figure/image",
    "suppl/extlink",
    "supplementary_material",
)

# Hosts whose PDF paths are structurally trustworthy for manuscripts.
TRUSTED_OA_HOSTS = (
    "arxiv.org",
    "europepmc.org",
    "ncbi.nlm.nih.gov",
    "openreview.net",
)


def is_non_pdf_url(url: str | None) -> bool:
    """True when the URL path marks a non-manuscript asset."""
    if not url:
        return False
    lowered = url.lower()
    for pattern in NON_PDF_URL_PATTERNS:
        if pattern in lowered:
            return True
    # PLOS serves figures/supplements via type=download; the manuscript is
    # type=printable.
    if (
        "journals.plos.org" in lowered
        and "type=download" in lowered
        and "type=printable" not in lowered
    ):
        return True
    return False


def doi_in_url(doi: str | None, url: str | None) -> bool:
    """True when the DOI appears in the URL (raw or percent-encoded)."""
    if not doi or not url:
        return False
    return doi.strip().lower() in unquote(url).lower()


def assess_pdf_url(doi: str | None, url: str | None) -> str:
    """Classify how much a final PDF URL vouches for the manuscript.

    Returns one of ``suspect_non_pdf``, ``doi_match``, ``trusted_host``,
    ``neutral``, or ``unknown``. Only ``suspect_non_pdf`` should block;
    the rest are audit context.
    """
    if not url:
        return "unknown"
    if is_non_pdf_url(url):
        return "suspect_non_pdf"
    if doi_in_url(doi, url):
        return "doi_match"
    host = urlparse(url).netloc.lower()
    for trusted in TRUSTED_OA_HOSTS:
        if host == trusted or host.endswith(f".{trusted}"):
            return "trusted_host"
    return "neutral"
