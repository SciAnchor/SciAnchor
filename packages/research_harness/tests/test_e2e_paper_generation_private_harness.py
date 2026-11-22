from __future__ import annotations

import io
import json
from pathlib import Path

from research_harness._selfdev.e2e_paper_generation import (
    main,
    run_e2e_paper_generation_replay_harness,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "writing" / "e2e_paper_generation_dataset.json"
)


def test_private_harness_returns_json_safe_payload() -> None:
    payload = run_e2e_paper_generation_replay_harness(dataset_path=FIXTURE)

    assert payload["schema_version"] == "rh.e2e_paper_generation_replay_report.v1"
    assert payload["status"] == "pass"
    assert payload["decision"] == "ready_for_private_replay"
    assert payload["eval_report"]["summary"]["failed_grader_names"] == []
    json.dumps(payload, sort_keys=True)


def test_private_harness_main_prints_json_and_returns_zero() -> None:
    stdout = io.StringIO()

    exit_code = main(["--dataset", str(FIXTURE)], stdout=stdout)
    payload = json.loads(stdout.getvalue())

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["decision"] == "ready_for_private_replay"


def test_private_harness_main_returns_nonzero_for_failed_eval(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["evidence_inventory"] = {
        **payload["cases"][0]["evidence_inventory"],
        "source_artifacts": [],
    }
    path = tmp_path / "source-drift.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stdout = io.StringIO()

    exit_code = main(["--dataset", str(path)], stdout=stdout)
    report = json.loads(stdout.getvalue())

    assert exit_code == 1
    assert report["status"] == "fail"
    assert report["decision"] == "blocked_by_private_eval"
    assert "failed_grader:evidence_bound_claims" in report["blockers"]
