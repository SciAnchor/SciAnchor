# RH Workflow Wrapper Contracts

Status: active.

These contracts productize the deterministic golden workflows as private
skill/runtime orchestration wrappers. They are operational contracts for skills
and local tests, not new public RH APIs.

The fixture source is
`packages/research_harness/tests/fixtures/workflows/lg15_workflow_wrappers.json`.

## No New Public Surface

The workflow wrappers add no MCP tools, CLI commands, HTTP routes, Python facade methods, or
advertised skills. Wrapper execution is private skill/runtime orchestration
over existing public tools and service-backed commands.

The wrapper fixture does not call real Zotero, network providers, real LLMs, Cloud,
benchmark services, or third-party resources. All evidence comes from
focused tests, local SQLite state, fixture/fake backend outputs, service
`next_actions`, project artifacts, provenance rows, and orchestrator gate reads.

## Failure Recovery

Wrappers recover from incomplete evidence in this order:

1. Use service `next_actions` from the last successful command.
2. Use orchestrator gate output when the wrapper is gate-oriented.
3. Write a handoff note that names missing topic, paper, primitive result,
   provenance, artifact, next-action, or gate evidence.
4. Refresh the run checkpoint before continuing or reporting a blocker.

The workflow contract should report an error status for missing local evidence
instead of inventing records or silently skipping recovery.

## Research Wiki Preflight

Research rerun, experiment design, method improvement, gap/opportunity analysis,
and paper writing workflows must try the paper-card-derived Research Wiki
context pack before using local synthesis notes. The auto-runner records a
checkpoint-safe `research_wiki_preflight.v1` summary in `stage_context` before
the `analyze`, `propose`, `experiment`, and `write` stage tools execute.

If `paper_wiki_status` is `loaded`, `research_wiki` is the priority evidence
layer and ordinary markdown synthesis must not be silently substituted. If the
status is `unavailable` or `not_triggered`, fallback evidence is allowed only
when the reason is declared in the workflow output or handoff.

## Provenance And Artifact Rules

Each wrapper must preserve both sides of the local audit loop:

- Provenance rows are written only by the existing tracked service/backend
  path.
- Artifacts are recorded through existing service result artifacts or
  `orchestrator_record_artifact`.
- Wrapper records must include a topic, at least one topic-linked paper, at
  least one primitive result, at least one provenance row, at least one
  artifact reference, and at least one next action.
- Gate-oriented wrappers must include an orchestrator gate decision.
- Fixture evidence must stay local and deterministic.

## Wrapper Contracts

### `delivery_protocol`

Validate the RH research delivery protocol as a private fixture-only
contract. The fixture maps deliverables to RH stages, gates,
and `orchestrator_record_artifact` without adding public tools or importing
external runtime code.

Composed tools: none. This is a static contract guard over
`docs/research-delivery-protocol.md`,
`packages/research_harness/tests/fixtures/workflows/delivery_protocol.json`,
and `research_harness._selfdev.delivery_protocol`.

Required records: `protocol_call`, `human_in_loop_call`, all required protocol
artifact labels, RH stage mapping, gate mapping, and no public-surface/runtime
dependency boundary violations.

### `literature_search_ingest`

Search fixture papers, ingest topic-linked evidence, record a literature-map artifact, and expose recovery through service next actions plus gate output.

Composed tools: `paper_search`, `paper_ingest`,
`orchestrator_record_artifact`, `orchestrator_gate_check`.

Required records: topic, paper, primitive result, provenance, artifact,
next actions, and gate decision.

Recovery starts from `service_next_actions` and falls back to
`orchestrator_gate`.

### `evidence_to_draft`

Convert fixture claims, gaps, baselines, and draft output into an auditable draft artifact with source-linked next actions.

Composed tools: `claim_extract`, `gap_detect`, `baseline_identify`,
`section_draft`, `orchestrator_record_artifact`.

Required records: topic, paper, primitive result, provenance, artifact, and
next actions.

Recovery starts from `service_next_actions` and falls back to the workflow
handoff.

### `artifact_provenance_gate_audit`

Audit fixture primitive provenance, workflow artifacts, and orchestrator gate output as a closed local recovery record.

Composed tools: `consistency_check`, `orchestrator_record_artifact`,
`orchestrator_gate_check`.

Required records: topic, paper, primitive result, provenance, artifact,
next actions, and gate decision.

Recovery starts from `orchestrator_gate` and falls back to
`service_next_actions`.

## Boundary

Allowed:

- private skill/runtime orchestration contracts;
- fixture/fake primitive execution in focused tests;
- local SQLite topics, papers, artifacts, provenance, and gate reads;
- self-dev gate, handoff, and checkpoint records.

Excluded:

- MCP tool, CLI command, HTTP route, Python facade, or advertised skill
  additions;
- public payload-shape changes;
- real Zotero sync/apply, real LLM calls, network search, Cloud submission, or
  third-party writes;
- public benchmark or performance claims;
- commits, pushes, PRs, releases, publishing, credential mutation, or public
  internet deployment.
