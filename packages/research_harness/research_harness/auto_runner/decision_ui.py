"""Decision rendering helpers for Claude Code and Codex native UI."""

from __future__ import annotations

from typing import Any


def format_decision_for_ask_user_question(
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Format decision into AskUserQuestion format for Claude Code.

    Args:
        decision: Decision dict from paper_production_pending_decisions

    Returns:
        Dict with 'questions' list ready for AskUserQuestion tool
    """
    prompt = decision.get("prompt", "")
    options = decision.get("options", [])
    reason_code = decision.get("reason_code", "")
    recommended_action = decision.get("recommended_action")

    # Build header from reason code
    header_map = {
        "insufficient_seed_papers": "Evidence",
        "multiple_directions_available": "Direction",
        "budget_exceeds_threshold": "Budget",
    }
    header = header_map.get(reason_code, "Decision")

    # Build AskUserQuestion options
    auq_options = []
    for opt in options:
        action = opt.get("action", "")
        label = opt.get("label", action)
        description = opt.get("description", "")

        # Add visual indicators
        if opt.get("recommended"):
            label = f"⭐ {label} (Recommended)"
        if opt.get("default_action"):
            label = f"{label} [Default]"

        # Enhance description with expected effect and score
        enhanced_desc = description
        if opt.get("expected_effect"):
            enhanced_desc += f"\n\n→ {opt['expected_effect']}"
        if opt.get("preference_score") is not None:
            score = opt["preference_score"]
            enhanced_desc += f"\n\nAI confidence: {score:.0%}"

        auq_options.append(
            {
                "label": label,
                "description": enhanced_desc,
            }
        )

    # Build the question
    question = {
        "question": prompt,
        "header": header,
        "options": auq_options,
        "multiSelect": False,
    }

    return {
        "questions": [question],
        "metadata": {
            "source": "rh_decision",
            "reason_code": reason_code,
            "recommended_action": recommended_action,
        },
    }


def format_decision_for_cli_display(
    decision: dict[str, Any],
    *,
    colorize: bool = True,
) -> str:
    """Format decision for CLI text display (Codex or plain terminal).

    Args:
        decision: Decision dict from paper_production_pending_decisions
        colorize: Whether to add ANSI color codes

    Returns:
        Formatted string ready for print
    """
    prompt = decision.get("prompt", "")
    options = decision.get("options", [])
    interaction_mode = decision.get("interaction_mode", "checkpoint")

    # ANSI colors
    if colorize:
        BOLD = "\033[1m"
        DIM = "\033[2m"
        YELLOW = "\033[33m"
        GREEN = "\033[32m"
        BLUE = "\033[34m"
        RESET = "\033[0m"
    else:
        BOLD = DIM = YELLOW = GREEN = BLUE = RESET = ""

    lines = []

    # Header
    lines.append(f"\n{BOLD}{'=' * 70}{RESET}")
    lines.append(f"{BOLD}{YELLOW}🤔 DECISION REQUIRED{RESET}")
    lines.append(f"{BOLD}{'=' * 70}{RESET}\n")

    # Prompt
    lines.append(f"{prompt}\n")

    # Mode indicator
    mode_color = GREEN if interaction_mode == "autonomous" else BLUE
    lines.append(f"{DIM}Mode: {mode_color}{interaction_mode}{RESET}\n")

    # Options
    lines.append(f"{BOLD}Available options:{RESET}\n")
    for idx, opt in enumerate(options, 1):
        action = opt.get("action", "")
        label = opt.get("label", action)
        description = opt.get("description", "")

        # Visual indicators
        indicators = []
        if opt.get("recommended"):
            indicators.append(f"{GREEN}⭐ RECOMMENDED{RESET}")
        if opt.get("default_action"):
            indicators.append(f"{BLUE}[Default]{RESET}")

        indicator_str = " ".join(indicators)

        # Option header
        lines.append(f"{BOLD}{idx}. {label}{RESET}")
        if indicator_str:
            lines.append(f"   {indicator_str}")

        # Description
        lines.append(f"   {DIM}{description}{RESET}")

        # Expected effect
        if opt.get("expected_effect"):
            lines.append(f"   {DIM}→ {opt['expected_effect']}{RESET}")

        # Preference score
        if opt.get("preference_score") is not None:
            score = opt["preference_score"]
            bar_length = int(score * 20)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            lines.append(f"   AI confidence: {bar} {score:.0%}")

        lines.append("")  # Spacing

    # Footer
    lines.append(f"{BOLD}{'=' * 70}{RESET}\n")

    return "\n".join(lines)


def extract_action_from_selection(
    selection: dict[str, str],
    options: list[dict[str, Any]],
) -> str | None:
    """Extract action ID from AskUserQuestion selection.

    Args:
        selection: Dict from AskUserQuestion answers (e.g., {"question_text": "label"})
        options: Original options list

    Returns:
        Action ID or None if not found
    """
    if not selection:
        return None

    # Get the selected label
    selected_label = next(iter(selection.values()), "")

    # Strip indicators to match against original labels
    clean_label = (
        selected_label.replace("⭐ ", "")
        .replace(" (Recommended)", "")
        .replace(" [Default]", "")
    )

    # Find matching option
    for opt in options:
        if opt.get("label") == clean_label:
            return opt.get("action")
        # Also try exact match
        if opt.get("label") == selected_label:
            return opt.get("action")

    return None


def build_decision_summary(
    decision: dict[str, Any],
    choice: str,
    reasoning: str,
) -> str:
    """Build a human-readable summary of decision made.

    Args:
        decision: Original decision dict
        choice: Selected action
        reasoning: User's reasoning

    Returns:
        Formatted summary string
    """
    options = decision.get("options", [])
    selected_opt = next(
        (opt for opt in options if opt.get("action") == choice),
        None,
    )

    if not selected_opt:
        return f"Decision recorded: {choice}"

    label = selected_opt.get("label", choice)
    description = selected_opt.get("description", "")

    lines = [
        "✅ Decision recorded:",
        f"   Choice: {label}",
    ]

    if reasoning:
        lines.append(f"   Reasoning: {reasoning}")

    if description:
        lines.append(f"   What this does: {description}")

    return "\n".join(lines)


def format_feedback_prompt(
    stage: str,
    gate_passed: bool,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Format feedback collection prompt for AskUserQuestion.

    Args:
        stage: Current stage name
        gate_passed: Whether the gate passed
        context: Additional context

    Returns:
        AskUserQuestion format dict
    """
    status = "completed successfully" if gate_passed else "encountered issues"

    prompt = (
        f"The {stage} stage {status}. "
        "Any feedback to help RH improve this stage in future runs?"
    )

    # Provide common feedback templates as options
    options = [
        {
            "label": "No feedback needed",
            "description": "The stage worked as expected",
        },
        {
            "label": "Performance issue",
            "description": "Stage took too long or used too many resources",
        },
        {
            "label": "Quality concern",
            "description": "Output quality could be improved",
        },
        {
            "label": "Process suggestion",
            "description": "I have a suggestion for improving the workflow",
        },
        {
            "label": "Other (please explain)",
            "description": "Custom feedback",
        },
    ]

    return {
        "questions": [
            {
                "question": prompt,
                "header": "Feedback",
                "options": options,
                "multiSelect": False,
            }
        ],
        "metadata": {
            "source": "rh_feedback",
            "stage": stage,
            "gate_passed": gate_passed,
        },
    }


def format_status_display(
    status: dict[str, Any],
    pending_decision: dict[str, Any] | None = None,
) -> str:
    """Format orchestrator status for CLI display.

    Args:
        status: Result from orchestrator_status
        pending_decision: Optional pending decision info

    Returns:
        Formatted status string
    """
    lines = []

    # Header
    lines.append("\n" + "=" * 70)
    lines.append("📊 RESEARCH HARNESS STATUS")
    lines.append("=" * 70 + "\n")

    # Topic info
    topic = status.get("topic", {})
    if topic:
        lines.append(f"Topic: {topic.get('name', 'Unknown')}")
        if topic.get("description"):
            lines.append(f"Description: {topic['description']}")
        lines.append("")

    # Run info
    run = status.get("run", {})
    if run:
        lines.append(f"Current Stage: {run.get('current_stage', 'unknown')}")
        lines.append(f"Stage Status: {run.get('stage_status', 'unknown')}")
        lines.append("")

    # Gate status
    gate = status.get("gate", {})
    if gate:
        decision = gate.get("decision", "unknown")
        lines.append(f"Gate Decision: {decision}")

        if gate.get("can_advance"):
            lines.append("✅ Can advance to next stage")
        else:
            lines.append("⏸️  Cannot advance yet")

            # Show missing artifacts
            stage_info = status.get("stage", {})
            if stage_info and stage_info.get("missing_artifacts"):
                lines.append("\nMissing artifacts:")
                for artifact in stage_info["missing_artifacts"]:
                    lines.append(f"  - {artifact}")

        lines.append("")

    # Pending decision
    if pending_decision:
        lines.append("⚠️  PENDING DECISION:")
        lines.append(f"   {pending_decision.get('reason_code', 'unknown')}")
        lines.append("   Run /rh-decide to make a choice")
        lines.append("")

    # Budget info
    budget = status.get("budget", {})
    if budget and budget.get("estimated_total_cost"):
        cost = budget["estimated_total_cost"]
        lines.append(f"Estimated cost: ${cost:.2f}")
        if budget.get("warning"):
            lines.append(f"⚠️  {budget['warning']}")
        lines.append("")

    lines.append("=" * 70 + "\n")

    return "\n".join(lines)
