"""Repo 插件 Skill 必须与 SPC 2.0 CLI 同步。"""

from pathlib import Path
import re

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_research_acquisition_skill_uses_current_public_contract():
    root = Path(__file__).parents[1]
    skill = (
        root / "plugins" / "spc" / "skills" / "spc-research-acquisition" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "spc system preflight" in skill
    assert "spc.result.v2" not in skill  # Agent 只需读 schema 字段，不背内部版本名
    assert "lifecycle" not in skill.lower()
    assert "import-agent-reviews" not in skill
    assert "business_summary" not in skill
    assert "spc job wait" in skill
    assert "spc paper lookup" in skill
    assert "spc paper search" in skill
    assert "spc paper graph" in skill
    assert "spc seed-pack init" in skill
    assert "spc seed-pack add" in skill
    assert "spc paper parse" in skill
    assert "spc lookup" not in skill
    assert "spc get-references" not in skill
    assert "spc get-citations" not in skill
    assert "search-metadata" not in skill
    assert "sync-papervault" not in skill
    assert "add-seed-papers" not in skill
    assert "enrich-seed-pack" not in skill
    assert "--route cst" not in skill
    assert "spc validate cst" not in skill


def test_every_spc_command_documented_by_skill_has_real_parser_help(
    monkeypatch, capsys
):
    from paperfetch.cli.root import main

    root = Path(__file__).parents[1]
    skill = (
        root / "plugins" / "spc" / "skills" / "spc-research-acquisition" / "SKILL.md"
    ).read_text(encoding="utf-8")
    documented = {
        tuple(match.split())
        for match in re.findall(
            r"`spc ([a-z][a-z-]*(?: [a-z][a-z-]*){0,2})\b[^`]*`", skill
        )
    }
    # Commands with runtime placeholders are validated at their parser level.
    for command in sorted(documented):
        args = [*command, "--help"]
        with pytest.raises(SystemExit) as caught:
            main(args)
        assert caught.value.code == 0
        capsys.readouterr()
