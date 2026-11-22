from __future__ import annotations

import json
import re
from pathlib import Path

from research_harness.runtime.skill_provenance import (
    SKILL_PROVENANCE_REPORT_SCHEMA_VERSION,
    SKILL_PROVENANCE_RECORD_SCHEMA_VERSION,
    scan_skill_provenance,
    skill_provenance_record_to_dict,
    skill_provenance_report_to_dict,
)


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "skills").exists() and (p / "AGENTS.md").exists()
)


def test_scan_current_public_skills_without_manifest_drift():
    report = scan_skill_provenance(REPO_ROOT)
    payload = skill_provenance_report_to_dict(report)

    assert report.schema_version == SKILL_PROVENANCE_REPORT_SCHEMA_VERSION
    assert report.manifest_path == "skills/manifest.json"
    # ``manifest_generated_at`` is a regeneration timestamp that changes on
    # every manifest rebuild; assert it is a well-formed UTC stamp instead of
    # pinning a value that breaks on each regen. Drift against the live skills
    # tree is asserted by ``manifest_drift`` below.
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", report.manifest_generated_at
    )
    assert report.public_skill_count == len(report.records)
    assert report.public_skill_count == len(payload["records"])
    assert report.manifest_drift is False
    assert report.missing_from_manifest == ()
    assert report.manifest_only == ()
    assert payload["public_skill_count"] == report.public_skill_count


def test_scan_v2_runtime_contract_sidecars_for_promoted_skills():
    report = scan_skill_provenance(REPO_ROOT)
    records = {record.skill_name: record for record in report.records}

    for skill_name in ("final-bundle-quality", "publication-pack"):
        record = records[skill_name]
        payload = skill_provenance_record_to_dict(record)

        assert record.schema_version == SKILL_PROVENANCE_RECORD_SCHEMA_VERSION
        assert record.source_kind == "promoted_runtime_skill"
        assert record.runtime_capability_type == "evaluator"
        assert record.runtime_contract_refs == (
            "contracts/input.yaml",
            "contracts/output.yaml",
            "contracts/guardrails.yaml",
        )
        assert "skill.yaml" in record.sidecar_files
        assert payload["content_hashes"]["SKILL.md"].startswith("sha256:")
        assert payload["content_hashes"]["skill.yaml"].startswith("sha256:")


def test_scan_records_agent_overlays_and_supporting_sidecars():
    report = scan_skill_provenance(REPO_ROOT)
    records = {record.skill_name: record for record in report.records}

    figure = records["figure-quality"]
    paper_writing = records["paper-writing"]

    assert figure.agent_overlays == ("agents/openai.yaml",)
    assert "references/nature-figure-adaptation.md" in figure.sidecar_files
    assert paper_writing.track_files == (
        "tracks/advisor-report.md",
        "tracks/original-research.md",
        "tracks/position-paper.md",
        "tracks/short-workshop.md",
        "tracks/survey-review.md",
        "tracks/system-benchmark.md",
    )


def test_scan_detects_manifest_drift_without_mutating_files(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    alpha_dir = skills_dir / "alpha"
    beta_dir = skills_dir / "beta"
    alpha_dir.mkdir(parents=True)
    beta_dir.mkdir(parents=True)
    (alpha_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Alpha skill.\npublic_suite: research\n"
        "task_type: discovery\ndata_access_level: local\ninputs: topic\n"
        "outputs: result\ngates: none\nartifact_schemas: report\n"
        "estimated_runtime: 1 min\n---\n# Alpha\n",
        encoding="utf-8",
    )
    (beta_dir / "SKILL.md").write_text(
        "---\nname: beta\ndescription: Beta skill.\n---\n# Beta\n",
        encoding="utf-8",
    )
    manifest_path = skills_dir / "manifest.json"
    before = {
        "schema_version": "1.0",
        "generated_at": "2026-06-09T00:00:00Z",
        "skills_dir": "skills",
        "skills": [
            {
                "name": "alpha",
                "path": "skills/alpha",
                "skill_md": "skills/alpha/SKILL.md",
                "description": "Alpha skill.",
            },
            {
                "name": "manifest-only",
                "path": "skills/manifest-only",
                "skill_md": "skills/manifest-only/SKILL.md",
                "description": "Missing source.",
            },
        ],
    }
    manifest_path.write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")

    report = scan_skill_provenance(tmp_path)

    assert json.loads(manifest_path.read_text(encoding="utf-8")) == before
    assert report.manifest_drift is True
    assert report.missing_from_manifest == ("beta",)
    assert report.manifest_only == ("manifest-only",)


def test_scan_excludes_generated_cache_files_from_hashes(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "cache-demo"
    cache_dir = skill_dir / "scripts" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: cache-demo\ndescription: Cache demo.\n---\n# Cache Demo\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "helper.py").write_text("print('ok')\n", encoding="utf-8")
    (cache_dir / "helper.cpython-311.pyc").write_bytes(b"compiled")
    (skills_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "generated_at": "2026-06-09T00:00:00Z",
                "skills_dir": "skills",
                "skills": [
                    {
                        "name": "cache-demo",
                        "path": "skills/cache-demo",
                        "skill_md": "skills/cache-demo/SKILL.md",
                        "description": "Cache demo.",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    record = scan_skill_provenance(tmp_path).records[0]

    assert "scripts/helper.py" in record.sidecar_files
    assert "scripts/helper.py" in record.content_hashes
    assert record.excluded_generated_files == (
        "scripts/__pycache__/helper.cpython-311.pyc",
    )
    assert "scripts/__pycache__/helper.cpython-311.pyc" not in record.content_hashes
