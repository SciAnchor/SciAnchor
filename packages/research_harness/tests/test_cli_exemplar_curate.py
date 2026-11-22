"""CLI `rh exemplar curate` forwards MCP source-selection flags."""

from __future__ import annotations

from types import SimpleNamespace
import json
import pytest

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_exemplar import _parse_paper_ids


def test_parse_paper_ids() -> None:
    assert _parse_paper_ids(None) is None
    assert _parse_paper_ids("") is None
    assert _parse_paper_ids("1, 2 3") == [1, 2, 3]


def test_curate_help_exposes_source_flags() -> None:
    result = CliRunner().invoke(main, ["exemplar", "curate", "--help"])
    assert result.exit_code == 0, result.output
    assert "--min-tier-score" in result.output
    assert "--paper-ids" in result.output


def test_curate_forwards_min_tier_score_and_paper_ids(runner, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_curate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            unit_type=kwargs["unit_type"],
            candidates_seen=0,
            kept=0,
            rejected=0,
            model_used="test",
            units=[],
        )

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    result = runner.invoke(
        main,
        [
            "exemplar",
            "curate",
            "--topic",
            "1",
            "--unit-type",
            "intro_arc",
            "--min-tier-score",
            "0",
            "--paper-ids",
            "11,22",
            "--no-record",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["min_tier_score"] == 0
    assert captured["paper_ids"] == [11, 22]
    assert "seen=0 kept=0" in result.output


def test_curate_default_min_tier_score_is_85(runner, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_curate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            unit_type="intro_arc",
            candidates_seen=0,
            kept=0,
            rejected=0,
            model_used="test",
            units=[],
        )

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    result = runner.invoke(
        main,
        [
            "exemplar",
            "curate",
            "--topic",
            "1",
            "--unit-type",
            "intro_arc",
            "--no-record",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["min_tier_score"] == 85
    assert captured["paper_ids"] is None


@pytest.mark.parametrize(
    "unit", ["abstract_moves", "intro_moves", "discussion_moves", "skeleton", "style"]
)
@pytest.mark.parametrize("command", ["curate", "plan"])
def test_move_cli_forwards_profile_through_every_stage(
    runner, monkeypatch, command, unit
):
    profile = {"exemplar_family": "nature_medical", "prose_register": "medical_imrad"}
    calls = []

    def fake_curate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            unit_type=unit,
            units=[],
            kept=0,
            candidates_seen=0,
            rejected=0,
            model_used="test",
        )

    def fake_retrieve(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(ranked=[], rationale="control")

    def fake_plan(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(plan={})

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_retrieve", fake_retrieve
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_plan", fake_plan
    )
    args = [
        "exemplar",
        command,
        "--topic",
        "1",
        "--unit-type",
        unit,
        "--venue-profile",
        json.dumps(profile),
        "--no-record",
    ]
    if command == "plan":
        args += ["--target", "Fixed evidence"]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert len(calls) == (3 if command == "plan" else 1)
    assert all(call["venue_profile"] == profile for call in calls)


@pytest.mark.parametrize("profile", ["not-json", "[]", '"text"'])
def test_cli_rejects_non_object_profile_before_primitive(runner, monkeypatch, profile):
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate",
        lambda **kwargs: pytest.fail("no calls"),
    )
    result = runner.invoke(
        main,
        [
            "exemplar",
            "curate",
            "--topic",
            "1",
            "--unit-type",
            "style",
            "--venue-profile",
            profile,
            "--no-record",
        ],
    )
    assert result.exit_code == 2 and "venue-profile" in result.output
