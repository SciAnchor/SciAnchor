# RH End-to-End Paper Writing Capability

Status: delivery-protocol capability contract.

## Capability

Research Harness should take a topic from research intent to a reviewable,
submission-grade manuscript package. The operator is a researcher or writing
agent working inside RH. The outcome is not a chat transcript or loose draft:
it is a chain of durable RH artifacts that can support topic framing,
literature evidence, novelty analysis, experiment/result evidence, manuscript
planning, section drafting, figure/table readiness, LaTeX/PDF assembly,
citation integrity, review audit, publication packaging, rebuttal, and
camera-ready replay.

RH remains the evidence and state source of truth. The protocol has no external
runtime dependency. The research delivery protocol contributes the discipline:
`protocol_call` for explicit stage deliverables, `human_in_loop_call` for
judgment-level requests, mandatory artifact records through
`orchestrator_record_artifact`, and stage gates that refuse to advance when the
required RH artifact is missing or stale. The paper-delivery stages are
RH artifact conventions: `RESEARCH_BRIEF`, `IDEA_REPORT`,
`RESEARCH_PROPOSAL`, `EVALUATION`, `EXPERIMENT_PLAN`, `IMPACT_REPORT`,
`CLAIMS_FROM_RESULTS`, `PAPER_PLAN`, `AUTO_REVIEW`, `PRESUBMISSION_AUDIT`,
`PAPER_PACKAGE`, and `REBUTTAL_PACKAGE`. Discovery artifacts such as
`wiki_context_pack.v1` and `paper_storyline_graph.v1` are upstream compiled
views, not independent truth stores. Publication outputs must converge on
recorded `draft_pack`, `publication_pack`, `final_bundle`, and
`final_bundle_quality_report` artifacts.
Manuscript-scale drafting must also pass a manuscript logic gate before prose
generation: `CORE_CLAIM_CONTRACT`, `ARGUMENT_TREE`, `TERM_REGISTRY`,
`PROMISE_REALIZATION_MATRIX`, `PARAGRAPH_INTENT_TREE`, and
`manuscript_logic_gate_report` are the pre-draft control artifacts that keep the
paper centered on one claim, defined terms, realized promises, and paragraph
intent.
Domain-specific writing is also a first-class control layer. Before
manuscript-scale drafting, `PAPER_PLAN` must carry `PAPER_PROFILE` and a
`DOMAIN_WRITING_PROFILE` selected from the domain-writing skill family:
`domain-writing-stem`, `domain-writing-biomedical`,
`domain-writing-social-science`, `domain-writing-humanities`, or
`domain-writing-law-policy`. `PAPER_PROFILE` names `discipline`,
`research_type`, `study_design`, `paper_type`, target venue, `reporting_map`,
and `evidence_rule`; it chooses the method/search/reporting/evidence route and
must not silently default ambiguous manuscripts to STEM. The domain profile
controls claim boundaries, evidence shape, rhetoric, and disciplinary gates;
the paper-writing track controls output form.
Domain-aware discovery is the companion control layer:
`DOMAIN_METHOD_SEARCH_PROFILE` names `method_route`, `search_route`,
`search_strategies`, `method_requirements`, and `baseline_anchor_fields` so
literature search, mapping, gap analysis, and evidence gates collect the right
baselines, theory anchors, source anchors, construct/scale evidence, or legal
authorities for the selected discipline.
Experiment grounding is the result-control layer:
`EXPERIMENT_GROUNDING_PROFILE` binds `EXPERIMENT_GOAL`, `EXPERIMENT_PLAN`,
`PAPER_PROFILE`, `variable_grounding`, codebook or source-inventory checks,
`pre_deploy_code_review`, and claim-bound `IMPACT_REPORT` before experiments
can be deployed, result claims can be extracted, or result-backed prose can be
written.
Result-to-claim analysis is the result-interpretation layer:
`RESULT_TO_CLAIM_ANALYSIS_PROFILE` binds completed result artifacts,
`IMPACT_REPORT`, `CLAIMS_FROM_RESULTS`, `relative_delta_table`,
`statistical_summary`, practical significance, baseline/robustness context,
negative results, competing evidence, and `claim_strength` before completed
results become contribution prose.
Skeleton and source integrity is the package-readiness layer:
`SKELETON_SOURCE_INTEGRITY_PROFILE` binds required section groups, non-stub
section bodies, `source_trace`, Claims-Evidence Matrix coverage, source
artifacts, `citation_integrity`, `bib_doi_verification`, and figure/table
references before presubmission audit, publication packaging, or
submission-facing readiness claims.
Review and rebuttal readiness is the final submission-facing layer:
`PRESUBMISSION_SEVERITY_GATE_PROFILE` binds `PRESUBMISSION_AUDIT`, CRITICAL /
MAJOR / MINOR findings, `integrity_gate`, final-bundle quality, and zero
critical submission rules before package readiness. `REBUTTAL_READINESS_GATE_PROFILE`
binds `REBUTTAL_PACKAGE`, `ISSUE_BOARD`, response letter, `REVISION_PLAN`,
response evidence, revision deltas, and replay metadata to provenance,
commitment, and coverage gates before response readiness.

## Constraints

- no unsupported claims: every research, novelty, result, limitation, and
  contribution claim must link to paper IDs, claim IDs, source artifacts, or be
  explicitly marked weak, speculative, or unsupported.
- no chat-only source of truth: plans, decisions, generated sections, images,
  reviews, and package state must be recorded as RH artifacts or checked-in
  self-development contracts.
- no invented BibTeX: citation metadata must come from programmatic paper
  sources, DOI/arXiv/CrossRef/Semantic Scholar style evidence, or a clearly
  marked citation-needed blocker.
- no invented experiment results: planned studies, protocol diagrams, expected
  outcomes, and observed results must remain distinct.
- no public readiness claim without QA evidence: submission-ready means the
  skeleton/source, citation, figure, final-bundle, provenance, and review gates
  pass.
- no credential mutation: writing, image, PDF, Zotero, or provider work may
  read configured capabilities but must not write or change API keys,
  gateway/base-url settings, or credential files.
- no external action: commits, pushes, PRs, releases, publishing, real public
  deployment, real Zotero network sync/apply, third-party writes, Cloud apply,
  and public benchmark/performance claims require a separate explicit request.

## Implementation Contract

### Actors

- Researcher: sets topic, target venue, paper type, and final judgment.
- RH writing agent: runs the staged workflow and records artifacts.
- Reviewer agent: performs `AUTO_REVIEW`, provenance, and presubmission checks.
- Packager: assembles `PAPER_PACKAGE`, `publication_pack`, and final bundle.

### Surfaces

- Skills: `research-init`, `literature-search`, `paper-sync`,
  `claim-extraction`, `gap-analysis`, `evidence-gating`, `paper-writing`,
  `section-drafting`, `domain-writing-stem`, `domain-writing-biomedical`,
  `domain-writing-social-science`, `domain-writing-humanities`,
  `domain-writing-law-policy`, `figure-quality`, `final-bundle-quality`,
  `publication-pack`, `provenance-review`.
- MCP/service primitives: `paper_search`, `paper_ingest`,
  `paper_summarize`, `claim_extract`, `gap_detect`, `baseline_identify`,
  `section_draft`, `consistency_check`, `publication_pack_generate`,
  `publication_pack_backfill`, `orchestrator_*`, and provenance summaries.
- Internal compiled views: Research Wiki, Topic Knowledge,
  `wiki_context_pack.v1`, `innovation_opportunity_report.v1`,
  `experiment_design_brief.v1`, `method_improvement_report.v1`,
  `paper_storyline_graph.v1`.
- Package artifacts: `PAPER_PLAN`, `draft_pack`, `figure_plan`,
  `RESULT_TO_CLAIM_ANALYSIS_PROFILE`,
  `SKELETON_SOURCE_INTEGRITY_PROFILE`, `citation_sanitization_report`,
  `final_bundle`,
  `final_bundle_quality_report`, `PRESUBMISSION_AUDIT`,
  `PRESUBMISSION_SEVERITY_GATE_PROFILE`, `PAPER_PACKAGE`,
  `publication_pack`, `REBUTTAL_PACKAGE`, `REBUTTAL_READINESS_GATE_PROFILE`,
  `ISSUE_BOARD`, and `REVISION_PLAN`.

### Delivery Protocol Logic To Add

- `protocol_call` must resolve an explicit requested deliverable to one RH
  owner skill, one RH stage, one required artifact type, one gate, and one
  recording action.
- `human_in_loop_call` must translate a broad user judgment into the nearest
  missing or stale protocol artifact before running broad drafting or review.
- Every protocol artifact must have an owner skill and must be recorded through
  `orchestrator_record_artifact` or an equivalent artifact manager path.
- Stage advancement must inspect required protocol artifacts, not chat
  assertions.
- `PAPER_PACKAGE` and `REBUTTAL_PACKAGE` must package recorded RH artifacts
  only; they must not package unrecorded chat output.
- The protocol adds no separate runtime, state directory, hooks, queue,
  credentials, or MCP servers to RH.

## Required Stages

### PW01_TOPIC_AND_VENUE_CONTRACT

Purpose: convert a vague research topic into a bounded manuscript target.

Required work:

- define topic, paper type, target venue/profile, audience, page budget, and
  anonymity policy;
- run problem-worthiness checks from `paper-writing` and record pass/fail
  evidence;
- create a topic/venue contract that states user-visible promises and
  non-goals;
- block drafting if the target venue, paper type, or contribution shape is
  ambiguous.

Output: `topic_venue_contract.v1` or equivalent RH artifact.

### PW02_EVIDENCE_ACQUISITION_AND_READING

Purpose: ensure the paper is grounded in real literature, not prompt memory.

Required work:

- search, ingest, verify, sync PDFs, and enrich metadata for the topic;
- run claim extraction, reading annotations, paper summaries, and paper-card
  refresh where available;
- build or refresh Research Wiki and Topic Knowledge context;
- preserve all paper IDs, DOI/arXiv identifiers, PDF status, source hashes, and
  weak/missing evidence warnings.

Output: current paper pool, claim/evidence sets, Research Wiki state, and
`wiki_context_pack.v1` for paper writing.

### PW03_GAP_BASELINE_NOVELTY_VALIDATION

Purpose: prove that the proposed paper has a defensible research position.

Required work:

- run gap analysis, baseline identification, novelty-risk review, and
  evidence gating;
- derive `DOMAIN_METHOD_SEARCH_PROFILE` from `PAPER_PROFILE` before broad
  discovery, baseline/theory/source/authority collection, or gap promotion;
- connect the selected opportunity to discovery outputs including
  `innovation_opportunity_report.v1` and `paper_storyline_graph.v1`;
- produce a three-problem to three-contribution map when the selected paper
  track requires it;
- mark all novelty, baseline, and contribution claims as evidence-bound,
  weakly supported, speculative, or unsupported.

Output: `DOMAIN_METHOD_SEARCH_PROFILE`, `IDEA_REPORT`, `RESEARCH_PROPOSAL`,
`EVALUATION_GATE_PROFILE`, `PROBLEM_ANCHOR`, `EVALUATION`, and gate decision.

The `EVALUATION_GATE_PROFILE` and `PROBLEM_ANCHOR` are the go/no-go layer
before experiment or manuscript investment. `PROBLEM_ANCHOR` freezes the
problem, beneficiary or debate, closest baseline/source/authority, and claim
boundary. `EVALUATION_GATE_PROFILE` records discipline-routed scoring axes,
`baseline_mode`, `paper_access_status`, `fatal_flaws`, feasibility risks,
verdict options, and whether a signal `pilot` is required. Advancement is
blocked when the problem anchor is not frozen, required papers/code/tables/
statistical values/sources/authorities are inaccessible, the baseline mode is
unsupported by the active domain method/search profile, or a critical fatal
flaw remains.

### PW04_EXPERIMENT_RESULT_INGESTION

Purpose: turn validation plans and actual results into manuscript evidence.

Required work:

- convert `experiment_design_brief.v1` into executable or externally supplied
  validation expectations;
- create or load `EXPERIMENT_GROUNDING_PROFILE` before running or accepting
  experiment evidence: `EXPERIMENT_GOAL` must match the frozen problem and
  target claim, `EXPERIMENT_PLAN` must be profile-aligned with `PAPER_PROFILE`,
  and plan rows must test actual manuscript claims;
- verify `variable_grounding` against the codebook, data dictionary, source
  corpus, authority inventory, or equivalent domain source list before
  treating variables, constructs, datasets, controls, metrics, sources, or
  legal authorities as available;
- require `pre_deploy_code_review` with zero blockers for variable grounding,
  data split/leakage, metric/formula fit, seeds/reproducibility, and
  ground-truth/source correctness before deployment or result acceptance;
- ingest result tables, logs, ablations, failure cases, qualitative examples,
  human-study notes, or negative results as recorded artifacts;
- distinguish planned, running, failed, partial, and completed result states;
- run consistency checks that tie each result to a claim, baseline, dataset, and
  figure/table candidate;
- require a claim-bound `IMPACT_REPORT` before completed result artifacts can
  produce `CLAIMS_FROM_RESULTS`; the report must compare expected vs actual
  outcomes, state evidence strength, name limitations or negative results, and
  avoid positioning weak results as confirmatory.
- require `RESULT_TO_CLAIM_ANALYSIS_PROFILE` before `CLAIMS_FROM_RESULTS` or
  result-backed prose: the profile must bind `relative_delta_table`,
  `statistical_summary`, practical significance, baseline/robustness context,
  negative results, competing evidence, and `claim_strength`;
- block overclaimed or unsupported result claims, including claims that exceed
  the domain/study-design boundary or belong in `F_unsupported_or_blocked`.

Output: `EXPERIMENT_GROUNDING_PROFILE`, `experiment_result_pack.v1`,
claim-bound `IMPACT_REPORT`, `RESULT_TO_CLAIM_ANALYSIS_PROFILE`, result claim
map, and updated evidence gate.

### PW05_PAPER_PLAN_AND_STORYLINE

Purpose: build the manuscript architecture before drafting prose.

Required work:

- generate or repair `PAPER_PLAN` from topic contract, evidence, gap/baseline
  reports, experiment results, and `paper_storyline_graph.v1`;
- select and record `PAPER_PROFILE` before domain writing selection, including
  `discipline`, `research_type`, `study_design`, `reporting_map`, and
  `evidence_rule`, so social-science, biomedical, humanities, law/policy, and
  STEM manuscripts route to the right method and evidence contract rather than
  a silent STEM default;
- require the active `DOMAIN_METHOD_SEARCH_PROFILE` to be satisfied before
  claiming baseline, theory-anchor, source-anchor, authority, scale,
  construct, dataset, metric, effect-size, or control-group coverage;
- select and record a `DOMAIN_WRITING_PROFILE` before manuscript-scale drafting
  so STEM, biomedical, social-science, humanities, and law/policy manuscripts
  do not share one generic rhetoric or evidence contract;
- generate and pass the manuscript logic gate before `PAPER_PLAN` promotion:
  `CORE_CLAIM_CONTRACT`, `ARGUMENT_TREE`, `TERM_REGISTRY`,
  `PROMISE_REALIZATION_MATRIX`, `PARAGRAPH_INTENT_TREE`, and
  `manuscript_logic_gate_report`;
- generate and pass the fine logic audit alongside the coarse gate:
  `ARGUMENT_LINK_MAP`, `ASSUMPTION_WARRANT_TABLE`, `CLAIM_CERTAINTY_AUDIT`,
  `PARAGRAPH_FLOW_AUDIT`, `INTRO_LOGIC_MAP`, `FIGURE_TABLE_MESSAGE_AUDIT`,
  `WRITING_DEFECT_LOG`, and `fine_logic_audit_report`;
- define section order, page budget, claim-to-section mapping, figure/table
  plan, and reviewer-risk notes;
- require a Claims-Evidence Matrix before manuscript-scale drafting.

A complete, sanitized example of a passing `PAPER_PLAN` carrying both the raw
logic-bundle inputs and the two recorded reports lives at
`packages/research_harness/tests/fixtures/writing/example_paper_plan_with_logic_reports.json`
(guarded by `test_example_paper_plan_logic_reports.py`). The runtime guard
recomputes both reports from the raw inputs, so a self-declared `{"status":
"pass"}` cannot bypass the gate — see `writing_logic_gate_runtime.py`.

The local end-to-end paper-generation test-data contract is the canonical
fixture
`packages/research_harness/tests/fixtures/writing/e2e_paper_generation_dataset.json`
(schema `rh.e2e_paper_generation_dataset.v1`). This fixture is not a benchmark
or readiness claim. It is a deterministic data contract for checking current RH
capability state across PW01-PW10, including a positive reviewable-package path
(`reviewable_package_ready`), evidence/source blockers (`blocked`),
result-overclaim blockers, package-integrity blockers, non-STEM routing, and
external-action denial.

The private trace-shape contract
`rh.e2e_paper_generation_trace_shape_contract.v1`. This contract defines the
run records, context refs, spans, events, artifact refs, gate decisions, and
durable completion event that a future real RH paper-generation dry run must
emit before it can be scored against the dataset. It remains private to
`research_harness._selfdev` and does not register a public command or claim
submission readiness.

Canonical local candidate trace fixtures live at
`packages/research_harness/tests/fixtures/writing/e2e_paper_generation_trace_cases.json`.
They cover one accepted positive trace and one blocked overclaim trace, both
validated by the private trace-shape report.

The internal paper-production runtime lane wires active
paper-plan, strict-evidence, venue-overlay, manuscript metadata, and
bibliography context through write-stage dispatch into section drafting,
section-loop drafting, LaTeX compilation, and publication-pack execution. A
private deterministic `rh.paper_production_runtime_context.v1` builder
in `research_harness.auto_runner.paper_production_context` converts a broad
topic plus target venue into `topic_venue_contract`, `venue_overlay`,
`PAPER_PROFILE`, `DOMAIN_METHOD_SEARCH_PROFILE`, initial `PAPER_PLAN`
requirements, blockers, and next actions without running LLMs, network search,
artifact writes, stage advancement, or public transports. The builder
intentionally exposes `paper_plan_requirements`, not an active `paper_plan`;
PW05 must still promote a real plan with passing logic-gate reports before
section drafting receives it. The deterministic runtime context is merged
into `plan_stage` and stage reset recovery, so `init`, `build`, and later
planner stages preserve the topic-plus-venue contract even when the LLM planner
falls back or checkpoint `stage_context` is cleared between stages.
The convenient public/local entry is
`rh paper-production plan/start`. The entry returns
`rh.paper_production_entry.v1`, can preview the runtime context without side
effects, and can prepare local topic, orchestrator run, and auto-runner
checkpoint state without running providers. It intentionally stops before
paper search, LLM calls, artifact promotion, stage advancement, or public
readiness claims.
`rh.paper_production_execution_preview.v1` is an internal fake-tool
execution preview that loads a prepared checkpoint, runs `execute_stage(init)`
without provider calls, saves the checkpoint, and reports checkpoint history
plus run-trace event evidence. This is an execution-smoke contract, not an
evidence-acquisition or PDF-readiness claim.
`rh.paper_production_execution_chain_preview.v1` is a local fake-tool
init-to-build chain preview from the prepared checkpoint. It preserves
`rh.paper_production_runtime_context.v1` across stage resets, records
checkpoint/run-trace events for both stages, and leaves a replayable
`rh.paper_production_control_artifact_preview.v1` evidence-acquisition control
artifact under fakes. This still does not call real paper search, ingest,
Zotero, LLM, image-provider, or artifact-promotion paths, and it does
not claim that the topic has acquired real evidence.
The local CLI command
`rh paper-production preview-chain --topic ... --target-venue ...` exposes that
chain preview: it prepares local topic/run/checkpoint state and runs the fake init-to-build
preview in one step, returning the same chain-preview payload in JSON mode and
a concise text summary otherwise. It remains fake-only and does not promote
artifacts or call providers.
The paper-production
state machine now declares PW01-PW10, readiness reporting, evidence acquisition
plans, experiment/result-to-claim profiles, `PAPER_PLAN` promotion gates,
write-to-PDF closure requirements, and the terminal condition
`final_bundle_pdf_and_publication_pack_pass_all_quality_gates`. The convenient
entry now has `rh paper-production run --topic ... --target-venue ...`, dry-run
by default, and `--execute` for the real local runner. The runner prepares and
reuses the caller's database, persists the paper-production context in the
checkpoint, and can execute through the normal auto-runner path instead of only
fake previews. The write stage has a paper-production completion gate: it cannot
complete unless active `final_bundle`, `publication_pack`, and `process_summary`
artifacts exist, and the final bundle must expose a real `pdf_path` or
`compiled_pdf_path` with non-draft payload state. `--local-only` is a stable
no-network path for rehearsal and local paper-pool execution; the local-only
provider policy is preserved across stage-context reset and planner
rehydration, so execute-mode cannot silently fall back to external provider
fanout. Default paper-production evidence acquisition uses
`guarded_provider_fanout` rather than unbounded provider fanout: `paper_search`
receives provider allow/deny filters, per-provider limits, and excludes the
long-wait/rate-limited `semantic_scholar` and `pasa` providers unless the caller
separately chooses a different provider policy. Provider filters are now part of
the primitive contract and accept arrays or comma-separated strings. This is a
real local execution lane, not a submission-readiness claim: with empty local
evidence or provider failures it stops at gates with explicit blockers instead
of inventing papers, experiments, PDF artifacts, or publication packs. The
empty-local-evidence stop is productized as
`rh.paper_production_runtime_gate.v1` with
`blocker_code=paper_production_evidence_gate`, seed-paper counts, and next
actions rather than a raw orchestrator `needs_approval` error.

Output: active `PAPER_PLAN`, `PAPER_PROFILE`, `DOMAIN_WRITING_PROFILE`,
manuscript logic artifacts, Claims-Evidence Matrix, and `figure_plan`.

### PW06_SECTION_DRAFTING_AND_REVISION

Purpose: draft, revise, and integrate manuscript sections without unsupported
freeform claims.

Required work:

- call or emulate `section_draft` using the active `PAPER_PLAN` and section
  evidence packs;
- load the active `PAPER_PROFILE` before writing section prose and use its
  `reporting_map` and `evidence_rule` to decide what method/result disclosures
  are required and how strong each claim may be;
- load the active `DOMAIN_WRITING_PROFILE` before writing section prose and
  apply its evidence shape and claim boundary to every unsupported or
  over-strong sentence;
- refuse abstract, introduction, and manuscript-scale drafting when
  `manuscript_logic_gate_report.status` is not `pass`;
- draft in evidence-aware order: results/evaluation, method/design, related
  work, final introduction, abstract;
- run style, terminology, anti-AI-trace, and cross-section consistency checks;
- record section revisions and unsupported-sentence blockers instead of
  smoothing them over.

Output: `draft_pack` with section text, evidence map, unresolved blockers, and
revision history.

### PW06B_SKELETON_SOURCE_AND_CITATION_INTEGRITY

Purpose: prevent manuscript structure, source provenance, and citation metadata
from drifting before package readiness.

Required work:

- create or load `SKELETON_SOURCE_INTEGRITY_PROFILE` after the manuscript has
  enough assembled structure for audit and before presubmission or package
  readiness claims;
- verify `required_section_groups` using the venue/profile override when
  available, and block missing or stubbed section groups;
- verify `source_trace` from manuscript claims to the Claims-Evidence Matrix,
  source artifacts, logic skeleton cells, contribution-section mappings, and
  limitation/challenge/module chains;
- verify source artifacts are present and current rather than chat-only or
  stale;
- verify `citation_integrity`: no dangling citations, table references match
  labels, figure targets resolve, and SVG-only or missing figure assets block
  readiness;
- verify `bib_doi_verification`: BibTeX/DOI or primary metadata is checked
  against trusted paper-source metadata; unverified entries remain blockers;
- send failures back to writing, section drafting, paper verification, or
  provenance review rather than paper packaging.

Output: `SKELETON_SOURCE_INTEGRITY_PROFILE` with skeleton checks,
source-trace checks, citation checks, BibTeX/DOI metadata checks, blockers, and
decision.

### PW07_FIGURE_TABLE_AND_ASSET_QUALITY

Purpose: make figures and tables publication-useful visual evidence.

Required work:

- require a recorded `figure_plan` before manuscript-scale figure repair;
- use existing RH figure/table quality surfaces without adding provider logic
  in this delivery-protocol line;
- keep conceptual, planned, and observed-result figures explicitly separated;
- record caption constraints, source-data links, provenance, and unresolved
  visual-risk notes;
- reject placeholder, blurry, unreadable, decorative, or evidence-gap figures.

Output: publication-ready assets, captions, source-data links, and visual-risk
report.

### PW08_LATEX_CITATION_AND_FINAL_BUNDLE

Purpose: compile a venue-shaped manuscript bundle with citation integrity.

Required work:

- assemble TeX, bibliography, assets, supplementary material, and metadata
  from active artifacts;
- run citation sanitization and `consistency_check`;
- require a passing `SKELETON_SOURCE_INTEGRITY_PROFILE` before readiness;
- compile or backfill `final_bundle` through existing RH writing primitives;
- run `final-bundle-quality` to produce `final_bundle_quality_report`;
- block readiness on undefined citations, invented BibTeX, high-severity
  overfull boxes, missing fonts, invalid encodings, page-limit failures,
  anonymization failures, or broken asset paths.

Output: `final_bundle`, citation report, and PDF/LaTeX quality report.

### PW09_REVIEW_AUDIT_AND_PUBLICATION_PACK

Purpose: decide whether the paper is reviewable, submission-ready, or blocked.

Required work:

- run adversarial review, provenance review, consistency checks, and
  `PRESUBMISSION_AUDIT`;
- create or load `PRESUBMISSION_SEVERITY_GATE_PROFILE`; findings must use the
  CRITICAL / MAJOR / MINOR taxonomy, any CRITICAL finding blocks
  submission-facing advancement, and the `integrity_gate` must pass before
  package readiness;
- generate `publication_pack` / `PAPER_PACKAGE` from latest draft, evidence,
  figures, final bundle, citation checks, and process summary;
- list missing required and optional components explicitly;
- ensure readiness flags are derived from QA artifacts, not from the existence
  of a draft.

Output: `PRESUBMISSION_AUDIT`, `PRESUBMISSION_SEVERITY_GATE_PROFILE`,
`publication_pack`, `PAPER_PACKAGE`, and next actions.

### PW10_REBUTTAL_CAMERA_READY_AND_REPLAY

Purpose: keep reviewer response, camera-ready repair, and future replay inside
the same evidence contract.

Required work:

- ingest reviewer comments, scores, editor constraints, or venue checklist
  feedback;
- create `REBUTTAL_PACKAGE` with claim-level response evidence and unresolved
  risk;
- create or load `REBUTTAL_READINESS_GATE_PROFILE` with `ISSUE_BOARD`,
  response letter, `REVISION_PLAN`, response evidence, revision deltas, and
  camera-ready replay metadata;
- require the provenance gate to source every factual response sentence, the
  commitment gate to put every promised edit in `REVISION_PLAN` with no orphan
  commitments, and the coverage gate to close every reviewer concern as
  answered, deferred intentionally, or needs user input;
- update camera-ready changes through the same section, citation, figure, and
  final-bundle gates;
- preserve replay metadata so future RH self-evolution can compare draft,
  review, response, and camera-ready trajectories.

Output: `REBUTTAL_PACKAGE`, `REBUTTAL_READINESS_GATE_PROFILE`,
camera-ready delta, final replay report, and updated publication pack.

## Non-Goals

- fully autonomous science: RH assists evidence-grounded research and writing;
  it does not prove scientific truth or remove human research judgment.
- real public deployment.
- real Zotero network sync/apply.
- commits, pushes, PRs, releases, or publishing.
- importing external runtime code into RH.
- adding `google-genai`, image-provider dependencies, or provider credentials
  during this delivery protocol line.
- public benchmark/performance or submission-readiness claims without local QA
  evidence and a recorded gate.

## Open Questions

- Whether `topic_venue_contract.v1`, `experiment_result_pack.v1`, and
  camera-ready replay should become first-class artifact schemas or remain
  private compiled views at first.
- Which public surface should lead after private capability closure: skill-only
  contract, CLI workflow wrapper, Python facade, MCP, or HTTP.
- How much real Zotero paper-sync and PDF annotation should be required before
  declaring a topic ready for writing.
- Whether figure/table repair should stay a downstream `figure-quality`
  responsibility or gain a protocol artifact gate beyond `figure_plan`.

## Implementation Components

The capability is implemented as the delivery paper-production protocol. The
contract is guarded by
`packages/research_harness/tests/test_end_to_end_paper_writing_capability.py`.
Components:

- Protocol state machine: a private deterministic state-machine contract for
  `protocol_call`, `human_in_loop_call`, owner-skill routing, required
  artifacts, gate names, stale states, and recording surfaces.
- Topic-to-proposal artifacts: `RESEARCH_BRIEF`, `IDEA_REPORT`,
  `RESEARCH_PROPOSAL`, and `EVALUATION` as evidence-bound RH artifact payload
  contracts.
- Experiment-to-claims artifacts: `EXPERIMENT_GOAL`, `EXPERIMENT_PLAN`,
  `IMPACT_REPORT`, and `CLAIMS_FROM_RESULTS` so planned, partial, failed, and
  observed results feed claim-safe paper writing.
- Result-to-claim analysis gates: evidence tiers, `relative_delta_table`,
  `statistical_summary`, practical significance, negative-result,
  competing-evidence, and overclaim blockers before result-backed prose.
- Paper-plan audit package: `PAPER_PLAN`, `AUTO_REVIEW`,
  `PRESUBMISSION_AUDIT`, and `PAPER_PACKAGE` so section drafting, final bundle
  QA, provenance, and package readiness all use recorded artifacts.
- Rebuttal and camera-ready replay: `REBUTTAL_PACKAGE` and camera-ready replay
  so reviewer feedback, response evidence, edits, and final package deltas
  remain reproducible RH state.

End-to-end paper-generation test data (component keys are asserted by tests):

- `LG78_E2E_PAPER_GENERATION_TEST_DATA`: deterministic local test data and code
  graders for measuring the current end-to-end paper-generation capability
  state without running real LLMs, network search, Zotero, image providers,
  publication submission, or external provider calls.
- `LG78B_E2E_PAPER_GENERATION_DATASET_LOADER`: a private, side-effect-free
  fixture loader and readiness summary helper for the dataset, with
  fail-closed validation for schema, external-action boundaries, duplicate
  case IDs, and missing positive/blocker coverage.
- `LG78C_E2E_PAPER_GENERATION_DRY_RUN_EVALUATOR`: a private deterministic
  evaluator and `rh.e2e_paper_generation_eval_report.v1` report so local
  fixtures produce pass/fail grader evidence without real LLMs, network,
  provider calls, storage writes, or public-surface changes.
- `LG78D_E2E_PAPER_GENERATION_REPLAY_REPORT`: a private JSON-safe replay
  report helper that combines dataset readiness and deterministic eval results
  into `rh.e2e_paper_generation_replay_report.v1`.
- `LG78E_PRIVATE_REPLAY_HARNESS`: a private `python -m
  research_harness._selfdev.e2e_paper_generation` harness that prints the replay
  report JSON and exits nonzero on deterministic private-eval failure without
  registering a public command.
- `LG78F_DATASET_EXPANSION_SOCIAL_BIOMEDICAL_PASS_CASES`: positive
  social-science education and biomedical clinical review full-chain cases so
  the default replay harness is not STEM-only.
- `LG78G_TRACE_SHAPE_CONTRACT`: the private
  `rh.e2e_paper_generation_trace_shape_contract.v1` contract and deterministic
  `rh.e2e_paper_generation_trace_shape_report.v1` validator so real dry runs
  must expose replayable run/context/span/event/artifact/gate/completion
  evidence before local scoring.
- `LG78H_CANDIDATE_TRACE_FIXTURES`: local
  `rh.e2e_paper_generation_trace_cases.v1` candidate trace fixtures for one
  positive full-chain case and one blocked result-overclaim case, both passing
  the private trace-shape validator.

Paper-production runtime lane:

- Write-stage context wiring: paper-production context flows through existing
  write-stage dispatch so section drafting, section loops, LaTeX, and
  publication packaging receive active paper-plan/evidence/venue/metadata
  context.
- Runtime context builder: a private deterministic
  `rh.paper_production_runtime_context.v1` helper that turns broad topic plus
  target venue into `topic_venue_contract`, `venue_overlay`, `PAPER_PROFILE`,
  `DOMAIN_METHOD_SEARCH_PROFILE`, initial `PAPER_PLAN` requirements, blockers,
  and next actions without opening public surfaces or running external calls.
- Planner context integration: the builder output is merged into
  `plan_stage`/checkpoint carry-forward so the runtime lane survives
  stage-context resets and evidence acquisition receives the topic/venue
  contract.
- Easy entry: the convenient public/local entry for
  `topic + target venue -> RH run/checkpoint`, as a CLI plus a reusable Python
  helper.
- Execution preview and chain preview: controlled fake-provider execution
  previews (single-stage and init-to-build) that prove prepared checkpoints can
  enter the runner without external calls, exposed through
  `rh paper-production preview-chain --topic ... --target-venue ...`.
- Runtime completion: a state-machine manifest, readiness report, guarded
  evidence plan, experiment/result-to-claim/PAPER_PLAN profiles,
  run/start/execute CLI path, caller-DB continuity, execution-time local-only
  preservation, bounded provider policy, productized evidence-gate blockers,
  and final PDF/publication-pack completion gate.
