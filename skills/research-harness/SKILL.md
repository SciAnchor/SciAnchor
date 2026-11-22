---
name: research-harness
description: Main entry skill for Research Harness workflows in Codex. Trigger on phrases like "research-harness", "/research-harness", "用 Research Harness", "进入科研工作流", "开始科研流程", or equivalent requests to route the task to topic initialization, literature search, citation tracing, claim extraction, gap analysis, evidence gating, section drafting, publication pack assembly, paper verification, provenance review, or self-evolution backlog capture from workspace feedback.
public_suite: research
task_type: routing
data_access_level: local
inputs: user request, topic context, available RH state
outputs: routed workflow, specific skill choice, next primitive calls
gates: route to a specific skill when intent is clear; read agent guide if context is incomplete
artifact_schemas: workflow_route
estimated_runtime: 1-5 min
---

# Research Harness

Use this skill as the default entry point when the user wants to work inside the Research Harness workflow but does not name a more specific skill.

## First Step

Read `docs/agent-guide.md` in the Research Harness checkout if the repo or topic context is incomplete.

## Routing Rules

Route to the most specific matching workflow:

- topic or project bootstrap: `research-init`
- broad paper discovery: `literature-search`
- topic-level clustering and baseline coverage: `literature-mapping`
- seed-paper expansion: `citation-trace`
- extract claims and evidence: `claim-extraction`
- identify research opportunities: `gap-analysis`
- decide readiness to advance: `evidence-gating`
- choose paper domain rhetoric and claim boundaries before manuscript-scale
  drafting: `domain-writing-stem`, `domain-writing-biomedical`,
  `domain-writing-social-science`, `domain-writing-humanities`, or
  `domain-writing-law-policy`
- block unclear manuscript logic before prose: `manuscript-logic-gate`
- write evidence-backed sections: `section-drafting`
- assemble submission/report output packages: `publication-pack`
- verify paper identity or metadata: `paper-verify`
- audit recorded history and artifacts: `provenance-review`
- capture human feedback, accepted agent proposals, repeated failures, or
  confirmed workflow bugs into the self-evolution backlog: `rh-self-evolution`

If the request spans multiple stages, execute them in dependency order instead of asking the user to split the request.

For paper writing requests, route domain before prose:

- First establish `PAPER_PROFILE` with `discipline`, `research_type`,
  `study_design`, paper type, target venue, `reporting_map`, and
  `evidence_rule`; missing or ambiguous fields block drafting, and the route
  must not silently default to STEM.
- Then establish `DOMAIN_METHOD_SEARCH_PROFILE` with `method_route`,
  `search_route`, `search_strategies`, `method_requirements`, and
  `baseline_anchor_fields`; use it for literature search, literature mapping,
  gap analysis, baseline/theory/source/authority collection, and evidence
  gates before prose.
- Then establish `EVALUATION_GATE_PROFILE` and `PROBLEM_ANCHOR` before
  promoting a candidate direction to experiments or manuscript planning. The
  evaluation gate must name `baseline_mode`, `paper_access_status`,
  `fatal_flaws`, feasibility risks, and whether a signal `pilot` is required.
- Then establish `EXPERIMENT_GROUNDING_PROFILE` before experiment execution,
  result-claim extraction, or manuscript planning from results. It must bind
  `EXPERIMENT_GOAL` and `EXPERIMENT_PLAN` to the active `PAPER_PROFILE`, check
  `variable_grounding` against the codebook or equivalent source inventory,
  require passing `pre_deploy_code_review`, and require a claim-bound
  `IMPACT_REPORT` before results become contribution claims.
- Then establish `SKELETON_SOURCE_INTEGRITY_PROFILE` before presubmission
  audit, publication packaging, or submission-facing readiness claims. It must
  name `required_section_groups`, verify non-stub sections, check
  `source_trace` from manuscript claims to the Claims-Evidence Matrix and
  source artifacts, and require `citation_integrity` plus
  `bib_doi_verification` to leave no dangling citations.
- STEM, AI/ML, CS, engineering, systems, or benchmarks:
  `domain-writing-stem` then `paper-writing` or `section-drafting`.
- Biomedical, medical, clinical, public-health, life-science, diagnostic,
  therapeutic, cohort, or intervention work: `domain-writing-biomedical` then
  the writing skill.
- Social science, education, psychology-style construct research, surveys,
  interviews, causal inference, qualitative, or mixed-methods work:
  `domain-writing-social-science` then the writing skill.
- Humanities, interpretive, historical, textual, archive, philosophy, cultural,
  or concept-genealogy work: `domain-writing-humanities` then the writing
  skill.
- Law, policy, governance, regulation, doctrine, precedent, stakeholder
  tradeoff, implementation, or enforcement work: `domain-writing-law-policy`
  then the writing skill.

Write both `PAPER_PROFILE` and `DOMAIN_WRITING_PROFILE` into `PAPER_PLAN`
before manuscript-scale writing. Before title, abstract, introduction, or
manuscript-scale prose, run `manuscript-logic-gate` and require its expanded
reader-facing artifacts: `REVIEWER_PERSUASION_PREFLIGHT`,
`CENTRAL_THREAD_AUDIT`, `MATERIAL_TO_ARGUMENT_GATE`,
`TERM_SURFACE_SEMANTICS_AUDIT`, `ENUMERATION_DISCIPLINE_GATE`,
`TITLE_ABSTRACT_RESULT_ALIGNMENT`, `PARAGRAPH_MICRO_PLAN`, and
`READER_CONFUSION_TRACE`.

For method/search planning, do not silently default to STEM. A psychology,
education, biomedical, humanities, or law/policy topic needs its own
`method_route`, `search_route`, `search_strategies`, `method_requirements`, and
`baseline_anchor_fields` before discovery or drafting claims are promoted.

For idea evaluation, do not advance from a chat-only kill-or-keep judgment.
Use `PROBLEM_ANCHOR` to freeze the problem and closest baseline/source/
authority, then use `EVALUATION_GATE_PROFILE` to decide one of:
advance full experiment, run signal `pilot`, accept revisions, or reject.
Block when `paper_access_status` is not verified, `baseline_mode` is
unsupported, or `fatal_flaws` contain a critical item.

For experiment grounding, do not deploy or claim results from an ungrounded
plan. `EXPERIMENT_GROUNDING_PROFILE` must verify that `EXPERIMENT_GOAL`,
`EXPERIMENT_PLAN`, profile-specific reporting, `variable_grounding`, codebook
or source inventory, and `pre_deploy_code_review` are satisfied. Completed
results need a claim-bound `IMPACT_REPORT`; otherwise route to
`evidence-gating` or `claim-extraction` for blockers instead of drafting.

For result-to-claim conversion, do not turn a completed table or chat summary
into paper claims until `RESULT_TO_CLAIM_ANALYSIS_PROFILE` passes. It must bind
`CLAIMS_FROM_RESULTS`, source result artifacts, `relative_delta_table`,
`statistical_summary`, practical significance, negative results, competing
evidence, and `claim_strength` to the domain evidence tier. Use the tier range
from `A_confirmed` through `F_unsupported_or_blocked`. Block overclaimed or
unsupported claims, including any result claim that should remain
`F_unsupported_or_blocked`.

For presubmission and packaging, do not treat a compiled draft as complete
without skeleton/source integrity. `SKELETON_SOURCE_INTEGRITY_PROFILE` blocks
missing or stubbed required_section_groups, stale source artifacts, broken
source_trace or logic-chain mappings, missing Claims-Evidence Matrix coverage,
unverified BibTeX/DOI metadata, unresolved figure/table references, and
dangling citations. Route those blockers to `paper-writing`,
`section-drafting`, `paper-verify`, `publication-pack`, or
`provenance-review` rather than making submission-ready claims.

For review audit and rebuttal, do not treat an external review, response
letter, or camera-ready patch as ready until the review/rebuttal gates pass.
`PRESUBMISSION_SEVERITY_GATE_PROFILE` must classify findings as `CRITICAL`,
`MAJOR`, or `MINOR`; any CRITICAL finding or failed `integrity_gate` blocks
submission-facing advancement. `REBUTTAL_READINESS_GATE_PROFILE` must include
`ISSUE_BOARD`, response letter, `REVISION_PLAN`, response evidence, revision
deltas, and replay metadata, with a passing provenance gate, commitment gate,
and coverage gate before `REBUTTAL_PACKAGE` readiness claims.

## Workspace Self-Evolution Backlog Gate

When the current path contains `rh-workspace/`, feedback about RH output or
workflow quality is not only a local editing request. Capture reusable human
feedback through `rh-self-evolution`, then continue the current research task as
a topic-specific repair. During active research and active paper work: Do not synchronously patch RH mechanisms during paper or experiment work unless the user explicitly asks for an RH repair pass or backlog batch.

Agent-discovered issues should be captured only when repeated, clearly buggy,
evidence/provenance-risky, or blocking a verified RH workflow. Capture them as
self-evolution backlog items; defer generic RH mechanism patches to a dedicated
batch self-evolution session.

## Research Wiki Context Preflight

When the current path contains `rh-workspace/` and the user is asking for a
research rerun, experiment design, method improvement, gap/opportunity analysis,
or paper writing, first try to load the paper-card-derived Research Wiki context
pack:

```bash
rh topic wiki-context-pack --action-name <action> --json
```

Use `action-name` values such as `experiment_design`, `method_improvement`,
`paper_writing`, or `science_discovery`. If the payload reports
`paper_wiki_status: loaded`, treat `wiki_context_pack.v1` as the priority
evidence navigation layer before local synthesis files. If it reports
`paper_wiki_status: unavailable` or `paper_wiki_status: not_triggered`, state
the reason before continuing.

Pass `--topic-id <topic_id>` explicitly when running outside a materialized
topic workspace or when workspace metadata is ambiguous.

Do not silently substitute local markdown synthesis, experiment drafts, or
chat memory for Research Wiki evidence while claiming paper wiki was used.

## Defaults

- Prefer explicit ingestion over keeping ad hoc paper lists in chat only.
- Prefer concrete next actions over abstract workflow summaries.
- If Research Harness tools are unavailable, still follow the same workflow shape and state the missing tool plainly.
