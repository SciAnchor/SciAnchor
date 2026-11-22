from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_guard_module():
    script_path = REPO_ROOT / "scripts" / "check-service-coverage.py"
    spec = importlib.util.spec_from_file_location("service_coverage_guard", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_service_coverage_guard_accepts_current_matrix():
    module = load_guard_module()

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=module.SERVICE_DISPATCH_PATH.read_text(encoding="utf-8"),
        registry_text=module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8"),
        coverage_text=module.COVERAGE_PATH.read_text(encoding="utf-8"),
    )

    assert errors == []


def test_service_coverage_guard_reads_adapter_set_from_dispatch_module():
    module = load_guard_module()

    names = module.parse_service_backed_mcp_names(
        module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        module.SERVICE_DISPATCH_PATH.read_text(encoding="utf-8"),
    )

    assert "paper_search" in names
    assert "productization_boundary" in names
    assert "figure_package" in names
    assert len(names) == 53


def test_service_coverage_guard_rejects_missing_public_tool():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `skill_get` | service-backed-mcp | `ResearchService` via MCP adapter | done |\n",
        "",
    )

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=module.SERVICE_DISPATCH_PATH.read_text(encoding="utf-8"),
        registry_text=module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8"),
        coverage_text=coverage_text,
    )

    assert any("missing public tools" in error for error in errors)


def test_service_coverage_guard_rejects_adapter_without_service_registry():
    module = load_guard_module()
    registry_text = module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8").replace(
        '        visibility=("public_mcp", "python"),\n        handler=handlers.paper_list,\n',
        '        visibility=("python",),\n        handler=handlers.paper_list,\n',
        1,
    )

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=module.SERVICE_DISPATCH_PATH.read_text(encoding="utf-8"),
        registry_text=registry_text,
        coverage_text=module.COVERAGE_PATH.read_text(encoding="utf-8"),
    )

    assert any("missing public service commands" in error for error in errors)


def test_service_coverage_guard_rejects_registered_only_without_service_registry():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `section_draft` | service-backed-mcp | `ResearchService` via MCP adapter | done |\n",
        "| `section_draft` | registered-only | MCP existing path; `ResearchService` registry only | S11 |\n",
    )
    service_dispatch_text = module.SERVICE_DISPATCH_PATH.read_text(
        encoding="utf-8"
    ).replace(
        '    "section_draft",\n',
        "",
    )
    registry_text = module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8").replace(
        '        name="section_draft",\n'
        '        description=_primitive_description("section_draft"),\n'
        '        input_schema=_primitive_input_schema("section_draft"),\n'
        "        output_schema=_COMMON_OUTPUT_SCHEMA,\n"
        '        visibility=("public_mcp", "python"),\n',
        '        name="section_draft",\n'
        '        description=_primitive_description("section_draft"),\n'
        '        input_schema=_primitive_input_schema("section_draft"),\n'
        "        output_schema=_COMMON_OUTPUT_SCHEMA,\n"
        '        visibility=("python",),\n',
    )

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=service_dispatch_text,
        registry_text=registry_text,
        coverage_text=coverage_text,
    )

    assert any(
        "registered-only status does not match service registry" in error
        for error in errors
    )


def test_service_coverage_guard_accepts_gate_deferred_existing_path_tool():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `orchestrator_advance` | service-backed-mcp | `ResearchService` via MCP adapter | done |\n",
        "| `orchestrator_advance` | deferred-gate | orchestrator MCP handler path | gate: orchestrator transition review |\n",
    )
    service_dispatch_text = module.SERVICE_DISPATCH_PATH.read_text(
        encoding="utf-8"
    ).replace(
        '    "orchestrator_advance",\n',
        "",
    )

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=service_dispatch_text,
        registry_text=module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8"),
        coverage_text=coverage_text,
    )

    assert module.parse_coverage_rows(coverage_text)["orchestrator_advance"] == (
        "deferred-gate"
    )
    assert errors == []


def test_service_coverage_guard_accepts_productization_boundary_service_routing():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8")

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=module.SERVICE_DISPATCH_PATH.read_text(encoding="utf-8"),
        registry_text=module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8"),
        coverage_text=coverage_text,
    )

    rows = module.parse_coverage_rows(coverage_text)
    next_actions = module.parse_coverage_next_actions(coverage_text)
    assert rows["productization_boundary"] == "service-backed-mcp"
    assert next_actions["productization_boundary"] == "K196"
    assert errors == []


def test_service_coverage_guard_rejects_deferred_without_gate_reason():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `orchestrator_advance` | service-backed-mcp | `ResearchService` via MCP adapter | done |\n",
        "| `orchestrator_advance` | deferred-gate | orchestrator MCP handler path | future orchestrator slice |\n",
    )
    service_dispatch_text = module.SERVICE_DISPATCH_PATH.read_text(
        encoding="utf-8"
    ).replace(
        '    "orchestrator_advance",\n',
        "",
    )

    errors = module.validate_service_coverage(
        surface_text=module.TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        mcp_tools_text=module.MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        service_dispatch_text=service_dispatch_text,
        registry_text=module.SERVICE_REGISTRY_PATH.read_text(encoding="utf-8"),
        coverage_text=coverage_text,
    )

    assert any("deferred-gate rows need gate reasons" in error for error in errors)
