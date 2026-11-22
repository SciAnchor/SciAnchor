from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "scripts").exists() and (p / "AGENTS.md").exists()
)
SCRIPT = REPO_ROOT / "scripts" / "rh-supervised-paper-e2e.py"


def load_harness_module():
    spec = importlib.util.spec_from_file_location("rh_supervised_paper_e2e", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pdf_quality_rejects_one_page_demo_fixture(tmp_path: Path) -> None:
    module = load_harness_module()
    paths = module.build_paths(tmp_path / "run")
    module.ensure_run_dirs(paths)
    demo_text = """\\documentclass{article}
\\begin{document}
\\section{Abstract}
This bounded demo manuscript is a smoke-test artifact and is not submission ready.
\\section{Method}
Tiny method.
\\end{document}
"""
    (paths.final_dir / "paper.tex").write_text(demo_text, encoding="utf-8")
    (paths.final_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")

    original_extract = module.extract_pdf_text
    module.extract_pdf_text = lambda _pdf_path: (1, demo_text, "")
    try:
        report = module.evaluate_pdf_quality(
            paths,
            module.QualityThresholds(
                min_pages=2,
                min_words=500,
                min_references=2,
                min_citation_markers=2,
            ),
        )
    finally:
        module.extract_pdf_text = original_extract

    assert report["status"] == "fail"
    assert any("pdf_pages_below_min" in item for item in report["blockers"])
    assert any("demo_or_smoke_markers_present" in item for item in report["blockers"])


def test_gold_alignment_reports_missing_rh_artifacts(tmp_path: Path) -> None:
    module = load_harness_module()
    dataset, case = module.load_case(module.DEFAULT_DATASET, "first_positive")
    paths = module.build_paths(tmp_path / "run")
    module.ensure_run_dirs(paths)

    report = module.evaluate_gold_alignment(dataset=dataset, case=case, paths=paths)

    assert report["status"] == "fail"
    assert "missing_rh_action_log" in report["blockers"]
    assert report["missing_required_artifacts"]
    assert report["missing_required_control_artifacts"]


def test_self_dev_outputs_include_integrated_protocol_gap(tmp_path: Path) -> None:
    module = load_harness_module()
    paths = module.build_paths(tmp_path / "run")
    module.ensure_run_dirs(paths)
    deficiencies = [
        module.Deficiency(
            category="integrated_protocol_capability_not_invoked",
            severity="major",
            summary="Missing RESULT_TO_CLAIM_ANALYSIS_PROFILE.",
            evidence={"missing": "RESULT_TO_CLAIM_ANALYSIS_PROFILE"},
            suggested_owner="rh_gate",
            suggested_regression="required control artifact must be observed",
        )
    ]

    payload = module.write_self_dev_outputs(paths, deficiencies)

    assert payload["status"] == "needs_self_dev"
    assert payload["candidate_count"] == 1
    assert (paths.run_dir / "self-dev-candidates.json").exists()
    md = (paths.run_dir / "self-dev-candidates.md").read_text(encoding="utf-8")
    assert "integrated_protocol_capability_not_invoked" in md


def test_worker_prompt_requires_early_ledger_and_bounded_execution(
    tmp_path: Path,
) -> None:
    module = load_harness_module()
    dataset, case = module.load_case(
        module.DEFAULT_DATASET, "stem_event_forecasting_full_chain"
    )
    paths = module.build_paths(tmp_path / "run")
    module.ensure_run_dirs(paths)
    config = module.HarnessConfig(
        repo_root=REPO_ROOT,
        run_root=tmp_path,
        dataset_path=module.DEFAULT_DATASET,
        case_id="stem_event_forecasting_full_chain",
        topic="fake topic",
        target_venue="ICLR",
        task_id="fake-task",
        codex_bin="codex",
        max_rounds=1,
        worker_timeout=30,
        supervisor_timeout=30,
        thresholds=module.QualityThresholds(),
    )
    task = module.task_payload(config, dataset, case)

    prompt = module.build_worker_prompt(
        config=config,
        paths=paths,
        round_index=1,
        task=task,
        feedback_path=None,
    )

    assert "First 10 minutes" in prompt
    assert "codex-decision-log.jsonl" in prompt
    assert "actions.jsonl" in prompt
    assert ".venv/bin/rh" in prompt
    assert "--db" in prompt
    assert "Do not spend the run browsing repository source" in prompt
    assert "run-specific generator" in prompt
    assert "preseeded candidate bundle" in prompt
    assert "Do not recreate the generator" in prompt


def test_initial_candidate_bundle_satisfies_mechanical_and_gold_gates(
    tmp_path: Path,
) -> None:
    module = load_harness_module()
    dataset, case = module.load_case(
        module.DEFAULT_DATASET, "stem_event_forecasting_full_chain"
    )
    paths = module.build_paths(tmp_path / "run")
    module.ensure_run_dirs(paths)
    config = module.HarnessConfig(
        repo_root=REPO_ROOT,
        run_root=tmp_path,
        dataset_path=module.DEFAULT_DATASET,
        case_id="stem_event_forecasting_full_chain",
        topic="fake topic",
        target_venue="ICLR",
        task_id="fake-task",
        codex_bin="codex",
        max_rounds=1,
        worker_timeout=30,
        supervisor_timeout=30,
        thresholds=module.QualityThresholds(),
    )
    task = module.task_payload(config, dataset, case)

    module.seed_initial_candidate_bundle(
        config=config,
        paths=paths,
        dataset=dataset,
        case=case,
        task=task,
    )

    pdf_report = module.evaluate_pdf_quality(paths, config.thresholds)
    gold_report = module.evaluate_gold_alignment(
        dataset=dataset, case=case, paths=paths
    )

    assert pdf_report["status"] == "pass"
    assert pdf_report["metrics"]["pages"] >= config.thresholds.min_pages
    assert pdf_report["metrics"]["words"] >= config.thresholds.min_words
    assert gold_report["status"] == "pass"
    assert (paths.worker_dir / "artifacts" / "seed_candidate_generator.py").exists()
    assert (paths.worker_dir / "worker-summary-round-001.json").exists()


def test_harness_runs_fake_codex_pass_loop(tmp_path: Path) -> None:
    module = load_harness_module()
    fake_codex = tmp_path / "fake-codex.py"
    fake_codex.write_text(
        f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv
out = pathlib.Path(args[args.index('-o') + 1])
prompt = sys.stdin.read()
run_dir = pathlib.Path({str(tmp_path / "runs" / "fake-task")!r})
final_dir = run_dir / 'final'
worker_dir = run_dir / 'worker'
rh_dir = run_dir / 'rh'
supervisor_dir = run_dir / 'supervisor'
for p in (final_dir, worker_dir, rh_dir, supervisor_dir):
    p.mkdir(parents=True, exist_ok=True)
if 'independent Supervisor Codex' in prompt:
    verdict = {{
        'schema_version': 'rh.supervised_paper_e2e_supervisor_verdict.v1',
        'round': 1,
        'verdict': 'pass',
        'allowed_next_action': 'accept_final',
        'summary': 'accepted',
        'critical_issues': [],
        'major_issues': [],
        'minor_issues': [],
        'required_repairs': [],
        'gold_alignment': {{'status': 'pass', 'missing_requirements': []}},
        'rh_improvement_candidates': []
    }}
    (supervisor_dir / 'verdict-round-001.json').write_text(json.dumps(verdict))
    out.write_text(json.dumps(verdict))
else:
    body = ' '.join(['word'] * 140)
    tex = r'''\\documentclass{{article}}
\\begin{{document}}
\\section{{Abstract}} ''' + body + r'''
\\section{{Introduction}} ''' + body + r'''
\\section{{Related Work}} \\cite{{a,b,c}} ''' + body + r'''
\\section{{Method}} Table 1 summarizes the approach. ''' + body + r'''
\\section{{Evaluation}} ''' + body + r'''
\\section{{Results}} Figure 1 shows the result. ''' + body + r'''
\\section{{Limitations}} ''' + body + r'''
\\section{{Conclusion}} ''' + body + r'''
\\section{{References}}
[1] A. Author. Title. doi:10.1/a
[2] B. Author. Title. doi:10.1/b
[3] C. Author. Title. https://example.com/c
\\end{{document}}
'''
    (final_dir / 'paper.tex').write_text(tex)
    (final_dir / 'paper.pdf').write_bytes(b'%PDF-1.4 fake')
    (worker_dir / 'worker-summary-round-001.json').write_text(json.dumps({{'status':'done'}}))
    required = json.loads((run_dir / 'task.json').read_text())['dataset']
    artifacts = {{name: {{'artifact_id': name}} for name in required['required_artifacts']}}
    controls = {{name: {{'artifact_id': name}} for name in required['required_control_artifacts']}}
    (rh_dir / 'artifact-map.json').write_text(json.dumps({{'artifacts': artifacts, 'control_artifacts': controls}}))
    with (rh_dir / 'actions.jsonl').open('w') as f:
        for name in list(artifacts) + list(controls):
            f.write(json.dumps({{'artifact_type': name}}) + '\\n')
    out.write_text('worker done')
print(json.dumps({{'event':'done'}}))
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    config = module.HarnessConfig(
        repo_root=REPO_ROOT,
        run_root=tmp_path / "runs",
        dataset_path=module.DEFAULT_DATASET,
        case_id="stem_event_forecasting_full_chain",
        topic="fake topic",
        target_venue="ICLR",
        task_id="fake-task",
        codex_bin=str(fake_codex),
        max_rounds=1,
        worker_timeout=30,
        supervisor_timeout=30,
        thresholds=module.QualityThresholds(
            min_pages=0,
            min_words=100,
            min_references=3,
            min_citation_markers=1,
        ),
    )

    def fake_extract_pdf_text(_pdf_path):
        text = (tmp_path / "runs/fake-task/final/paper.tex").read_text()
        return 8, text, ""

    original_extract = module.extract_pdf_text
    module.extract_pdf_text = fake_extract_pdf_text
    try:
        final = module.run_harness(config)
    finally:
        module.extract_pdf_text = original_extract

    assert final["status"] == "completed_final_candidate"
    assert final["pdf_quality_status"] == "pass"
    assert final["gold_eval_status"] == "pass"


def test_harness_terminates_hanging_worker_after_artifacts_are_complete(
    tmp_path: Path,
) -> None:
    module = load_harness_module()
    fake_codex = tmp_path / "fake-codex-hangs.py"
    fake_codex.write_text(
        f"""#!/usr/bin/env python3
import json, pathlib, sys, time
args = sys.argv
out = pathlib.Path(args[args.index('-o') + 1])
prompt = sys.stdin.read()
run_dir = pathlib.Path({str(tmp_path / "runs" / "hanging-task")!r})
final_dir = run_dir / 'final'
worker_dir = run_dir / 'worker'
rh_dir = run_dir / 'rh'
supervisor_dir = run_dir / 'supervisor'
for p in (final_dir, worker_dir, rh_dir, supervisor_dir):
    p.mkdir(parents=True, exist_ok=True)
if 'independent Supervisor Codex' in prompt:
    verdict = {{
        'schema_version': 'rh.supervised_paper_e2e_supervisor_verdict.v1',
        'round': 1,
        'verdict': 'pass',
        'allowed_next_action': 'accept_final',
        'summary': 'accepted',
        'critical_issues': [],
        'major_issues': [],
        'minor_issues': [],
        'required_repairs': [],
        'gold_alignment': {{'status': 'pass', 'missing_requirements': []}},
        'rh_improvement_candidates': []
    }}
    (supervisor_dir / 'verdict-round-001.json').write_text(json.dumps(verdict))
    out.write_text(json.dumps(verdict))
    print(json.dumps({{'event': 'supervisor_done'}}), flush=True)
    raise SystemExit(0)

body = ' '.join(['word'] * 140)
tex = r'''\\documentclass{{article}}
\\begin{{document}}
\\section{{Abstract}} ''' + body + r'''
\\section{{Introduction}} ''' + body + r'''
\\section{{Related Work}} \\cite{{a,b,c}} ''' + body + r'''
\\section{{Method}} Table 1 summarizes the approach. ''' + body + r'''
\\section{{Evaluation}} ''' + body + r'''
\\section{{Results}} Figure 1 shows the result. ''' + body + r'''
\\section{{Limitations}} ''' + body + r'''
\\section{{Conclusion}} ''' + body + r'''
\\section{{References}}
[1] A. Author. Title. doi:10.1/a
[2] B. Author. Title. doi:10.1/b
[3] C. Author. Title. https://example.com/c
\\end{{document}}
'''
(final_dir / 'paper.tex').write_text(tex)
(final_dir / 'paper.pdf').write_bytes(b'%PDF-1.4 fake')
(worker_dir / 'worker-summary-round-001.json').write_text(json.dumps({{'status': 'done'}}))
(worker_dir / 'codex-decision-log.jsonl').write_text(json.dumps({{'phase': 'worker', 'decision': 'done'}}) + '\\n')
required = json.loads((run_dir / 'task.json').read_text())['dataset']
artifacts = {{name: {{'artifact_id': name}} for name in required['required_artifacts']}}
controls = {{name: {{'artifact_id': name}} for name in required['required_control_artifacts']}}
(rh_dir / 'artifact-map.json').write_text(json.dumps({{'artifacts': artifacts, 'control_artifacts': controls}}))
with (rh_dir / 'actions.jsonl').open('w') as f:
    for name in list(artifacts) + list(controls):
        f.write(json.dumps({{'surface': 'rh_python', 'artifact_type': name, 'status': 'success'}}) + '\\n')
out.write_text('worker produced artifacts but did not exit')
print(json.dumps({{'event': 'worker_artifacts_written'}}), flush=True)
time.sleep(60)
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    config = module.HarnessConfig(
        repo_root=REPO_ROOT,
        run_root=tmp_path / "runs",
        dataset_path=module.DEFAULT_DATASET,
        case_id="stem_event_forecasting_full_chain",
        topic="fake topic",
        target_venue="ICLR",
        task_id="hanging-task",
        codex_bin=str(fake_codex),
        max_rounds=1,
        worker_timeout=30,
        supervisor_timeout=30,
        thresholds=module.QualityThresholds(
            min_pages=0,
            min_words=100,
            min_references=3,
            min_citation_markers=1,
        ),
        artifact_quiescence_seconds=0.05,
        process_poll_interval_seconds=0.02,
    )

    def fake_extract_pdf_text(_pdf_path):
        text = (tmp_path / "runs/hanging-task/final/paper.tex").read_text()
        return 8, text, ""

    original_extract = module.extract_pdf_text
    module.extract_pdf_text = fake_extract_pdf_text
    try:
        final = module.run_harness(config)
    finally:
        module.extract_pdf_text = original_extract

    assert final["status"] == "completed_final_candidate"
    assert final["worker_status"]["artifact_completion_terminated"] is True
    assert final["worker_status"]["timeout"] is False


def test_harness_does_not_accept_seed_when_worker_only_updates_ledgers(
    tmp_path: Path,
) -> None:
    module = load_harness_module()
    fake_codex = tmp_path / "fake-codex-ledger-only.py"
    fake_codex.write_text(
        f"""#!/usr/bin/env python3
import json, pathlib, sys, time
args = sys.argv
out = pathlib.Path(args[args.index('-o') + 1])
prompt = sys.stdin.read()
run_dir = pathlib.Path({str(tmp_path / "runs" / "ledger-only-task")!r})
worker_dir = run_dir / 'worker'
rh_dir = run_dir / 'rh'
supervisor_dir = run_dir / 'supervisor'
for p in (worker_dir, rh_dir, supervisor_dir):
    p.mkdir(parents=True, exist_ok=True)
if 'independent Supervisor Codex' in prompt:
    verdict = {{
        'schema_version': 'rh.supervised_paper_e2e_supervisor_verdict.v1',
        'round': 1,
        'verdict': 'pass',
        'allowed_next_action': 'accept_final',
        'summary': 'accepted',
        'critical_issues': [],
        'major_issues': [],
        'minor_issues': [],
        'required_repairs': [],
        'gold_alignment': {{'status': 'pass', 'missing_requirements': []}},
        'rh_improvement_candidates': []
    }}
    (supervisor_dir / 'verdict-round-001.json').write_text(json.dumps(verdict))
    out.write_text(json.dumps(verdict))
    raise SystemExit(0)
(worker_dir / 'codex-decision-log.jsonl').write_text(json.dumps({{'phase': 'worker', 'decision': 'ledger_only'}}) + '\\n')
with (rh_dir / 'actions.jsonl').open('a') as f:
    f.write(json.dumps({{'surface': 'rh_cli', 'action': 'topic_init', 'status': 'success'}}) + '\\n')
out.write_text('worker only updated logs')
print(json.dumps({{'event': 'ledger_only'}}), flush=True)
time.sleep(60)
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    config = module.HarnessConfig(
        repo_root=REPO_ROOT,
        run_root=tmp_path / "runs",
        dataset_path=module.DEFAULT_DATASET,
        case_id="stem_event_forecasting_full_chain",
        topic="fake topic",
        target_venue="ICLR",
        task_id="ledger-only-task",
        codex_bin=str(fake_codex),
        max_rounds=1,
        worker_timeout=1,
        supervisor_timeout=30,
        thresholds=module.QualityThresholds(),
        artifact_quiescence_seconds=0.01,
        process_poll_interval_seconds=0.01,
    )

    final = module.run_harness(config)

    assert final["status"] == "needs_repair_or_blocked"
    assert final["worker_status"]["timeout"] is True
    assert final["worker_succeeded"] is False
    assert "worker_did_not_complete" in final["blockers"]


def test_rh_cli_failures_and_fallbacks_become_self_dev_candidates(
    tmp_path: Path,
) -> None:
    module = load_harness_module()
    paths = module.build_paths(tmp_path / "run")
    module.ensure_run_dirs(paths)
    (paths.rh_dir / "actions.jsonl").write_text(
        "\n".join(
            [
                json_line
                for json_line in (
                    '{"surface":"rh_cli","action":"topic_init","status":"failed","details":{"reason":"schema_migrations UNIQUE constraint"}}',
                    '{"surface":"codex_fallback","action":"fallback_to_path_backed_artifacts","status":"active","details":{"reason":"RH CLI unavailable"}}',
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    deficiencies = module.deficiencies_from_rh_actions(paths)

    assert [item.category for item in deficiencies] == [
        "rh_tool_routing_gap",
        "rh_artifact_lineage_gap",
    ]
    assert "topic_init" in deficiencies[0].summary
    assert "path-backed" in deficiencies[1].summary
