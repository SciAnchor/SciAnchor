from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "scripts" / "build_showcase_bundle.py").exists()
    or (p / "setup.sh").exists()
)


def load_script_module():
    script_path = REPO_ROOT / "scripts" / "build_showcase_bundle.py"
    spec = importlib.util.spec_from_file_location("build_showcase_bundle", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_showcase_bundle_builder_copies_artifacts_and_writes_manifest(tmp_path):
    module = load_script_module()
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    artifact_paths = {}
    for slot in module.SHOWCASE_SLOTS:
        source = source_dir / f"{slot}.txt"
        source.write_text(f"{slot} artifact\n")
        artifact_paths[slot] = source

    output_dir = tmp_path / "bundle"
    manifest = module.build_showcase_bundle(
        output_dir=output_dir,
        artifact_paths=artifact_paths,
        title="RH public launch showcase",
        created_at="2026-06-03T00:00:00Z",
        require_complete=True,
    )

    assert manifest["complete"] is True
    assert manifest["missing_slots"] == []
    assert (output_dir / "README.md").exists()
    manifest_path = output_dir / "manifest.json"
    assert manifest_path.exists()
    stored = json.loads(manifest_path.read_text())
    assert stored["title"] == "RH public launch showcase"
    for slot in module.SHOWCASE_SLOTS:
        item = stored["artifacts"][slot]
        assert item["status"] == "present"
        assert item["sha256"]
        assert (output_dir / item["bundle_path"]).read_text() == f"{slot} artifact\n"
    assert "productization_boundary" not in stored


def test_showcase_bundle_builder_reports_missing_required_slots(tmp_path):
    module = load_script_module()
    only_pdf = tmp_path / "final.pdf"
    only_pdf.write_bytes(b"%PDF-1.4 sample\n")

    output_dir = tmp_path / "bundle"
    try:
        module.build_showcase_bundle(
            output_dir=output_dir,
            artifact_paths={"final_pdf": only_pdf},
            title="Incomplete showcase",
            created_at="2026-06-03T00:00:00Z",
            require_complete=True,
        )
    except module.IncompleteShowcaseBundle as exc:
        missing = set(exc.missing_slots)
    else:
        raise AssertionError("expected IncompleteShowcaseBundle")

    assert "provenance_export" in missing
    assert "researchflowbench_score_report" in missing
    assert (output_dir / "manifest.json").exists()
    stored = json.loads((output_dir / "manifest.json").read_text())
    assert stored["complete"] is False
    assert stored["artifacts"]["final_pdf"]["status"] == "present"
    assert stored["artifacts"]["provenance_export"]["status"] == "missing"
    assert "productization_boundary" not in stored


def test_showcase_bundle_builder_adds_opt_in_productization_boundary(tmp_path):
    module = load_script_module()
    only_pdf = tmp_path / "final.pdf"
    only_pdf.write_bytes(b"%PDF-1.4 sample\n")

    output_dir = tmp_path / "bundle"
    manifest = module.build_showcase_bundle(
        output_dir=output_dir,
        artifact_paths={"final_pdf": only_pdf},
        title="Showcase boundary preview",
        created_at="2026-06-11T00:00:00Z",
        productization_boundary=True,
    )

    boundary = manifest["productization_boundary"]
    assert boundary["boundary_id"] == "lg10-public-productization-boundary"
    assert boundary["schema_version"] == "lg10_productization_boundary.v1"
    assert boundary["scope"] == "public-showcase-opt-in-preview"
    assert boundary["lg10_status"] == "gate_bound"
    assert boundary["allowed_future_pattern"] == "one_public_surface_per_gate_slice"
    assert boundary["risk_flags"] == {
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
        "orchestrator_gate_changed": False,
        "benchmark_claim_changed": False,
        "dependency_changed": False,
    }

    encoded = json.dumps(manifest, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "sk-",
        "env_",
    ):
        assert fragment not in encoded

    stored = json.loads((output_dir / "manifest.json").read_text())
    assert stored["productization_boundary"] == boundary


def test_showcase_bundle_cli_flag_adds_productization_boundary(
    tmp_path,
    monkeypatch,
):
    module = load_script_module()
    only_pdf = tmp_path / "final.pdf"
    only_pdf.write_bytes(b"%PDF-1.4 sample\n")
    output_dir = tmp_path / "bundle"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_showcase_bundle.py",
            "--output",
            str(output_dir),
            "--created-at",
            "2026-06-11T00:00:00Z",
            "--artifact",
            f"final_pdf={only_pdf}",
            "--productization-boundary",
        ],
    )

    result = module.main()

    assert result == 0
    stored = json.loads((output_dir / "manifest.json").read_text())
    boundary = stored["productization_boundary"]
    assert boundary["boundary_id"] == "lg10-public-productization-boundary"
    assert boundary["scope"] == "public-showcase-opt-in-preview"
