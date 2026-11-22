---
name: domain-writing-humanities
description: Humanities domain writing profile for Research Harness paper workflows. Use before paper-writing or section-drafting when the manuscript is interpretive, historical, textual, philosophical, archival, cultural, literary, art-historical, or concept-genealogical.
public_suite: paper
task_type: domain-writing-profile
data_access_level: local
inputs: topic_id, corpus or archive, interpretive question, historical context, target venue, evidence artifacts, PAPER_PROFILE, PAPER_PLAN
outputs: HUMANITIES_WRITING_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PROFILE route, interpretive argument boundaries, archive and corpus evidence map
gates: select this profile before humanities manuscript-scale drafting; do not force baseline, ablation, metric, or experiment rhetoric onto interpretive work; apply PAPER_PROFILE reporting_map and evidence_rule to source-grounding claims
artifact_schemas: PAPER_PROFILE, DOMAIN_WRITING_PROFILE, HUMANITIES_WRITING_PROFILE, PAPER_PLAN
estimated_runtime: 5-15 min
---

# Domain Writing: Humanities

Use this skill when the manuscript is grounded in interpretation, archives,
texts, images, performances, historical materials, philosophy, cultural
analysis, literary analysis, art history, media studies, or concept genealogy.
It produces a `DOMAIN_WRITING_PROFILE` for `paper-writing` and
`section-drafting`.

## PAPER_PROFILE Interop

Use this skill when `PAPER_PROFILE.discipline` is humanities, history,
philosophy, literary studies, cultural studies, art history, archive studies,
or an adjacent interpretive field. Qualitative and interpretive work should
route to humanities source/context reporting rather than STEM benchmark
reporting:

```yaml
PAPER_PROFILE:
  domain_skill: domain-writing-humanities
  domain_profile: HUMANITIES_WRITING_PROFILE
  method_route: humanities-method-search
  reporting_map: humanities-source-context
  evidence_rule: interpretive-source-grounding
```

Use `reporting_map` to make corpus, archive, edition, translation, and context
visible. Use `evidence_rule` to keep claims inside the source and interpretive
frame.

## DOMAIN_WRITING_PROFILE

Write the profile into `PAPER_PLAN.domain_writing_profile` or the active
drafting handoff:

```yaml
profile_id: HUMANITIES_WRITING_PROFILE
domain_skill: domain-writing-humanities
domain_family: humanities
claim_unit: interpretive_argument_source_context
evidence_shape:
  required: [archive_or_corpus, interpretive_question, source_context, argument_stakes]
  optional: [close_reading, historical_context, concept_genealogy, counter_reading, translation_note]
claim_boundary: source corpus, archive limits, historical context, interpretive method, and language/translation limits
blocked_claims:
  - empirical prevalence claims without appropriate evidence
  - forced baseline or ablation framing for interpretive arguments
  - universal cultural claims beyond corpus and context
```

## Rhetorical Contract

- Lead with the interpretive problem, archive or corpus, and why the reading
  changes an existing scholarly conversation.
- Make the thesis arguable, source-grounded, and historically or conceptually
  situated.
- Use evidence as close reading, archival trace, contextual comparison,
  genealogy, or conceptual analysis, not as metric-driven proof unless the
  project genuinely includes quantitative humanities evidence.
- Let counter-readings sharpen the argument rather than treating them as
  baselines to defeat.

## Evidence Requirements

- Every major interpretive claim should point to source material, archive
  location, textual passage, image, historical record, or established scholarly
  debate.
- Context claims need temporal, geographic, linguistic, and cultural scope.
- Translation and edition choices should be visible when they affect meaning.
- Generalization should stay within the corpus, archive, period, or conceptual
  frame.

## Drafting Bias

- Section order should follow argumentative movement, not IMRAD by default.
- Literature review can be woven into the argument when that is the field norm.
- Topic sentences should advance the thesis, not summarize sources neutrally.
- Limitations may appear as scope conditions, archive silences, alternative
  readings, or future interpretive paths.
