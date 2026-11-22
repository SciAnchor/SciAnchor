---
name: domain-writing-law-policy
description: Law, governance, regulation, and policy domain writing profile for Research Harness paper workflows. Use before paper-writing or section-drafting when the manuscript depends on normative claims, statutes, precedent, doctrine, institutional design, stakeholder tradeoffs, implementation, or enforcement feasibility.
public_suite: paper
task_type: domain-writing-profile
data_access_level: local
inputs: topic_id, jurisdiction or policy arena, normative question, legal or policy sources, target venue, evidence artifacts, PAPER_PROFILE, PAPER_PLAN
outputs: LAW_POLICY_WRITING_PROFILE, DOMAIN_WRITING_PROFILE, PAPER_PROFILE route, normative and doctrinal claim boundaries, stakeholder and implementation map
gates: select this profile before law or policy manuscript-scale drafting; normative, doctrinal, precedent, and policy-effect claims must name authority, jurisdiction, assumptions, tradeoffs, PAPER_PROFILE reporting_map, and evidence_rule
artifact_schemas: PAPER_PROFILE, DOMAIN_WRITING_PROFILE, LAW_POLICY_WRITING_PROFILE, PAPER_PLAN
estimated_runtime: 5-15 min
---

# Domain Writing: Law And Policy

Use this skill when the manuscript concerns law, regulation, governance,
public policy, institutional design, rights, compliance, enforcement,
constitutional or administrative doctrine, or policy evaluation. It produces a
`DOMAIN_WRITING_PROFILE` for `paper-writing` and `section-drafting`.

## PAPER_PROFILE Interop

Use this skill when `PAPER_PROFILE.discipline` is law, policy, governance,
regulation, or institutional design, or when `PAPER_PROFILE.research_type` is
policy analysis. Route the paper profile to:

```yaml
PAPER_PROFILE:
  domain_skill: domain-writing-law-policy
  domain_profile: LAW_POLICY_WRITING_PROFILE
  method_route: law-policy-method-search
  reporting_map: law-policy-analysis
  evidence_rule: authority-tradeoff-implementation
```

Use `reporting_map` to require authority, jurisdiction, stakeholder, and
implementation fields. Use `evidence_rule` to separate legal authority,
empirical policy evidence, normative argument, and implementation feasibility.

## DOMAIN_WRITING_PROFILE

Write the profile into `PAPER_PLAN.domain_writing_profile` or the active
drafting handoff:

```yaml
profile_id: LAW_POLICY_WRITING_PROFILE
domain_skill: domain-writing-law-policy
domain_family: law_policy
claim_unit: normative_claim_authority_tradeoff_implementation
evidence_shape:
  required: [jurisdiction_or_policy_arena, authority, normative_standard, precedent_or_policy_evidence, stakeholder_tradeoff]
  optional: [implementation_path, enforcement_risk, comparative_case, cost_benefit, institutional_constraint]
claim_boundary: jurisdiction, authority, precedent, statutory text, policy assumptions, and implementation feasibility
blocked_claims:
  - legal conclusion without authority and jurisdiction
  - policy recommendation without stakeholder tradeoffs
  - implementation claim without enforcement or institutional feasibility
```

## Rhetorical Contract

- State the legal or policy problem, the governing authority or institutional
  setting, and the normative standard used to judge alternatives.
- Separate descriptive doctrine, empirical policy evidence, normative argument,
  and implementation recommendation.
- Use precedent, statute, regulation, agency guidance, cases, comparative
  examples, or policy evidence as distinct evidence types.
- Make tradeoffs explicit: rights, costs, feasibility, accountability,
  distributional effects, and enforcement.

## Evidence Requirements

- Legal claims need jurisdiction, authority hierarchy, and relevant precedent
  or statutory text.
- Policy-effect claims need empirical evidence, model assumptions, or explicit
  uncertainty labels.
- Normative claims need a stated value frame rather than implicit preference.
- Recommendations need implementation pathway, responsible actor, enforcement
  mechanism, and foreseeable objections.

## Drafting Bias

- Introductions should make the stakes and the decision point visible early.
- Analysis should move through issue, rule or authority, application, tradeoff,
  and recommendation when doctrinal structure is appropriate.
- Policy sections should compare alternatives rather than present one option as
  cost-free.
- Limitations should cover jurisdictional scope, institutional feasibility,
  evidence uncertainty, and political or administrative constraints.
