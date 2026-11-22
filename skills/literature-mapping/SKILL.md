---
name: literature-mapping
description: Build a structured literature map in Research Harness. Trigger on phrases like "literature-mapping", "/literature-mapping", "文献地图", "建立文献库", "systematic literature map", or equivalent requests to cluster papers, identify baselines, and organize a topic-level paper pool.
public_suite: research
task_type: mapping
data_access_level: local+external
inputs: topic scope, topic_id, candidate papers, venue or time constraints, PAPER_PROFILE, DOMAIN_METHOD_SEARCH_PROFILE
outputs: clustered literature map, baseline coverage, domain method/search coverage, ingestion plan
gates: useful papers must be ingested; map must separate evidence from inference; method and baseline clusters must follow DOMAIN_METHOD_SEARCH_PROFILE and do not silently default to STEM
artifact_schemas: literature_map, paper_pool, DOMAIN_METHOD_SEARCH_PROFILE
estimated_runtime: 20-60 min
---

# Literature Mapping

Use this skill when the user wants a topic-level literature map instead of a one-off search.

## Domain Method/Search Profile Preflight

Before clustering baselines or method families, load
`DOMAIN_METHOD_SEARCH_PROFILE`. It must provide `method_route`,
`search_route`, `search_strategies`, `method_requirements`, and
`baseline_anchor_fields`.

Use the profile to decide what "baseline coverage" means:

- ML/system work maps task, dataset, metric, method, code availability, and
  source table or figure.
- Psychology/social-science work maps variables, scales, population, sample
  size, effect size, and analysis method.
- Education intervention work maps intervention type, construct measure,
  student level, design, control group, and effect size.
- Humanities and law/policy work map source, corpus, authority, jurisdiction,
  theory, policy arena, and implementation evidence instead of benchmark
  metrics.

## Workflow

1. Gather or confirm the topic scope.
2. Search and ingest core papers.
3. Group papers by problem, `method_route`, `search_route`, dataset, source
   type, construct, authority, or evaluation style as required by the profile.
4. Identify baseline, theory-anchor, source-anchor, or policy-authority
   coverage and missing coverage.
5. Record a structured map or summary suitable for later `claim_extract` and `gap_detect`.
