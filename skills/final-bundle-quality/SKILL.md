---
name: final-bundle-quality
description: Evaluate and replay final_bundle PDF/LaTeX quality for Research Harness project-level self-evolution. Trigger on phrases like "final bundle quality", "PDF quality replay", "LaTeX quality gate", "AAAI PDF QA", "final_bundle_quality", or equivalent requests to scan publication bundles, classify layout/encoding/recompile defects, and decide whether a skill can be promoted.
category: research
version: 0.1.2
public_suite: benchmark
task_type: evaluation
data_access_level: local-files
inputs: topic_id, final_bundle artifact, TeX/PDF/log paths, target profile
outputs: final_bundle_quality_report, replay trajectory, promotion decision
gates: zero blocking and zero recompile-repairable issues before promotion claims
artifact_schemas: final_bundle_quality_report, runtime_trace_grade
estimated_runtime: 5-30 min
---

# Final Bundle Quality

Use this skill when a Research Harness topic has a `final_bundle` artifact and the goal is to verify PDF/LaTeX quality, compare quality trajectory, or evaluate whether a project-level repair policy can be promoted.

## Inputs

- Source topic id and active `final_bundle` artifact id.
- Target profile, for example `AAAI-style-science-discovery`.
- TeX, PDF, log, and optional bibliography paths from the artifact payload.
- Lifecycle pack and trajectory gate artifacts when evaluating promotion.
- Held-out `final_bundle` artifacts from another topic.

## Workflow

1. Scan the source bundle with `scan_pdf_quality_bundle`.
2. Classify issues into blocking, recompile-repairable, layout-only, and encoding groups.
3. Build or load a path-safe `pdf_quality_replay_trajectory`; do not infer historical quality by rescanning shared mutable paths.
4. Run the trajectory gate before any held-out replay decision.
5. Collect held-out replay signals from active non-source `final_bundle` artifacts.
6. Evaluate lifecycle promotion with `evaluate_skill_lifecycle_pack`.
7. If a `multi_route_review_report` exists, parse it as strong readiness guidance before reporting significant PDF quality improvement.
8. If the blocker is figure readability, placeholder diagrams, or weak visual evidence, trigger `figure-quality` before reporting publication-readiness improvement.
9. Record gate, discovery, and management artifacts before changing global skill behavior.

## Promotion Rules

- Source trajectory must pass final PDF quality thresholds.
- Source bundle and held-out bundle must have zero blocking and zero recompile-repairable issues.
- Layout-only warnings must include line ranges, source excerpts, or accepted thresholds.
- Real held-out replay must pass page, citation, anonymization, and bibliography gates.
- Controlled or synthetic backfills can exercise replay plumbing but must not count as promotion evidence.
- Exact target-profile replay is preferred. Compatible target profiles are allowed only when explicitly supplied through `compatible_target_profiles`, and the artifact metadata must preserve `target_profile_match=compatible`.
- Promotion metadata must distinguish `promotion_strength=exact_profile_held_out` from `promotion_strength=compatible_profile_held_out`; do not report compatible-profile evidence as exact-profile validation.
- A clean deterministic PDF scan does not override a multi-route consensus reject; reviewer consensus blocks publication-readiness handoff until project-level review gates record and address the blockers.
- Novelty, scope, and evidence objections from multi-route review are submission-readiness blockers only; this skill must not mutate topic-level research strategy or topic self-evolution policy.
- Figure/table quality objections should route to `figure-quality`; deterministic PDF cleanliness does not make placeholder figures publication-ready.

## Current Evidence

- Current strongest promotion evidence is exact-profile held-out replay: `project_artifacts:771`, topic 5 ResearchFlowBench recompiled through the RH AAAI-style compiler path.
- Current lifecycle gate: `project_artifacts:772`, action `promote`, `promotion_strength=exact_profile_held_out`, `target_profile_match=exact`.
- Current strongest reviewer-readiness evidence is `project_artifacts:778`: all completed host-agent routes rejected `layout-v8`, with minimum scores `aaai_readiness=2`, `evidence=2`, `visuals=3`, `format=2`.
- Earlier compatible-profile replay remains useful historical evidence: `project_artifacts:757`, `target_profile_match=compatible`, `promotion_strength=compatible_profile_held_out`.
- Controlled replay `project_artifacts:752` remains plumbing-only evidence and must not count as promotion evidence.

## Memory Policy

- Transferable memory: issue category, severity, target profile, gate outcome, and repair policy.
- Topic-local memory: topic id, artifact id, file paths, source paths, and one-off bundle layout details.
- Do not hard-code topic 8 paths, artifact ids, filenames, or AAAI-specific thresholds into project-level behavior.

## Known Lessons

- Tab-prefixed malformed LaTeX commands and invalid UTF-8 are recompile-repairable defects.
- Underfull hbox warnings are layout-only diagnostics and should not trigger infinite repair loops.
- Overfull hbox warnings require line-level diagnostics and should not mask citation or venue gates.
- A clean source topic is insufficient for project-level promotion without held-out replay.
- A compatible-profile held-out replay can promote this skill only when explicitly declared and recorded.
- When recompiling single-column source material into AAAI-style two-column drafts, infer `tabularx`/`array` dependencies and promote `tabularx{\textwidth}` tables to `table*` floats to avoid high-severity overfull boxes.
- A hand-written `twocolumn` preamble without an explicit user request or a declared two-column target venue is a layout defect: the default English manuscript layout is single-column (11pt article, 1in margins). When converting two-column drafts back to single column, demote `figure*`/`table*`, drop `\resizebox{\columnwidth}` wrappers so small tables keep natural size, cap single-plot figures near `0.6\textwidth`, and re-check wide multi-column result tables — they may newly overflow `\textwidth` and need `\resizebox{\textwidth}` or column trimming.
- Multi-route review consensus can be stricter than deterministic PDF scanning: official venue style, evidence-bearing tables/visuals, reproducibility artifacts, and reviewer score minima should guide project-level gates before any human handoff claim.
