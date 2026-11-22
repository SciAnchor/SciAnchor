---
name: rh-self-evolution
description: Record RH workspace human feedback, accepted agent proposals, repeated agent-observed failures, and confirmed workflow bugs into a durable self-evolution backlog, then repair Research Harness mechanisms in explicit batch self-evolution sessions rather than interrupting active research work.
public_suite: review
task_type: workflow-optimization
data_access_level: local-files
inputs: human feedback, accepted agent proposal, repeated failure evidence, logic bug, affected RH module
outputs: optimization target, mechanism patch, feedback note, regression check, Codex sync result
gates: human feedback is an absolute trigger; agent-discovered issues require repetition, clear logic bug, evidence/provenance risk, or verified workflow blocker
artifact_schemas: process_feedback, review_issue, gate_check, ADVISOR_FEEDBACK_INGEST
estimated_runtime: 5-30 min
---

# RH Self Evolution

Use this skill when a Research Harness workflow should improve itself, not only
repair the current output.

## Workspace Trigger

When the current work happens under a path containing `rh-workspace/`, treat the
session as RH-backed research work. Reusable feedback and confirmed workflow
defects should be recorded into a self-evolution backlog first, not synchronously
patched during the active paper or experiment task. The active research task
continues as a topic-specific fix unless the user explicitly asks to enter a
self-evolution repair session.

The Research Harness source repository remains the source of truth for later
batch repairs:

```text
<path-to-research-harness>
```

Codex-local skill folders such as `~/.codex/skills` are consumer surfaces, not
the source of truth.

## Trigger Policy

### Human Feedback: Absolute Capture Trigger

Human feedback always triggers self-evolution capture when it expresses:

- dissatisfaction with an RH output;
- a correction to quality, evidence, workflow, or tool routing;
- a durable preference or rule;
- acceptance of an agent-proposed rule or quality criterion;
- a request that future RH behavior should change.

Do not handle this as chat-only memory. Prefer durable RH capture over chat memory:

- topic-bound human feedback → `rh self-evolution record-human-feedback`
- self-dev / cross-agent reflections with no topic (or optional topic) →
  `rh self-evolution record-note --note "..."` (D3 non-MCP intake)
- if neither CLI path is available → open a GitHub Issue

During active paper work, stop after capture and continue the paper-specific
repair. Patch RH mechanisms only in a later explicit batch self-evolution
session, or when the user explicitly says to fix RH now.

### Agent-Discovered Issues: Cautious Trigger

Codex-discovered issues should mutate RH mechanisms only when at least one
condition holds:

- the same failure mode has appeared repeatedly and affected quality;
- the issue is an unambiguous logic bug;
- the issue risks evidence leakage, provenance loss, claim-boundary confusion,
  or durable workflow corruption;
- the issue blocks a verified RH workflow.

Speculative improvements and one-off taste concerns should be recorded as local
notes or review issues first, not immediately promoted to mechanism changes.

## Advisor Feedback Ingest

When advisor, reviewer, PI, or stakeholder feedback diagnoses unclear writing,
concept sprawl, weak logic, promise/result mismatch, or reader confusion, capture
it as `ADVISOR_FEEDBACK_INGEST` before patching mechanisms.

Required fields:

```yaml
ADVISOR_FEEDBACK_INGEST:
  raw_feedback_source: <transcript|meeting notes|review|email|chat summary>
  recurring_failure_pattern: <what failed across outputs, not just one sentence>
  affected_skill: <manuscript-logic-gate|paper-writing|section-drafting|publication-pack|other>
  current_topic_repair: <smallest repair for the active paper or topic>
  proposed_gate_update: <schema field, gate rule, prompt rule, or regression check>
  reusable_backlog_item: <durable RH behavior change>
  regression_check: <how the same failure becomes harder to repeat>
```

For writing feedback, default the owning surface to `manuscript-logic-gate` when
it concerns the core claim, argument tree, terminology, reader confusion,
enumeration, title/abstract/result alignment, or material-to-argument mapping.
Default to `paper-writing` when it concerns track/profile selection or prose
workflow order. Default to `publication-pack` when the issue is submission or
review readiness.

## Required Capture Loop During Research Work

During an active paper, experiment, or topic-production task, perform only this
capture loop:

1. Restate the feedback or failure in concrete terms.
2. Classify the trigger as `human_feedback`,
   `accepted_agent_proposal`, `repeated_agent_observation`, or `logic_bug`.
3. Translate it into a reusable RH optimization target.
4. Route it to the owning RH module: skill, workflow prompt, artifact schema,
   gate, script, MCP route, documentation, or runtime code.
5. Record capture with trigger, suspected root cause, owning surface, and
   suggested regression check:
   - topic available → `rh self-evolution record-human-feedback`
   - no topic / self-dev reflection → `rh self-evolution record-note`
   - CLI unavailable → open a GitHub Issue
6. Return to the current research artifact and apply a topic-specific fix when
   needed.

When diagnosing a self-evolution regression against distilled strategy text,
prefer the raw-trajectory path first (D5):

```bash
rh self-evolution trajectory-list --topic <name>
rh self-evolution trajectory-show --session <id>
rh self-evolution trajectory-diff --session-a <id> --session-b <id>
```

Do not patch `research-harness`, update generic RH skills, or run broad RH
regression suites inside the paper loop unless the user explicitly requests a
self-evolution repair pass.

## Batch Repair Loop

When the user explicitly asks to process the self-evolution backlog or fix RH
itself, perform the durable mechanism loop:

1. Select backlog items by severity and repetition.
2. Patch the owning RH mechanism in `research-harness`.
3. Record the trigger, root cause, mechanism patch, and regression check in
   the GitHub Issue or pull request description.
4. Add or update a focused regression check when feasible.
5. If Codex-visible skills, agent profiles, or workflow docs
   changed, run `scripts/sync-rh-to-codex.sh`.

## Branch Policy

Use the local branch `self-eov` for this policy family unless the user asks for
another branch:

```bash
git -C <path-to-research-harness> checkout -B self-eov
```

Do not push, open a PR, publish, or mutate remote resources without an explicit
user request.

## Output Contract

When feedback appears during active research work, keep the response concise:

1. state that the reusable issue was captured for the self-evolution backlog;
2. name the owning RH surface when clear;
3. continue the current paper/topic-specific repair.

When running an explicit batch self-evolution repair session, report:

1. `RH 优化目标`
2. `失败模式诊断`
3. `机制更新方案`
4. `持久化位置`
5. `回归验证方式`
6. `当前任务处理`

Keep the report concise unless the user asks for a full implementation plan.

## Regression Checks

A valid self-evolution patch should make the same failure harder to repeat.
Acceptable checks include a prompt gate, checklist item, unit test, eval
fixture, artifact schema field, or review focus.

Minimum checks:

- human feedback from `rh-workspace/` is captured into a self-evolution backlog
  when reusable;
- active paper/topic work is not interrupted by synchronous RH mechanism patches
  unless the user explicitly requests an RH repair pass;
- agent-discovered issues are not promoted unless repeated or clearly buggy;
- evidence/provenance/claim-boundary risks are recorded as mechanism-level
  backlog items even when handled locally for the current topic;
- Codex-visible RH updates run `scripts/sync-rh-to-codex.sh` or an installed
  local hook during batch repair;
- topic-specific rules do not leak into generic RH skills;
- advisor/reviewer writing feedback is split into an active topic repair and a
  reusable mechanism patch through `ADVISOR_FEEDBACK_INGEST`;
- manuscript writing feedback that mentions reader confusion, concept sprawl,
  overloaded enumeration, or title/abstract/result mismatch routes to the
  expanded `manuscript-logic-gate` artifacts instead of being handled as prose
  polishing only.
