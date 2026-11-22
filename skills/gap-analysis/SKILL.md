---
name: gap-analysis
description: Analyze research gaps using Research Harness paper pools and extracted evidence. Trigger on phrases like "gap-analysis", "/gap-analysis", "研究空白分析", "找研究 gap", or equivalent requests to identify underexplored questions, missing baselines, or contradictory findings.
public_suite: research
task_type: analysis
data_access_level: local
inputs: topic_id, paper pool, extracted claims, baseline context, PAPER_PROFILE, DOMAIN_METHOD_SEARCH_PROFILE, EVALUATION_GATE_PROFILE, PROBLEM_ANCHOR
outputs: candidate gaps, novelty risks, baseline gaps, method/search gaps, IDEA_REPORT, RESEARCH_PROPOSAL, EVALUATION, PROBLEM_ANCHOR, next experiments
gates: every gap claim must cite paper-pool evidence or be labeled speculative; method/search gap claims must follow DOMAIN_METHOD_SEARCH_PROFILE and do not silently default to STEM; candidate directions need PROBLEM_ANCHOR, baseline_mode, paper_access_status, fatal_flaws, and pilot decision before promotion
artifact_schemas: gap_report, literature_map, DOMAIN_METHOD_SEARCH_PROFILE, EVALUATION_GATE_PROFILE, PROBLEM_ANCHOR, IDEA_REPORT, RESEARCH_PROPOSAL, EVALUATION
estimated_runtime: 10-30 min
---

# Gap Analysis

Use this skill when the user wants candidate research opportunities grounded in evidence.

## RH research delivery protocol

Use RH as the evidence and state source of truth. The protocol has no external runtime dependency.
Express the research delivery protocol as RH artifact conventions:
`IDEA_REPORT` for candidate opportunities, `RESEARCH_PROPOSAL` for the selected
direction, and `EVALUATION` for go/no-go evidence before experiment investment.
For `human_in_loop_call` requests, infer whether the user is asking to refine
an idea, select a direction, or block advancement until evidence improves.

## Domain Method/Search Profile Preflight

Before declaring a novelty, baseline, theory, method, source, or policy gap,
load `DOMAIN_METHOD_SEARCH_PROFILE`. It must name `method_route`,
`search_route`, `search_strategies`, `method_requirements`, and
`baseline_anchor_fields`.

Use the profile as the gap boundary:

- ML gaps require recent baseline, dataset, metric, and source table/figure
  coverage.
- Psychology/social-science gaps require variable, scale, population, effect
  size, analysis method, and design-validity coverage.
- Education intervention gaps require intervention, construct measure,
  control-group/design, treatment fidelity, and effect-size coverage.
- Humanities and law/policy gaps require source/context or
  authority/jurisdiction/tradeoff coverage rather than benchmark metrics.

## Evaluation And Problem Anchor Gate

Before promoting a candidate gap into `RESEARCH_PROPOSAL` or `EVALUATION`,
create or load `EVALUATION_GATE_PROFILE` and `PROBLEM_ANCHOR`.

`PROBLEM_ANCHOR` freezes the concrete problem, beneficiary or scholarly debate,
closest baseline or authority, and the claim boundary. It must be `frozen`
before experiment or paper-writing investment. `EVALUATION_GATE_PROFILE` must
name:

- `baseline_mode`: `extract-only`, replication/access-check, public-dataset
  analysis, authority-access-check, archive-access-check, or another explicit
  domain route from `DOMAIN_METHOD_SEARCH_PROFILE`;
- `paper_access_status`: whether the baseline paper, code, table, statistical
  value, source, corpus, or authority is verified and accessible;
- `fatal_flaws`: at most two specific flaws, with `CRITICAL` flaws blocking
  promotion;
- `pilot`: whether the direction advances now, runs a signal pilot, needs
  revisions, or is rejected.

Do not promote an idea when `PROBLEM_ANCHOR` is draft, `paper_access_status`
is blocked, the selected `baseline_mode` is unsupported, or a critical fatal
flaw remains unresolved.

## Research Wiki Context Preflight

When running gap/opportunity analysis from `rh-workspace/`, first try:

```bash
rh topic wiki-context-pack --action-name science_discovery --json
```

If `paper_wiki_status` is `loaded`, treat the Research Wiki context pack as the
priority evidence layer over ad hoc markdown synthesis. If unavailable or not
triggered, report the reason and label any fallback evidence source explicitly.

## Workflow

1. Confirm the topic and relevant paper set.
2. Review claims, baselines, method/search coverage, and contradictions first.
3. Use `gap_detect` if available.
4. Run the evaluation/problem-anchor gate and separate:
   - evidence-backed gaps
   - speculative opportunities
   - directions requiring a signal `pilot`
   - directions blocked by `fatal_flaws` or paper/source access
5. Recommend the most defensible next direction.
