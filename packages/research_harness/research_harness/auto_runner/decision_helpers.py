"""Helper functions for building structured human decision requests (v2)."""

from __future__ import annotations

from typing import Any


def build_decision_option(
    *,
    action: str,
    label: str,
    description: str,
    recommended: bool = False,
    preference_score: float | None = None,
    expected_effect: str = "",
    default_action: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 decision option with AI recommendations.

    Args:
        action: Machine-readable action identifier (e.g., "broaden_search", "stop")
        label: Human-readable option label (e.g., "Expand to external providers")
        description: Detailed explanation of what this option does
        recommended: Whether this is the AI's recommended choice
        preference_score: AI's confidence/preference for this option (0.0-1.0)
        expected_effect: Brief description of expected outcome
        default_action: Whether this is the default in autonomous mode
        metadata: Additional option-specific data

    Returns:
        v2 decision option dict
    """
    option = {
        "action": action,
        "label": label,
        "description": description,
        "recommended": recommended,
        "default_action": default_action,
    }

    if preference_score is not None:
        option["preference_score"] = max(0.0, min(1.0, preference_score))

    if expected_effect:
        option["expected_effect"] = expected_effect

    if metadata:
        option["metadata"] = dict(metadata)

    return option


def rank_options_by_preference(
    options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort options by preference_score descending, mark top as recommended.

    Args:
        options: List of decision options

    Returns:
        Sorted options with top option marked as recommended
    """
    if not options:
        return []

    # Sort by preference_score if present, otherwise keep original order
    sorted_options = sorted(
        options,
        key=lambda opt: opt.get("preference_score", 0.0),
        reverse=True,
    )

    # Mark top option as recommended if it has a score
    if sorted_options[0].get("preference_score") is not None:
        sorted_options[0]["recommended"] = True

    return sorted_options


def add_continue_option(
    options: list[dict[str, Any]],
    *,
    label: str = "Continue",
    description: str = "Proceed with current plan",
    recommended: bool = True,
) -> list[dict[str, Any]]:
    """Add a 'continue' option to decision options.

    Common pattern: when AI suggests a plan, human can approve or modify.
    """
    continue_opt = build_decision_option(
        action="continue",
        label=label,
        description=description,
        recommended=recommended,
        preference_score=0.8,
        default_action=True,
    )
    return [continue_opt, *options]


def add_stop_option(
    options: list[dict[str, Any]],
    *,
    label: str = "Stop workflow",
    description: str = "Halt and require manual intervention",
) -> list[dict[str, Any]]:
    """Add a 'stop' option to decision options.

    Always placed last, never recommended or default.
    """
    stop_opt = build_decision_option(
        action="stop",
        label=label,
        description=description,
        recommended=False,
        preference_score=0.0,
        default_action=False,
    )
    return [*options, stop_opt]


def format_decision_prompt(
    *,
    situation: str,
    question: str,
    options_summary: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """Build a well-formatted decision prompt.

    Args:
        situation: Current situation or problem description
        question: The decision question
        options_summary: Optional summary of available choices
        context: Additional context data to include

    Returns:
        Formatted prompt text
    """
    parts = [situation.strip()]

    if context:
        context_lines = []
        for key, value in context.items():
            if isinstance(value, (int, float)):
                context_lines.append(f"- {key}: {value}")
            else:
                context_lines.append(f"- {key}: {value}")
        if context_lines:
            parts.append("\nContext:\n" + "\n".join(context_lines))

    parts.append(f"\n{question}")

    if options_summary:
        parts.append(f"\n{options_summary}")

    return "\n".join(parts)


def extract_decision_metadata(
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    """Extract relevant metadata for decision-making from checkpoint.

    Args:
        checkpoint_data: Current checkpoint state

    Returns:
        Metadata dict with context for decision prompts
    """
    metadata = {}

    # Topic context
    if "topic_id" in checkpoint_data:
        metadata["topic_id"] = checkpoint_data["topic_id"]

    stage_context = checkpoint_data.get("stage_context", {})
    if isinstance(stage_context, dict):
        if "direction" in stage_context:
            metadata["research_direction"] = stage_context["direction"]
        if "target_venue" in stage_context:
            metadata["target_venue"] = stage_context["target_venue"]

    # Budget context
    budget = checkpoint_data.get("budget", {})
    if isinstance(budget, dict):
        if "estimated_total_cost" in budget:
            metadata["estimated_cost_usd"] = budget["estimated_total_cost"]
        if "warning" in budget:
            metadata["budget_warning"] = budget["warning"]

    # Run policy
    run_policy = checkpoint_data.get("paper_production_run_policy", {})
    if isinstance(run_policy, dict):
        if "interaction_mode" in run_policy:
            metadata["interaction_mode"] = run_policy["interaction_mode"]
        if "local_only" in run_policy:
            metadata["local_only"] = run_policy["local_only"]

    return metadata
