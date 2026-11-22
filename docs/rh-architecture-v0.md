# Research Harness Architecture v0

Status: draft for rebuild planning

This document defines the target architecture for rebuilding Research Harness
(RH) after disabling the legacy RH skill surface. It is intentionally
contract-first: implementation details can change, but every runtime path must
preserve typed inputs, typed outputs, provenance, guardrails, and replayable
evaluation traces.

## Goals

RH should become a research agent harness plus a research evaluation harness,
not a loose collection of skills and Python scripts.

The target system must:

- Run research workflows through stable execution contracts.
- Keep skill instructions small, testable, and progressively loadable.
- Record enough trace data to debug, grade, replay, and optimize agent runs.
- Gate scientific writing with domain-specific mechanism checks, not only
  surface-level quality scoring.
- Reuse strong open-source skills and tools before building RH-specific
  implementations.
- Support self-evolution through bounded skill edits, held-out replay, and
  rollback.
- Preserve human authority for external publication, destructive actions, and
  promotion of new capabilities.

## Design References

The rebuild follows these external design ideas:

- Anthropic-style agent evaluation: separate task, trial, grader, trace,
  outcome, evaluation harness, and agent harness.
- Anthropic/Agent Skills style capability packaging: a skill is a folder with
  instructions plus optional scripts, references, assets, and tests, loaded by
  progressive disclosure.
- OpenAI Agents SDK style guardrails: input, tool, and output checks can block
  or transform execution.
- OpenAI tracing and trace grading: record the end-to-end run, then grade the
  trace to identify failures and regressions.
- SkillOpt-style optimization: treat a compact skill artifact as trainable
  external state, update it through bounded edits, and accept only validated
  improvements.
- MUSE-Autoskill-style lifecycle: create, remember, manage, evaluate, and
  refine skills as long-lived assets.

Reference URLs:

- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- https://github.com/anthropics/skills
- https://github.com/agentskills/agentskills
- https://openai.github.io/openai-agents-python/tracing/
- https://openai.github.io/openai-agents-js/guides/guardrails
- https://platform.openai.com/docs/guides/trace-grading
- https://arxiv.org/abs/2605.23904
- https://arxiv.org/abs/2605.27366

## Non-Goals

This rebuild does not require RH to invent every capability itself.

RH should not:

- Copy large external projects into core without attribution and isolation.
- Make prompts the only source of truth for policy or validation.
- Let MCP or CLI adapters own workflow logic.
- Optimize against hidden benchmark information that real users cannot provide.
- Promote skill edits based on one successful trajectory.
- Treat polished prose as sufficient evidence of scientific correctness.

## Architecture

```text
Clients and agents
  CLI | MCP | HTTP API | Codex | Claude Code | OpenAI Agents | other harnesses
        |
Interface adapters
  Thin request/response adapters, auth, parameter validation, envelopes
        |
Control plane
  Topics, projects, bounded stage graph, gates, approvals, budgets, stop policies
        |
Runtime plane
  RunSpec -> ContextAssembler -> CapabilityResolver -> ToolRuntime -> ArtifactWriter
        |
Guardrail and judge plane
  Input guardrails | tool guardrails | output guardrails | mechanism judges
        |
Artifact plane
  Typed artifacts, lineage, versions, staleness, reproducibility metadata
        |
Evaluation and evolution plane
  RHBench, trace grading, failure taxonomy, skill optimization, promotion, rollback
        |
Storage and observability
  SQLite first, Postgres-ready schema, traces, costs, latency, audit log
```

## Planes

### Interface Adapters

Adapters expose RH to external agents and users. They must remain thin.

Allowed responsibilities:

- Convert CLI/MCP/HTTP input into `RunSpec` or typed primitive calls.
- Validate basic argument shape.
- Enforce permission boundaries.
- Return a consistent envelope with success, data, error, next actions, and
  trace/artifact IDs.

Forbidden responsibilities:

- Owning stage progression rules.
- Constructing hidden context outside the runtime contract.
- Running ad hoc scripts without trace registration.
- Embedding scientific writing policy in adapter code.

### Control Plane

The control plane owns workflow state and readiness decisions.

Core objects:

- `Topic`: research domain and paper pool boundary.
- `Project`: publishable research effort inside a topic.
- `WorkflowRun`: one orchestrated run with mode, stage, budget, and stop policy.
- `StageNode`: a workflow graph node such as retrieval, analysis, writing, or PDF.
- `GateDecision`: pass, block, warn, or require human approval.
- `HumanOverride`: explicit user action with rationale and timestamp.

The existing orchestrator is currently a 6-stage bounded graph with explicit
self-loops and loopback edges. A generalized user-editable DAG is [planned], but
not the current contract. Today, writing failures may loop back to experiment
through configured gate rules without restarting the whole project.

### Runtime Plane

Every meaningful operation must run through a `RunSpec`.

```yaml
run_spec:
  schema_version: rh.run.v0
  run_id: string
  task_type: retrieval | analysis | writing | rendering | evaluation | evolution
  topic_id: integer
  project_id: integer | null
  objective: string
  visible_inputs:
    user_brief: object
    artifact_refs: []
    literal_inputs: object
  forbidden_inputs:
    - hidden_gold
    - original_target_sections
    - benchmark_reference_outputs
  capability_policy:
    allowed_capabilities: []
    allowed_tools: []
    denied_tools: []
    max_cost_usd: number | null
    max_wall_time_s: integer | null
  guardrails:
    input: []
    tool: []
    output: []
  required_outputs:
    - artifact_type: string
      schema: string
      required: true
  trace_policy:
    record_llm_calls: true
    record_tool_calls: true
    record_guardrails: true
    record_artifacts: true
    include_sensitive_data: false
```

Runtime stages:

1. Validate `RunSpec`.
2. Assemble context from visible inputs and referenced artifacts.
3. Resolve capabilities from primitive registry, skill catalog, and external
   adapters.
4. Validate the `RunSpec` against the resolved `CapabilityManifest`, including
   allowed tools, forbidden tools, required artifacts, required outputs, and
   required guardrails.
5. Run input guardrails.
6. Execute the selected capability through a traced runtime.
7. Run tool guardrails around every tool call where applicable.
8. Write typed artifacts.
9. Run output guardrails and domain judges.
10. Persist `RunTrace`.
11. Return only stable artifact IDs and summary diagnostics.

Runner checkpoints may carry either a fully materialized runtime contract or a
compact promoted-skill reference:

```yaml
runtime_contract:
  skill_name: final-bundle-quality
  execute_skill: true
  artifact_refs:
    - artifact:final_bundle:716
  objective: Evaluate the active final_bundle.
  literal_inputs:
    mode: quality_scan
```

Before tool dispatch, the stage executor expands this into
`capability_manifest` plus `run_spec` from the skill package's `skill.yaml`.
When `execute_skill` is true, dispatch treats the contract as a direct skill
invocation: it validates the run against the skill's abstract allowed tools,
runs the registered evaluator runtime, and records the produced artifact instead
of applying the normal stage-policy tool list.

Current callable evaluator:

- `final-bundle-quality`: reads a `final_bundle` artifact, scans TeX/PDF/log
  paths with the deterministic PDF quality scanner, groups blocking,
  recompile-repairable, layout, and encoding issues, then records a
  `final_bundle_quality_report` artifact linked to the source bundle.

Callable evaluators are registered through `research_harness.evaluator.runtime`
rather than through one-off dispatch branches. The historical
`research_harness.evaluator.runtime` is the internal evaluator entrypoint. A successful evaluator execution now
records:

- the declared output artifact, such as `final_bundle_quality_report`
- a sidecar `run_trace` artifact containing the run spec hash, guardrail step,
  evaluator tool-call step, artifact-write step, output artifact IDs, and error
  diagnostics when applicable
- a `runtime_trace_grade` artifact that checks run-id binding, run-spec hash
  binding, required trace steps, tool policy, and required output artifacts

The grade artifact is the promotion/replay boundary: future lifecycle gates
should trust a successful evaluator only when both the domain report and the
trace grade pass.

### Capability Plane

RH has four kinds of capabilities:

| Capability | Description | Example |
| --- | --- | --- |
| Primitive | Typed operation callable by runtime | `paper_search`, `citation_sanitize` |
| Skill | Agent-facing procedure package | `scientific-writing-judge` |
| Adapter | Wrapper around external code or tools | `paperqa2.grounded_qa` |
| Evaluator | Guardrail, grader, or replay gate callable by runtime | `final-bundle-quality` |

All four must register through one capability catalog.

```yaml
capability:
  name: citation-evidence.resolve
  version: 0.1.0
  type: primitive | skill | adapter | evaluator
  owner: core | external | pro
  license: MIT | Apache-2.0 | unknown | proprietary
  input_schema: rh.schema.input.citation_evidence.v0
  output_schema: rh.schema.artifact.evidence_pack.v0
  required_artifacts: []
  produced_artifacts: []
  allowed_tools: []
  guardrails: []
  tests: []
  eval_profiles: []
```

### Artifact Plane

Artifacts are the stable data interface between agents, primitives, skills,
judges, and evals.

Required artifact metadata:

```yaml
artifact:
  artifact_id: integer
  artifact_type: string
  schema_version: string
  topic_id: integer
  project_id: integer | null
  run_id: string
  created_at: string
  producer:
    capability_name: string
    capability_version: string
    model: string | null
  payload: object
  lineage:
    source_artifact_ids: []
    source_paper_ids: []
    source_claim_ids: []
  validation:
    schema_valid: boolean
    guardrail_results: []
    judge_results: []
  staleness:
    stale: boolean
    stale_reason: string | null
```

Core writing artifacts:

- `topic_brief`
- `target_profile`
- `method_card`
- `result_card`
- `citation_pool`
- `evidence_pack`
- `claim_ledger`
- `draft_pack`
- `figure_table_spec`
- `figure_bundle`
- `latex_bundle`
- `pdf_bundle`
- `mechanism_report`
- `quality_report`
- `publication_pack`

## Skill Package Standard v2

Legacy RH skills are disabled. New RH skills should use a stricter package
standard.

```text
skills/<name>/
  SKILL.md
  skill.yaml
  contracts/
    input.yaml
    output.yaml
    guardrails.yaml
  references/
  scripts/
  tests/
  examples/
  attribution.md
```

`SKILL.md` is a short entry point. It should define when to use the skill,
which contract to load, and which scripts or references are relevant. It should
not be a long handbook or the only source of policy.

`skill.yaml` is the authoritative machine-readable manifest.

```yaml
name: scientific-writing-judge
version: 0.1.0
license: MIT
capability_type: evaluator
description: Verify scientific manuscript outputs against evidence and writing contracts.
input_schema: rh.schema.input.writing_judge.v0
output_schema: rh.schema.artifact.mechanism_report.v0
allowed_tools:
  - artifact.read
  - citation.verify
forbidden_tools:
  - paper.search.open_world
required_artifacts:
  - draft_pack
  - claim_ledger
  - citation_pool
guardrails:
  input:
    - no_hidden_gold
  output:
    - mechanism_report_schema
graders:
  deterministic:
    - citation_key_exists
    - number_grounded
  model_based:
    - overclaiming_check
replay_tests:
  - rhbench.writing.dev
promotion_policy:
  mechanism_veto_rate_max: 0.0
  held_out_regression_allowed: false
source_attribution:
  external_sources: []
```

## Scientific Writing Contract

The writing contract is the domain-specific "soul" that every writing skill and
judge must inherit.

```text
The system is not inventing research.
The system converts provided method cards, result cards, evidence packs,
citation pools, and figure/table assets into a valid manuscript.

Forbidden:
- invent citations
- invent methods, experiments, baselines, datasets, or numerical results
- claim novelty not present in the method card
- cite papers for claims they do not support
- hide missing evidence with polished prose
- move result interpretation beyond the result card

Required:
- every factual claim traces to paper_id, claim_id, artifact_id, method_card, or result_card
- method, result, analysis, and limitation boundaries remain explicit
- related work groups papers by technical role and evidence, not by flat paper lists
- figure/table captions match the provided data or assets
- LaTeX and PDF outputs compile, render, and preserve references correctly
```

The mechanism judge must run before any quality judge. Mechanism failures veto
the output even if the prose is fluent.

## Writing Runtime

Writing is a pipeline of artifacts, not one giant prompt.

```text
topic_brief
target_profile
method_card
result_card
citation_pool
evidence_pack
figure_table_spec
        |
writing planner
        |
section writers
        |
claim ledger + citation map
        |
figure/table planner and renderer
        |
LaTeX builder
        |
PDF compiler
        |
mechanism judge
        |
quality judge
        |
publication pack
```

Generator-visible inputs must match real use:

- The generator may see method and result cards because RH treats method
  design and experiment execution as separate upstream modules.
- The generator may not see original paper section text, hidden citation
  contexts, original figure layouts, or gold PDF layouts.
- Hidden gold belongs only to eval graders.

## Guardrail Model

RH should support three guardrail scopes.

| Scope | When | Examples |
| --- | --- | --- |
| Input | Before capability execution | no hidden gold, required artifact present |
| Tool | Around individual tool calls | citation tool cannot cite absent paper IDs |
| Output | After artifact generation | schema valid, all claims traceable |

Guardrails return:

```yaml
guardrail_result:
  name: string
  scope: input | tool | output
  passed: boolean
  severity: info | warning | blocking
  tripwire_triggered: boolean
  checked_refs: []
  diagnostics: []
```

Blocking guardrails stop promotion or stage advancement. Some blocking
guardrails may still allow artifact persistence if the artifact is explicitly
marked invalid and used only for diagnosis.

## Trace Model

Every runtime attempt produces a `RunTrace`.

```yaml
run_trace:
  schema_version: rh.trace.v0
  run_id: string
  task_id: string
  trial_id: string | null
  started_at: string
  finished_at: string
  status: success | failed | blocked
  inputs:
    run_spec_hash: string
    visible_artifact_ids: []
  steps:
    - step_id: string
      kind: llm_call | tool_call | guardrail | artifact_write | judge | handoff
      started_at: string
      finished_at: string
      status: success | failed | blocked
      input_ref: string | null
      output_ref: string | null
      cost_usd: number | null
      model: string | null
  outputs:
    artifact_ids: []
    final_report_id: integer | null
  costs:
    total_usd: number
    total_tokens: integer | null
  errors:
    - code: string
      message: string
      recoverable: boolean
```

Trace data should be sufficient for:

- debugging one failed run;
- replaying a capability against the same visible inputs;
- grading trace behavior at scale;
- attributing cost and latency;
- generating skill-level failure memory.

## Evaluation Harness

RHBench must evaluate the same runtime path used in real execution.

```yaml
task:
  task_id: rhbench.writing.cs.paper_001
  task_type: writing
  visible_inputs:
    topic_brief: artifact_ref
    target_profile: artifact_ref
    method_card: artifact_ref
    result_card: artifact_ref
    citation_pool: artifact_ref
    evidence_pack: artifact_ref
    figure_table_spec: artifact_ref
  hidden_gold:
    original_pdf: file_ref
    original_sections: file_ref
    original_figures_tables: file_ref
    expert_rubric: file_ref
  success_criteria:
    required_artifacts:
      - draft_pack
      - claim_ledger
      - latex_bundle
      - pdf_bundle
      - run_trace
    mechanism_gate: pass
    pdf_compile: pass
```

Grader layers:

1. Deterministic graders:
   - schema validation
   - citation key existence
   - paper ID validity
   - numeric result grounding
   - LaTeX compile
   - PDF page and layout checks
2. Mechanism LLM graders:
   - overclaiming
   - citation support
   - related-work fairness
   - method/result boundary
   - figure/table factuality
3. Quality LLM graders:
   - abstract clarity
   - introduction narrative
   - related-work synthesis
   - method exposition
   - result analysis
   - conclusion and limitation quality
   - whole-paper coherence
4. Human calibration:
   - sampled expert review to calibrate LLM judges.

Metrics:

- mechanism pass rate
- citation hallucination rate
- unsupported claim rate
- PDF compile pass rate
- layout defect rate
- whole-paper quality score
- cost per successful paper
- pass@1 and pass^k for consistency-sensitive workflows

## Reuse-First External Adapter Policy

When RH needs a capability, it must check reusable open-source options before
building a native implementation.

| Level | Action | Condition |
| --- | --- | --- |
| P0 direct reuse | Use as first version with attribution | MIT/Apache, aligned behavior, stable interface |
| P1 wrapped reuse | Keep external code isolated and wrap with RH contracts | Useful logic, incompatible interface |
| P2 method reuse | Reimplement from idea only | License unclear, too coupled, or unsafe to vendor |
| P3 reject | Do not use | Restrictive license, provenance risk, security risk |

Candidate adapter families:

| RH capability | First reuse candidates |
| --- | --- |
| citation-grounded QA | PaperQA2, STORM |
| related-work synthesis | STORM, PaperOrchestra literature agent |
| scientific writing conventions | nature-skills, K-Dense scientific-writing, Nature-Paper-Skills |
| citation verification | nature-citation, K-Dense citation-management |
| figure/table planning | nature-figure, K-Dense scientific-visualization, PaperOrchestra plotting |
| LaTeX/PDF generation | PaperOrchestra templates, RH existing PDF checks after refactor |
| autoraters | PaperOrchestra autoraters plus RH mechanism judges |
| skill lifecycle | MUSE-Autoskill concepts, SkillOpt optimizer pattern |

External adapters live outside core:

```text
external_adapters/
  paperqa2/
    adapter.py
    contract.yaml
    attribution.md
    license.txt
    tests/
  storm/
  paper_orchestra/
  nature_skills/
  k_dense/
```

Adapter requirements:

- license recorded;
- source URL and commit recorded;
- input and output schemas mapped to RH artifacts;
- all external tool calls traced;
- deterministic smoke tests included;
- failure modes mapped into RH failure taxonomy;
- no external adapter may bypass RH guardrails.

## Skill Evolution

Skill evolution is not free-form self-rewriting. It is a controlled promotion
pipeline.

```text
baseline run
  -> failure taxonomy
  -> open-source reuse lookup
  -> candidate skill diff
  -> train replay
  -> dev replay
  -> mechanism gate
  -> held-out replay
  -> human review
  -> promote or reject
```

Candidate edits must be bounded:

- small add/delete/replace operations;
- no hidden benchmark leakage;
- no hard-coded topic IDs, artifact IDs, paths, or paper titles unless scoped
  to a fixture;
- no broad behavioral change without regression suite coverage;
- rollback metadata required.

Promotion requires:

- no mechanism regression;
- no citation hallucination increase;
- held-out quality improvement or cost/latency improvement;
- no PDF compile or layout regression;
- source attribution and license checks pass;
- reviewable diff.

## Storage Direction

SQLite remains the default local database. Schema design should stay
Postgres-compatible:

- explicit primary keys;
- no SQLite-only business logic;
- JSON payloads are acceptable for v0 but should carry schema versions;
- large binary assets stay outside DB with content-addressed file refs;
- every artifact and trace references producer, inputs, and validation state.

## Security and Permissions

RH must separate local read-only analysis from external actions.

External actions requiring explicit approval:

- posting, publishing, uploading, or submitting manuscripts;
- pushing, merging, or opening PRs;
- spending money or launching paid compute jobs;
- changing credentials or remote project state;
- installing unreviewed external code into core runtime.

Runtime security requirements:

- no hardcoded secrets;
- adapters run with explicit tool permissions;
- prompt-injection-sensitive content must be treated as data;
- external repository code is quarantined until license and test checks pass;
- generated LaTeX and shell commands are executed only through guarded runners.

## Migration Plan

### Phase 0: Freeze legacy skills

Legacy RH skills remain disabled during architecture work. They may be used as
historical reference only after explicit review, not as runtime inputs.

### Phase 1: Contract foundations

Implement or document:

- `RunSpec`
- `RunTrace`
- `CapabilityManifest`
- `Artifact` schema
- guardrail result schema
- failure taxonomy

### Phase 2: Runtime refactor

Move execution from primitive-specific dispatch toward:

```text
RunSpec -> Runtime -> Capability -> ArtifactWriter -> Guardrail/Judge -> Trace
```

MCP and CLI should call runtime APIs instead of owning orchestration.

### Phase 3: First rebuilt skills

Create only the smallest core skill set:

- `writing-router`
- `citation-evidence`
- `scientific-writing-judge`
- `figure-table-quality`
- `latex-pdf-quality`
- `skill-evolution-manager`

Each skill must include `skill.yaml`, contracts, tests, and attribution.

### Phase 4: External adapters

Add wrapped adapters in this order:

1. PaperQA2 or equivalent grounded citation QA.
2. STORM-style outline and literature synthesis.
3. PaperOrchestra-style writing/plotting/autorater components.
4. nature-skills/K-Dense writing and figure conventions as policy/reference
   adapters.

### Phase 5: RHBench writing suite

Build the initial writing benchmark:

- 10 high-impact CS seed papers;
- visible inputs aligned with real RH usage;
- hidden gold isolated from generation;
- deterministic, mechanism, quality, and human-calibrated graders.

### Phase 6: Skill evolution loop

Enable bounded candidate generation and replay gates. Promotion remains
human-approved until the system has stable regression history.

## Acceptance Criteria for v0

Architecture v0 is implemented when:

- every core workflow can run from `RunSpec`;
- every run persists `RunTrace`;
- every generated manuscript artifact is typed and traceable;
- scientific writing mechanism gate can veto outputs before quality scoring;
- MCP/CLI adapters are thin and share runtime logic;
- at least one external adapter is reused with attribution;
- RHBench can replay at least one writing task end to end;
- skill promotion requires held-out replay and rollback metadata.
