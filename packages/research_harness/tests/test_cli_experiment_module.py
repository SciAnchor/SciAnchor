"""Shape-lock tests for the split CLI experiment command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_experiment import register


def test_cli_experiment_module_exports_register() -> None:
    assert callable(register)
    assert "experiment" in main.commands


def test_experiment_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "scaffold": ["--name", "--out", "--description", "--metric", "--direction"],
        "run": [
            "--topic",
            "--scaffold",
            "--name",
            "--metric",
            "--direction",
            "--mode",
            "--max-iterations",
            "--max-cost-usd",
            "--patience",
            "--timeout-sec",
        ],
        "list": ["--topic"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["experiment", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_experiment_scaffold_output_shape_is_preserved(
    runner: CliRunner, tmp_path
) -> None:
    scaffold_dir = tmp_path / "scaffold"

    result = runner.invoke(
        main,
        [
            "experiment",
            "scaffold",
            "--name",
            "demo-exp",
            "--out",
            str(scaffold_dir),
            "--description",
            "Demo task.",
            "--metric",
            "score",
            "--direction",
            "min",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"Wrote scaffold to {scaffold_dir}",
        "  program.md   — task spec (read-only)",
        "  eval.jsonl   — fixture: evaluation set (PLACEHOLDER)",
        "  scorer.py    — fixture: grading logic",
        "  main.py      — mutable: the LLM rewrites this",
        "",
        "WARNING: eval.jsonl contains toy placeholder cases; replace it "
        "with topic-specific evaluation data. `experiment run` refuses "
        "unmodified placeholders.",
        "",
        f"Next: rh experiment run --topic <name> --scaffold {scaffold_dir} --metric score --direction min",
    ]
    assert "Experiment: demo-exp" in (scaffold_dir / "program.md").read_text(
        encoding="utf-8"
    )
    assert "Primary metric\n- **Name:** score" in (
        scaffold_dir / "program.md"
    ).read_text(encoding="utf-8")
    assert (scaffold_dir / "eval.jsonl").read_text(encoding="utf-8") == (
        '{"input": "2+2", "answer": "4"}\n{"input": "3*5", "answer": "15"}\n'
    )
    assert "def solve(question: str) -> str:" in (scaffold_dir / "main.py").read_text(
        encoding="utf-8"
    )


def test_experiment_list_empty_db_output_shape(runner: CliRunner) -> None:
    create = runner.invoke(main, ["topic", "init", "exp-topic"])
    assert create.exit_code == 0, create.output

    result = runner.invoke(main, ["experiment", "list", "--topic", "exp-topic"])

    assert result.exit_code == 0, result.output
    assert result.output == "No experiments for topic 'exp-topic'.\n"
