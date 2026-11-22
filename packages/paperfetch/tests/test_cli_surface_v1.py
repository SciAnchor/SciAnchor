"""公开 CLI 表面只宣传现行入口；旧别名必须消失。"""

from __future__ import annotations

import pytest

from paperfetch.cli.root import main


pytestmark = [pytest.mark.unit, pytest.mark.contract]


REMOVED = (
    "sync-papervault",
    "search-metadata",
    "get-references",
    "get-citations",
    "audit-repro",
    "acquire",
)


def test_public_help_hides_legacy_and_dead_commands(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert "paper" in help_text
    assert "seed-pack" in help_text
    for name in REMOVED:
        assert name not in help_text


def test_sync_papervault_is_removed():
    with pytest.raises(SystemExit) as caught:
        main(["sync-papervault", "--help"])
    assert caught.value.code == 1


def test_legacy_lookup_alias_is_removed():
    with pytest.raises(SystemExit) as caught:
        main(["lookup", "--help"])
    assert caught.value.code == 1


def test_paper_acquire_alias_is_removed():
    with pytest.raises(SystemExit) as caught:
        main(["paper", "acquire", "--help"])
    assert caught.value.code == 1


def test_legacy_graph_aliases_are_removed():
    for name in ("search-metadata", "get-references", "get-citations", "audit-repro"):
        with pytest.raises(SystemExit) as caught:
            main([name, "--help"])
        assert caught.value.code == 1


def test_paper_download_help_is_public(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["paper", "download", "--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert "--no-parse" in help_text
    assert "--download-only" not in help_text


def test_paper_parse_help_is_public(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["paper", "parse", "--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert "--pdf" in help_text
    assert "--output-dir" in help_text
    assert "--doi" not in help_text
    assert "papers.jsonl" in help_text
