---
name: literature-search
description: Run comprehensive literature search for Research Harness. Trigger on phrases like "literature-search", "/literature-search", "文献检索", "系统检索论文", "帮我搜相关论文", or equivalent requests to search, shortlist, and ingest relevant papers.
public_suite: research
task_type: discovery
data_access_level: local+external
inputs: topic scope, time range, venue/domain constraints, topic_id, PAPER_PROFILE, DOMAIN_METHOD_SEARCH_PROFILE
outputs: ranked paper candidates, ingestion decisions, frontier evidence, domain method/search evidence table
gates: ingestion requires topic_id; frontier claims need academic and industry signals; domain searches must follow DOMAIN_METHOD_SEARCH_PROFILE and do not silently default to STEM
artifact_schemas: paper_pool, frontier_attention_evidence, DOMAIN_METHOD_SEARCH_PROFILE
estimated_runtime: 10-45 min
---

# Literature Search

Use this skill for broad paper discovery.

## Domain Method/Search Profile Preflight

When the search supports a manuscript, proposal, baseline selection, or
experiment plan, first load or derive `DOMAIN_METHOD_SEARCH_PROFILE` from
`PAPER_PROFILE`. It must name:

```yaml
DOMAIN_METHOD_SEARCH_PROFILE:
  method_route: <domain method route>
  search_route: <domain search route>
  search_strategies: [<strategy ids>]
  method_requirements: [<method gates>]
  baseline_anchor_fields: [<fields to extract>]
```

Use this profile to choose queries and extraction columns. Do not silently
default to STEM. Examples:

- ML benchmarks use `ml-baseline-search` with recent SOTA reverse search,
  code-available baseline search, and citation-network baseline search.
- Psychology/social-science surveys use variable-combination search, scale
  provenance search, and meta-analysis positioning rather than GitHub baseline
  extraction.
- Education interventions use intervention-effect, construct-measure, and
  effect-size searches rather than Path 1 ML defaults.

## Workflow

1. Read `docs/agent-guide.md` in the Research Harness checkout if topic context is unclear.
2. Clarify or infer:
   - research topic
   - time range
   - venue or domain constraints
3. Select `method_route`, `search_route`, `search_strategies`,
   `method_requirements`, and `baseline_anchor_fields` from
   `DOMAIN_METHOD_SEARCH_PROFILE`.
4. Use `paper_search` or `rhub`-compatible search flow.
5. Deduplicate and rank results by relevance and domain-method fit.
6. Recommend which papers to ingest and ingest them when the user intent is clearly operational rather than exploratory.

## Existing SPC Routes

- Start with production `spc paper search`, `paper lookup`, or `paper graph`
  (Semantic Scholar/OpenAlex pools, with PubMed for biomedical discovery).
  Preserve the RH topic ingestion flow and its existing provider merge; do not
  issue the same search again merely to exercise another wrapper.
- When the question requires methods or results inside papers, use
  `spc paper sciverse --query "<query>" --top-k 3 --output-format json` if its
  credential is configured. Read relevant sections with
  `spc paper sciverse --doc-id <id> --offset <offset> --limit 2000 --output-format json`.
  Follow the returned `next_offset` rather than assuming byte/character units.
- Record document ID, returned offsets, retrieval date and source identifiers.
  Cross-check title, authors, year and DOI against authoritative metadata when
  they conflict. A retrieved passage is not a complete paper or a verified PDF;
  it does not mark the RH paper as acquired or replace topic ingestion.
- Use these routes on demand, not as an unconditional all-source fan-out.
  Cache/reuse successful evidence. Use web search only to supplement missing
  official pages, venue announcements or records.
- Inspect `spc schema <command path>` before unfamiliar operations. If an
  unversioned arXiv lookup fails, verify the current version through the official
  arXiv record and retry that explicit version; never guess the version suffix.

## Output

- concise search query formulation
- top relevant papers
- active `method_route`, `search_route`, and `search_strategies`
- extracted `baseline_anchor_fields` when the search supports baselines or
  method planning
- ingestion decision or next-step recommendation

## Frontier Attention Evidence

When the search supports a paper, survey, or topic-validation task, include a
frontier-attention pass:

- latest top academic signals: recent top-venue papers, best/oral/spotlight
  papers, benchmarks, surveys, and workshop/tutorial activity
- industry signals: official lab/company blogs, technical reports, SDKs,
  standards, open-source frameworks, and product releases
- trend summary: why the topic is timely now, and which scope boundaries the
  evidence does or does not support

Papers must be ingested under the topic; non-paper sources should be recorded
in a `frontier_attention_evidence` artifact with URL, date, source type, and
the claim they support.
