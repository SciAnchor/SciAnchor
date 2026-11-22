import json
from types import SimpleNamespace

from research_harness.cli import main


def test_doctor_json(runner, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "proxy-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8765/v1")
    monkeypatch.setenv("OPENAI_MODEL", "composer-2.5-fast")

    result = runner.invoke(main, ["--json", "doctor"])
    assert result.exit_code == 0
    checks = json.loads(result.output)
    names = {item["check"] for item in checks}
    assert "python" in names
    assert "sqlite3" in names
    assert "database" in names
    assert "llm_config" in names
    assert "execution_backend" in names
    assert "primitives" in names
    assert "provenance" in names

    llm_check = next(item for item in checks if item["check"] == "llm_config")
    assert llm_check["configured"] is True
    assert llm_check["selected_provider"] == "openai"
    assert llm_check["route_kind"] == "openai-compatible"
    assert "openai" in llm_check["available_providers"]


def test_doctor_json_default_output_shape_unchanged(runner, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "proxy-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8765/v1")
    monkeypatch.setenv("OPENAI_MODEL", "composer-2.5-fast")

    result = runner.invoke(main, ["--json", "doctor"])

    assert result.exit_code == 0
    checks = json.loads(result.output)
    # This list is a deliberate guard: the default doctor surface must not
    # change silently. `context_telemetry` was added 2026-08-08 (P-6) because a
    # disabled context recorder is only discoverable BEFORE a run — context
    # drops cannot be reconstructed afterwards.
    assert [item["check"] for item in checks] == [
        "python",
        "sqlite3",
        "paperindex",
        "config",
        "database",
        "state_trees",
        "llm_config",
        "execution_backend",
        "primitives",
        "spc_provider",
        "venue_facts",
        "context_telemetry",
        "provenance",
    ]
    assert all("runtime_diagnostics" not in item for item in checks)
    assert all(item["check"] != "productization_boundary" for item in checks)


def test_doctor_productization_boundary_json_is_opt_in_preview(runner, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://internal.example.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL", "composer-2.5-fast")

    result = runner.invoke(main, ["--json", "doctor", "--productization-boundary"])

    assert result.exit_code == 0
    checks = json.loads(result.output)
    preview = checks[-1]
    assert preview["check"] == "productization_boundary"
    assert preview["preview"] is True
    assert preview["ok"] is True
    assert preview["origin"] == "rh doctor --productization-boundary"
    assert preview["note"] == "preview: gate-bound LG10 productization boundary"

    boundary = preview["boundary"]
    assert boundary["boundary_id"] == "lg10-public-productization-boundary"
    assert boundary["schema_version"] == "lg10_productization_boundary.v1"
    assert boundary["scope"] == "public-doctor-opt-in-preview"
    assert boundary["lg8_lg9_prerequisite"] == "complete"
    assert boundary["lg10_status"] == "gate_bound"
    assert boundary["allowed_future_pattern"] == "one_public_surface_per_gate_slice"

    encoded_preview = json.dumps(preview, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "sk-",
        "env_",
        "internal.example.invalid",
    ):
        assert fragment not in encoded_preview


def test_doctor_runtime_diagnostics_json_is_opt_in_preview(runner, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "proxy-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8765/v1")
    monkeypatch.setenv("OPENAI_MODEL", "composer-2.5-fast")

    result = runner.invoke(main, ["--json", "doctor", "--runtime-diagnostics"])

    assert result.exit_code == 0
    checks = json.loads(result.output)
    preview = checks[-1]
    assert preview["check"] == "runtime_diagnostics"
    assert preview["preview"] is True
    assert preview["schema_version"] == "runtime_diagnostics_preview.v0"
    assert preview["origin"] == "rh doctor --runtime-diagnostics"
    assert preview["summary"]["record_count"] == len(preview["diagnostics"])

    names = {item["check_name"] for item in preview["diagnostics"]}
    assert "skill_manifest_validity" in names
    assert "generated_skill_cache" in names
    assert "artifact_path_writability" in names


def test_doctor_runtime_diagnostics_preview_does_not_leak_secrets_or_local_paths(
    runner,
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://internal.example.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL", "composer-2.5-fast")

    result = runner.invoke(main, ["--json", "doctor", "--runtime-diagnostics"])

    assert result.exit_code == 0
    payload = result.output
    assert "sk-test-secret-token" not in payload
    assert "internal.example.invalid" not in payload
    assert "/private/" not in payload
    assert "/var/folders/" not in payload
    assert "/tmp/" not in payload

    checks = json.loads(payload)
    preview = next(item for item in checks if item["check"] == "runtime_diagnostics")
    for diagnostic in preview["diagnostics"]:
        for artifact_ref in diagnostic["artifact_refs"]:
            assert not artifact_ref.startswith("/")


def _fake_route(provider: str = "openai") -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider, route_kind="openai-compatible", source="env"
    )


def test_llm_check_reports_not_ok_when_no_route_is_usable(monkeypatch):
    """BUG-05: rh doctor must be able to fail the LLM check.

    ``ok`` used to be hardcoded True, so a machine with no usable route still
    printed ``[OK] llm_config`` and LLM-backed primitives failed later with no
    diagnosis.
    """
    from research_harness import cli_doctor

    monkeypatch.setattr(
        "llm_router.config.detect_available_provider_details", lambda: []
    )
    monkeypatch.setattr("llm_router.client.llm_route_can_attempt", lambda config: False)

    check = cli_doctor._build_llm_check()

    assert check["check"] == "llm_config"
    assert check["configured"] is False
    assert check["probe_ready"] is False
    assert check["ok"] is False
    assert "optional for non-LLM flows" in str(check["note"])


def test_llm_check_is_ok_when_a_route_can_be_attempted(monkeypatch):
    from research_harness import cli_doctor

    monkeypatch.setattr(
        "llm_router.config.detect_available_provider_details",
        lambda: [_fake_route()],
    )
    monkeypatch.setattr("llm_router.client.llm_route_can_attempt", lambda config: True)

    check = cli_doctor._build_llm_check()

    assert check["probe_ready"] is True
    assert check["ok"] is True


def test_doctor_output_warns_when_llm_route_is_unusable(runner, monkeypatch):
    from research_harness.cli import main

    monkeypatch.setattr(
        "llm_router.config.detect_available_provider_details", lambda: []
    )
    monkeypatch.setattr("llm_router.client.llm_route_can_attempt", lambda config: False)

    result = runner.invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "[WARN] llm_config" in result.output
