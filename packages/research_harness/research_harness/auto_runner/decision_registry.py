"""Decision point registry for Research Harness workflows.

Declarative definition of structured decision points that can pause
workflow for human input or auto-apply defaults in autonomous mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

DecisionHandler = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]
TriggerCheck = Callable[[dict[str, Any], dict[str, Any]], bool]


@dataclass(frozen=True)
class DecisionPoint:
    """Metadata for a structured decision point."""

    name: str
    stage: str  # Which stage this decision applies to
    checkpoint: str  # Decision checkpoint identifier
    reason_code: str  # Machine-readable reason code
    description: str  # Human-readable description
    trigger_check: TriggerCheck  # Function to check if decision is needed
    build_options: DecisionHandler  # Function to build decision options
    apply_handler: DecisionHandler  # Function to apply selected choice
    risk_level: Literal["low", "medium", "high"] = "medium"
    requires_human: bool = False  # If True, never auto-apply even in autonomous mode
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision handlers
# ---------------------------------------------------------------------------


def _trigger_insufficient_seed_papers(
    checkpoint_data: dict[str, Any],
    context: dict[str, Any],
) -> bool:
    """Check if seed paper count is below threshold."""
    seed_count = context.get("seed_count", 0)
    minimum = context.get("minimum_seed_paper_count", 10)
    return seed_count < minimum


def _build_evidence_acquisition_options(
    checkpoint_data: dict[str, Any],
    stage: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build options for evidence acquisition decision."""
    from .decision_helpers import build_decision_option, format_decision_prompt

    seed_count = context.get("seed_count", 0)
    minimum = context.get("minimum_seed_paper_count", 10)
    shortfall = minimum - seed_count

    broaden = build_decision_option(
        action="broaden_search",
        label="Expand to external providers",
        description=(
            "Enable semantic_scholar and pasa for broader coverage "
            "(requires network access)"
        ),
        recommended=True,
        preference_score=0.85,
        expected_effect=f"May find {shortfall}+ additional papers",
        default_action=True,
    )

    manual = build_decision_option(
        action="add_papers_manually",
        label="Add papers manually",
        description="Provide local papers or specific DOI/arXiv IDs",
        recommended=False,
        preference_score=0.4,
        expected_effect="Workflow pauses until papers are added",
    )

    stop = build_decision_option(
        action="stop",
        label="Stop workflow",
        description="Halt and require manual intervention",
        recommended=False,
        preference_score=0.1,
    )

    prompt = format_decision_prompt(
        situation=f"Found {seed_count} seed papers, need {minimum}.",
        question="How should we acquire more papers?",
        context={
            "current": seed_count,
            "required": minimum,
            "shortfall": shortfall,
        },
    )

    return {
        "prompt": prompt,
        "options": [broaden, manual, stop],
    }


def _apply_evidence_acquisition_decision(
    checkpoint_data: dict[str, Any],
    choice: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Apply evidence acquisition decision to checkpoint."""
    if choice == "broaden_search":
        policy = checkpoint_data.setdefault("paper_production_run_policy", {})
        if isinstance(policy, dict):
            policy["local_only"] = False
            policy.setdefault("external_actions", []).append("provider_fanout")

        stage_context = checkpoint_data.setdefault("stage_context", {})
        stage_context["local_only"] = False

        evidence_plan = stage_context.get("paper_production_evidence_plan")
        if isinstance(evidence_plan, dict):
            search_params = evidence_plan.setdefault("search_parameters", {})
            search_params["local_only"] = False
            search_params["provider_allowlist"] = ["semantic_scholar", "pasa"]
            evidence_plan["provider_mode"] = "expanded_provider_search"

        return {"applied": True, "next_action": "resume"}

    elif choice == "add_papers_manually":
        return {
            "applied": True,
            "next_action": "wait",
            "message": "Please add papers then run: rh paper-production resume",
        }

    elif choice == "stop":
        return {"applied": True, "next_action": "stop"}

    return {"applied": False, "error": f"Unknown choice: {choice}"}


def _trigger_direction_selection(
    checkpoint_data: dict[str, Any],
    context: dict[str, Any],
) -> bool:
    """Check if multiple research directions are available for selection."""
    direction_count = context.get("direction_proposal_count", 0)
    return direction_count > 1


def _build_direction_selection_options(
    checkpoint_data: dict[str, Any],
    stage: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build options for research direction selection."""
    from .decision_helpers import (
        build_decision_option,
        format_decision_prompt,
        rank_options_by_preference,
    )

    directions = context.get("direction_proposals", [])
    if not directions:
        return {"prompt": "No directions available", "options": []}

    # Build option for each direction with AI scoring
    options = []
    for idx, direction in enumerate(directions):
        novelty = direction.get("novelty_score", 0.5)
        feasibility = direction.get("feasibility_score", 0.5)
        # Combined preference: balance novelty and feasibility
        preference = (novelty * 0.6) + (feasibility * 0.4)

        option = build_decision_option(
            action=f"select_direction_{idx}",
            label=direction.get("title", f"Direction {idx + 1}"),
            description=direction.get("summary", ""),
            preference_score=preference,
            expected_effect=direction.get("expected_contribution", ""),
            metadata={
                "direction_id": direction.get("id"),
                "novelty_score": novelty,
                "feasibility_score": feasibility,
            },
        )
        options.append(option)

    # Rank and mark top as recommended
    options = rank_options_by_preference(options)

    prompt = format_decision_prompt(
        situation=f"Research analysis identified {len(directions)} promising directions.",
        question="Which direction should we pursue?",
        options_summary=(
            "Options are ranked by combined novelty and feasibility scores."
        ),
    )

    return {"prompt": prompt, "options": options}


def _apply_direction_selection(
    checkpoint_data: dict[str, Any],
    choice: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Apply direction selection to checkpoint."""
    if not choice.startswith("select_direction_"):
        return {"applied": False, "error": f"Invalid direction choice: {choice}"}

    try:
        idx = int(choice.split("_")[-1])
    except (ValueError, IndexError):
        return {"applied": False, "error": f"Cannot parse direction index: {choice}"}

    stage_context = checkpoint_data.setdefault("stage_context", {})
    stage_context["selected_direction_index"] = idx
    stage_context["direction_selection_confirmed"] = True

    return {"applied": True, "next_action": "advance"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

DECISION_REGISTRY: dict[str, DecisionPoint] = {
    "insufficient_seed_papers": DecisionPoint(
        name="insufficient_seed_papers",
        stage="init",
        checkpoint="paper_production_evidence_gate",
        reason_code="insufficient_seed_papers",
        description="Seed paper count below threshold for evidence acquisition",
        trigger_check=_trigger_insufficient_seed_papers,
        build_options=_build_evidence_acquisition_options,
        apply_handler=_apply_evidence_acquisition_decision,
        risk_level="medium",
        requires_human=False,
    ),
    "direction_selection": DecisionPoint(
        name="direction_selection",
        stage="analyze",
        checkpoint="research_direction_selection",
        reason_code="multiple_directions_available",
        description="Multiple research directions available, user must choose",
        trigger_check=_trigger_direction_selection,
        build_options=_build_direction_selection_options,
        apply_handler=_apply_direction_selection,
        risk_level="high",
        requires_human=True,  # Always require human for direction choice
    ),
}


def get_decision_point(reason_code: str) -> DecisionPoint | None:
    """Get decision point metadata by reason code."""
    return DECISION_REGISTRY.get(reason_code)


def check_decision_triggers(
    checkpoint_data: dict[str, Any],
    stage: str,
    context: dict[str, Any],
) -> list[str]:
    """Check which decision points are triggered for current state.

    Args:
        checkpoint_data: Current checkpoint state
        stage: Current workflow stage
        context: Additional context for trigger checks

    Returns:
        List of triggered decision point reason codes
    """
    triggered = []
    for reason_code, decision_point in DECISION_REGISTRY.items():
        if decision_point.stage != stage:
            continue
        try:
            if decision_point.trigger_check(checkpoint_data, context):
                triggered.append(reason_code)
        except Exception:
            # Trigger check failed, skip this decision point
            continue
    return triggered
