---
name: rh-status
description: Show Research Harness workflow status including current stage, gate status, pending decisions, and next actions. Quick diagnostic for "where are we now?"
trigger: Use when user types /rh-status or asks "what's the status", "where are we", "what's next"
public_suite: paper
task_type: diagnostic
data_access_level: local-files
inputs: topic_id (optional, auto-detected)
outputs: formatted status display
gates: none
artifact_schemas: workflow_status, gate_report, human_decision_request
estimated_runtime: 5-15s
---

# RH Status - Workflow Diagnostic

## Purpose

Provide a concise, actionable status summary of Research Harness workflows.
Shows current stage, gate decision, missing artifacts, pending decisions,
and recommended next actions.

## When to Use

- User types `/rh-status`
- User asks "what's the status?", "where are we?", "what's next?"
- Before calling `/rh-decide` or `/rh-continue`
- After any major workflow action to confirm state
- When debugging blocked workflows

## Implementation

One call. `topic_state` returns the complete picture — resolved DB and state
trees, orchestrator stage/gate, checkpoint, pending decision, blockers, and a
computed `next_action` — so no stitching is needed.

```python
# Get topic_id (auto-detect or from args; see rh-decide skill for detection logic)
state = topic_state(topic_id=TOPIC_ID)          # public MCP tool
payload = state["output"]                        # rh.topic_state.v1

topic = payload["topic"]
checkpoint = payload["checkpoint"]
next_action = payload["next_action"]

print(f"Topic: {topic['name']} (id {topic['id']})")
print(f"Stage: {checkpoint.get('current_stage')} / {checkpoint.get('stage_state')}")
if payload["blockers"]:
    print("Blockers: " + ", ".join(payload["blockers"]))
if payload.get("pending_decision"):
    print(f"⚠️  PENDING DECISION: {payload['pending_decision']['reason_code']}")
nonempty = [t for t in payload["state_trees"] if t["pool_db_bytes"] > 0]
if len(nonempty) > 1:
    print(f"⚠️  {len(nonempty)} non-empty state trees — split-brain risk (rh doctor)")

print(f"💡 Next action [{next_action['code']}]: {next_action['summary']}")
for cmd in next_action["commands"]:
    print(f"   -> {cmd}")
```

CLI fallback (identical payload):

```bash
rh --json topic state --topic <id>
```

## Output Format

```
======================================================================
📊 RESEARCH HARNESS STATUS
======================================================================

Topic: Temporal Graph Neural Networks
Description: Dynamic GNN with causal attention for time-series

Current Stage: analyze
Stage Status: in_progress

Gate Decision: needs_approval
⏸️  Cannot advance yet

Missing artifacts:
  - direction_proposal
  - baseline_matrix

⚠️  PENDING DECISION:
   multiple_directions_available
   Run /rh-decide to make a choice

Estimated cost: $12.50

======================================================================

💡 Next action: /rh-decide to make a choice
```

## Compact Mode

For quick checks, support `--compact` flag:

```python
# Compact output (one-liner)
stage = status.get("run", {}).get("current_stage", "unknown")
gate = status.get("gate", {}).get("decision", "unknown")
has_pending = bool(pending)

print(f"[{stage}] Gate: {gate} | Pending: {has_pending}")
# Output: [analyze] Gate: needs_approval | Pending: True
```

## JSON Mode

For programmatic use:

```python
import json

output = {
    "topic_id": topic_id,
    "status": status,
    "pending_decision": pending,
    "recommended_action": _determine_next_action(status, pending),
}

print(json.dumps(output, indent=2))
```

## Best Practices

1. **Always check before deciding**: Run /rh-status before /rh-decide
2. **Show next action**: Don't leave users guessing what to do
3. **Highlight blockers**: Make missing artifacts obvious
4. **Budget awareness**: Show cost if it's tracking
5. **Detect stale states**: Warn if workflow hasn't progressed in >1 hour

## Integration

- **Before /rh-decide**: Confirm decision is actually pending
- **After /rh-continue**: Verify workflow resumed
- **In /rh-feedback**: Show which stage feedback applies to
- **Error recovery**: Diagnose why workflow is stuck

## Skill Metadata

- **Frequency**: High (multiple times per session)
- **Criticality**: Medium (diagnostic only, doesn't block)
- **User satisfaction**: High (clear visibility)
- **Automation potential**: Can auto-run before other commands
