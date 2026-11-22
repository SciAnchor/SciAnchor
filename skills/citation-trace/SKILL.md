---
name: citation-trace
description: Expand from seed papers by following references and citations inside Research Harness workflows. Trigger on phrases like "citation-trace", "/citation-trace", "引用追踪", "沿引用链扩展", or equivalent requests to grow a paper set from one or more seed papers.
public_suite: research
task_type: discovery
data_access_level: local+external
inputs: topic_id, seed paper IDs or identifiers, expansion focus
outputs: expanded paper candidates, ingestion recommendations, citation-chain notes
gates: ingest useful papers with topic_id; preserve seed and citation provenance
artifact_schemas: paper_pool, literature_map
estimated_runtime: 15-45 min
---

# Citation Trace

Use this skill to expand a paper pool from known seed papers.

## Workflow

1. Confirm seed paper IDs, DOI, arXiv IDs, or titles.
2. Trace backward references and forward citations when available.
3. Filter out low-relevance branches.
4. Ingest high-value expansions into Research Harness.
5. Summarize which citation branches matter and why.
