"""Experiment command group for the RH CLI."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


_AGENT_TEMPLATE_PROGRAM = """\
# Experiment: {name}

## Task
{description}

## Primary metric
- **Name:** {metric}
- **Direction:** {direction} (higher is better = max; lower is better = min)

## Fixtures (do NOT modify)
- `eval.jsonl` — evaluation set
- `scorer.py`  — grading logic; reads predictions, prints metrics

## What the LLM edits
- `main.py` — your implementation. Must print one line like:
  `{metric}: <float>`

## Budget
Filled from CLI flags: max_iterations, max_cost_usd, patience.
"""

_AGENT_TEMPLATE_EVAL = (
    '{"input": "2+2", "answer": "4"}\n{"input": "3*5", "answer": "15"}\n'
)

_AGENT_TEMPLATE_SCORER = '''\
"""Fixture scorer: reads eval.jsonl, runs the solver, prints metrics."""

import json
from pathlib import Path


def score(solver):
    correct = 0
    total = 0
    for line in Path("eval.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        try:
            pred = solver(item["input"])
        except Exception:  # noqa: BLE001
            pred = ""
        total += 1
        if str(pred).strip() == str(item["answer"]).strip():
            correct += 1
    acc = correct / total if total else 0.0
    print(f"val_acc: {acc:.4f}")
'''

_AGENT_TEMPLATE_MAIN = '''\
"""Mutable implementation. The LLM rewrites this each iteration."""

from scorer import score


def solve(question: str) -> str:
    # TODO: call your LLM / rule / tool here. Must return a string.
    return ""


if __name__ == "__main__":
    score(solve)
'''


_TRIVIAL_ARITHMETIC_RE = re.compile(r"^\s*\d+\s*[+\-*/]\s*\d+\s*$")


def _placeholder_fixture_error(fixtures: dict[str, str]) -> str | None:
    """Return an error message when eval.jsonl is still the scaffold placeholder.

    The scaffold ships a toy arithmetic eval set so the template runs out of
    the box; running a real topic experiment against it silently validates
    nothing, so it must be replaced before `experiment run` accepts it.
    """
    eval_text = fixtures.get("eval.jsonl")
    if eval_text is None:
        return None
    if eval_text == _AGENT_TEMPLATE_EVAL:
        return (
            "eval.jsonl is the unmodified scaffold placeholder (2+2 / 3*5). "
            "Replace it with topic-specific evaluation cases before running."
        )
    inputs: list[str] = []
    for line in eval_text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            return None  # not the placeholder shape; let the scorer surface it
        inputs.append(str(item.get("input", "")))
    if inputs and all(_TRIVIAL_ARITHMETIC_RE.match(text) for text in inputs):
        return (
            "every eval.jsonl input is trivial arithmetic (e.g. '2+2'), which "
            "matches the scaffold placeholder pattern. Replace eval.jsonl with "
            "topic-specific evaluation cases before running."
        )
    return None


def _load_scaffold(scaffold_dir: Path) -> tuple[str, dict[str, str], str]:
    """Return (task_description, fixture_files, mutable_code)."""
    program_md = (scaffold_dir / "program.md").read_text(encoding="utf-8")
    fixtures: dict[str, str] = {}
    for name in ("eval.jsonl", "scorer.py"):
        path = scaffold_dir / name
        if path.exists():
            fixtures[name] = path.read_text(encoding="utf-8")
    # Include any additional fixture files (read-only support: anything not main.py)
    for path in scaffold_dir.iterdir():
        if path.is_file() and path.name not in {"program.md", "main.py"}:
            fixtures.setdefault(path.name, path.read_text(encoding="utf-8"))
    mutable_path = scaffold_dir / "main.py"
    mutable_code = (
        mutable_path.read_text(encoding="utf-8") if mutable_path.exists() else ""
    )
    return program_md, fixtures, mutable_code


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
) -> None:
    """Register experiment commands on the root CLI group."""

    @main.group()
    def experiment() -> None:
        """Autonomous experiment iteration loop (CPU agent experiments)."""

    @experiment.command("scaffold")
    @click.option("--name", required=True, help="Experiment name.")
    @click.option(
        "--out",
        "out_dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=Path("./experiment_scaffold"),
        help="Output directory for the three-file template.",
    )
    @click.option(
        "--description",
        default="Agent experiment — edit main.py to beat the baseline.",
        help="Task description (written into program.md).",
    )
    @click.option("--metric", default="val_acc", help="Primary metric name.")
    @click.option(
        "--direction",
        type=click.Choice(["max", "min"]),
        default="max",
    )
    @click.pass_context
    def experiment_scaffold(
        ctx: click.Context,
        name: str,
        out_dir: Path,
        description: str,
        metric: str,
        direction: str,
    ) -> None:
        """Write a karpathy-style three-file experiment template.

        Produces program.md (task spec, read-only), eval.jsonl + scorer.py
        (fixtures) and main.py (mutable). Ready to feed into `rh experiment run`.
        """
        del ctx
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "program.md").write_text(
            _AGENT_TEMPLATE_PROGRAM.format(
                name=name,
                description=description,
                metric=metric,
                direction=direction,
            ),
            encoding="utf-8",
        )
        (out_dir / "eval.jsonl").write_text(_AGENT_TEMPLATE_EVAL, encoding="utf-8")
        (out_dir / "scorer.py").write_text(_AGENT_TEMPLATE_SCORER, encoding="utf-8")
        (out_dir / "main.py").write_text(_AGENT_TEMPLATE_MAIN, encoding="utf-8")

        click.echo(f"Wrote scaffold to {out_dir}")
        click.echo("  program.md   — task spec (read-only)")
        click.echo("  eval.jsonl   — fixture: evaluation set (PLACEHOLDER)")
        click.echo("  scorer.py    — fixture: grading logic")
        click.echo("  main.py      — mutable: the LLM rewrites this")
        click.echo("")
        click.echo(
            "WARNING: eval.jsonl contains toy placeholder cases; replace it "
            "with topic-specific evaluation data. `experiment run` refuses "
            "unmodified placeholders."
        )
        click.echo("")
        click.echo(
            f"Next: rh experiment run --topic <name> --scaffold {out_dir} "
            f"--metric {metric} --direction {direction}"
        )

    @experiment.command("run")
    @click.option("--topic", required=True, help="Topic name.")
    @click.option(
        "--scaffold",
        "scaffold_dir",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        required=True,
    )
    @click.option("--name", default="", help="Experiment display name.")
    @click.option("--metric", default="val_acc")
    @click.option("--direction", type=click.Choice(["max", "min"]), default="max")
    @click.option(
        "--mode",
        type=click.Choice(["strict", "agent"]),
        default="strict",
        help="Only strict runs; experiments are OS-confined with no network.",
    )
    @click.option("--max-iterations", type=int, default=5)
    @click.option("--max-cost-usd", type=float, default=0.0)
    @click.option("--patience", type=int, default=3)
    @click.option("--timeout-sec", type=float, default=300.0)
    @click.option(
        "--allow-placeholder-fixtures",
        is_flag=True,
        default=False,
        help="Skip the placeholder eval.jsonl guard (template smoke tests only).",
    )
    @click.pass_context
    def experiment_run_cmd(
        ctx: click.Context,
        topic: str,
        scaffold_dir: Path,
        name: str,
        metric: str,
        direction: str,
        mode: str,
        max_iterations: int,
        max_cost_usd: float,
        patience: int,
        timeout_sec: float,
        allow_placeholder_fixtures: bool,
    ) -> None:
        """Run experiment_loop on a scaffold directory."""
        from .primitives.experiment_loop_impl import experiment_loop
        from .primitives.types import ExperimentBudget

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic)
        finally:
            conn.close()

        task_description, fixtures, _mutable = _load_scaffold(scaffold_dir)

        placeholder_error = _placeholder_fixture_error(fixtures)
        if placeholder_error and not allow_placeholder_fixtures:
            raise click.ClickException(
                f"Refusing to run: {placeholder_error} "
                "(pass --allow-placeholder-fixtures only for template smoke tests)"
            )

        out = experiment_loop(
            db=db,
            topic_id=topic_id,
            name=name or scaffold_dir.name,
            task_description=task_description,
            fixture_files=fixtures,
            mutable_entry="main.py",
            primary_metric=metric,
            direction=direction,
            mode=mode,
            timeout_sec=timeout_sec,
            budget=ExperimentBudget(
                max_iterations=max_iterations,
                max_cost_usd=max_cost_usd,
                patience=patience,
            ),
        )

        click.echo(
            f"experiment_id={out.experiment_id} "
            f"iterations={out.total_iterations} "
            f"best_iter={out.best_iteration} best={out.best_value} "
            f"stopped={out.stopped_reason} cost=${out.total_cost_usd:.4f}"
        )
        for r in out.runs:
            click.echo(
                f"  #{r.iteration} {r.status:9s} {r.primary_metric_value} "
                f"({r.elapsed_sec:.1f}s, ${r.cost_usd:.3f})"
            )

    @experiment.command("list")
    @click.option("--topic", required=True)
    @click.pass_context
    def experiment_list(ctx: click.Context, topic: str) -> None:
        """List autonomous experiments for a topic."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic)
            try:
                rows = conn.execute(
                    "SELECT id, name, primary_metric, direction, status, stopped_reason,"
                    " best_run_id, created_at FROM experiments WHERE topic_id = ?"
                    " ORDER BY created_at DESC",
                    (topic_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        finally:
            conn.close()

        if not rows:
            click.echo(f"No experiments for topic {topic!r}.")
            return

        for r in rows:
            click.echo(
                f"[{r['id']}] {r['name']:<30s} "
                f"{r['primary_metric']:<12s} {r['direction']:<4s} "
                f"{r['status']:<10s} stopped={r['stopped_reason']}"
            )
