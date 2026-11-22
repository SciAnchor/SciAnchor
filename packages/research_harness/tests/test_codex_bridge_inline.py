"""API-backend blindness guard: chat backends must see the artifact content."""

from __future__ import annotations

from research_harness.auto_runner.codex_bridge import (
    _ARTIFACT_INLINE_MAX_CHARS,
    _artifact_content_block,
)


def test_artifact_content_block_inlines_and_truncates(tmp_path):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article} UNIQUE-BODY-MARKER", encoding="utf-8")
    block = _artifact_content_block(tex)
    assert "ARTIFACT CONTENT (verbatim):" in block
    assert "UNIQUE-BODY-MARKER" in block

    big = tmp_path / "big.tex"
    big.write_text("x" * (_ARTIFACT_INLINE_MAX_CHARS + 500), encoding="utf-8")
    block = _artifact_content_block(big)
    assert "[... truncated for length ...]" in block
    assert len(block) < _ARTIFACT_INLINE_MAX_CHARS + 200


def test_artifact_content_block_missing_or_empty_file(tmp_path):
    assert _artifact_content_block(tmp_path / "absent.tex") == ""
    empty = tmp_path / "empty.tex"
    empty.write_text("   ", encoding="utf-8")
    assert _artifact_content_block(empty) == ""
