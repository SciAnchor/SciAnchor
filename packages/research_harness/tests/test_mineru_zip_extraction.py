from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from research_harness.integrations.mineru import (
    MinerUZipContentError,
    MinerUZipPathError,
    extract_mineru_zip,
)


def _write_valid_zip(path: Path, extra: dict[str, str] | None = None) -> None:
    extra = extra or {}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("full.md", "markdown")
        archive.writestr("layout.json", "{}")
        archive.writestr("paper_content_list.json", "[]")
        archive.writestr("paper_model.json", "{}")
        for name, value in extra.items():
            archive.writestr(name, value)


def test_extract_mineru_zip_extracts_required_outputs(tmp_path):
    zip_path = tmp_path / "result.zip"
    output_dir = tmp_path / "parsed"
    _write_valid_zip(zip_path, {"images/figure.png": "png"})

    extract_mineru_zip(zip_path, output_dir)

    assert (output_dir / "full.md").read_text() == "markdown"
    assert (output_dir / "layout.json").exists()
    assert (output_dir / "images" / "figure.png").exists()


@pytest.mark.parametrize("bad_name", ["../full.md", "/abs/full.md", "C:/temp/full.md"])
def test_extract_mineru_zip_rejects_unsafe_paths(tmp_path, bad_name):
    zip_path = tmp_path / "result.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(bad_name, "bad")
        archive.writestr("layout.json", "{}")
        archive.writestr("paper_content_list.json", "[]")
        archive.writestr("paper_model.json", "{}")

    with pytest.raises(MinerUZipPathError):
        extract_mineru_zip(zip_path, tmp_path / "parsed")


@pytest.mark.parametrize(
    "missing_name",
    ["full.md", "layout.json", "paper_content_list.json", "paper_model.json"],
)
def test_extract_mineru_zip_requires_primary_outputs(tmp_path, missing_name):
    zip_path = tmp_path / "result.zip"
    files = {
        "full.md": "markdown",
        "layout.json": "{}",
        "paper_content_list.json": "[]",
        "paper_model.json": "{}",
    }
    del files[missing_name]
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)

    with pytest.raises(MinerUZipContentError):
        extract_mineru_zip(zip_path, tmp_path / "parsed")
