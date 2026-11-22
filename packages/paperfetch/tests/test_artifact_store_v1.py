"""SPC 1.0 不可变文件保存与实际文件探测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperfetch.artifacts.models import ArtifactProducer
from paperfetch.artifacts.store import (
    ArtifactStoreError,
    materialize_artifact,
    probe_artifact,
)


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def test_pdf_and_mineru_artifacts_are_content_addressed_and_reprobed(
    tmp_path: Path, make_pdf_bytes
):
    seed_pack = tmp_path / "pack"
    seed_pack.mkdir()
    paper_id = f"spc_{'1' * 32}"
    pdf_source = tmp_path / "source.pdf"
    pdf_source.write_bytes(make_pdf_bytes(title="Example", doi="10.1000/example"))
    pdf = materialize_artifact(
        seed_pack,
        paper_id=paper_id,
        kind="paper_pdf",
        files={"article_pdf": pdf_source},
        producer=ArtifactProducer(name="test-pdf-validator", version="1"),
    )
    assert pdf == materialize_artifact(
        seed_pack,
        paper_id=paper_id,
        kind="paper_pdf",
        files={"article_pdf": pdf_source},
        producer=ArtifactProducer(name="test-pdf-validator", version="1"),
    )
    pdf_manifest = probe_artifact(seed_pack, pdf, expected_paper_id=paper_id)
    assert pdf_manifest.files[0].path == "article.pdf"

    markdown_source = tmp_path / "full.md"
    markdown_source.write_text("# Example\n", encoding="utf-8")
    layout = tmp_path / "layout.json"
    layout.write_text("{}", encoding="utf-8")
    content_list = tmp_path / "content_list.json"
    content_list.write_text("[]", encoding="utf-8")
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    archive = tmp_path / "result.zip"
    archive.write_bytes(b"PK-test")
    image_source = tmp_path / "figure.png"
    image_source.write_bytes(b"png")
    markdown = materialize_artifact(
        seed_pack,
        paper_id=paper_id,
        kind="mineru_fulltext",
        files={
            "document_markdown": (markdown_source, "document.md"),
            "layout": (layout, "layout.json"),
            "content_list": (content_list, "content-list.json"),
            "model": (model, "model.json"),
            "raw_archive": (archive, "raw/mineru-result.zip"),
            "image:figure.png": (image_source, "images/figure.png"),
        },
        producer=ArtifactProducer(name="mineru", version="2"),
        source_artifact_id=pdf.artifact_id,
    )
    markdown_manifest = probe_artifact(seed_pack, markdown, expected_paper_id=paper_id)
    assert markdown_manifest.source_artifact_id == pdf.artifact_id
    assert {item.path for item in markdown_manifest.files} >= {
        "document.md",
        "layout.json",
        "content-list.json",
        "model.json",
        "raw/mineru-result.zip",
        "images/figure.png",
    }

    pdf_path = seed_pack / Path(pdf.manifest_path).parent / "article.pdf"
    pdf_path.write_bytes(pdf_path.read_bytes() + b"corrupt")
    with pytest.raises(ArtifactStoreError) as caught:
        probe_artifact(seed_pack, pdf, expected_paper_id=paper_id)
    assert caught.value.code == "artifact_file_corrupt"


def test_artifact_rejects_html_and_never_publishes_partial_directory(tmp_path: Path):
    seed_pack = tmp_path / "pack"
    seed_pack.mkdir()
    source = tmp_path / "landing.pdf"
    source.write_text("<html>challenge</html>", encoding="utf-8")
    with pytest.raises(ArtifactStoreError) as caught:
        materialize_artifact(
            seed_pack,
            paper_id=f"spc_{'2' * 32}",
            kind="paper_pdf",
            files={"article_pdf": source},
            producer=ArtifactProducer(name="test"),
        )
    assert caught.value.code == "artifact_pdf_invalid"
    assert (
        not list((seed_pack / "artifacts").rglob("manifest.json"))
        if (seed_pack / "artifacts").exists()
        else True
    )


def test_manifest_does_not_expose_source_paths(tmp_path: Path, make_pdf_bytes):
    seed_pack = tmp_path / "pack"
    seed_pack.mkdir()
    source = tmp_path / "private-source-name.pdf"
    source.write_bytes(make_pdf_bytes(title="Example"))
    pointer = materialize_artifact(
        seed_pack,
        paper_id=f"spc_{'3' * 32}",
        kind="paper_pdf",
        files={"article_pdf": source},
        producer=ArtifactProducer(name="test"),
    )
    payload = json.loads(
        (seed_pack / pointer.manifest_path).read_text(encoding="utf-8")
    )
    assert "private-source-name" not in json.dumps(payload)
    assert payload["files"][0]["path"] == "article.pdf"
