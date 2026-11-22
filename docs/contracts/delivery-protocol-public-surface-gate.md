# RH Research Delivery Protocol Public Surface Gate

Status: gate contract.

## Decision

The first implementation surface: Python facade.

The first public-facing usable entry should be
`ResearchAPI.delivery_paper_production_snapshot(...)`, returning
`rh.delivery.paper_production_snapshot.v1`.

Rationale:

- the private delivery-protocol helpers already produce a read-only snapshot;
- Python facade is the lowest-risk public surface for skills and local scripts;
- it can remain opt-in and local without opening MCP, CLI, or HTTP transport;
- it avoids introducing a real workflow executor before the read model is
  shape-locked.

## Payload Shape

The facade method should return a dictionary with:

- `schema_version`: `rh.delivery.paper_production_snapshot.v1`;
- `status`: `complete`, `in_progress`, or `blocked`;
- `next_artifact`;
- `next_action`;
- `summary`: counts for total, satisfied, ready_to_advance, and blocked;
- `records`: ordered protocol artifact readiness records;
- `blockers`;
- `dry_run`: true.

The method must not perform artifact writes. It may inspect provided
`artifact_states` and provided payload dictionaries only in the first
implementation slice. Loading real topic/orchestrator state can be a later
bounded slice with storage/provenance tests.

## Explicit Non-Surfaces

- No MCP tool in LG50.
- No CLI command in LG50.
- No HTTP route in LG50.
- No advertised skill change in LG50.
- No Zotero path in LG50.

## Implementation Boundary

The follow-up implementation slice should add only:

- `ResearchAPI.delivery_paper_production_snapshot`;
- focused Python facade shape-lock tests;
- documentation that labels the result read-only and dry-run.

It should reuse `build_delivery_paper_production_snapshot` rather than
duplicating protocol logic.

## Tests

Required shape-lock tests:

- method exists on `ResearchAPI`;
- output schema version is `rh.delivery.paper_production_snapshot.v1`;
- output includes status, next artifact/action, summary, records, blockers,
  and dry_run;
- no DB write happens when explicit `artifact_states` and `payloads` are
  supplied;
- invalid payloads surface blockers instead of raising opaque exceptions.

## Rollback

rollback boundary:

- remove the Python facade method;
- keep private `_selfdev.delivery_protocol` helpers and tests;
- no migration rollback is required because the first implementation surface
  must not change schema, storage, provenance, or orchestrator behavior.

## Exclusions

- no image-provider work;
- no real orchestrator_record_artifact call;
- no real stage advancement;
- no DB/storage/provenance write;
- no dependency addition;
- no credential/config mutation;
- no network, LLM, image, PDF, Zotero, Cloud, or third-party action;
- no public readiness, submission-readiness, benchmark, or performance claim;
- no commits, pushes, PRs, releases, or publishing.
