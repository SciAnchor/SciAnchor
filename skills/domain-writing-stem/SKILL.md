---
name: domain-writing-stem
description: STEM and engineering domain writing profile for Research Harness paper workflows. Use before paper-writing or section-drafting when the manuscript is in AI/ML, computer science, engineering, physical science, systems, benchmark, or method-development work.
public_suite: paper
task_type: domain-writing-profile
data_access_level: local
inputs: topic_id, discipline, research type, study design, target venue, evidence artifacts, PAPER_PROFILE, PAPER_PLAN
outputs: STEM_ENGINEERING_WRITING_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PROFILE route, claim boundaries, section priorities, reproducibility and evidence gates
gates: select this profile before manuscript-scale drafting for STEM or engineering work; performance, novelty, baseline, and ablation claims must be evidence-bound by PAPER_PROFILE reporting_map and evidence_rule
artifact_schemas: PAPER_PROFILE, DOMAIN_WRITING_PROFILE, STEM_ENGINEERING_WRITING_PROFILE, PAPER_PLAN
estimated_runtime: 5-15 min
---

# Domain Writing: STEM And Engineering

Use this skill when the paper's center of gravity is a technical method,
system, model, benchmark, empirical engineering result, or reproducibility
claim. It produces a `DOMAIN_WRITING_PROFILE` to be loaded before
`paper-writing` and `section-drafting`.

## PAPER_PROFILE Interop

Use this skill when `PAPER_PROFILE.discipline` is ML, AI, data, computer
science, systems, engineering, physical science, or another STEM field. For
empirical ML or system benchmarks, route to:

```yaml
PAPER_PROFILE:
  domain_skill: domain-writing-stem
  domain_profile: STEM_ENGINEERING_WRITING_PROFILE
  method_route: domain-method-search-stem
  reporting_map: ml-empirical-method
  evidence_rule: ml-benchmark
```

Use `reporting_map` to require dataset, metric, baseline, ablation,
implementation, and reproducibility details. Use `evidence_rule` to keep
performance, novelty, and generalization claims inside the tested task,
dataset, system, and benchmark boundary.

## DOMAIN_WRITING_PROFILE

Write the profile into `PAPER_PLAN.domain_writing_profile` or attach it to the
active drafting handoff:

```yaml
profile_id: STEM_ENGINEERING_WRITING_PROFILE
domain_skill: domain-writing-stem
domain_family: stem_engineering
claim_unit: problem_method_evidence
evidence_shape:
  required: [task, dataset_or_system_context, metric, baseline, ablation]
  optional: [complexity, robustness, sensitivity, failure_case, reproducibility]
claim_boundary: tested datasets, splits, metrics, seeds, baselines, and system context
blocked_claims:
  - untested generalization beyond the evaluated task or system
  - novelty claims without comparison to current baselines
  - performance claims without metric, data, and baseline anchors
```

## Rhetorical Contract

- Lead with the concrete technical problem and why existing methods, systems,
  or benchmarks fail under a specific condition.
- Frame contributions as a small set of testable claims: problem formulation,
  method or system design, empirical result, and reproducibility or deployment
  implication.
- Keep method prose causal only at the mechanism level that is implemented and
  inspected; empirical superiority still depends on measured evidence.
- Use analytical Related Work groups rather than per-paper summaries.

## Evidence Requirements

- Every performance sentence names or inherits the metric, dataset, split,
  baseline, and comparison direction.
- The strongest method claim needs a fair baseline comparison.
- Component claims need ablation evidence, sensitivity analysis, complexity
  analysis, or a clearly labeled design rationale.
- Reproducibility claims need enough setup detail for a reviewer to inspect
  data, code, hyperparameters, environment, and random seeds.

## Drafting Bias

- Method/design sections should define symbols, dimensions, inputs, outputs,
  and the data flow between modules.
- Experiment sections should explain what claim each table or figure tests.
- Abstract and introduction should avoid field-generic openings and lead with
  the task, bottleneck, method, and strongest scoped result.
- Limitations should name scope boundaries without implying unsupported
  collapse of the whole contribution.

## Section contract

For an engineering or CS method paper, draft and revise each section against
`skills/domain-writing-stem/ENGINEERING_SECTION_CONTRACT.md`. That file states
what each section answers, what it must not contain, and how Related Work,
Problem Formulation, Method, Results, and Discussion divide the work. The
exemplar plan bound to the topic is the comparison set. Do not open a second
search to imitate published section shapes. Medical IMRaD and humanities
skeletons do not load this contract.
