"""Unified interaction mode for Research Harness workflows.

Replaces the fragmented mode/autonomy/auto_approve trio with a single
interaction_mode parameter.
"""

from __future__ import annotations

from typing import Literal

InteractionMode = Literal["autonomous", "checkpoint", "interactive"]


def resolve_interaction_mode(
    *,
    mode: str | None = None,
    autonomy: str | None = None,
    auto_approve: bool = False,
    interaction_mode: str | None = None,
) -> InteractionMode:
    """Resolve the interaction mode from legacy or new parameters.

    Priority:
    1. Explicit interaction_mode parameter (new)
    2. Derived from mode/autonomy/auto_approve (legacy)

    Args:
        mode: Legacy mode parameter (standard/demo/strict)
        autonomy: Legacy autonomy parameter (supervised/autonomous)
        auto_approve: Legacy auto-approval flag
        interaction_mode: New unified parameter

    Returns:
        One of: "autonomous", "checkpoint", "interactive"
    """
    # New parameter takes precedence
    if interaction_mode:
        normalized = interaction_mode.lower()
        if normalized in ("autonomous", "checkpoint", "interactive"):
            return normalized  # type: ignore[return-value]

    # Legacy parameter derivation
    if mode in ("demo", "autonomous") or autonomy == "autonomous":
        return "autonomous"
    if auto_approve:
        return "autonomous"
    if mode == "strict":
        return "checkpoint"

    # Default: checkpoint (pause at structured decision points)
    return "checkpoint"


def should_pause_for_decision(
    interaction_mode: InteractionMode,
    decision_required: bool = False,
    risk_level: str = "low",
) -> bool:
    """Determine if workflow should pause for human decision.

    Args:
        interaction_mode: Current interaction mode
        decision_required: Whether this is a mandatory decision point
        risk_level: Risk level (low/medium/high)

    Returns:
        True if should pause and wait for human input
    """
    if interaction_mode == "autonomous":
        # Autonomous mode: only pause for critical decisions
        return decision_required and risk_level == "high"

    if interaction_mode == "checkpoint":
        # Checkpoint mode: pause at all structured decision points
        return decision_required

    # Interactive mode: pause for decisions and information requests
    return decision_required


def should_request_feedback(
    interaction_mode: InteractionMode,
    stage: str,
    gate_passed: bool = True,
) -> bool:
    """Determine if workflow should request optional feedback.

    Args:
        interaction_mode: Current interaction mode
        stage: Current stage name
        gate_passed: Whether the stage gate passed

    Returns:
        True if should prompt for feedback (non-blocking)
    """
    if interaction_mode == "autonomous":
        return False

    if interaction_mode == "checkpoint":
        # Only at stage boundaries
        return gate_passed and stage in ("analyze", "propose", "write")

    # Interactive mode: request feedback more frequently
    return gate_passed


def default_action_for_decision(
    interaction_mode: InteractionMode,
    options: list[dict],
) -> str | None:
    """Get the default action to apply in autonomous mode.

    Args:
        interaction_mode: Current interaction mode
        options: List of decision options with 'action' and optional 'default_action'

    Returns:
        Action name to apply, or None if should wait for human
    """
    if interaction_mode != "autonomous":
        return None

    # Look for explicitly marked default
    for option in options:
        if option.get("default_action"):
            return option.get("action")

    # Look for recommended option
    for option in options:
        if option.get("recommended"):
            return option.get("action")

    # Fallback to first option
    if options:
        return options[0].get("action")

    return None


def interaction_mode_description(mode: InteractionMode) -> str:
    """Get human-readable description of interaction mode."""
    descriptions = {
        "autonomous": (
            "Fully autonomous: AI makes all decisions, only pauses for critical "
            "high-risk choices. No feedback prompts."
        ),
        "checkpoint": (
            "Checkpoint mode: AI pauses at structured decision points for human "
            "approval, applies recommended defaults. Feedback requested at stage boundaries."
        ),
        "interactive": (
            "Interactive mode: AI can ask clarifying questions and request additional "
            "information throughout the workflow. Feedback encouraged."
        ),
    }
    return descriptions.get(mode, "Unknown interaction mode")
