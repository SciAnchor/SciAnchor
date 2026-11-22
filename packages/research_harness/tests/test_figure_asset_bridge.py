"""UF02 figure-asset bridge: synthetic MinerU candidates, no private corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_harness.acquisition.figure_asset_bridge import (
    BBOX_AMBIGUOUS,
    CANDIDATE,
    CAPTION_MISSING,
    CAPTION_MULTI,
    REJECTED,
    SCOPE_FIGURE,
    SCOPE_PANEL,
    VERIFIED,
    FigureAssetBridgeError,
    build_figure_asset_records,
    load_content_list,
)


def _png(tag: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + tag


def _write_image(root: Path, rel: str, payload: bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_complete_figure_is_verified(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    image = _write_image(source, "images/fig1.png", _png(b"fig1"))
    markdown = "See Figure 1 for the pipeline."
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/fig1.png",
                "img_caption": "Figure 1. Method overview.",
                "page_idx": 2,
                "bbox": [10.0, 20.0, 200.0, 180.0],
            }
        ],
        markdown=markdown,
        source_dir=source,
        dest_dir=tmp_path / "dest",
        parser_version="mineru-2.5-fixture",
    )
    rec = report["records"][0]
    assert rec["verification_status"] == VERIFIED
    assert rec["scope"] == SCOPE_FIGURE
    assert rec["figure_id"] == "fig:1"
    assert rec["page"] == 3
    assert rec["body_references"] == ["Figure 1"]
    copied = Path(rec["asset_path"])
    assert copied.is_file()
    assert copied.read_bytes() == image.read_bytes()
    assert (
        rec["bytes_sha256"]
        == __import__("hashlib").sha256(image.read_bytes()).hexdigest()
    )
    assert rec["parser_version"] == "mineru-2.5-fixture"


def test_panel_scope_from_caption(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    _write_image(source, "images/fig2a.png", _png(b"a"))
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/fig2a.png",
                "img_caption": "Figure 2a. Ablation on dataset A.",
                "page_idx": 0,
                "bbox": [0, 0, 10, 10],
            }
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    rec = report["records"][0]
    assert rec["scope"] == SCOPE_PANEL
    assert rec["figure_id"] == "fig:2a"
    assert rec["verification_status"] == VERIFIED


def test_multi_panel_caption_stays_candidate(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    _write_image(source, "images/fig3.png", _png(b"multi"))
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/fig3.png",
                "img_caption": "Figure 3. (a) benchmark; (b) ablation.",
                "page_idx": 1,
                "bbox": [0, 0, 50, 50],
            }
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    rec = report["records"][0]
    assert rec["verification_status"] == CANDIDATE
    assert rec["caption_status"] == CAPTION_MULTI
    assert rec["panel_labels"] == ["a", "b"]
    assert "multi_panel_caption_unsplit" in rec["issues"]


def test_vector_page_render_without_bytes_is_candidate(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    source.mkdir()
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_caption": "Figure 4. Vector schematic.",
                "page_idx": 0,
                "bbox": [1, 1, 9, 9],
            }
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    rec = report["records"][0]
    assert rec["verification_status"] == CANDIDATE
    assert rec["bytes_sha256"] == ""
    assert "vector_or_page_render_without_bytes" in rec["issues"]


def test_duplicate_assets_share_hash(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    _write_image(source, "images/dup.png", _png(b"same"))
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/dup.png",
                "img_caption": "Figure 5. First mention.",
                "page_idx": 0,
                "bbox": [0, 0, 8, 8],
            },
            {
                "type": "image",
                "img_path": "images/dup.png",
                "img_caption": "Figure 6. Duplicate crop.",
                "page_idx": 1,
                "bbox": [1, 1, 9, 9],
            },
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    hashes = {rec["bytes_sha256"] for rec in report["records"]}
    assert len(hashes) == 1
    assert all(rec["verification_status"] == VERIFIED for rec in report["records"])


def test_missing_caption_is_candidate(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    _write_image(source, "images/nocap.png", _png(b"x"))
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/nocap.png",
                "page_idx": 0,
                "bbox": [0, 0, 4, 4],
            }
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    rec = report["records"][0]
    assert rec["verification_status"] == CANDIDATE
    assert rec["caption_status"] == CAPTION_MISSING


def test_ambiguous_bbox_is_candidate(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    _write_image(source, "images/a.png", _png(b"a"))
    _write_image(source, "images/b.png", _png(b"b"))
    box = [0.0, 0.0, 12.0, 12.0]
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/a.png",
                "img_caption": "Figure 7. Left.",
                "page_idx": 4,
                "bbox": box,
            },
            {
                "type": "image",
                "img_path": "images/b.png",
                "img_caption": "Figure 8. Right.",
                "page_idx": 4,
                "bbox": box,
            },
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    assert all(rec["bbox_status"] == BBOX_AMBIGUOUS for rec in report["records"])
    assert all(rec["verification_status"] == CANDIDATE for rec in report["records"])


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    source.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png(b"out"))
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "../outside.png",
                "img_caption": "Figure 9. Escaped.",
                "page_idx": 0,
                "bbox": [0, 0, 3, 3],
            }
        ],
        source_dir=source,
        parser_version="mineru-2.5-fixture",
    )
    rec = report["records"][0]
    assert rec["verification_status"] == REJECTED
    assert "path_not_contained_or_missing" in rec["issues"]
    assert rec["bytes_sha256"] == ""


def test_missing_parser_version_keeps_candidate(tmp_path: Path) -> None:
    source = tmp_path / "mineru"
    _write_image(source, "images/fig.png", _png(b"v"))
    report = build_figure_asset_records(
        content_list=[
            {
                "type": "image",
                "img_path": "images/fig.png",
                "img_caption": "Figure 10. Provenance gap.",
                "page_idx": 0,
                "bbox": [0, 0, 5, 5],
            }
        ],
        source_dir=source,
        parser_version="",
    )
    rec = report["records"][0]
    assert rec["verification_status"] == CANDIDATE
    assert "parser_version_missing" in rec["issues"]
    assert rec["parser_version"] == ""


def test_load_content_list_rejects_object(tmp_path: Path) -> None:
    path = tmp_path / "content_list.json"
    path.write_text(json.dumps({"type": "image"}), encoding="utf-8")
    with pytest.raises(FigureAssetBridgeError, match="JSON array"):
        load_content_list(path)
