"""Tests for the coverage / manuscript diagnostic CLI entry points (P-1..P-7 ①).

The diagnostics built in this round — blocker attribution, acquisition yield
trend, manuscript measurement — were only reachable from Python. During a run
the operator and the agent both need them at the command line; a diagnostic
that requires writing a script does not get consulted mid-run, which is how the
2026-08-08 session ended up hand-counting a manuscript after the fact.

These commands are read-only. They must not mutate state or require an LLM.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from research_harness.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


SAMPLE_TEX = r"""
\documentclass{article}
\begin{document}
\section{Introduction}
Prose citing \cite{a2024} and \cite{b2023}. See Figure~\ref{fig:one}.
\begin{figure}\includegraphics{a.png}\caption{A}\label{fig:one}\end{figure}
\begin{figure}\includegraphics{b.png}\caption{B}\label{fig:two}\end{figure}
\end{document}
"""


def test_paper_measure_reports_manuscript_metrics(runner, tmp_path) -> None:
    (tmp_path / "paper.tex").write_text(SAMPLE_TEX, encoding="utf-8")
    result = runner.invoke(main, ["--json", "paper", "measure", str(tmp_path)])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    m = payload["measurements"]
    assert m["figure_asset_count"] == 2
    # The signal the postmortem was about: assets exist, prose references one.
    assert m["figure_narrative_reference_count"] == 1
    assert m["unreferenced_figure_labels"] == ["fig:two"]
    assert m["unique_citation_keys"] == 2


def test_paper_measure_human_output_shows_the_two_figure_numbers(
    runner, tmp_path
) -> None:
    """Asset count and narrative-reference count must be visibly distinct —
    printing one number invites exactly the misreading this round fixed."""
    (tmp_path / "paper.tex").write_text(SAMPLE_TEX, encoding="utf-8")
    result = runner.invoke(main, ["paper", "measure", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "figure assets" in result.output.lower()
    assert "referenced" in result.output.lower()


def test_paper_measure_on_missing_directory_fails_clearly(runner, tmp_path) -> None:
    result = runner.invoke(main, ["paper", "measure", str(tmp_path / "nope")])
    assert result.exit_code != 0
    assert "no .tex" in result.output.lower() or "not" in result.output.lower()


def test_topic_coverage_reports_blockers_and_yield(runner, monkeypatch) -> None:
    """The mid-run question is 'how far, blocked by what, and is fetching still
    working?' — one command must answer all three."""
    from research_harness import cli_topic_read

    fake_audit = {
        "topic_id": 73,
        "counts": {"coverage_eligible": 11, "total_linked": 137},
        "coverage_blockers": {
            "eligible": 11,
            "required": 50,
            "shortfall": 39,
            "repairable_papers": 125,
            "shortfall_closable_by_repair": True,
            "blockers": [{"blocker": "metadata_unusable", "papers": 55}],
            "single_blocker_ranking": [
                {"blocker": "metadata_unusable", "papers": 31, "repairable": True}
            ],
        },
    }
    monkeypatch.setattr(
        cli_topic_read, "_coverage_audit_for_cli", lambda ctx, topic: fake_audit
    )

    result = runner.invoke(main, ["--json", "topic", "coverage", "73"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["coverage_blockers"]["shortfall"] == 39
    assert "acquisition_yield" in payload

    human = runner.invoke(main, ["topic", "coverage", "73"])
    assert human.exit_code == 0, human.output
    # The actionable line: which single repair converts the most papers.
    assert "metadata_unusable" in human.output
    assert "31" in human.output
