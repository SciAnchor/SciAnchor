---
name: evidence-gating
description: Decide whether a research stage has enough evidence to advance in Research Harness. Trigger on phrases like "evidence-gating", "/evidence-gating", "证据门控", "现在能推进吗", or equivalent requests to check whether current literature, claims, and artifacts justify moving to the next stage.
public_suite: review
task_type: gating
data_access_level: local
inputs: topic_id, current stage, paper pool, claims, artifacts, PAPER_PROFILE, DOMAIN_METHOD_SEARCH_PROFILE, EVALUATION_GATE_PROFILE, PROBLEM_ANCHOR, EXPERIMENT_GROUNDING_PROFILE, RESULT_TO_CLAIM_ANALYSIS_PROFILE
outputs: gate decision, blockers, missing evidence, method/search readiness, evaluation gate readiness, experiment grounding readiness, result-to-claim readiness, protocol artifact readiness, next actions
gates: do not advance when required evidence, method/search coverage, evaluation gate fields, experiment grounding fields, result-to-claim analysis fields, or protocol artifacts are missing; do not silently default to STEM
artifact_schemas: gate_check, advisory_report, DOMAIN_METHOD_SEARCH_PROFILE, EVALUATION_GATE_PROFILE, PROBLEM_ANCHOR, EXPERIMENT_GROUNDING_PROFILE, RESULT_TO_CLAIM_ANALYSIS_PROFILE, EVALUATION, EXPERIMENT_PLAN, PAPER_PLAN, IMPACT_REPORT, CLAIMS_FROM_RESULTS, relative_delta_table, statistical_summary
estimated_runtime: 3-10 min
---

# Evidence Gating

Use this skill when the user asks whether the work is ready to advance.

## RH research delivery protocol

Use RH as the evidence and state source of truth. The protocol has no external runtime dependency.
Under the research delivery protocol, gates should inspect delivery
artifacts such as `EVALUATION`, `EXPERIMENT_PLAN`, and `PAPER_PLAN` when those
stages are relevant. A `protocol_call` checks the named stage; a
`human_in_loop_call` first maps the user's judgment to the nearest RH stage and
then checks the required artifacts, evidence links, and unresolved objections.

## Domain Method/Search Profile Gate

When gating proposal, experiment, or paper-writing readiness, inspect
`DOMAIN_METHOD_SEARCH_PROFILE` alongside `PAPER_PROFILE`. The profile must
name `method_route`, `search_route`, `search_strategies`,
`method_requirements`, and `baseline_anchor_fields`.

Block advancement when:

- the profile is missing for a manuscript or experiment-bound topic;
- the evidence pool lacks the baseline, theory-anchor, source-anchor,
  authority, scale, construct, dataset, metric, effect-size, or control-group
  fields required by `baseline_anchor_fields`;
- the proposed method violates `method_requirements`;
- the workflow would silently route a non-STEM topic through STEM/ML baseline
  defaults.

## Evaluation And Problem Anchor Gate

For proposal, experiment, and paper-readiness decisions, inspect
`EVALUATION_GATE_PROFILE` and `PROBLEM_ANCHOR` before allowing advancement.
The gate must include `baseline_mode`, `paper_access_status`, `fatal_flaws`,
discipline-routed scoring axes, feasibility risks, and the `pilot` decision.

Block advancement when:

- `PROBLEM_ANCHOR` is missing or not frozen;
- `baseline_mode` is unsupported by the active `DOMAIN_METHOD_SEARCH_PROFILE`;
- `paper_access_status` says the baseline paper, code, table, statistical
  value, source, corpus, or authority is blocked;
- any `fatal_flaws` item is tagged `CRITICAL`, or two fatal flaws remain;
- the verdict requires a signal `pilot` but no pilot design or result artifact
  exists;
- the decision would advance from chat assertions rather than recorded
  `EVALUATION` evidence.

## Experiment Grounding Gate

Before advancing from proposal/evaluation into experiment execution, result
claims, or manuscript planning, inspect `EXPERIMENT_GROUNDING_PROFILE`.
It must bind `EXPERIMENT_GOAL`, `EXPERIMENT_PLAN`, and `PAPER_PROFILE` to the
active domain route, and it must name `variable_grounding`, `codebook`,
`pre_deploy_code_review`, `IMPACT_REPORT`, and claim-bound result checks.

Block advancement when:

- `EXPERIMENT_GOAL` does not match the frozen problem and target claim;
- `EXPERIMENT_PLAN` is not profile-aligned with `PAPER_PROFILE` and
  `DOMAIN_METHOD_SEARCH_PROFILE`;
- `variable_grounding` is missing or any named variable cannot be resolved in
  the codebook, data dictionary, source corpus, authority list, or equivalent
  domain source inventory;
- `pre_deploy_code_review` has blockers for variable grounding, leakage,
  metric/formula fit, seeds/reproducibility, or ground-truth source;
- completed result artifacts lack a claim-bound `IMPACT_REPORT`;
- the workflow would turn planned or failed results into claims without
  evidence-strength and limitation boundaries.

## Result To Claim Analysis Gate

Before advancing from completed result artifacts into `CLAIMS_FROM_RESULTS`,
section drafting, or contribution wording, inspect
`RESULT_TO_CLAIM_ANALYSIS_PROFILE`. It must bind completed results,
`IMPACT_REPORT`, `relative_delta_table`, `statistical_summary`, practical
significance, baseline/robustness context, negative results, competing
evidence, and `claim_strength`.

Block advancement when:

- result artifacts, expected-vs-actual rows, `relative_delta_table`, or
  `statistical_summary` are missing;
- statistical significance and practical significance are conflated;
- negative results or competing evidence are not recorded;
- `claim_strength` exceeds the domain/study-design boundary, including
  `A_confirmed` overclaims for cross-sectional survey results;
- any claim is overclaimed, unsupported, or would route to
  `F_unsupported_or_blocked`.

## Workflow

1. Identify the current stage or infer it from project state.
2. Review available papers, claims, artifacts, method/search profile coverage,
   `EVALUATION_GATE_PROFILE`, `PROBLEM_ANCHOR`,
   `EXPERIMENT_GROUNDING_PROFILE`, `RESULT_TO_CLAIM_ANALYSIS_PROFILE`, and
   unresolved objections.
3. Use orchestrator checks if available.
4. Return a clear decision:
   - pass
   - pass with caveats
   - fail
5. List the minimum missing evidence required to pass.
