# Compatibility Inventory

Status: guarded lifecycle plan for review.

This inventory classifies Tier B MCP executable names after the public surface
was contracted to 30 advertised tools. It is a planning artifact only: approving
this document does not remove, deprecate, or change runtime behavior.

`scripts/check-compatibility-inventory.py` keeps this inventory synchronized
with `docs/mcp-tool-audit.md` and rejects missing Tier B names, unsupported
policy values, duplicate entries, and public Tier A names classified as Tier B.

Runtime check used for coverage:

- Public advertised MCP tools: 30
- Compatibility-dispatch executable names: 141
- Tier B primitive compatibility names: 77
- Tier B internal surface names: 38
- Tier B total: 115

## Policy Meanings

| Policy | Meaning | Implementation gate |
|---|---|---|
| `keep` | Retain as executable internal/admin/building-block surface. Do not advertise in `tools/list`. | Add service handler only when a migration slice needs it. |
| `wrapper` | Fold behind a workflow-level public or internal wrapper before discouraging direct use. | Wrapper contract, tests, and migration notes required first. |
| `deprecate` | A replacement already exists or the direct name is legacy-shaped. Keep executable during grace period. | Warning/telemetry shape and grace period required before behavior change. |
| `remove-later` | Experimental or over-generalized path with weak current product value. Candidate for removal after usage audit. | Usage telemetry, maintainer approval, and compatibility release notes required. |

## Primitive Compatibility Names

| Name | Policy | Target / wrapper | Rationale |
|---|---|---|---|
| `topic_set_contributions` | keep | internal topic state | Shared writing context; not a public workflow entrypoint. |
| `topic_get_contributions` | keep | internal topic state | Read helper for writing primitives. |
| `select_seeds` | wrapper | retrieval expansion workflow | Building block for citation expansion. |
| `expand_citations` | wrapper | retrieval expansion workflow | Fold with seed selection and acquisition. |
| `paper_acquire` | wrapper | `paper_ingest` / acquisition workflow | Acquisition side effects need a higher-level contract. |
| `paper_coverage_check` | keep | internal advisory/build gate | Coverage diagnostic remains useful internally. |
| `competitive_learning` | wrapper | writing pattern workflow | Venue-learning workflow should be packaged, not direct. |
| `code_generate` | wrapper | experiment workflow | Direct code generation is too low-level for agents. |
| `code_validate` | wrapper | experiment workflow | Keep behind generated-code validation flow. |
| `experiment_run` | wrapper | experiment workflow | Needs budget/sandbox contract before public use. |
| `experiment_loop` | wrapper | experiment workflow | Autonomous loop must stay gated. |
| `verified_registry_build` | keep | verification internals | Number registry support remains useful. |
| `verified_registry_check` | keep | verification internals | Number registry support remains useful. |
| `paper_verify_numbers` | wrapper | `consistency_check` / publication QA | Direct verification should be part of a QA bundle. |
| `citation_verify` | wrapper | `consistency_check` / publication QA | Direct external verification needs bundled reporting. |
| `citation_sanitize` | wrapper | publication QA | Useful deterministic closure step, but not public alone. |
| `evidence_trace` | wrapper | `consistency_check` / provenance review | Fold into evidence consistency contract. |
| `outline_generate` | wrapper | `section_draft` / writing workflow | Outline should be part of drafting flow. |
| `section_review` | wrapper | `consistency_check` / writing workflow | Direct review should be adapter behind consistency checks. |
| `section_revise` | wrapper | `section_draft` / writing workflow | Revision belongs in a bounded writing loop. |
| `latex_compile` | deprecate | publication workflow | Direct compile is legacy-shaped; use publication bundle flow. |
| `lesson_extract` | keep | self-evolution archive | Read-only evidence archive support. |
| `experience_ingest` | keep | self-evolution archive | Read-only evidence archive support. |
| `lesson_overlay` | keep | self-evolution archive | Prompt overlay remains internal. |
| `strategy_distill` | keep | self-evolution archive | Keep manual archive/champion path only. |
| `strategy_inject` | keep | self-evolution archive | Keep as internal overlay; do not promote. |
| `experiment_log` | keep | experiment evidence archive | Useful durable experiment record. |
| `meta_reflect` | keep | self-evolution archive | Keep read-only reflection; no mutation authority. |
| `deep_read` | keep | paper reading workflow | Core internal capability used by paper workflows. |
| `get_deep_reading` | keep | paper reading workflow | Read helper for existing deep-read notes. |
| `enrich_affiliations` | keep | metadata enrichment | Narrow utility with low public value but useful internally. |
| `reading_prioritize` | keep | paper reading workflow | Internal prioritization helper. |
| `method_taxonomy` | keep | analysis internals | Supports gap/method analysis. |
| `experiment_design_checklist` | keep | experiment planning internals | Deterministic checklist helper. |
| `evidence_matrix` | keep | analysis internals | Supports claim/evidence quality work. |
| `contradiction_detect` | keep | analysis internals | Supports downstream consistency work. |
| `dataset_index` | keep | analysis internals | Deterministic topic analysis helper. |
| `author_coverage` | keep | analysis internals | Deterministic coverage helper. |
| `table_extract` | keep | paper reading internals | PDF extraction helper; not public alone. |
| `figure_interpret` | keep | paper reading internals | PDF/figure helper; not public alone. |
| `metrics_aggregate` | keep | evidence aggregation | Supports publication QA and experiments. |
| `rebuttal_format` | wrapper | review workflow | Rebuttal output belongs in review/package flow. |
| `topic_export` | keep | reporting internals | Useful report/export helper. |
| `visualize_topic` | keep | reporting internals | Useful visualization helper. |
| `iterative_retrieval_loop` | wrapper | retrieval expansion workflow | Fold with query refinement and acquisition. |
| `topic_framing` | wrapper | research-init workflow | Belongs behind initialization/intake surface. |
| `direction_ranking` | wrapper | gap/proposal workflow | Fold behind proposal/gap workflow. |
| `method_layer_expansion` | wrapper | retrieval expansion workflow | Fold into method-aware search workflow. |
| `writing_architecture` | wrapper | writing workflow | Belongs behind section/publication drafting. |
| `writing_pattern_extract` | keep | writing internals | Internal observation collector. |
| `writing_skill_aggregate` | keep | writing internals | Internal aggregate, not public surface. |
| `figure_plan` | wrapper | publication workflow | Figure planning should be bundled. |
| `paper_finalize` | deprecate | publication workflow | Legacy one-shot finalization; prefer publication bundle flow. |
| `publication_pack_generate` | wrapper | publication workflow | Candidate public wrapper, but not advertised today. |
| `publication_pack_backfill` | keep | publication QA internals | Deterministic closure helper. |
| `publication_run` | wrapper | publication workflow | Candidate wrapper after service contract. |
| `venue_compliance_check` | keep | publication QA internals | Deterministic venue check remains useful. |
| `research_state_update` | keep | self-evolution archive | Read-only state feedback. |
| `design_brief_expand` | remove-later | algorithm-design future work | Over-generalized design loop; require benchmark evidence. |
| `design_gap_probe` | remove-later | algorithm-design future work | Over-generalized design loop; require benchmark evidence. |
| `algorithm_candidate_generate` | remove-later | algorithm-design future work | Over-generalized design loop; require benchmark evidence. |
| `originality_boundary_check` | remove-later | algorithm-design future work | Over-generalized design loop; require benchmark evidence. |
| `algorithm_design_refine` | remove-later | algorithm-design future work | Over-generalized design loop; require benchmark evidence. |
| `algorithm_design_loop` | remove-later | algorithm-design future work | Autonomous design loop should not remain default compatibility surface. |
| `cold_start_run` | keep | cold-start internals | Readiness diagnostic for topic bootstrapping. |
| `candidate_seed` | keep | recommendation internals | Deterministic candidate pipeline helper. |
| `candidate_upsert` | keep | recommendation internals | Deterministic candidate pipeline helper. |
| `cs_classify` | keep | CS harvest internals | Internal classification helper. |
| `head_paper_rank` | keep | CS harvest internals | Deterministic ranking helper. |
| `cs_harvest` | keep | CS harvest internals | Bulk harvest should remain internal. |
| `gap_cross_verify` | keep | gap QA internals | Useful QA helper for gap verification. |
| `compute_area_red_ocean` | keep | recommendation internals | Deterministic scoring helper. |
| `compute_task_red_ocean` | keep | recommendation internals | Deterministic scoring helper. |
| `compute_method_red_ocean` | keep | recommendation internals | Deterministic scoring helper. |
| `recommendations_generate` | wrapper | proposal/recommendation workflow | Candidate wrapper after downstream evaluation. |
| `task_canonicalize` | keep | claim/task normalization | Internal normalization helper. |
| `query_refine` | wrapper | retrieval expansion workflow | Fold into search/retrieval loop. |

## Internal Surface Compatibility Names

| Name | Policy | Target / wrapper | Rationale |
|---|---|---|---|
| `task_list` | keep | admin/UI internals | Useful read-only task inspection. |
| `provenance_token_report` | keep | provenance internals | Cost/token report remains useful internally. |
| `paper_dismiss` | keep | paper triage internals | Stateful triage helper; not public. |
| `decision_log_record` | keep | decision log internals | Durable decision capture. |
| `decision_log_list` | keep | decision log internals | Durable decision inspection. |
| `search_query_list` | keep | search registry internals | Search registry inspection. |
| `search_query_add` | keep | search registry internals | Search registry mutation with narrow semantics. |
| `advisory_list` | keep | advisory internals | Advisory inspection. |
| `advisory_acknowledge` | keep | advisory internals | Advisory acknowledgement. |
| `paper_purge` | keep | admin-only paper management | Destructive admin helper; keep unadvertised. |
| `venue_refresh` | keep | admin-only metadata refresh | Narrow admin helper. |
| `domain_list` | keep | domain admin internals | Domain administration. |
| `domain_init` | keep | domain admin internals | Domain administration. |
| `domain_show` | keep | domain admin internals | Domain administration. |
| `orchestrator_add_artifact_dependency` | keep | orchestrator internals | Artifact graph maintenance. |
| `orchestrator_mark_artifact_stale` | keep | orchestrator internals | Artifact staleness maintenance. |
| `orchestrator_clear_artifact_stale` | keep | orchestrator internals | Artifact staleness maintenance. |
| `orchestrator_list_stale_artifacts` | keep | orchestrator internals | Artifact staleness inspection. |
| `integrity_check` | wrapper | review / publication QA | Fold into integrity/review workflow. |
| `finalize` | deprecate | publication workflow | Legacy finalization surface. |
| `review_bundle_create` | wrapper | review workflow | Review workflow should expose fewer entrypoints. |
| `review_add_issue` | wrapper | review workflow | Fold into review workflow. |
| `review_issues` | wrapper | review workflow | Fold into review workflow. |
| `review_respond` | wrapper | review workflow | Fold into review workflow. |
| `review_resolve` | wrapper | review workflow | Fold into review workflow. |
| `review_status` | wrapper | review workflow | Fold into review workflow. |
| `adversarial_run` | deprecate | `adversarial_review` | Public replacement exists. |
| `adversarial_resolve` | deprecate | `adversarial_review` | Public replacement exists. |
| `adversarial_status` | deprecate | `adversarial_review` | Public replacement exists. |
| `experiment_handoff_prepare` | keep | experiment handoff internals | Human-gated handoff helper. |
| `experiment_handoff_submit` | keep | experiment handoff internals | Human-gated handoff helper. |
| `workflow_entry` | deprecate | `orchestrator_resume` | Public resume/status path exists. |
| `claim_verify` | wrapper | `consistency_check` / review QA | Fold into consistency/review workflow. |
| `adversarial_section_review` | wrapper | review workflow | Fold into review workflow. |
| `paperindex_structure` | keep | paperindex internals | Local PDF structure helper. |
| `paperindex_card` | keep | paperindex internals | Local PDF card helper. |
| `paper_ingest_manual` | deprecate | `paper_ingest` | Public ingestion path exists. |
| `paper_resolve_pdfs` | wrapper | `paper_ingest` / acquisition workflow | Fold into acquisition workflow. |

## Follow-Up Gates

No implementation should change compatibility behavior until these gates pass:

1. Add telemetry or provenance-safe warning counts for Tier B direct calls.
2. Add tests for deprecated warning shape and public replacement hints.
3. Create wrapper contracts before moving any `wrapper` name to `deprecate`.
4. Require maintainer approval before changing any `remove-later` name.
5. Keep `tools/list` frozen at 30 unless a separate public-surface exception is
   approved.
