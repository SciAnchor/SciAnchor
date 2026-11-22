from __future__ import annotations

import json

from research_harness.cli import main


def test_productization_boundary_requires_explicit_lg10_opt_in(runner):
    result = runner.invoke(main, ["--json", "productization", "boundary"])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "error": {
            "code": "lg10_opt_in_required",
            "message": "pass --experimental-lg10 to view the LG10 boundary",
        }
    }


def test_productization_boundary_cli_outputs_shape_locked_json_without_db(
    runner,
    monkeypatch,
):
    def fail_get_db(ctx):
        raise AssertionError("productization boundary must not open the database")

    monkeypatch.setattr("research_harness.cli.get_db", fail_get_db)

    result = runner.invoke(
        main,
        [
            "productization",
            "boundary",
            "--experimental-lg10",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["schema_version"] == "lg10_productization_boundary.v1"
    assert payload["scope"] == "public-cli-opt-in-preview"
    assert payload["lg8_lg9_prerequisite"] == "complete"
    assert payload["lg10_status"] == "gate_bound"
    assert payload["allowed_future_pattern"] == "one_public_surface_per_gate_slice"
    assert payload["public_surfaces"] == [
        "CLI",
        "MCP",
        "HTTP",
        "Python facade",
        "Zotero",
        "doctor",
        "showcase",
        "skills/docs",
    ]
    assert payload["required_pre_implementation_evidence"] == [
        "shape-lock tests",
        "opt-in default",
        "compatibility proof",
        "docs claim review",
        "rollback/fallback plan",
    ]
    assert payload["risk_flags"] == {
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
        "orchestrator_gate_changed": False,
        "benchmark_claim_changed": False,
        "dependency_changed": False,
    }

    encoded = json.dumps(payload, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "sk-",
        "env_",
    ):
        assert fragment not in encoded
