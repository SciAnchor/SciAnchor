---
name: section-drafting
description: Draft paper sections from Research Harness evidence. Trigger on phrases like "section-drafting", "/section-drafting", "章节起草", "根据证据写 related work", or equivalent requests to produce evidence-backed draft sections tied to ingested papers and extracted claims.
public_suite: paper
task_type: writing
data_access_level: local
inputs: topic_id, section name, evidence IDs, paper pool, PAPER_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PLAN, SKELETON_SOURCE_INTEGRITY_PROFILE, outline
outputs: evidence-backed section draft, citation/evidence mapping, Claims-Evidence Matrix updates, source_trace updates, domain-specific claim boundary notes
gates: no unsupported freeform claims; use section_draft when available; require PAPER_PROFILE and DOMAIN_WRITING_PROFILE and prefer PAPER_PLAN before manuscript-scale drafting; keep source_trace and citation_integrity repairable before submission-facing drafts
artifact_schemas: draft_section, consistency_check, PAPER_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PLAN, SKELETON_SOURCE_INTEGRITY_PROFILE
estimated_runtime: 10-45 min
---

# Section Drafting

Use this skill for evidence-backed writing, not freeform speculation.

## RH research delivery protocol

Use RH as the evidence and state source of truth. The protocol has no external runtime dependency.
When drafting is part of the research delivery protocol, prefer a
recorded `PAPER_PLAN` and Claims-Evidence Matrix before producing prose. For a
`human_in_loop_call`, infer whether the user is asking for a section draft,
paper-plan repair, or evidence-gap cleanup before writing.

## Domain Writing Profile Preflight

Before drafting any manuscript-scale section, load `PAPER_PROFILE` from
`PAPER_PLAN.paper_profile` and the active `DOMAIN_WRITING_PROFILE` from
`PAPER_PLAN.domain_writing_profile`. `PAPER_PROFILE` must name `discipline`,
`research_type`, `study_design`, `reporting_map`, and `evidence_rule`; missing
or ambiguous fields block drafting; do not silently default to STEM.

Use `PAPER_PROFILE.domain_skill` or select the right domain skill first:

- `domain-writing-stem` for STEM, engineering, AI/ML, systems, benchmarks, and
  method papers.
- `domain-writing-biomedical` for medical, clinical, public-health,
  biomedical, diagnostic, therapeutic, and biological-mechanism papers.
- `domain-writing-social-science` for theory, constructs, identification
  strategy, surveys, interviews, qualitative, quantitative, and mixed-methods
  social research.
- `domain-writing-humanities` for interpretive, archive, textual, historical,
  philosophical, cultural, and concept-genealogy work.
- `domain-writing-law-policy` for normative, precedent, statutory, regulatory,
  governance, policy, stakeholder, implementation, and enforcement work.

Use the domain profile to decide what a sentence is allowed to claim. For
example, do not force baseline and ablation rhetoric onto humanities writing,
do not turn observational social-science results into causal effects, and do
not turn biomedical associations into clinical recommendations. Use
`reporting_map` to decide what methods/results information must appear in the
section and `evidence_rule` to decide how strong each claim may be.

## Research Wiki Context Preflight

Before drafting sections from an `rh-workspace/` topic, run:

```bash
rh topic wiki-context-pack --action-name paper_writing --json
```

If `paper_wiki_status` is `loaded`, use `wiki_context_pack.v1` as the priority
evidence navigation layer for selecting claims, pages, and anchors. If the
preflight is unavailable or not triggered, state the reason and do not represent
local markdown synthesis as paper wiki evidence.

## Workflow

1. Confirm the target section and audience.
2. Confirm or select the matching `PAPER_PROFILE` and
   `DOMAIN_WRITING_PROFILE`.
3. Gather the relevant papers, claims, baselines, sources, cases, constructs,
   corpus, or policy authorities required by that profile.
4. Use `section_draft` if available.
5. Make citations traceable to paper IDs or source records.
6. Flag unsupported sentences instead of smoothing over evidence gaps.
7. For submission-facing sections, update or request
   `SKELETON_SOURCE_INTEGRITY_PROFILE`: required_section_groups must still be
   present and non-stubbed, every new claim needs source_trace into the
   Claims-Evidence Matrix and source artifacts, and citation_integrity plus
   bib_doi_verification must leave no dangling citations before packaging.
