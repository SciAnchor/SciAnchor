# RH research delivery protocol

This document describes the Research Harness research delivery protocol: the
stage-by-stage deliverables (brief, proposal, experiment, paper, review,
rebuttal) that carry a topic from scoping to submission.

## Positioning

Research Harness remains the evidence and state source of truth. RH owns topic
state, paper pools, claims, evidence links, recorded artifacts, gates, and
provenance. The delivery protocol adds workflow discipline on top of that state:
research briefs, idea evaluation, proposal formation, experiment planning,
review, paper packaging, presubmission audit, and rebuttal packaging.

The protocol has no external runtime dependency. It is expressed entirely as RH
artifacts, skills, and gates; it does not introduce installers, hooks, MCP
servers, separate runtime state, queue state, or credentials.
No storage schema migration is part of this protocol.
No new public MCP or CLI tool is introduced by this document.

## Entry modes

Use two RH-native entry modes:

| Mode | Meaning | RH handling |
|---|---|---|
| `protocol_call` | The user asks for a specific research-stage deliverable, such as an experiment plan or paper plan. | Execute the matching RH skill or primitive, then record the output with `orchestrator_record_artifact`. |
| `human_in_loop_call` | The user gives a judgment-level request without naming the stage. | Infer the affected RH stage, identify the missing or stale artifact, run the narrowest RH skill, and record the decision as provenance. |

Both modes must resolve back to RH stage, artifact, gate, and provenance
records. The agent should not leave the result only in chat text.

## Artifact mapping

These names are RH artifact conventions, not new database tables. They are
stable labels for outputs that RH skills may create, inspect, or package.

| deliverable | RH role |
|---|---|
| `RESEARCH_BRIEF` | Topic bootstrap artifact that captures scope, constraints, venue, success criteria, and seed evidence. |
| `IDEA_REPORT` | Candidate opportunity report grounded in the RH paper pool, claims, and weak spots. |
| `RESEARCH_PROPOSAL` | Selected direction with gap links, baseline expectations, assumptions, and evidence boundary. |
| `EVALUATION` | Go/no-go decision before experiment investment, including missing evidence and risks. |
| `EXPERIMENT_GOAL` | Claim-aligned question that an experiment should answer. |
| `EXPERIMENT_PLAN` | Experiment design, baselines, metrics, budget, stop rules, and failure criteria. |
| `IMPACT_REPORT` | Post-result summary tying observations to claims, limitations, and next actions. |
| `CLAIMS_FROM_RESULTS` | Evidence-strength-labeled claims derived from experiments or analysis. |
| `PAPER_PLAN` | Manuscript logic skeleton plus Claims-Evidence Matrix before section drafting. |
| `AUTO_REVIEW` | Structured review report over proposal, experiment, code, paper, or package readiness. |
| `PRESUBMISSION_AUDIT` | Strict final audit before submission-facing claims. |
| `PAPER_PACKAGE` | Reviewable manuscript package assembled from recorded RH artifacts. |
| `REBUTTAL_PACKAGE` | Reviewer-response package tied to review reports, paper revisions, and provenance. |

## Skill mapping

Existing RH skills carry the protocol instead of creating a separate
protocol surface:

- `research-init` creates or requests `RESEARCH_BRIEF` when a topic needs
  delivery-level scope, constraints, and success criteria.
- `gap-analysis` turns evidence-backed opportunities into `IDEA_REPORT`,
  `RESEARCH_PROPOSAL`, and `EVALUATION` candidates.
- `evidence-gating` checks whether protocol artifacts such as
  `EXPERIMENT_PLAN` or `PAPER_PLAN` are present and evidence-supported before
  stage advancement.
- `section-drafting` and `paper-writing` use `PAPER_PLAN` and the
  Claims-Evidence Matrix before drafting unsupported prose.
- `publication-pack` assembles `PAPER_PACKAGE` and `REBUTTAL_PACKAGE` only from
  recorded RH artifacts.
- `provenance-review` audits whether protocol deliverables were recorded as RH
  artifacts and linked to the right topic, stage, and evidence.

## Local replay contract

The local fixture
`packages/research_harness/tests/fixtures/workflows/delivery_protocol.json`
is the private replay contract for this protocol. It lists the required
artifacts, RH stages, gates, recording surface, entry modes, and boundary flags
that must remain true. The helper
`research_harness._selfdev.delivery_protocol.build_delivery_protocol_contract`
validates that the fixture still has both entry modes, all required artifact
records, owner-skill routing, and no public-surface/runtime dependency boundary
violation.

## Read-only Python snapshot

The first usable surface is
`ResearchAPI.delivery_paper_production_snapshot(...)`. It returns
`rh.delivery.paper_production_snapshot.v1` as a read-only, dry-run runbook
snapshot over caller-supplied artifact states, optional topic artifact state,
and payload dictionaries. When `topic_id` is provided, the method reads active
RH project artifacts for that topic, normalizes matching artifact-type labels,
and treats stale artifacts as blocked. Caller-supplied `artifact_states`
override topic-derived states so hypothetical dry-run snapshots remain
possible. The Python facade routes through the Python-only
`ResearchService` command `delivery_paper_production_snapshot`; the command
is not registered as public MCP, CLI, or HTTP transport. The method reports
status, next artifact/action, readiness records, summary counts, and blockers.
It also includes an `inputs` summary with normalized artifact-state keys,
source labels, payload keys, and counts, but not artifact payload contents or
stored artifact contents. It does not call `orchestrator_record_artifact`,
advance stages, write the database, call a provider, or open MCP, CLI, or HTTP
transport.

## Python usage example

Use `topic_id` for recorded topic state. Use `artifact_states` for
hypothetical overrides. The example does not record artifacts or advance
stages; it only asks RH what the next paper-production action
would be.

```python
from research_harness import ResearchAPI

api = ResearchAPI()
snapshot = api.delivery_paper_production_snapshot(
    topic_id=42,
    artifact_states={"RESEARCH_BRIEF": "active"},
    payloads={
        "IDEA_REPORT": {
            "schema_version": "rh.delivery.idea_report.v1",
            "recording_surface": "orchestrator_record_artifact",
            "public_surface": "none",
            "runtime_dependency": "none",
            "observed_problem": "Paper production can drift from evidence.",
            "candidate_opportunity": "Protocol-bound paper production.",
            "in_domain_evidence": ["paper:p1"],
            "cross_topic_analogies": [],
            "novelty_risks": ["needs stronger baseline positioning"],
            "evidence_anchors": ["paper:p1"],
            "support_status": "seeded",
            "missing_evidence_warnings": [],
            "promotion_blockers": [],
        }
    },
)

assert snapshot["dry_run"] is True
sources = snapshot["inputs"]["artifact_states"]["sources"]
```

## Non-goals

- Do not import external runtime code or make RH depend on it.
- Do not add a new public MCP tool, CLI command, or HTTP route for this
  protocol.
- Do not change storage schema, provenance ownership, or orchestrator gate
  semantics.
- Do not make benchmark, publication-readiness, or external deployment claims
  from this protocol text alone.
