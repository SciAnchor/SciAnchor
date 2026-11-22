"""root.py 只做启动；选刊与领域注册不堆在入口文件。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from paperfetch.cli import dispatch, register, root
from paperfetch.cli.root import main


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_root_is_bootstrap_not_venue_orchestrator():
    source = Path(root.__file__).read_text(encoding="utf-8")
    assert "EvidenceFirstVenueOrchestrator" not in source
    assert "VenueSemanticIndexer" not in source
    assert "SpecialIssueCrawlerOrchestrator" not in source
    assert "register_all_commands" in source
    assert "dispatch(" in source


def test_internal_venue_and_manuscript_products_are_not_shipped():
    import importlib

    for name in (
        "paperfetch.venue_ana",
        "paperfetch.manuscript",
        "paperfetch.api",
        "paperfetch.cli.venue",
        "paperfetch.cli.manuscript",
        "paperfetch.cli.key",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)
    from paperfetch.cli.system import CAPABILITIES

    for name in ("venue", "manuscript", "web"):
        assert name not in CAPABILITIES


def test_domain_register_and_dispatch_modules_exist():
    assert hasattr(register, "register_all_commands")
    assert hasattr(dispatch, "dispatch")


def test_retired_packages_are_gone():
    import importlib

    from paperfetch.core.code_audit import CodeAuditAction

    assert CodeAuditAction.__module__ == "paperfetch.core.code_audit"
    for name in (
        "paperfetch.acquisition",
        "paperfetch.tasks",
        "paperfetch.cli.legacy",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)
    from paperfetch.cli.system import CAPABILITIES

    assert "paper.acquire" not in CAPABILITIES
    assert "paper.acquire.oa" not in CAPABILITIES
    assert "paper.acquire.cst" not in CAPABILITIES
    assert "paper.download" in CAPABILITIES


def test_public_help_still_lists_core_commands(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    for name in ("paper", "seed-pack", "system", "doctor", "job"):
        assert name in help_text
    with pytest.raises(SystemExit) as paper_help:
        main(["paper", "--help"])
    assert paper_help.value.code == 0
    paper_text = capsys.readouterr().out
    assert "parse" in paper_text
    assert "download" in paper_text
