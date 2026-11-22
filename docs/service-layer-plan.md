# Service Layer Consolidation Plan

Status: LG16 existing-system finalization complete; LG2 read transport
convergence complete; LG15 action-equivalent inventory closed; LG3
compatibility guard active.
Last verified: 2026-06-15.

Research Harness currently exposes overlapping surfaces:

- Python API (`research_harness.api`)
- CLI (`research_harness.cli`)
- MCP stdio (`research_harness_mcp.tools`)
- HTTP API (`research_harness_mcp.http_api`)

The target is one service dispatcher that owns command lookup, validation, and
error normalization. Surface modules should translate transport-specific input
and output only.

## Current Skeleton

`research_harness.service.ResearchService` now provides the initial transport-
independent dispatcher:

- `ResearchService.invoke(name, payload)` returns a `ServiceResult`.
- The dispatcher initializes the RH database lazily and supports explicitly
  db-less read commands for filesystem-only surfaces.
- `ServiceResult.to_dict()` exposes the adapter-friendly envelope shape.
- Errors use a machine-readable `{code, message}` object.
- The first registered commands are read-only: `topic_list`, `topic_show`,
  `paper_list`, `provenance_summary`, `provenance_export`,
  `orchestrator_status`, `orchestrator_gate_check`, `paperindex_search`,
  `skill_list`, and `skill_get`.
- Public primitive commands are now registered in `ResearchService`.
  `paper_search`, `paper_ingest`, `paper_summarize`, `claim_extract`,
  `evidence_link`, `gap_detect`, `baseline_identify`, `section_draft`,
  `figure_generate`, and `consistency_check` are routed through tracked
  primitive service handlers.
- The MCP adapter now routes all thirty-one public tools through `ResearchService`
  before applying the existing transport response shape: the ten read/db-less
  commands plus `paper_search`, `paper_ingest`, `paper_summarize`,
  `claim_extract`, `evidence_link`, `gap_detect`, `baseline_identify`,
  `section_draft`, `figure_generate`, `consistency_check`, `orchestrator_resume`,
  `orchestrator_advance`, `orchestrator_record_artifact`,
  `paper_task_intake`,
  `adversarial_review`, `advisory_check`, `zotero_sync`, and the db-less
  `productization_boundary` preview plus `topic_knowledge_status`,
  `topic_knowledge_refresh`, and `cross_topic_atlas`.
  The existing MCP HarnessResponse envelope is preserved for wrapped tools; the
  skill tools keep their raw manifest/content payload shape.
- `docs/contracts/service-coverage.md` tracks all 31 public MCP
  tools. `scripts/check-service-coverage.py` keeps the coverage matrix, service
  registry, MCP adapter routing, and any future deferral reasons in sync.
- `docs/contracts/transport-coverage.md` tracks Python API, CLI,
  and HTTP equivalents for the service-backed read, action, and write/effect
  command sets. `scripts/check-transport-service-coverage.py` keeps that
  transport inventory synchronized with the service coverage matrix and rejects
  `existing-direct`/`deferred-shape` as LG16 internal-complete states.
- `docs/contracts/compatibility-inventory.md` classifies
  all Tier B compatibility names. `scripts/check-compatibility-inventory.py`
  keeps the lifecycle inventory synchronized with `docs/mcp-tool-audit.md`
  without changing compatibility runtime behavior.
- `packages/research_harness/tests/test_cli_read_service_shape.py` locks the
  current JSON shape for the lowest-risk CLI read-only group before any CLI
  runtime routing slice changes implementation.
- CLI `topic list` and `topic show` now invoke `ResearchService`. The CLI
  adapter preserves the existing JSON/text shape.
- CLI `paper list` now invokes `ResearchService`. The CLI adapter preserves the
  existing JSON/text shape, including status-filter behavior.
- CLI `topic list` and `paper list` consume complete service output without
  legacy SQL fallback.
- CLI `provenance summary` now invokes `ResearchService` for the default and
  `--topic` paths while preserving the existing JSON/text shape. The legacy
  `--backend` filter remains on the direct provenance recorder path until the
  service contract explicitly accepts backend filtering.
- CLI `provenance export` now invokes `ResearchService` for the JSON default
  path while preserving the existing JSON list output shape. The legacy CSV
  export path remains direct because the current service contract explicitly
  supports JSON only.
- CLI `orchestrator status` and `orchestrator gate-check` now invoke
  `ResearchService` through adapter-only routing. The CLI adapter strips
  service-only metadata and restores the legacy `stage` field so JSON output
  shape is preserved; orchestrator gate decisions and transitions remain owned
  by the existing orchestrator service.
- Python facade `ResearchAPI.orchestrator_status()` and `ResearchAPI.gate_check()`
  now invoke `ResearchService` through adapter-only routing. The facade restores
  the existing return shapes, including raw gate-decision return values from
  `gate_check()`.
- Python facade `ResearchAPI.paper_search()`, `ResearchAPI.paper_ingest()`,
  `ResearchAPI.execute_primitive()` for service-backed public primitive
  actions, and `ResearchAPI.record_artifact()` now invoke `ResearchService`
  while preserving the existing primitive-output and artifact-record return
  shapes.
- HTTP `GET /api/topics` now invokes `ResearchService.topic_list` through
  adapter-only routing. The HTTP adapter preserves the existing
  `TopicSummary` response shape by enriching service topic rows with
  transport-specific fields (`target_venue`, `deadline`, `created_at`,
  `paper_count`, domain metadata, and orchestrator stage status).
- HTTP `GET /api/provenance/summary` now invokes
  `ResearchService.provenance_summary` through adapter-only routing. The HTTP
  adapter preserves the existing `ProvenanceSummary` response shape and
  topic-scoped query behavior by keeping the HTTP-specific aggregate lists and
  recent-record projection in the transport layer.
- HTTP deferred-shape tests now lock the existing read-only response shapes for
  `GET /api/topics/{topic_id}`, `GET /api/papers?topic_id=...`, and
  `GET /api/topics/{topic_id}/gate` before any future routing slice changes
  implementation. S42 does not route runtime behavior.
- HTTP `GET /api/topics/{topic_id}` now invokes
  `ResearchService.topic_show` through adapter-only routing. The HTTP adapter
  keeps id-based lookup, 404 behavior, and the existing `TopicDetail` response
  shape by resolving the topic name before service invocation and preserving
  HTTP-specific counts, domain metadata, artifact counts, and orchestrator
  fields in the transport layer.
- HTTP `GET /api/papers?topic_id=...` now invokes
  `ResearchService.paper_list` through adapter-only routing. The HTTP adapter
  resolves the topic name before service invocation, uses service paper ids as
  the topic-scoped candidate set, and preserves the existing pagination,
  status/search/sort filters, per-topic relevance, and `PaginatedResponse`
  shape in the transport layer.
- HTTP `GET /api/topics/{topic_id}/gate` now invokes
  `ResearchService.orchestrator_gate_check` through adapter-only read routing.
  The HTTP adapter preserves the existing orchestrator harness envelope
  (`status`, `summary`, `output`, `next_actions`, artifact/recovery metadata,
  and local orchestrator backend fields) and does not change gate evaluator
  semantics, decisions, or orchestrator transitions.
- HTTP `GET /api/topics/{topic_id}` now invokes
  `ResearchService.orchestrator_status` for topic-detail status enrichment.
  The HTTP adapter preserves the existing `TopicDetail` response shape and
  keeps `gate_status`/`stop_before` on the previous HTTP-compatible database
  fields so this routing slice does not change gate decision semantics.
- CLI `topic knowledge-status` and `topic knowledge-refresh` now invoke
  `ResearchService.topic_knowledge_status` and
  `ResearchService.topic_knowledge_refresh` while preserving existing JSON/text
  output and public error shapes.
- CLI `orchestrator advance` now invokes `ResearchService.orchestrator_advance`
  while preserving existing JSON/text output and transition semantics.
- HTTP `GET /api/topics/{topic_id}/knowledge-status`,
  `POST /api/topics/{topic_id}/knowledge-refresh`, and
  `POST /api/topics/knowledge-refresh-all` now invoke the Topic Knowledge
  service commands directly. The HTTP route adapters keep path validation,
  status-code mapping, and cache-control headers.
- HTTP `POST /api/papers/search` and `POST /api/papers/ingest` now reach
  service-backed primitive execution through the Python facade. Retrieval-log
  writes and field-brief staleness remain HTTP adapter side effects; primitive
  freshness/provenance stay in service/tracked execution.
- `primitive_result_to_service_result()` defines the tracked primitive
  conversion contract used by service-backed primitive routing.
- `cross_topic_atlas` is now tracked in the transport coverage matrix and the
  CLI/HTTP equivalents route through `ResearchService.cross_topic_atlas` while
  preserving public shapes.

LG2 read transport convergence is complete for service-backed commands with
Python, CLI, or HTTP equivalents. LG16 closes the action-equivalent rows for
`paper_search`, `paper_ingest`, `paper_summarize`, `claim_extract`,
`evidence_link`, `gap_detect`, `baseline_identify`, `section_draft`,
`consistency_check`, `topic_knowledge_status`, and
`topic_knowledge_refresh`, and adds write/effect
rows for `orchestrator_resume`, `orchestrator_advance`,
`orchestrator_record_artifact`, and `zotero_sync`. No new public names, routes,
Python facade methods, MCP tools, or advertised skills were added. S22 inventories transport equivalents
and adds a guard; S24 adds CLI response-shape tests before runtime routing; S26
routes the first CLI read group (`topic list` and `topic show`); S28 routes
`paper list` through the service while preserving the locked CLI shape. S30
routes the default/topic CLI `provenance summary` path through the service and
leaves the backend-filtered compatibility path direct. S32 routes the JSON CLI
`provenance export` path through the service and leaves CSV export direct. S34
routes CLI `orchestrator status` and `orchestrator gate-check` through the
service with adapter-only shape preservation. S36 routes the matching Python
facade orchestrator reads through the service while preserving existing return
shapes. S38 starts HTTP read routing with `GET /api/topics`, preserving the
existing HTTP response shape. S40 routes `GET /api/provenance/summary` through
the service while preserving its existing aggregate response shape. S42 locks
the remaining deferred HTTP topic detail, paper-list pagination/filter, and gate
pass-through shapes without routing them. S44 routes HTTP topic detail through
the service while preserving the locked id-based shape. S46 routes the
topic-filtered HTTP paper list through the service while preserving pagination
and filter shape. S48 routes HTTP gate-check reads through the service while
preserving gate pass-through envelope shape. S49 routes HTTP topic-detail
orchestrator status enrichment through the service while preserving the locked
topic-detail shape. Commands without equivalent transports remain explicitly
`missing-equivalent` in the transport coverage matrix.

MCP public-tool routing is service-backed:
`paper_search`, `paper_ingest`, `paper_summarize`, `claim_extract`,
`evidence_link`, `gap_detect`, `baseline_identify`, `section_draft`, and
`consistency_check` use the service dispatcher with `TrackedBackend`.
The public MCP `orchestrator_resume` uses a service-layer wrapper over the
existing `OrchestratorService.resume_run()` and keeps the MCP
`_wrap_orchestrator()` response behavior.
`orchestrator_advance` and `orchestrator_record_artifact` now use service-layer
wrappers over the existing `OrchestratorService` methods; artifact lineage,
stage transition, and gate semantics remain owned by the orchestrator service.
The public MCP `adversarial_review` now routes through a service-layer wrapper
that preserves the existing independent-review, adversarial-round, and
resolution artifact flow. Automated tests mock the reviewer and do not run real
external review.
The public MCP `advisory_check` now uses a service-layer wrapper over the
existing `AdvisoryEngine`; `advisory_list` and `advisory_acknowledge` remain on
the existing MCP convenience path.
The public MCP `zotero_sync` now routes through a service-layer wrapper over
the existing `ZoteroSyncService`; automated tests cover dry-run and validation
paths only and do not call the Zotero API.
The public MCP `productization_boundary` preview is also service-backed through
a db-less handler; it remains opt-in with `experimental_lg10=true` and preserves
the existing `lg10_productization_boundary.v1` payload shape.
The public MCP `topic_knowledge_status`, `topic_knowledge_refresh`, and
`cross_topic_atlas` commands route through service-layer wrappers over the
derived Topic Knowledge read model. Topic Knowledge remains rebuildable from
canonical RH rows; refresh failures on ingest are reported but do not roll back
paper persistence.

## Tracked Primitive Result Contract

When a future slice routes public primitives through `ResearchService`, the
handler must execute them through `TrackedBackend` and convert the returned
`PrimitiveResult` with `primitive_result_to_service_result()`. The service
result contract is:

| Field | Contract |
|---|---|
| `command` | Primitive name, matching `PrimitiveResult.primitive`. |
| `status` | `success` when `PrimitiveResult.success` is true, otherwise `error`. |
| `summary` | Existing harness summary from `compute_summary()`. |
| `output` | JSON-serializable primitive output; dataclass outputs become dictionaries. |
| `error` | `None` on success; `{code: PRIMITIVE_FAILED, message: ...}` on failure. |
| `next_actions` | Existing harness guidance from `compute_next_actions()`. |
| `artifacts` | Existing artifact references from `extract_artifacts()`. |
| `recovery_hint` | Existing `classify_error()` hint on failure, empty on success. |
| `metadata` | Primitive, backend, model, cost, prompt/completion tokens, duration, and `provenance_recorded_by=TrackedBackend`. |

The service contract does not write provenance records itself. Provenance remains
owned by `TrackedBackend`, matching the current MCP primitive path.

## Target Interface

```python
from research_harness.service import ResearchService

service = ResearchService()
result = service.invoke("paper_search", {"query": "agentic science", "topic_id": 1})
```

Command records should include:

| Field | Purpose |
|---|---|
| `name` | Stable command id shared by CLI/MCP/HTTP/Python |
| `description` | Human and agent-facing operation summary |
| `input_schema` | Boundary validation |
| `output_schema` | Stable response contract |
| `handler` | Pure service handler, independent of transport |
| `visibility` | `public_mcp`, `http`, `cli`, `internal`, or combinations |

### Service Boundary Validator v1

`ResearchService.invoke()` applies a small service-boundary validator before it
calls a handler. This is not a full JSON Schema implementation and should not be
documented or treated as one.

Validation has two command policies:

| Policy | Behavior |
|---|---|
| `compat` | Default for all current public commands. Preserves legacy adapter compatibility by allowing unknown object properties and ignoring stricter schema keywords that were previously unsupported. |
| `strict` | Opt-in for commands whose transports are ready for stricter boundary checks. Rejects unknown object properties by default and enforces the additional strict keywords below. |

Supported keywords:

| Keyword | Behavior |
|---|---|
| `type` | Validates `object`, `array`, `string`, `integer`, `number`, `boolean`, `null`, and simple type lists. |
| `required` | Validates required object properties and reports the first missing path. |
| `enum` | Validates exact value membership. |
| `items` | Validates array item schemas recursively. |
| `minimum` / `maximum` | Validates numeric lower and upper bounds for integer/number values. |
| `additionalProperties` | In `strict`, rejects unknown object properties when omitted or `false`, permits them when `true`, or validates them against a schema object. In `compat`, unknown properties are passed through. |
| `minLength` / `maxLength` | In `strict`, validates string length. Ignored in `compat`. |
| `pattern` | In `strict`, validates strings with a Python regular expression search. Ignored in `compat`. |
| `format` | In `strict`, validates supported string formats. Currently supported: `uri`, `date-time`. Unknown formats are ignored. Ignored in `compat`. |
| `minItems` / `maxItems` | In `strict`, validates array length. Ignored in `compat`. |

Unsupported or intentionally ignored keywords include `oneOf`, `anyOf`, and
`allOf`. Public commands should remain on `compat` until their public MCP, CLI,
HTTP, and Python adapter shapes have explicit shape-lock tests and a gate names
any stricter behavior.

## Migration Sequence

1. Keep all 31 public MCP tools service-backed, because they are the contracted
   agent surface.
2. Move HTTP action endpoints that already call `execute_tool()` to
   `ResearchService.invoke()`.
3. Move CLI commands one group at a time. Keep CLI output formatting in
   `cli.py`; do not move Click concerns into the service.
4. Leave read-only table browsing endpoints in HTTP until equivalent service
   commands exist.
5. Once routing is centralized, shrink `cli.py` and `http_api.py` to transport
   adapters.

## Acceptance Target

- Every public command has one service handler.
- MCP, HTTP, CLI, and Python API call the same handler for the same command.
- Transport files contain parsing/formatting only.
- Error responses use the same machine-readable error code shape across
  transports.

The full rewrite is intentionally not bundled with the MCP surface contraction
because it touches every user-facing transport.
