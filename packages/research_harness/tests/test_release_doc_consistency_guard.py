from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_guard_module():
    script_path = REPO_ROOT / "scripts" / "check-release-doc-consistency.py"
    spec = importlib.util.spec_from_file_location(
        "release_doc_consistency_guard", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_doc_inputs(module):
    return {
        "status_text": module.STATUS_PATH.read_text(encoding="utf-8"),
        "audit_text": module.AUDIT_PATH.read_text(encoding="utf-8"),
        "coverage_text": module.COVERAGE_PATH.read_text(encoding="utf-8"),
        "readme_text": module.README_PATH.read_text(encoding="utf-8"),
        "readme_en_text": module.README_EN_PATH.read_text(encoding="utf-8"),
        "quickstart_text": module.QUICKSTART_PATH.read_text(encoding="utf-8"),
        "quickstart_zh_text": module.QUICKSTART_ZH_PATH.read_text(encoding="utf-8"),
        "boundary_text": module.RELEASE_BOUNDARY_PATH.read_text(encoding="utf-8"),
        "python_api_text": module.PYTHON_API_PATH.read_text(encoding="utf-8"),
        "knowledge_http_text": module.KNOWLEDGE_HTTP_PATH.read_text(encoding="utf-8"),
        "service_plan_text": module.SERVICE_PLAN_PATH.read_text(encoding="utf-8"),
        "rfb_results_text": module.RFB_RESULTS_PATH.read_text(encoding="utf-8"),
        "benchmark_feedback_text": module.read_benchmark_feedback_docs_text(),
    }


def test_release_doc_consistency_guard_accepts_current_docs():
    module = load_guard_module()

    errors = module.validate_release_doc_consistency(**current_doc_inputs(module))

    assert errors == []


def test_release_doc_consistency_guard_rejects_stale_status_public_tool_count():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    status_text = module.STATUS_PATH.read_text(encoding="utf-8").replace(
        "54 public contracted tools",
        "25 public contracted tools",
    )
    inputs["status_text"] = status_text

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("STATUS.md public MCP count" in error for error in errors)


def test_release_doc_consistency_guard_rejects_stale_audit_service_claim():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    audit_text = module.AUDIT_PATH.read_text(encoding="utf-8").replace(
        "Service dispatcher coverage: 53 of the 54 public tools route through\n"
        "  `ResearchService` in the MCP adapter;",
        "Service dispatcher coverage: skeleton active. `topic_list`, "
        "`topic_show`, and `paper_list` route through `ResearchService` in the "
        "MCP adapter; other public tools stay on existing paths until later "
        "migration slices. Also",
    )
    inputs["audit_text"] = audit_text

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("audit service-backed MCP count" in error for error in errors)


def test_release_doc_consistency_guard_rejects_service_coverage_count_drift():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `skill_get` | service-backed-mcp | `ResearchService` via MCP adapter | done |\n",
        "",
    )
    inputs["coverage_text"] = coverage_text

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("service coverage matrix public tool count" in error for error in errors)


def test_release_doc_consistency_guard_requires_release_boundary_links():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["readme_en_text"] = inputs["readme_en_text"].replace(
        "[Release boundary](docs/contracts/release-boundary.md)",
        "Release boundary",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "README.en.md is missing release boundary link" in error for error in errors
    )


def test_release_doc_consistency_guard_rejects_external_api_overclaim():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["boundary_text"] = inputs["boundary_text"].replace(
        "Stable external API release: deferred.",
        "Stable external API release: approved.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("stable external API release overclaim" in error for error in errors)


def test_release_doc_consistency_guard_rejects_real_zotero_overclaim():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["quickstart_text"] = inputs["quickstart_text"].replace(
        "Real Zotero network sync/apply remains deferred.",
        "Real Zotero network sync/apply is stable.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("real Zotero sync/apply overclaim" in error for error in errors)


def test_release_doc_consistency_guard_requires_zotero_sandbox_boundary():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["boundary_text"] = inputs["boundary_text"].replace(
        "Fake/sandbox Zotero pull/both and apply evidence is local-only.",
        "Zotero sync is ready.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("Zotero sandbox boundary" in error for error in errors)


def test_release_doc_consistency_guard_rejects_public_benchmark_overclaim():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["status_text"] = inputs["status_text"].replace(
        "Public benchmark/performance claims remain deferred.",
        "Public benchmark/performance claims are approved.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("public benchmark/performance overclaim" in error for error in errors)


def test_release_doc_consistency_guard_requires_localized_quickstart_boundary():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["quickstart_zh_text"] = inputs["quickstart_zh_text"].replace(
        "非 loopback HTTP 绑定不受支持",
        "非 loopback HTTP 绑定可直接公开使用",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "docs/quickstart.zh.md localized release boundary missing" in error
        for error in errors
    )


def test_release_doc_consistency_guard_rejects_benchmark_result_overclaim():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = (
        "The full-agent smoke shows that RH + Codex can improve recall "
        "on selected full1000 tasks."
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("benchmark result overclaim" in error for error in errors)


def test_release_doc_consistency_guard_rejects_benchmark_gold_derived_doc_leak():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = """
| Task | Runner | Predicted | Gold | Matched arXiv IDs | Wide IoU |
|---|---|---:|---:|---|---:|
| `autoresearchbench.797` | RH + Codex agent | 11 | 5 | `2505.19120` | 0.230769 |
"""

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("benchmark gold-derived task table" in error for error in errors)
    assert any("benchmark matched gold identifiers" in error for error in errors)


def test_release_doc_consistency_guard_rejects_benchmark_gold_prose_leak():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = (
        "For task autoresearchbench.797, the agent predicted 11 papers against "
        "5 gold papers, matched arXiv IDs 2505.19120 and 2505.19121, and "
        "recorded wide precision 0.333333 with wide recall 0.400000."
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("benchmark task-level gold-count prose" in error for error in errors)
    assert any(
        "benchmark task-level matched-identifier prose" in error for error in errors
    )
    assert any("benchmark task-level score prose" in error for error in errors)


def test_release_doc_consistency_guard_rejects_benchmark_deep_score_table():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = """
| Task | Deep accuracy | Runner |
|---|---:|---|
| `autoresearchbench.301` | 0.500000 | RH + Codex agent |
"""

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "benchmark task-level selected-sample score table" in error for error in errors
    )


def test_release_doc_consistency_guard_rejects_alternate_selected_sample_table():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = """
| Task | Runner | Selected sample precision | Selected sample recall |
|---|---|---:|---:|
| `autoresearchbench.797` | RH + Codex agent | 0.333333 | 0.400000 |
"""

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "benchmark task-level selected-sample score table" in error for error in errors
    )


def test_release_doc_consistency_guard_rejects_benchmark_feedback_doc_leak():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = ""
    inputs["benchmark_feedback_text"] = """
Older handoff excerpt:

- Wide task `autoresearchbench.source-600-wide`:
  - matched arXiv ids: 2 of 20
  - `wide_iou`: 0.060606
"""

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "benchmark task-level matched-identifier prose" in error for error in errors
    )
    assert any("benchmark task-level score prose" in error for error in errors)


def test_release_doc_consistency_guard_rejects_benchmark_predicted_output_leak():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["rfb_results_text"] = ""
    inputs["benchmark_feedback_text"] = """
Historical benchmark handoff excerpt:

The Codex agent predicted:

- title: `Diffusion Policy: Visuomotor Policy Learning via Action Diffusion`
- arXiv id: `2303.04137`
"""

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "benchmark task-level predicted-output prose" in error for error in errors
    )


def test_release_doc_consistency_guard_rejects_status_benchmark_overclaim():
    module = load_guard_module()
    inputs = current_doc_inputs(module)

    inputs["status_text"] = inputs["status_text"].replace(
        "Private benchmark/performance regression governance only.",
        "Private benchmark/performance regression governance only. "
        "Full1000 real candidate-source runs now have positive but small metrics.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any("STATUS benchmark overclaim" in error for error in errors)


def test_release_doc_consistency_guard_requires_python_api_partial_facade_wording():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["python_api_text"] = inputs["python_api_text"].replace(
        "partial/programmatic facade",
        "complete stable facade",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "Python API doc must qualify the facade as partial/programmatic" in error
        for error in errors
    )


def test_release_doc_consistency_guard_requires_non_loopback_http_wording():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["boundary_text"] = inputs["boundary_text"].replace(
        "Non-loopback HTTP binding is unsupported and not release-approved.",
        "Non-loopback HTTP binding is available.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "HTTP docs must state non-loopback is unsupported/not release-approved" in error
        for error in errors
    )


def test_release_doc_consistency_guard_requires_public_http_policy_wording():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["boundary_text"] = inputs["boundary_text"].replace(
        "Public HTTP deployment requires RESEARCH_HARNESS_HTTP_API_TOKEN plus reviewed",
        "Public HTTP deployment is allowed with default local settings.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "HTTP docs must state public deployment auth/TLS/proxy/allowlist/"
        "CORS/cache policy" in error
        for error in errors
    )


def test_release_doc_consistency_guard_requires_service_plan_current_routing():
    module = load_guard_module()
    inputs = current_doc_inputs(module)
    inputs["service_plan_text"] = inputs["service_plan_text"].replace(
        "CLI `topic list` and `paper list` consume complete service output without\n"
        "  legacy SQL fallback.",
        "CLI `topic list` and `paper list` may fall back to legacy SQL.",
    )

    errors = module.validate_release_doc_consistency(**inputs)

    assert any(
        "service plan must document current CLI list convergence" in error
        for error in errors
    )
