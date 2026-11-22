# Survey-First Retrieval Policy

Status: stable internal retrieval policy.
Schema: `survey_first_retrieval_policy.v1`.

Survey-first retrieval is an internal `paper_search` policy. It does not add a
public API flag, change public payload shape, write provenance, change storage
schema, change orchestrator behavior, or approve benchmark/public performance
claims.

## Guardrails

- under-filled topics run survey seed first.
- normal topics do not incur extra seed fanout.
- auto_ingest never ingests survey or facet results; when `auto_ingest=True`,
  survey-first fanout is disabled and only the original-query result set can be
  ingested.
- no-survey fallback preserves original retrieval behavior.

## Internal Parameters

- Topic paper floor: `5`.
- Facet query limit: `2`.
- Recent survey window: current year or previous year.
- Survey candidate gate: recent high-tier survey/review/overview signal meeting
  CCF-B or CAS-Q2 threshold.

## Exclusions

- No public API shape change.
- No storage schema change.
- No provenance ownership or artifact-lineage change.
- No orchestrator gate change.
- No dependency change.
- No Zotero, benchmark, release, publish, commit, push, or PR action.
