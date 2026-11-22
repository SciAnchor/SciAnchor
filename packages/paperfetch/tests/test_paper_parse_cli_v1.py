"""SPC 1.0 `paper parse`：无绑定物理解析，不写 papers.jsonl。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperfetch.cli.root import main
from paperfetch.fulltext.file_parse import FileParseOutcome, FileParseService


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _outcome(*, pdf: Path, output_dir: Path, error=None) -> FileParseOutcome:
    digest = "a" * 64
    markdown = output_dir / "parse" / "parse_aaaaaaaaaaaaaaaa" / "document.md"
    manifest = output_dir / "parse" / "parse_aaaaaaaaaaaaaaaa" / "manifest.json"
    if error is None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text("# title\n", encoding="utf-8")
        manifest.write_text("{}", encoding="utf-8")
    return FileParseOutcome(
        parse_id="parse_aaaaaaaaaaaaaaaa",
        input_path=str(pdf),
        input_sha256=digest,
        input_size_bytes=2048,
        markdown_path=None if error else str(markdown),
        markdown_sha256=None if error else "b" * 64,
        markdown_size_bytes=None if error else 8,
        manifest_path=None if error else str(manifest),
        error=error,
        audit_ref=None,
    )


def test_paper_parse_rejects_missing_file(tmp_path, capsys):
    missing = tmp_path / "nope.pdf"
    output = tmp_path / "out"
    assert (
        main(
            [
                "paper",
                "parse",
                "--pdf",
                str(missing),
                "--output-dir",
                str(output),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "spc.result.v2"
    assert payload["status"] == "failed"
    assert payload["data"]["parse"]["identity_bound"] is False
    assert payload["error"]["code"] == "parse_input_missing"
    assert not (output / "papers.jsonl").exists()


def test_paper_parse_rejects_non_pdf(tmp_path, capsys):
    fake = tmp_path / "note.txt"
    fake.write_text("this is not a pdf file\n" * 20, encoding="utf-8")
    output = tmp_path / "out"
    assert (
        main(
            [
                "paper",
                "parse",
                "--pdf",
                str(fake),
                "--output-dir",
                str(output),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "parse_input_not_pdf"
    assert payload["data"]["parse"]["identity_bound"] is False
    assert not (output / "papers.jsonl").exists()


def test_paper_parse_success_does_not_write_seed_pack(monkeypatch, tmp_path, capsys):
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 200)
    output = tmp_path / "out"
    existing = output / "papers.jsonl"

    async def fake_parse(self, *, pdf, output_dir, no_cache=False):
        assert no_cache is False
        output_dir.mkdir(parents=True, exist_ok=True)
        return _outcome(pdf=pdf, output_dir=output_dir)

    monkeypatch.setattr(FileParseService, "parse", fake_parse)
    assert (
        main(
            [
                "paper",
                "parse",
                "--pdf",
                str(pdf),
                "--output-dir",
                str(output),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    parse = payload["data"]["parse"]
    assert parse["available"] is True
    assert parse["identity_bound"] is False
    assert payload["files"][0]["type"] == "markdown"
    assert not existing.exists()
