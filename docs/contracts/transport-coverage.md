# Transport Coverage

Status: active release guard.

This matrix tracks transport convergence for service-backed MCP commands that
have plausible Python, CLI, or HTTP equivalents. The read-equivalent matrix
is complete. The same guard covers high-value action-equivalent
commands without changing public names, routes, payload shapes, or runtime
routing.

Allowed transport statuses:

- `service-backed`: the transport already invokes `ResearchService`.
- `missing-equivalent`: no equivalent transport command or endpoint is present.
- `not-applicable`: an adjacent transport exists, but it is not a shape-
  equivalent adapter for the service command and remains outside Phase A.

`existing-direct` and `deferred-shape` are no longer valid internal-complete
states for rows tracked by this matrix.

## Read-Equivalent Matrix

| Command | MCP service status | Python API | CLI | HTTP | Next action |
|---|---|---|---|---|---|
| `topic_list` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI routed; HTTP `/api/topics` adapter routed |
| `topic_show` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI routed; HTTP `/api/topics/{topic_id}` adapter routed while preserving id-based detail shape |
| `paper_list` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI routed; HTTP `/api/papers?topic_id=...` adapter routed while preserving pagination/filter shape |
| `provenance_summary` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI default/topic path routed; `--backend` compatibility filter remains legacy; HTTP `/api/provenance/summary` adapter routed |
| `provenance_export` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `missing-equivalent` | done: CLI JSON path routed; CSV compatibility export remains legacy |
| `orchestrator_status` | `service-backed-mcp` | `service-backed` | `service-backed` | `service-backed` | done: CLI adapter-only routing; Python facade routing; HTTP topic detail status enrichment routed while preserving shape |
| `orchestrator_gate_check` | `service-backed-mcp` | `service-backed` | `service-backed` | `service-backed` | done: CLI adapter-only routing; Python facade routing; HTTP `/api/topics/{topic_id}/gate` routed while preserving gate pass-through shape |
| `cross_topic_atlas` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI `topic cross-topic-atlas` and HTTP `/api/topics/cross-topic-atlas` route through `ResearchService` while preserving public shapes |
| `paperindex_search` | `service-backed-mcp` | `missing-equivalent` | `missing-equivalent` | `missing-equivalent` | defer: no transport equivalent to route |
| `skill_list` | `service-backed-mcp` | `missing-equivalent` | `missing-equivalent` | `missing-equivalent` | defer: MCP-only skill manifest surface |
| `skill_get` | `service-backed-mcp` | `missing-equivalent` | `missing-equivalent` | `missing-equivalent` | defer: MCP-only skill manifest surface |

## Action-Equivalent Matrix

| Command | MCP service status | Python API | CLI | HTTP | Next action |
|---|---|---|---|---|---|
| `paper_search` | `service-backed-mcp` | `service-backed` | `not-applicable` | `service-backed` | done: Python facade and HTTP `/api/papers/search` route through `ResearchService`; CLI `search papers` is a multi-provider search surface rather than a service-shape equivalent |
| `paper_ingest` | `service-backed-mcp` | `service-backed` | `not-applicable` | `service-backed` | done: Python facade and HTTP `/api/papers/ingest` route through `ResearchService`; CLI `paper ingest` is a richer manual-ingest surface with dry-run/manual metadata flags |
| `paper_summarize` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `missing-equivalent` | done: Python facade `execute_primitive` routes through `ResearchService`; no shape-equivalent CLI/HTTP action exists |
| `claim_extract` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `service-backed` | done: Python facade `execute_primitive` and HTTP primitive action path route through `ResearchService` |
| `evidence_link` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `missing-equivalent` | done: Python facade `execute_primitive` routes through `ResearchService`; no shape-equivalent CLI/HTTP action exists |
| `gap_detect` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `service-backed` | done: Python facade `execute_primitive` and HTTP primitive action path route through `ResearchService` |
| `baseline_identify` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `service-backed` | done: Python facade `execute_primitive` and HTTP primitive action path route through `ResearchService` |
| `section_draft` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `service-backed` | done: Python facade `execute_primitive` and HTTP primitive action path route through `ResearchService` |
| `consistency_check` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `service-backed` | done: Python facade `execute_primitive` and HTTP primitive action path route through `ResearchService` |
| `topic_knowledge_status` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI and HTTP status adapters invoke `ResearchService`; no Python facade method exists |
| `topic_knowledge_refresh` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI and HTTP refresh adapters invoke `ResearchService`; no Python facade method exists |

## Write/Effect Matrix

| Command | MCP service status | Python API | CLI | HTTP | Next action |
|---|---|---|---|---|---|
| `orchestrator_resume` | `service-backed-mcp` | `missing-equivalent` | `missing-equivalent` | `service-backed` | done: MCP and HTTP topic-create side effect route through service-backed tool dispatch; no Python or CLI resume facade exists |
| `orchestrator_advance` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI advance uses `ResearchService`; HTTP advance uses service-backed tool dispatch |
| `orchestrator_record_artifact` | `service-backed-mcp` | `service-backed` | `missing-equivalent` | `service-backed` | done: Python `record_artifact` facade and HTTP artifact route use `ResearchService` or service-backed tool dispatch |
| `zotero_sync` | `service-backed-mcp` | `missing-equivalent` | `not-applicable` | `not-applicable` | done: MCP stable dry-run command is service-backed; CLI/HTTP Zotero surfaces retain richer Phase B real-sync/apply semantics and are not service-shape equivalents |
