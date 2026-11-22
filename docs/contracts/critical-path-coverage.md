# RH Critical Path Coverage

Status: active release guard.

This matrix is a structural guard for local critical-path test coverage. It
does not replace the global coverage floor in
`docs/contracts/release-coverage-threshold.json`; the current release floor
remains 24% with 80% tracked as debt. The guard records whether each public
workflow-critical area has focused coverage and is wired into
`scripts/codex-check.sh --coverage`.

| Critical path | Status | Primary guard | Focused tests | Release hook |
|---|---|---|---|---|
| `public_mcp_tools` | `covered` | `scripts/check-service-coverage.py` | `packages/research_harness/tests/test_service_coverage_guard.py`, `packages/research_harness/tests/test_mcp_public_surface_guard.py`, `packages/research_harness_mcp/research_harness_mcp/tests/test_tools.py` | `scripts/codex-check.sh --coverage` |
| `service_validation` | `covered` | `scripts/check-service-coverage.py` | `packages/research_harness/tests/test_service_layer.py`, `packages/research_harness/tests/test_service_coverage_guard.py` | `scripts/codex-check.sh --coverage` |
| `orchestrator_artifact_gate` | `covered` | `scripts/check-release-gates.py` | `packages/research_harness/tests/test_orchestrator_service.py`, `packages/research_harness/tests/test_artifact_trace_contract.py`, `packages/research_harness/tests/test_orchestrator_rollback_governance.py` | `scripts/codex-check.sh --coverage` |
| `topic_knowledge` | `covered` | `scripts/check-service-coverage.py` | `packages/research_harness/tests/test_topic_knowledge_status.py`, `packages/research_harness/tests/test_topic_knowledge_layer.py`, `packages/research_harness_mcp/tests/test_topic_knowledge_status_http.py`, `packages/research_harness_mcp/tests/test_topic_knowledge_refresh_http.py` | `scripts/codex-check.sh --coverage` |
| `zotero_dry_run_boundary` | `covered` | `scripts/check-release-gates.py` | `packages/research_harness/tests/test_service_layer.py`, `packages/research_harness/tests/test_zotero_sync.py`, `packages/research_harness_mcp/tests/test_mcp_tool_boundary.py`, `packages/research_harness_mcp/tests/test_http_boundary_auth.py` | `scripts/codex-check.sh --coverage` |
| `golden_workflows` | `covered` | `scripts/check-critical-path-coverage.py` | `packages/research_harness/tests/test_golden_workflows.py`, `packages/research_harness/tests/test_critical_path_coverage_guard.py` | `scripts/codex-check.sh --coverage` |
| `transport_service_convergence` | `covered` | `scripts/check-transport-service-coverage.py` | `packages/research_harness/tests/test_transport_service_coverage_guard.py`, `packages/research_harness/tests/test_python_facade_service_routing.py`, `packages/research_harness/tests/test_cli_topic_knowledge_module.py`, `packages/research_harness_mcp/tests/test_topic_knowledge_status_http.py`, `packages/research_harness_mcp/tests/test_topic_knowledge_refresh_http.py`, `packages/research_harness_mcp/tests/test_http_paper_service_routing.py` | `scripts/codex-check.sh --coverage` |

## Boundary

This guard reports local coverage evidence only. It does not make public
benchmark, performance, release-grade quality, or external readiness claims.
Adding or removing a critical path must update this matrix and the focused
guard tests in the same change.
