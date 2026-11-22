from __future__ import annotations

from pathlib import Path


def test_pdf_root_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, pdf_roots

    assert http_api._default_pdf_roots is pdf_roots.default_pdf_roots


def test_configured_pdf_roots_uses_defaults_for_missing_or_empty_env(
    monkeypatch,
):
    from research_harness_mcp import pdf_roots

    monkeypatch.delenv("RESEARCH_HARNESS_PDF_ROOTS", raising=False)
    assert pdf_roots.configured_pdf_roots() == pdf_roots.default_pdf_roots()

    monkeypatch.setenv("RESEARCH_HARNESS_PDF_ROOTS", "")
    assert pdf_roots.configured_pdf_roots() == pdf_roots.default_pdf_roots()


def test_configured_pdf_roots_parses_colon_separated_env(tmp_path: Path):
    from research_harness_mcp import pdf_roots

    first_root = tmp_path / "one"
    second_root = tmp_path / "two"

    assert pdf_roots.configured_pdf_roots(env_value=f"{first_root}:{second_root}:") == [
        first_root.resolve(),
        second_root.resolve(),
    ]


def test_default_pdf_roots_include_current_and_legacy_locations():
    from research_harness_mcp import pdf_roots

    roots = pdf_roots.default_pdf_roots()

    assert (Path.home() / ".research-harness").resolve() in roots
    assert (
        Path(pdf_roots.__file__).resolve().parents[3] / ".research-harness"
    ).resolve() in roots
    assert (
        Path.home() / "code" / "research-harness" / ".research-harness"
    ).resolve() in roots
    assert len(roots) == len(set(roots))
