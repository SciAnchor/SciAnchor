"""Internal evaluator candidates for promoted Research Harness capabilities.

Evaluators are internal capability runners managed by replay and promotion
gates. They are not user-facing workflow skills; those live in the repository
top-level ``skills/`` directory and are installed into agent hosts.
"""

from .runtime import (
    Evaluator,
    EvaluatorResult,
    register_evaluator,
    run_evaluator,
    supported_evaluators,
)

__all__ = [
    "Evaluator",
    "EvaluatorResult",
    "register_evaluator",
    "run_evaluator",
    "supported_evaluators",
]
