---
name: rh-continue
description: Smart workflow continuation - checks for pending decisions, presents them if needed, then resumes. One-command flow from paused to running.
trigger: Use when user types /rh-continue or asks "continue", "keep going", "resume workflow"
public_suite: paper
task_type: workflow
data_access_level: local-files
inputs: topic_id (optional, auto-detected)
outputs: workflow resumed or decision made
gates: same as underlying commands
artifact_schemas: workflow_status, human_decision_request, gate_decision
estimated_runtime: 30s-5min (depends on pending decisions)
---

# RH Continue - Smart Workflow Resume

## Purpose

Intelligent workflow continuation that handles the common pattern:
1. Check status
2. If decision pending → present options → apply choice
3. If no blockers → resume workflow
4. Report what happened

This is the "just make it work" command for users who don't want
to manually chain /rh-status → /rh-decide → resume.

## When to Use

- User types `/rh-continue`
- User says "continue", "keep going", "resume", "next"
- Workflow is paused and user wants to proceed
- After manually fixing something (e.g., adding papers)

## Core Logic

```python
from research_harness_mcp import tools as rh
from research_harness.auto_runner.decision_ui import (
    format_decision_for_ask_user_question,
    extract_action_from_selection,
    build_decision_summary,
)

def rh_continue(topic_id: int, auto_mode: bool = False):
    """Smart continuation with decision handling.

    Args:
        topic_id: Topic to continue
        auto_mode: If True, apply recommended defaults without asking
    """

    # Step 1: Check status
    status = rh.orchestrator_status(topic_id=topic_id)
    print(f"📊 Current stage: {status.get('run', {}).get('current_stage')}")

    # Step 2: Check for pending decisions
    decisions = rh.paper_production_pending_decisions(topic_id=topic_id)

    if decisions.get("has_pending"):
        decision = decisions["decision"]
        print(f"\n⚠️  Decision required: {decision.get('reason_code')}")

        if auto_mode:
            # Auto mode: apply recommended or default action
            recommended = decision.get("recommended_action")
            default = decision.get("default_action")
            choice = recommended or default

            if not choice:
                print("❌ No default action available, switching to interactive mode")
                auto_mode = False
            else:
                print(f"🤖 Auto-applying: {choice}")
                result = rh.paper_production_decide(
                    topic_id=topic_id,
                    choice=choice,
                    reasoning="Auto-applied recommended action via /rh-continue",
                )
                print(build_decision_summary(decision, choice, result.get("reasoning", "")))

        if not auto_mode:
            # Interactive mode: present options
            auq_format = format_decision_for_ask_user_question(decision)
            answers = AskUserQuestion(questions=auq_format["questions"])

            choice = extract_action_from_selection(answers, decision["options"])
            if not choice:
                print("❌ Could not determine selection. Aborting.")
                return

            result = rh.paper_production_decide(
                topic_id=topic_id,
                choice=choice,
                reasoning="Selected via /rh-continue",
            )
            print(build_decision_summary(decision, choice, ""))

    # Step 3: Check if can advance
    gate_info = status.get("gate", {})
    if not gate_info.get("can_advance"):
        missing = status.get("stage", {}).get("missing_artifacts", [])
        if missing:
            print(f"\n⏸️  Cannot advance - missing artifacts: {', '.join(missing)}")
            print("Fix these issues then run /rh-continue again")
            return
        else:
            print("\n⏸️  Gate not passed. Check gate decision:")
            print(f"   {gate_info.get('decision', 'unknown')}")
            return

    # Step 4: Resume workflow
    print("\n▶️  Resuming workflow...")
    try:
        resume_result = rh.orchestrator_resume(topic_id=topic_id)
        print(f"✅ Workflow resumed: {resume_result.get('stage', 'unknown')} stage")

        # Optionally: auto-advance if gate passed
        if gate_info.get("can_advance"):
            print("   Advancing to next stage...")
            advance_result = rh.orchestrator_advance(topic_id=topic_id)
            next_stage = advance_result.get("to_stage", "unknown")
            print(f"   → Now in {next_stage} stage")

    except Exception as e:
        print(f"❌ Resume failed: {e}")
        print("Run /rh-status for diagnostics")
```

## Usage Modes

### Interactive (default)

```bash
/rh-continue
```

Presents decisions if needed, then resumes.

### Auto mode

```bash
/rh-continue --auto
```

Applies recommended defaults without asking. Useful for:
- Trusted workflows
- Scripted runs
- When you want AI to handle routine decisions

### Specific topic

```bash
/rh-continue --topic 5
```

## Output Examples

### Example 1: Has pending decision

```
User: /rh-continue

📊 Current stage: init

⚠️  Decision required: insufficient_seed_papers

[AskUserQuestion shows options]
User selects: "Expand to external providers"

✅ Decision recorded:
   Choice: Expand to external providers
   What this does: Enable semantic_scholar and pasa

▶️  Resuming workflow...
✅ Workflow resumed: build stage
   Advancing to next stage...
   → Now in build stage

💡 Workflow is running. Use /rh-status to check progress.
```

### Example 2: No blockers, direct resume

```
User: /rh-continue

📊 Current stage: analyze
✅ No pending decisions

▶️  Resuming workflow...
✅ Workflow resumed: analyze stage
   Advancing to next stage...
   → Now in propose stage

💡 Workflow is running. Use /rh-status to check progress.
```

### Example 3: Auto mode

```
User: /rh-continue --auto

📊 Current stage: init

⚠️  Decision required: insufficient_seed_papers
🤖 Auto-applying: broaden_search

✅ Decision recorded:
   Choice: Expand to external providers

▶️  Resuming workflow...
✅ Workflow resumed: build stage
```

### Example 4: Blocked by missing artifacts

```
User: /rh-continue

📊 Current stage: analyze

⏸️  Cannot advance - missing artifacts: direction_proposal, baseline_matrix

Fix these issues then run /rh-continue again

💡 The current stage needs to complete before advancing.
   Run /rh-status for details.
```

## Error Handling

- **No topic found**: Prompt user to select or start a workflow
- **Decision apply fails**: Show error, suggest manual /rh-decide
- **Resume fails**: Show error, suggest checking logs
- **Multiple blockers**: Prioritize: decision > missing artifacts > gate > unknown

## Best Practices

1. **Use /rh-status first** for complex diagnostics
2. **Use --auto mode** only when you trust the workflow
3. **Check output** to confirm workflow actually resumed
4. **Don't spam**: If continue fails twice, use /rh-status to diagnose
5. **Combine with /rh-feedback**: Give feedback after major milestones

## Integration

- **Calls /rh-decide** internally if decision pending
- **Calls orchestrator_resume** to actually continue
- **Calls orchestrator_advance** if gate allows
- **Reports to /rh-status** level diagnostics on failure

## Skill Metadata

- **Frequency**: High (main progress command)
- **Criticality**: High (primary workflow driver)
- **User satisfaction**: Very high (convenience)
- **Automation potential**: Medium (auto mode available)
