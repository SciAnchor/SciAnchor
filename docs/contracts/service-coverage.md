# Service Coverage

Status: active release guard.

This matrix tracks how the 55 public MCP tools are moving toward
`ResearchService`. It is intentionally separate from runtime code so reviewers
can approve each migration group before behavior changes.

Allowed statuses:

- `service-backed-mcp`: registered in `ResearchService` and routed through the
  MCP adapter.
- `registered-only`: registered in `ResearchService`, but not yet routed from
  MCP.
- `existing-path`: still handled by the pre-service MCP path.
- `deferred-gate`: intentionally left off service-backed MCP routing until a
  future bounded slice resolves the named gate reason.

| Public MCP tool | Status | Current path | Next slice |
|---|---|---|---|
| `topic_list` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `topic_show` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `topic_state` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_search` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_ingest` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_list` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_summarize` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `claim_extract` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `evidence_link` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `gap_detect` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `baseline_identify` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `section_draft` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `figure_generate` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `consistency_check` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `orchestrator_status` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `orchestrator_resume` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `orchestrator_advance` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `orchestrator_gate_check` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `orchestrator_record_artifact` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_commit_version` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_task_intake` | service-backed-mcp | `ResearchService` via MCP adapter | durable-paper-intake |
| `adversarial_review` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `advisory_check` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `provenance_summary` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `provenance_export` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `zotero_sync` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paperindex_search` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `topic_init` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_pending_decisions` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_decide` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_start` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_status` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_resume` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_mode` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_set_mode` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `paper_production_export` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `skill_list` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `skill_get` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `productization_boundary` | service-backed-mcp | `ResearchService` via MCP adapter | K196 |
| `topic_knowledge_status` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `topic_knowledge_refresh` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `cross_topic_atlas` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `exemplar_curate` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `exemplar_retrieve` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `exemplar_plan` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `exemplar_generate` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `exemplar_critique` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `figure_suite_plan` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `figure_suite_render` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `figure_package` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `manuscript_review` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `manuscript_polish` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `resource_ready_get` | service-backed-mcp | `ResearchService` via MCP adapter | done |
| `deposit_zenodo` | existing-path | convenience MCP → `research_harness.deposit.zenodo` | deposit-zenodo-v1 |
