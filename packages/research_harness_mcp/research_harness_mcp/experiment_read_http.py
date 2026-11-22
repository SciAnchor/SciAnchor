"""FastAPI route registration for read-only experiment loop views."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import FastAPI


def register_experiment_read_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> None:
    """Register experiment list and run history read routes."""

    @app.get("/api/topics/{topic_id}/experiments")
    def list_topic_experiments(topic_id: int):
        """Return autonomous-loop experiments for this topic, newest first."""
        with get_db_context() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT id, topic_id, name, task_description, primary_metric,
                           direction, mode, status, stopped_reason, best_run_id,
                           budget_json, created_at, updated_at
                    FROM experiments
                    WHERE topic_id = ?
                    ORDER BY created_at DESC
                    """,
                    (topic_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

            experiments = []
            for row in rows:
                experiment = row_to_dict(row)
                experiment["budget"] = parse_json_field(
                    experiment.pop("budget_json", None), {}
                )
                if experiment.get("best_run_id"):
                    try:
                        best = conn.execute(
                            "SELECT iteration, primary_metric_value, cost_usd, tokens_used "
                            "FROM experiment_loop_runs WHERE id = ?",
                            (experiment["best_run_id"],),
                        ).fetchone()
                        experiment["best"] = row_to_dict(best) if best else None
                    except sqlite3.OperationalError:
                        experiment["best"] = None
                else:
                    experiment["best"] = None
                experiments.append(experiment)

        return {"topic_id": topic_id, "experiments": experiments}

    @app.get("/api/experiments/{experiment_id}/runs")
    def list_experiment_runs(experiment_id: int):
        """Return per-iteration records for one experiment."""
        with get_db_context() as conn:
            try:
                experiment = conn.execute(
                    """
                    SELECT id, topic_id, name, primary_metric, direction, mode,
                           status, stopped_reason, best_run_id
                    FROM experiments WHERE id = ?
                    """,
                    (experiment_id,),
                ).fetchone()
                rows = conn.execute(
                    """
                    SELECT id, iteration, code_hash, primary_metric_value,
                           elapsed_sec, cost_usd, tokens_used, status, returncode,
                           stdout_tail, stderr_tail, feedback_to_next, created_at
                    FROM experiment_loop_runs
                    WHERE experiment_id = ?
                    ORDER BY iteration ASC
                    """,
                    (experiment_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                experiment, rows = None, []

        if experiment is None:
            return {"experiment": None, "runs": []}

        return {
            "experiment": row_to_dict(experiment),
            "runs": [row_to_dict(row) for row in rows],
        }
