---
name: domain-writing-social-science
description: Social science domain writing profile for Research Harness paper workflows. Use before paper-writing or section-drafting when the manuscript depends on theory, constructs, variables, identification strategy, survey, interview, observational, causal-inference, qualitative, or mixed-methods evidence.
public_suite: paper
task_type: domain-writing-profile
data_access_level: local
inputs: topic_id, theory or construct focus, study design, variables, population, target venue, evidence artifacts, PAPER_PROFILE, PAPER_PLAN
outputs: SOCIAL_SCIENCE_WRITING_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PROFILE route, construct and identification boundaries, theory-method-evidence mapping
gates: select this profile before social-science manuscript-scale drafting; causal, theoretical, and construct claims must match PAPER_PROFILE study_design, reporting_map, evidence_rule, measurement, and identification strategy
artifact_schemas: PAPER_PROFILE, DOMAIN_WRITING_PROFILE, SOCIAL_SCIENCE_WRITING_PROFILE, PAPER_PLAN
estimated_runtime: 5-15 min
---

# Domain Writing: Social Science

Use this skill when the manuscript is organized around social theory,
constructs, institutions, behavior, policy effects, organizations, education,
psychology-adjacent social research, communication, economics, sociology,
political science, qualitative inquiry, surveys, interviews, experiments, or
mixed methods. It produces a `DOMAIN_WRITING_PROFILE` for `paper-writing` and
`section-drafting`.

## PAPER_PROFILE Interop

Use this skill when `PAPER_PROFILE.discipline` is social science, psychology,
education, communication, economics, sociology, political science, or adjacent
construct-driven work. For survey or cross-sectional designs, route to:

```yaml
PAPER_PROFILE:
  domain_skill: domain-writing-social-science
  domain_profile: SOCIAL_SCIENCE_WRITING_PROFILE
  method_route: social-science-method-search
  reporting_map: psychology-survey-correlational
  evidence_rule: cross-sectional-survey
```

If `PAPER_PROFILE.study_design` is `cross_sectional`, do not use causal,
temporal, or mechanism-proof language. Use `reporting_map` for construct,
sample, measure, and model disclosure, and use `evidence_rule` to bound
generalization and effect language.

## DOMAIN_WRITING_PROFILE

Write the profile into `PAPER_PLAN.domain_writing_profile` or the active
drafting handoff:

```yaml
profile_id: SOCIAL_SCIENCE_WRITING_PROFILE
domain_skill: domain-writing-social-science
domain_family: social_science
claim_unit: theory_construct_design_evidence
evidence_shape:
  required: [theory, construct, operationalization, sample_or_case, identification_strategy]
  optional: [validity_threat, mechanism, qualitative_theme, robustness_check, positionality]
claim_boundary: measurement validity, sampling, design, identification strategy, and social context
blocked_claims:
  - causal language without a credible identification strategy
  - construct claims without operationalization or qualitative grounding
  - population generalization beyond sampling and context
```

## Rhetorical Contract

- Start from the social problem, theoretical puzzle, or institutional context,
  then introduce constructs and hypotheses or research questions.
- Define each construct before using it as an explanatory variable, mechanism,
  or outcome.
- Make the identification strategy explicit for causal work and the
  interpretive strategy explicit for qualitative work.
- Keep theory, method, results, and implications connected; do not let model
  outputs replace theoretical explanation.

## Evidence Requirements

- Quantitative work needs variables, measurement sources, model specification,
  uncertainty, robustness, and design limitations.
- Qualitative work needs corpus or field site, sampling, coding or interpretive
  procedure, reflexivity or positionality when relevant, and representative
  evidence.
- Mixed-methods work must state which evidence stream supports each claim.
- Causal claims require design leverage; associations, correlations, and
  cross-sectional models must use bounded language.

## Drafting Bias

- Introduction should build from theory and construct gap to research question
  or hypotheses.
- Methods should be detailed enough for a reader to judge validity, not only
  reproduce software commands.
- Discussion should return to theory, boundary conditions, and practical or
  policy implications.
- Limitations should name measurement, sampling, external validity, omitted
  variable, researcher-position, and design threats where applicable.
