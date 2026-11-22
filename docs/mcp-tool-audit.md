# MCP Tool Surface Audit

Verified: 2026-07-05.

ARH02 public-surface update: 2026-09-10.

Current counts from `research_harness_mcp.tools`:

- Public advertised MCP tools: 54
- Compatibility-dispatch executable names: 175
- Registered primitives: 103

`tools/list` is intentionally limited to Tier A. Tier B names remain executable
through `execute_tool` for compatibility, but they are not advertised to agents
as the public contract. Compatibility-only calls add an `_deprecated` field to
the response so agents can migrate to Tier A tools.

## Guard Rails

- `scripts/check-mcp-public-surface.py` freezes the advertised count at 55 and
  checks that this audit's Tier A table matches
  `research_harness_mcp.tool_surface.PUBLIC_MCP_TOOL_NAMES`.
- `scripts/check-compatibility-inventory.py` checks that every Tier B name in
  this audit has exactly one lifecycle policy in the compatibility inventory,
  that policies are limited to `keep`, `wrapper`, `deprecate`, or
  `remove-later`, and that public Tier A names are not classified as Tier B.
- `scripts/codex-check.sh --quick` runs the guard before architecture and schema
  checks, so public MCP surface or compatibility inventory drift fails the
  normal Codex verification entry.
- Service dispatcher coverage: 53 of the 54 public tools route through
  `ResearchService` in the MCP adapter; `deposit_zenodo` is a convenience
  surface that calls `research_harness.deposit.zenodo` directly. CLI, HTTP, and
  Python facade transport convergence is tracked separately and still covers
  only the read-equivalent surface completed by bounded migration slices.

## Tier A: Public Contracted Tools

These are defined in `research_harness_mcp.tool_surface.PUBLIC_MCP_TOOL_NAMES`.

| Tool | Kind | Workflow role |
|---|---|---|
| `topic_list` | surface | Discover topics. |
| `topic_show` | surface | Inspect one topic. |
| `topic_init` | surface | Create a research topic without the CLI. |
| `topic_state` | surface | Unified single-call topic introspection with a computed next action. |
| `paper_search` | primitive | Search local/remote literature. |
| `paper_ingest` | primitive | Add known papers/PDFs to the pool. |
| `paper_list` | surface | Inspect the local paper pool. |
| `paper_summarize` | primitive | Summarize one known paper. |
| `claim_extract` | primitive | Extract structured claims. |
| `evidence_link` | primitive | Link claims to supporting sources. |
| `gap_detect` | primitive | Identify research gaps. |
| `baseline_identify` | primitive | Identify baseline methods. |
| `section_draft` | primitive | Draft evidence-constrained sections. |
| `figure_generate` | primitive | Generate paper-ready figure assets. |
| `consistency_check` | primitive | Check draft and evidence consistency. |
| `orchestrator_status` | surface | Inspect workflow state. |
| `orchestrator_resume` | surface | Resume/create a workflow run. |
| `orchestrator_advance` | surface | Advance a gated stage. |
| `orchestrator_gate_check` | surface | Evaluate readiness gates. |
| `orchestrator_record_artifact` | surface | Persist durable outputs. |
| `paper_commit_version` | surface | Commit one manuscript version atomically (hash + artifact trio + lineage validation). |
| `paper_task_intake` | surface | Create or resume durable paper-production state from a natural-language task. |
| `adversarial_review` | surface | Run independent challenge/review. |
| `advisory_check` | surface | Run lightweight workflow advisories. |
| `provenance_summary` | surface | Summarize provenance and costs. |
| `provenance_export` | surface | Export detailed provenance. |
| `zotero_sync` | surface | Sync topic state with Zotero. |
| `paperindex_search` | surface | Search local PDF annotations/cards. |
| `paper_production_pending_decisions` | surface | List decisions waiting on a human. |
| `paper_production_decide` | surface | Record a human decision for a paused workflow. |
| `paper_production_start` | surface | Start a paper-production workflow without the CLI. |
| `paper_production_status` | surface | Inspect paper-production progress and interaction mode. |
| `paper_production_resume` | surface | Resume a paused paper-production workflow. |
| `paper_production_mode` | surface | Get the current interaction mode. |
| `paper_production_set_mode` | surface | Change the interaction mode mid-workflow. |
| `paper_production_export` | surface | Export the generated paper bundle. |
| `skill_list` | surface | Discover RH workflow skills. |
| `skill_get` | surface | Read one workflow skill package. |
| `productization_boundary` | surface | Inspect the opt-in LG10 public-productization boundary preview. |
| `topic_knowledge_status` | surface | Inspect Topic Knowledge readiness and coverage. |
| `topic_knowledge_refresh` | surface | Refresh derived Topic Knowledge snapshots. |
| `cross_topic_atlas` | surface | Inspect evidence-bound links across topics. |
| `exemplar_curate` | primitive | Build a quality-gated exemplar library slice (FORM only) from a topic's papers. |
| `exemplar_retrieve` | primitive | Rank curated exemplars by structure over topic; return top-k. |
| `exemplar_plan` | primitive | FORM-only plan (skeleton/arc/figure-suite spec) by analogy to exemplars. |
| `exemplar_generate` | primitive | Plan→draft→anti-plagiarism-critique→revise loop for prose artifacts. |
| `exemplar_critique` | primitive | Deterministic n-gram form-not-content (anti-plagiarism) gate. |
| `figure_suite_plan` | primitive | Design or reconcile the whole-paper figure contract (spec + matrix coverage + logging requirements + generative export). |
| `figure_suite_render` | primitive | Deterministically render an exemplar-planned figure suite from recorded experiment records. |
| `figure_package` | primitive | Build one evidence-bound Figure Package from a FigureTask (top-one; fake provider on the public path). |
| `manuscript_review` | primitive | Multi-angle reviewer critique of a full manuscript. |
| `manuscript_polish` | primitive | Orchestrated final-draft polish with a submission-readiness verdict. |
| `resource_ready_get` | surface | Fetch the active SPC resource-ready binding for a topic/workflow/host. |
| `deposit_zenodo` | surface | Pack topic code+data, deposit to Zenodo, return separate code/data DOIs. |

## Tier B: Internal Primitive Compatibility Names

These are registered primitives but no longer advertised through MCP
`tools/list`.

```text
topic_set_contributions
topic_get_contributions
select_seeds
expand_citations
paper_acquire
paper_coverage_check
competitive_learning
code_generate
code_validate
experiment_run
experiment_loop
verified_registry_build
verified_registry_check
paper_verify_numbers
citation_verify
citation_sanitize
evidence_trace
outline_generate
section_review
section_revise
latex_compile
lesson_extract
experience_ingest
lesson_overlay
strategy_distill
strategy_inject
experiment_log
meta_reflect
deep_read
get_deep_reading
enrich_affiliations
reading_prioritize
method_taxonomy
experiment_design_checklist
evidence_matrix
contradiction_detect
dataset_index
author_coverage
table_extract
figure_interpret
metrics_aggregate
rebuttal_format
topic_export
visualize_topic
iterative_retrieval_loop
topic_framing
direction_ranking
method_layer_expansion
writing_architecture
writing_pattern_extract
writing_skill_aggregate
figure_plan
paper_finalize
publication_pack_generate
publication_pack_backfill
publication_run
venue_compliance_check
research_state_update
design_brief_expand
design_gap_probe
algorithm_candidate_generate
originality_boundary_check
algorithm_design_refine
algorithm_design_loop
cold_start_run
candidate_seed
candidate_upsert
cs_classify
head_paper_rank
cs_harvest
gap_cross_verify
compute_area_red_ocean
compute_task_red_ocean
compute_method_red_ocean
recommendations_generate
task_canonicalize
query_refine
```

## Tier B: Internal Surface Compatibility Names

These are non-primitive MCP handlers retained for compatibility, admin, UI, or
specialized workflows.

```text
task_list
provenance_token_report
paper_dismiss
decision_log_record
decision_log_list
search_query_list
search_query_add
advisory_list
advisory_acknowledge
paper_purge
venue_refresh
domain_list
domain_init
domain_show
orchestrator_add_artifact_dependency
orchestrator_mark_artifact_stale
orchestrator_clear_artifact_stale
orchestrator_list_stale_artifacts
integrity_check
finalize
review_bundle_create
review_add_issue
review_issues
review_respond
review_resolve
review_status
adversarial_run
adversarial_resolve
adversarial_status
experiment_handoff_prepare
experiment_handoff_submit
workflow_entry
claim_verify
adversarial_section_review
paperindex_structure
paperindex_card
paper_ingest_manual
paper_resolve_pdfs
```

## Follow-up Consolidation Candidates

These compatibility names are good candidates for later workflow-level wrappers:

| Cluster | Internal names | Candidate public wrapper |
|---|---|---|
| Retrieval expansion | `select_seeds`, `expand_citations`, `query_refine`, `iterative_retrieval_loop`, `paper_acquire` | `paper_expand` or keep under `paper_search`/`paper_ingest` workflows |
| Experiment loop | `code_generate`, `code_validate`, `experiment_run`, `experiment_loop`, `verified_registry_*` | `experiment_run` workflow tool |
| Publication closure | `publication_*`, `venue_compliance_check`, `paper_finalize`, `latex_compile` | `bundle_finalize` |
| Review loop | `review_*`, `adversarial_*`, `integrity_check` | `review_run` / `review_status` |
| Evolution | `lesson_*`, `strategy_*`, `experience_ingest`, `research_state_update` | `evolution_propose` / `evolution_promote` |

## Tier B Lifecycle Inventory

Detailed lifecycle policy for every Tier B executable name is tracked in
`docs/contracts/compatibility-inventory.md`.

The inventory classifies 115 Tier B names: 77 internal primitive compatibility
names and 38 internal surface compatibility names. Policy values are `keep`,
`wrapper`, `deprecate`, and `remove-later`. The inventory is planning-only: no
runtime behavior, warning shape, deprecation, or removal is approved by the
classification itself.
