---
name: rh-decide
description: Interactive decision making for Research Harness workflows. Detects pending decisions, presents options with AI recommendations using native UI, and records human choices.
trigger: Use when user types /rh-decide or when a paper-production workflow is paused at a decision point
public_suite: paper
task_type: human-in-loop
data_access_level: local-files
inputs: topic_id (optional, auto-detected from context)
outputs: decision recorded, workflow can resume
gates: decision must match available options
artifact_schemas: human_decision_request.v2
estimated_runtime: 30s-2min (user input time)
---

# RH Decide - Interactive Decision Making

## Purpose

Present pending Research Harness decisions to users using Claude Code's native
`AskUserQuestion` UI or Codex's selection interface, collect human choices, and
apply them to resume workflows.

## When to Use

- User types `/rh-decide`
- A paper-production workflow is paused with status "paused" or "blocked"
- You detect a `needs_human` or `pending_decision` state
- User asks "what should I do next" or "how do I proceed"

## Core Behavior

1. **Auto-detect topic**: Check conversation context for active RH topic
2. **Fetch pending decisions**: Call `paper_production_pending_decisions(topic_id)`
3. **Present options**: Use AskUserQuestion with:
   - Clear question text from the decision prompt
   - Options showing recommended choice (⭐), preference scores, expected effects
   - Visual indicators for default actions
4. **Collect reasoning**: Optionally ask "Why did you choose this?" for audit trail
5. **Apply decision**: Call `paper_production_decide(topic_id, choice, reasoning)`
6. **Show next steps**: Display what happens next and how to resume

## Implementation

```python
# Step 1: Get pending decisions
from research_harness_mcp import tools as rh

decisions = rh.paper_production_pending_decisions(topic_id=TOPIC_ID)

if not decisions.get("has_pending"):
    print("✅ No pending decisions. Workflow can continue.")
    print(f"Run: rh paper-production resume --topic {TOPIC_ID}")
    return

decision = decisions["decision"]

# Step 2: Format for AskUserQuestion
from research_harness.auto_runner.decision_ui import format_decision_for_ask_user_question

auq_format = format_decision_for_ask_user_question(decision)

# Step 3: Present to user
answers = AskUserQuestion(questions=auq_format["questions"])

# Step 4: Extract chosen action
from research_harness.auto_runner.decision_ui import extract_action_from_selection

choice = extract_action_from_selection(answers, decision["options"])

if not choice:
    print("❌ Could not determine selection. Please try again.")
    return

# Step 5: Optional - ask for reasoning
reasoning_prompt = {
    "questions": [{
        "question": f"Why did you choose '{choice}'? (Optional, helps RH learn)",
        "header": "Reasoning",
        "options": [
            {"label": "Skip reasoning", "description": "No explanation needed"},
            {"label": "Provide reasoning", "description": "I'll explain why"},
        ],
        "multiSelect": False,
    }]
}

reasoning_choice = AskUserQuestion(questions=reasoning_prompt["questions"])
reasoning = ""

if "Provide reasoning" in str(reasoning_choice):
    # Ask for free-form reasoning
    print("Please explain your reasoning:")
    # (In practice, could use another AskUserQuestion with text input,
    #  or instruct user to type it in next message)

# Step 6: Apply decision
result = rh.paper_production_decide(
    topic_id=TOPIC_ID,
    choice=choice,
    reasoning=reasoning
)

# Step 7: Show summary and next steps
from research_harness.auto_runner.decision_ui import build_decision_summary

summary = build_decision_summary(decision, choice, reasoning)
print(summary)

if result.get("next_steps"):
    print("\n📋 Next steps:")
    for step in result["next_steps"]:
        print(f"  • {step}")
```

## Topic Detection

If user doesn't provide topic_id, auto-detect:

1. Check conversation history for recent `topic_id` mentions
2. Look for recent `rh paper-production start` command output
3. Call `rh topic_list` and use most recently active topic
4. If multiple topics: use AskUserQuestion to let user pick

```python
def detect_topic_id(conversation_context):
    # Try conversation context first
    # (Implementation depends on available context)

    # Fallback: list topics and pick most recent
    topics = rh.topic_list()
    if not topics:
        return None

    if len(topics) == 1:
        return topics[0]["id"]

    # Multiple topics: ask user
    options = [
        {
            "label": f"{t['name']} (#{t['id']})",
            "description": t.get('description', '')[:100]
        }
        for t in topics[:5]  # Limit to 5 most recent
    ]

    answer = AskUserQuestion(questions=[{
        "question": "Which topic do you want to decide for?",
        "header": "Topic",
        "options": options,
        "multiSelect": False,
    }])

    # Extract topic_id from selection
    # ...
```

## Error Handling

- **No pending decisions**: Inform user, show how to check status
- **Invalid selection**: Show error, re-present options
- **Apply failure**: Show error message, suggest manual intervention
- **Network error**: Retry with exponential backoff

## Codex Adaptation

For Codex (which doesn't have AskUserQuestion), use CLI display:

```python
from research_harness.auto_runner.decision_ui import format_decision_for_cli_display

# Format and print to terminal
cli_output = format_decision_for_cli_display(decision, colorize=True)
print(cli_output)

# Then wait for user to type their choice or use Codex's native input
```

## Examples

### Example 1: Seed Papers Decision

```
User: /rh-decide

🤔 DECISION REQUIRED
==============================================================================

Found 3 seed papers, need 10.

Mode: checkpoint

Available options:

⭐ 1. Expand to external providers [RECOMMENDED] [Default]
   Enable semantic_scholar and pasa for broader coverage (requires network)
   → May find 7+ additional papers from semantic_scholar and pasa
   AI confidence: ████████████████░░░░ 85%

2. Add papers manually
   Provide local papers or specific DOI/arXiv IDs
   → Workflow pauses until papers are added
   AI confidence: ████████░░░░░░░░░░░░ 40%

3. Stop workflow
   Halt and require manual intervention
   AI confidence: ██░░░░░░░░░░░░░░░░░░ 10%

==============================================================================

[AskUserQuestion shows these options]
User selects: "Expand to external providers"

✅ Decision recorded:
   Choice: Expand to external providers
   What this does: Enable semantic_scholar and pasa for broader coverage

📋 Next steps:
  • Decision 'broaden_search' recorded successfully
  • Resume workflow with: orchestrator_resume(topic_id=1)
  • Or check status: orchestrator_status(topic_id=1)
```

### Example 2: Direction Selection

```
User: /rh-decide

🤔 DECISION REQUIRED
==============================================================================

Research analysis identified 3 promising directions.

Which direction should we pursue?

Options are ranked by combined novelty and feasibility scores.

Available options:

⭐ 1. Temporal Graph Attention with Causal Masking [RECOMMENDED]
   Combines self-attention with strict causality for time-series forecasting
   → Novel architecture addressing temporal leakage in GNNs
   AI confidence: ████████████████████ 92%

2. Hierarchical Dynamic Pooling
   Multi-scale temporal aggregation with learnable pooling
   → Incremental improvement over existing temporal pooling methods
   AI confidence: ███████████████░░░░░ 75%

3. Event-Driven Graph Evolution
   Sparse update propagation triggered by event detection
   → High novelty but uncertain feasibility with current datasets
   AI confidence: ████████████░░░░░░░░ 60%

==============================================================================

[User selects option 1]

✅ Decision recorded:
   Choice: Temporal Graph Attention with Causal Masking
   Reasoning: Highest novelty+feasibility score, fits our NeurIPS target

📋 Next steps:
  • Direction selected, proceeding to propose stage
  • Baseline identification will begin
  • Experiment design phase coming next
```

## Best Practices

1. **Always show AI recommendations**: Don't hide preference scores
2. **Explain expected effects**: Help users understand consequences
3. **Preserve reasoning**: Even brief explanations improve self-learning
4. **Show what's next**: Users should know what happens after decision
5. **Make it fast**: Auto-detect topic, minimize steps to decision

## Integration with Other Skills

- Use `/rh-status` first to check if decision is needed
- After decision, consider `/rh-continue` to auto-resume
- Pair with `/rh-feedback` at stage boundaries

## Skill Metadata

- **Frequency**: Multiple times per paper-production run
- **Criticality**: High (blocks workflow progress)
- **User satisfaction**: Depends on clear option presentation
- **Automation potential**: High in autonomous mode, zero in checkpoint mode
