"""FastAPI route registration for topic experiment creation."""

from typing import Any, Callable

from fastapi import FastAPI


def _experiment_loop(**kwargs: Any) -> Any:
    from research_harness.primitives.experiment_loop_impl import experiment_loop

    return experiment_loop(**kwargs)


def _experiment_budget(
    *,
    max_iterations: int,
    max_cost_usd: float,
    max_tokens: int,
    patience: int,
) -> Any:
    from research_harness.primitives.types import ExperimentBudget

    return ExperimentBudget(
        max_iterations=max_iterations,
        max_cost_usd=max_cost_usd,
        max_tokens=max_tokens,
        patience=patience,
    )


def register_topic_experiment_create_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Any],
    create_experiment_request_model: type[Any],
    experiment_loop_fn: Callable[..., Any] | None = None,
    experiment_budget_factory: Callable[..., Any] | None = None,
) -> None:
    """Register topic experiment create route with injected dependencies."""

    loop_fn = experiment_loop_fn or _experiment_loop
    budget_factory = experiment_budget_factory or _experiment_budget

    @app.post("/api/topics/{topic_id}/experiments")
    def create_topic_experiment(topic_id: int, req: create_experiment_request_model):
        from research_harness.storage.db import Database

        db = Database(db_path=db_path_provider())

        out = loop_fn(
            db=db,
            topic_id=topic_id,
            name=req.name,
            task_description=req.task_description,
            fixture_files=req.fixture_files,
            mutable_entry=req.mutable_entry,
            primary_metric=req.primary_metric,
            direction=req.direction,
            mode=req.mode,
            timeout_sec=req.timeout_sec,
            env_vars=req.env_vars,
            budget=budget_factory(
                max_iterations=req.max_iterations,
                max_cost_usd=req.max_cost_usd,
                max_tokens=req.max_tokens,
                patience=req.patience,
            ),
        )

        return {
            "experiment_id": out.experiment_id,
            "total_iterations": out.total_iterations,
            "best_iteration": out.best_iteration,
            "best_value": out.best_value,
            "best_run_id": out.best_run_id,
            "stopped_reason": out.stopped_reason,
            "total_cost_usd": out.total_cost_usd,
            "total_tokens": out.total_tokens,
        }
