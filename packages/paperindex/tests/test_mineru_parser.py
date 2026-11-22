from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperindex import PaperIndexer
from paperindex.parsing import MinerUArtifactParser, resolve_document_parser

MARKDOWN = """# Sample Paper Title

Opening abstract text.

## Method

We do the thing carefully.

## Experiments

Numbers went up.
"""

CONTENT_LIST = [
    {"type": "text", "text": "Sample Paper Title", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "Opening abstract text.", "page_idx": 0},
    {"type": "text", "text": "Method", "text_level": 2, "page_idx": 1},
    {"type": "text", "text": "We do the thing carefully.", "page_idx": 1},
    {"type": "image", "page_idx": 2},
    {"type": "text", "text": "Experiments", "text_level": 2, "page_idx": 3},
    {"type": "text", "text": "Numbers went up.", "page_idx": 3},
]


@pytest.fixture
def artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    markdown_path = tmp_path / "full.md"
    markdown_path.write_text(MARKDOWN, encoding="utf-8")
    content_list_path = tmp_path / "paper_content_list.json"
    content_list_path.write_text(json.dumps(CONTENT_LIST), encoding="utf-8")
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    return markdown_path, content_list_path, pdf_path


def test_markdown_only_parse(artifacts):
    markdown_path, _, pdf_path = artifacts
    parsed = MinerUArtifactParser(markdown_path).parse(pdf_path)

    assert parsed.parser_name == "mineru"
    assert parsed.raw["structure_source"] == "markdown_headings"
    assert parsed.markdown == MARKDOWN
    assert [item[:2] for item in parsed.toc] == [
        (1, "Sample Paper Title"),
        (2, "Method"),
        (2, "Experiments"),
    ]
    # No content list: pages fall back to the whole markdown, headings to page 1.
    assert parsed.pages_text == (MARKDOWN,)
    assert {page for _, _, page in parsed.toc} == {1}
    assert parsed.title == "Sample Paper Title"


def test_content_list_supplies_pages(artifacts):
    markdown_path, content_list_path, pdf_path = artifacts
    parsed = MinerUArtifactParser(markdown_path, content_list_path).parse(pdf_path)

    assert parsed.page_count == 4
    assert len(parsed.pages_text) == 4
    assert parsed.pages_text[2] == ""  # image-only page keeps numbering aligned
    assert parsed.toc == (
        (1, "Sample Paper Title", 1),
        (2, "Method", 2),
        (2, "Experiments", 4),
    )
    assert not parsed.warnings


def test_malformed_content_list_degrades_to_markdown(artifacts, tmp_path: Path):
    markdown_path, _, pdf_path = artifacts
    bad = tmp_path / "bad_content_list.json"
    bad.write_text("{not json", encoding="utf-8")
    parsed = MinerUArtifactParser(markdown_path, bad).parse(pdf_path)

    assert parsed.raw["structure_source"] == "markdown_headings"
    assert parsed.pages_text == (MARKDOWN,)
    assert parsed.warnings


def test_missing_markdown_raises(tmp_path: Path):
    parser = MinerUArtifactParser(tmp_path / "absent.md")
    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path / "paper.pdf")


def test_resolver_rejects_name_but_accepts_instance(artifacts):
    markdown_path, _, _ = artifacts
    with pytest.raises(ValueError, match="MinerUArtifactParser"):
        resolve_document_parser("mineru")
    parser = MinerUArtifactParser(markdown_path)
    assert resolve_document_parser(parser) is parser


def test_indexer_builds_structure_without_llm(artifacts):
    markdown_path, content_list_path, pdf_path = artifacts
    indexer = PaperIndexer(
        parser=MinerUArtifactParser(markdown_path, content_list_path)
    )
    structure = indexer.extract_structure(pdf_path)

    assert structure.raw["source"] == "markdown_headings"
    root = structure.tree[0]
    assert root.title == "Sample Paper Title"
    assert [child.title for child in root.children] == ["Method", "Experiments"]
    method = root.children[0]
    assert method.start_page == 2
    assert "We do the thing carefully." in method.section_text
    assert "Numbers went up." not in method.section_text
