"""Regression tests for the downloader SSRF guard (``is_safe_fetch_url``).

The downloader follows URLs parsed out of untrusted fetched content
(``citation_pdf_url`` tags, PMC OA ``<link>`` hrefs). The guard must allow
public hosts but reject non-http(s) schemes and private/loopback/link-local/
reserved targets so a poisoned page cannot redirect RH at internal endpoints
such as the cloud metadata service.
"""

from __future__ import annotations

import pytest

from research_harness.acquisition.downloader import is_safe_fetch_url


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/pdf/2401.00001",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/x.pdf",
        "http://export.arxiv.org/pdf/2401.00001",
        "https://files.example.org/paper.pdf",
    ],
)
def test_public_https_hosts_are_allowed(url: str) -> None:
    assert is_safe_fetch_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://localhost:8080/x",
        "http://sub.localhost/x",
        "http://127.0.0.1/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://[::1]/x",  # IPv6 loopback
        "http://0.0.0.0/x",
        "file:///etc/passwd",  # non-http scheme
        "ftp://internal/x",
        "gopher://internal/x",
        "",  # malformed / no host
    ],
)
def test_unsafe_targets_are_blocked(url: str) -> None:
    assert is_safe_fetch_url(url) is False
