# -*- coding: utf-8 -*-
import os
import zipfile

import pytest

from paperfetch.fulltext.mineru import (
    MinerUParseAction,
    MinerUZipContentError,
    MinerUZipPathError,
)


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)


def _valid_members():
    prefix = "12345678-1234-1234-1234-123456789abc"
    return {
        "full.md": "# parsed\n",
        "layout.json": "{}",
        f"{prefix}_content_list.json": "[]",
        f"{prefix}_content_list_v2.json": "[]",
        f"{prefix}_model.json": "{}",
        "images/" + ("a" * 64) + ".jpg": b"image-bytes",
    }


def test_extract_mineru_zip_handles_long_windows_style_paths(tmp_path):
    zip_path = tmp_path / "mineru.zip"
    _write_zip(zip_path, _valid_members())

    long_dir_name = "emotion-driven-multimodal-3d-avatar-expression-animation-generation__20260627-031434__75bcba"
    nested = (
        tmp_path
        / ("seed_pack_" + "x" * 30)
        / long_dir_name
        / "mineru"
        / "10.1145_3664647.3681366"
    )

    md_path, parse_quality = MinerUParseAction._extract_mineru_zip(
        str(zip_path), str(nested)
    )

    assert parse_quality == "high"
    assert os.path.basename(md_path) == "full.md"
    assert MinerUParseAction.path_exists(md_path)
    assert MinerUParseAction.path_exists(str(nested / "layout.json"))
    assert MinerUParseAction.path_exists(
        str(nested / ("images/" + ("a" * 64) + ".jpg"))
    )


def test_extract_mineru_zip_rejects_zip_slip(tmp_path):
    zip_path = tmp_path / "bad.zip"
    members = _valid_members()
    members["../escape.txt"] = "bad"
    _write_zip(zip_path, members)

    with pytest.raises(MinerUZipPathError):
        MinerUParseAction._extract_mineru_zip(str(zip_path), str(tmp_path / "out"))


def test_extract_mineru_zip_requires_full_markdown(tmp_path):
    zip_path = tmp_path / "bad.zip"
    members = _valid_members()
    del members["full.md"]
    _write_zip(zip_path, members)

    with pytest.raises(MinerUZipContentError, match="full.md"):
        MinerUParseAction._extract_mineru_zip(str(zip_path), str(tmp_path / "out"))


def test_extract_mineru_zip_requires_primary_json_outputs(tmp_path):
    zip_path = tmp_path / "bad.zip"
    members = _valid_members()
    for name in list(members):
        if name.endswith("_content_list.json"):
            del members[name]
    _write_zip(zip_path, members)

    with pytest.raises(MinerUZipContentError, match="content_list"):
        MinerUParseAction._extract_mineru_zip(str(zip_path), str(tmp_path / "out"))
