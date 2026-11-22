from __future__ import annotations

import json
from pathlib import Path

from research_harness._selfdev.e2e_paper_generation import (
    E2E_PAPER_GENERATION_REPLAY_REPORT_SCHEMA_VERSION,
    build_default_e2e_paper_generation_replay_report,
    build_e2e_paper_generation_replay_report,
    load_e2e_paper_generation_dataset,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "writing" / "e2e_paper_generation_dataset.json"
)


def test_default_replay_report_is_json_safe_and_passing() -> None:
    report = build_default_e2e_paper_generation_replay_report()
    payload = report.to_dict()

    assert report.schema_version == E2E_PAPER_GENERATION_REPLAY_REPORT_SCHEMA_VERSION
    assert report.status == "pass"
    assert report.decision == "ready_for_private_replay"
    assert report.blockers == ()
    assert "LG78E_PRIVATE_REPLAY_HARNESS" in report.next_actions
    assert payload["readiness_summary"]["status"] == "ready_for_private_eval"
    assert payload["eval_report"]["status"] == "pass"

    # The report is intended to be directly recordable as a local JSON artifact.
    json.dumps(payload, sort_keys=True)


def test_replay_report_surfaces_eval_failures(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["evidence_inventory"] = {
        **payload["cases"][0]["evidence_inventory"],
        "claim_ids": [],
    }
    path = tmp_path / "claim-drift.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_e2e_paper_generation_replay_report(
        load_e2e_paper_generation_dataset(path)
    )

    assert report.status == "fail"
    assert report.decision == "blocked_by_private_eval"
    assert "failed_grader:evidence_bound_claims" in report.blockers
    assert "repair_failing_fixture_or_grader" in report.next_actions
    assert report.to_dict()["eval_report"]["summary"]["failed_grader_names"] == [
        "evidence_bound_claims"
    ]
