---
name: domain-writing-biomedical
description: Biomedical, clinical, medical, public-health, and life-science domain writing profile for Research Harness paper workflows. Use before paper-writing or section-drafting when claims involve patients, cohorts, interventions, exposures, mechanisms, diagnostics, therapeutics, or biological evidence.
public_suite: paper
task_type: domain-writing-profile
data_access_level: local
inputs: topic_id, biomedical question, population or model system, study design, target venue, evidence artifacts, PAPER_PROFILE, PAPER_PLAN
outputs: BIOMEDICAL_WRITING_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PROFILE route, clinical and biological claim boundaries, ethics and reporting gates
gates: select this profile before biomedical manuscript-scale drafting; clinical, diagnostic, therapeutic, and biological mechanism claims must match PAPER_PROFILE study_design, reporting_map, evidence_rule, ethics, and evidence strength
artifact_schemas: PAPER_PROFILE, DOMAIN_WRITING_PROFILE, BIOMEDICAL_WRITING_PROFILE, PAPER_PLAN
estimated_runtime: 5-15 min
---

# Domain Writing: Biomedical And Medical

Use this skill when the manuscript concerns medicine, public health, clinical
care, biomedical science, diagnostics, therapeutics, cohorts, trials, patient
data, biological mechanisms, or translational claims. It produces a
`DOMAIN_WRITING_PROFILE` for `paper-writing` and `section-drafting`.

## PAPER_PROFILE Interop

Use this skill when `PAPER_PROFILE.discipline` is biomedical, medical,
clinical, public health, or life science. `PAPER_PROFILE.research_type` and
`PAPER_PROFILE.study_design` determine the biomedical reporting route and claim
strength. For clinical or intervention work, set:

```yaml
PAPER_PROFILE:
  domain_skill: domain-writing-biomedical
  domain_profile: BIOMEDICAL_WRITING_PROFILE
  method_route: biomedical-method-search
  reporting_map: biomedical-clinical
  evidence_rule: intervention-and-quasi-experiment
```

If `study_design` is observational, retrospective, exploratory, or mechanism
only, keep recommendations and causal language bounded by the routed
`evidence_rule`.

## DOMAIN_WRITING_PROFILE

Write the profile into `PAPER_PLAN.domain_writing_profile` or the active
drafting handoff:

```yaml
profile_id: BIOMEDICAL_WRITING_PROFILE
domain_skill: domain-writing-biomedical
domain_family: biomedical
claim_unit: population_or_model_system_intervention_or_exposure_outcome
question_frame: PICO
evidence_shape:
  required: [population_or_model_system, exposure_or_intervention, comparator, outcome, ethics]
  optional: [mechanism, clinical_significance, statistical_significance, adverse_events, subgroup]
claim_boundary: study design, cohort/trial limits, biological model limits, and outcome definitions
blocked_claims:
  - clinical recommendation without appropriate clinical evidence
  - causal or therapeutic language from observational or exploratory evidence
  - mechanism proof from association-only data
```

## Rhetorical Contract

- State the biomedical question through PICO or an explicit equivalent:
  population or model system, intervention or exposure, comparator, and outcome.
- Separate statistical significance, clinical significance, biological
  plausibility, and mechanistic proof.
- Explain cohort, trial, assay, or model-system limits before making broad
  translational claims.
- Use cautious language for exploratory, retrospective, underpowered, or
  single-site evidence.

## Evidence Requirements

- Methods must state design, inclusion/exclusion criteria, data source,
  endpoint definitions, ethics or IRB/consent status where relevant, and
  analysis plan.
- Results should report effect size and uncertainty, not only p values.
- Clinical claims need comparator, outcome, risk, and population boundaries.
- Biological mechanism claims need direct mechanistic evidence or must be
  labeled as plausible or hypothesis-generating.

## Drafting Bias

- Abstracts should include objective, design, population or model, main outcome,
  key result, and bounded conclusion.
- Discussion should distinguish implications for research, clinical practice,
  and policy.
- Limitations should cover confounding, selection bias, endpoint validity,
  generalizability, measurement limits, and safety where applicable.
- Do not produce medical advice; keep recommendations tied to the manuscript's
  evidence and review status.
