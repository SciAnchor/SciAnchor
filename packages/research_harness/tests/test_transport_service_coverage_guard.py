from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_guard_module():
    script_path = REPO_ROOT / "scripts" / "check-transport-service-coverage.py"
    assert script_path.exists()
    spec = importlib.util.spec_from_file_location(
        "transport_service_coverage_guard", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transport_coverage_guard_accepts_current_matrix():
    module = load_guard_module()

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=module.TRANSPORT_COVERAGE_PATH.read_text(
            encoding="utf-8"
        ),
    )

    assert errors == []


def test_transport_coverage_guard_tracks_action_equivalent_commands():
    module = load_guard_module()

    rows = module.parse_transport_coverage_rows(
        module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8")
    )

    assert module.ACTION_TRANSPORT_COMMANDS == (
        "paper_search",
        "paper_ingest",
        "paper_summarize",
        "claim_extract",
        "evidence_link",
        "gap_detect",
        "baseline_identify",
        "section_draft",
        "consistency_check",
        "topic_knowledge_status",
        "topic_knowledge_refresh",
    )
    for command in module.ACTION_TRANSPORT_COMMANDS:
        assert command in rows

    assert rows["paper_ingest"]["python_api"] == "service-backed"
    assert rows["paper_summarize"]["python_api"] == "service-backed"
    assert rows["paper_summarize"]["http"] == "missing-equivalent"
    assert rows["evidence_link"]["python_api"] == "service-backed"
    assert rows["evidence_link"]["http"] == "missing-equivalent"
    assert rows["gap_detect"]["http"] == "service-backed"
    assert rows["topic_knowledge_refresh"]["cli"] == "service-backed"


def test_transport_coverage_guard_tracks_cross_topic_atlas_read_equivalent():
    module = load_guard_module()

    rows = module.parse_transport_coverage_rows(
        module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8")
    )

    assert "cross_topic_atlas" in module.READ_TRANSPORT_COMMANDS
    assert rows["cross_topic_atlas"]["cli"] == "service-backed"
    assert rows["cross_topic_atlas"]["http"] == "service-backed"


def test_transport_coverage_guard_tracks_write_effect_commands():
    module = load_guard_module()

    rows = module.parse_transport_coverage_rows(
        module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8")
    )

    assert module.WRITE_EFFECT_TRANSPORT_COMMANDS == (
        "orchestrator_resume",
        "orchestrator_advance",
        "orchestrator_record_artifact",
        "zotero_sync",
    )
    for command in module.WRITE_EFFECT_TRANSPORT_COMMANDS:
        assert command in rows

    assert rows["orchestrator_advance"]["cli"] == "service-backed"
    assert rows["orchestrator_record_artifact"]["python_api"] == "service-backed"
    assert rows["zotero_sync"]["cli"] == "not-applicable"


def test_transport_coverage_guard_rejects_missing_required_read_command():
    module = load_guard_module()
    transport_text = module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `topic_list` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI routed; HTTP `/api/topics` adapter routed |\n",
        "",
    )

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=transport_text,
    )

    assert any("missing read commands" in error for error in errors)


def test_transport_coverage_guard_rejects_missing_required_action_command():
    module = load_guard_module()
    transport_text = module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `gap_detect` | `service-backed-mcp` | `service-backed` | "
        "`missing-equivalent` | `service-backed` | done: Python facade "
        "`execute_primitive` and HTTP primitive action path route through "
        "`ResearchService` |\n",
        "",
    )

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=transport_text,
    )

    assert any("missing action commands" in error for error in errors)


def test_transport_coverage_guard_rejects_missing_python_service_primitive_row():
    module = load_guard_module()
    transport_text = module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `paper_summarize` | `service-backed-mcp` | `service-backed` | "
        "`missing-equivalent` | `missing-equivalent` | done: Python facade "
        "`execute_primitive` routes through `ResearchService`; no "
        "shape-equivalent CLI/HTTP action exists |\n",
        "",
    )

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=transport_text,
    )

    assert any("missing Python service-routed primitives" in error for error in errors)


def test_transport_coverage_guard_rejects_invalid_transport_status():
    module = load_guard_module()
    transport_text = module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `topic_list` | `service-backed-mcp` | `missing-equivalent` | `service-backed` | `service-backed` | done: CLI routed; HTTP `/api/topics` adapter routed |\n",
        "| `topic_list` | `service-backed-mcp` | `missing-equivalent` | `unknown-status` | `service-backed` | done: CLI routed; HTTP `/api/topics` adapter routed |\n",
    )

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=transport_text,
    )

    assert any("invalid transport statuses" in error for error in errors)


def test_transport_coverage_guard_rejects_lg16_debt_statuses():
    module = load_guard_module()
    transport_text = module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `paper_search` | `service-backed-mcp` | `service-backed` | "
        "`not-applicable` | `service-backed` | done: Python facade and HTTP "
        "`/api/papers/search` route through `ResearchService`; CLI `search papers` "
        "is a multi-provider search surface rather than a service-shape equivalent |\n",
        "| `paper_search` | `service-backed-mcp` | `existing-direct` | "
        "`not-applicable` | `service-backed` | done: injected debt for test |\n",
    )

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=transport_text,
    )

    assert any("LG16 debt statuses are not allowed" in error for error in errors)


def test_transport_coverage_guard_rejects_non_service_backed_read_command():
    module = load_guard_module()
    transport_text = module.TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8") + (
        "| `unknown_write` | `service-backed-mcp` | `missing-equivalent` | "
        "`missing-equivalent` | `missing-equivalent` | defer: out of scope |\n"
    )

    errors = module.validate_transport_coverage(
        service_coverage_text=module.SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=transport_text,
    )

    assert any(
        "not tracked read/action/write-effect commands" in error for error in errors
    )
