---
name: claim-extraction
description: Extract core claims from papers for Research Harness evidence structuring. Trigger on phrases like "claim-extraction", "/claim-extraction", "提取论文声明", "claim extract", or equivalent requests to identify key claims, evidence, assumptions, and limitations from ingested papers.
public_suite: research
task_type: extraction
data_access_level: local
inputs: topic_id, paper_ids, optional claim focus, optional IMPACT_REPORT, EXPERIMENT_GROUNDING_PROFILE, RESULT_TO_CLAIM_ANALYSIS_PROFILE
outputs: structured claims, evidence notes, assumptions, limitations, claim-bound result implications, claim-strength blockers
gates: target papers must be ingested and topic-scoped before extraction; experiment result claims need a claim-bound IMPACT_REPORT, passing EXPERIMENT_GROUNDING_PROFILE, and RESULT_TO_CLAIM_ANALYSIS_PROFILE before CLAIMS_FROM_RESULTS
artifact_schemas: claim_set, evidence_link, IMPACT_REPORT, EXPERIMENT_GROUNDING_PROFILE, RESULT_TO_CLAIM_ANALYSIS_PROFILE, CLAIMS_FROM_RESULTS, relative_delta_table, statistical_summary
estimated_runtime: 5-20 min
---

# Claim Extraction

Use this skill when the user needs structured claims from papers.

## Experiment Result Claims

When extracting claims from experiment outputs, do not treat raw result tables,
logs, or chat summaries as publishable claims. Require
`EXPERIMENT_GROUNDING_PROFILE` before turning results into manuscript claims.
The profile must show that `EXPERIMENT_GOAL` and `EXPERIMENT_PLAN` match the
active `PAPER_PROFILE`, `variable_grounding` and the codebook are verified,
`pre_deploy_code_review` has no blockers, and `IMPACT_REPORT` is claim-bound.

If `IMPACT_REPORT` is missing, not claim-bound, or disconnected from source
result artifacts, return blockers instead of extracting contribution claims.

Before producing `CLAIMS_FROM_RESULTS`, create or load
`RESULT_TO_CLAIM_ANALYSIS_PROFILE`. It must connect result artifacts to
`relative_delta_table`, `statistical_summary`, practical significance,
baseline/robustness context, negative results, competing evidence, and
`claim_strength`. Use the evidence tiers `A_confirmed`,
`B_empirical_strong`, `C_empirical_limited`, `D_exploratory`,
`E_speculative`, and `F_unsupported_or_blocked` to bound wording. Block
overclaimed or unsupported result claims instead of upgrading them during
claim extraction.

## Workflow

1. Identify the target papers and topic focus.
2. For result claims, verify `EXPERIMENT_GROUNDING_PROFILE` and
   claim-bound `IMPACT_REPORT` first.
3. Verify `RESULT_TO_CLAIM_ANALYSIS_PROFILE` before `CLAIMS_FROM_RESULTS`.
4. Use `claim_extract` when available.
5. Organize outputs into:
   - key claims
   - supporting evidence
   - assumptions
   - limitations or contradictions
6. Preserve paper identifiers, result artifact IDs, and evidence-strength
   labels so later steps can cite them.
