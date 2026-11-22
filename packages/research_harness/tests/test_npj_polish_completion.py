"""Synthetic source-behavior repros: incomplete review is not a clean result."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import research_harness.primitives.polish_impls as polish
from research_harness._workflow.execution import finish_form_contract, style_fingerprint
from research_harness.primitives import writing_impls

TEXT = "## Methods\nWe evaluated the method using held-out examples and reported uncertainty."
SECRET = "synthetic-provider-secret"


@pytest.fixture
def clean_review(monkeypatch):
    calls = []

    def chat(*args):
        calls.append(args)
        return '{"findings": []}'

    monkeypatch.setattr(polish, "_chat", chat)
    monkeypatch.setattr(
        writing_impls,
        "section_review",
        lambda **kw: SimpleNamespace(deterministic_checks=[]),
    )
    monkeypatch.setattr(
        style_fingerprint, "style_fingerprint_findings", lambda text: []
    )
    monkeypatch.setattr(finish_form_contract, "finish_form_findings", lambda text: [])
    monkeypatch.setattr(
        finish_form_contract, "ablation_contract_findings", lambda payload: []
    )
    return calls


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not JSON " + SECRET,
        "{}",
        "[]",
        '{"findings": null}',
        '{"findings": {}}',
        '{"findings": ""}',
        '{"findings": [null]}',
        '{"findings": [{}]}',
        '{"findings": []',
        '{"findings": [{"severity":"low","location":"Methods","issue":"ok","fix":"ok"},',
        json.dumps(
            {
                "findings": [
                    {
                        "severity": "critical",
                        "location": "",
                        "issue": "problem",
                        "fix": "fix",
                    }
                ]
            }
        ),
        json.dumps(
            {
                "findings": [
                    {"severity": "low", "location": "", "issue": " ", "fix": "fix"}
                ]
            }
        ),
        json.dumps(
            {
                "findings": [
                    {
                        "severity": "low",
                        "location": "",
                        "issue": {"secret": SECRET},
                        "fix": "fix",
                    }
                ]
            }
        ),
        json.dumps(
            {
                "findings": [
                    {"severity": "low", "location": "", "issue": "problem", "fix": None}
                ]
            }
        ),
    ],
)
def test_invalid_angle_response_fails_closed(monkeypatch, bad, clean_review):
    monkeypatch.setattr(polish, "_chat", lambda *a: bad)
    with pytest.raises(RuntimeError, match="manuscript_review") as caught:
        polish.manuscript_review(manuscript=TEXT)
    assert caught.value.__cause__ is not None
    assert SECRET not in str(caught.value)
    assert len(str(caught.value)) < 200


@pytest.mark.parametrize("failed_angle", range(3))
@pytest.mark.parametrize("entry", [polish.manuscript_review, polish.manuscript_polish])
def test_any_required_angle_failure_aborts(
    monkeypatch, clean_review, failed_angle, entry
):
    failure = TimeoutError(SECRET)
    responses = iter([None] * failed_angle + [failure])

    def chat(*a):
        value = next(responses)
        if value is failure:
            raise failure
        return '{"findings": []}'

    monkeypatch.setattr(polish, "_chat", chat)
    with pytest.raises(RuntimeError, match=polish._ANGLES[failed_angle]) as caught:
        entry(manuscript=TEXT)
    assert caught.value.__cause__ is failure
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("angles", [["domain", "unknown"], ["unknown"]])
def test_unsupported_required_angle_cannot_be_dropped(clean_review, angles):
    with pytest.raises(RuntimeError, match="manuscript_review"):
        polish.manuscript_review(manuscript=TEXT, angles=angles)
    assert clean_review == []


def test_selected_known_angle_completes(clean_review):
    out = polish.manuscript_review(manuscript=TEXT, angles=["editorial"])
    assert out.angles == ["editorial"]
    assert len(clean_review) == 1


@pytest.mark.parametrize("fenced", [False, True])
def test_complete_empty_review_remains_ready(monkeypatch, clean_review, fenced):
    if fenced:
        monkeypatch.setattr(
            polish, "_chat", lambda *a: '```json\n{"findings": []}\n```'
        )
    out = polish.manuscript_polish(manuscript=TEXT)
    assert out.submission_readiness == "ready"
    assert out.findings == []
    assert set(out.checks_run) == {
        "manuscript_review",
        "section_review(deterministic)",
        "style_fingerprint",
        "finish_form_contract",
    }
    if not fenced:
        assert len(clean_review) == 3


@pytest.mark.parametrize(
    "severity,readiness",
    [("low", "ready"), ("medium", "needs_revision"), ("high", "blocked")],
)
def test_completed_findings_keep_verdicts(
    monkeypatch, clean_review, severity, readiness
):
    monkeypatch.setattr(
        polish,
        "_chat",
        lambda *a: json.dumps(
            {
                "findings": [
                    {
                        "severity": severity,
                        "location": "Methods",
                        "issue": "explain uncertainty",
                        "fix": "report intervals",
                    }
                ]
            }
        ),
    )
    out = polish.manuscript_polish(manuscript=TEXT)
    assert out.submission_readiness == readiness
    assert len(out.findings) == 3


@pytest.mark.parametrize(
    "check",
    [
        "section_review",
        "style_fingerprint_findings",
        "finish_form_findings",
        "ablation_contract_findings",
        "consistency_check",
        "source_fidelity_audit",
    ],
)
def test_enabled_check_exception_is_not_ready(monkeypatch, clean_review, check):
    import research_harness.execution.llm_primitives as lp

    module = {
        "section_review": writing_impls,
        "style_fingerprint_findings": style_fingerprint,
        "finish_form_findings": finish_form_contract,
        "ablation_contract_findings": finish_form_contract,
        "consistency_check": lp,
        "source_fidelity_audit": polish,
    }[check]
    failure = OSError(SECRET)

    def boom(*a, **kw):
        raise failure

    monkeypatch.setattr(module, check, boom)
    kwargs = {}
    if check == "consistency_check":
        kwargs.update(db=object(), topic_id=1)
    if check == "ablation_contract_findings":
        kwargs["ablation_payload"] = {"planned": []}
    if check == "source_fidelity_audit":
        kwargs["composition_contract"] = {"allowed_citation_keys": []}
    with pytest.raises(RuntimeError, match="manuscript_polish") as caught:
        polish.manuscript_polish(manuscript=TEXT, **kwargs)
    assert caught.value.__cause__ is failure
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("command", ["review", "run"])
@pytest.mark.parametrize("failure_kind", ["timeout", "invalid_json"])
def test_public_cli_failure_is_nonzero_and_records_no_report(
    monkeypatch, tmp_path, db, command, failure_kind
):
    from research_harness.cli import main
    from research_harness.orchestrator import OrchestratorService

    manuscript = tmp_path / "manuscript.md"
    manuscript.write_text(TEXT)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.path))
    recorded = []

    def record(*a, **kw):
        recorded.append(kw)
        return SimpleNamespace(id=1, version=1)

    monkeypatch.setattr(OrchestratorService, "record_artifact", record)

    def boom(*a):
        if failure_kind == "invalid_json":
            return "invalid JSON " + SECRET
        raise TimeoutError(SECRET)

    monkeypatch.setattr(polish, "_chat", boom)
    args = ["polish", command, "--manuscript-file", str(manuscript)]
    if command == "run":
        args += ["--topic", "1", "--json", "--no-consistency", "--no-deterministic"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0
    assert "did not complete" in result.output.lower()
    assert SECRET not in result.output
    assert "ready" not in result.output.lower()
    assert recorded == []


@pytest.mark.parametrize("command", ["manuscript_review", "manuscript_polish"])
@pytest.mark.parametrize("failure_kind", ["exception", "invalid_json"])
def test_public_service_backend_returns_failure_envelope(
    monkeypatch, db, command, failure_kind
):
    from research_harness.service import ResearchService
    from research_harness.execution import harness

    monkeypatch.setattr(
        harness,
        "resolve_llm_config",
        lambda: SimpleNamespace(
            provider="offline", model="offline", api_key="synthetic-unused"
        ),
    )

    def boom(*a):
        if failure_kind == "invalid_json":
            return "invalid JSON " + SECRET
        raise RuntimeError(SECRET)

    monkeypatch.setattr(polish, "_chat", boom)
    result = ResearchService(db=db).invoke(command, {"manuscript": TEXT})
    assert result.status == "error"
    assert result.error["code"] == "PRIMITIVE_FAILED"
    assert "manuscript_review" in result.error["message"]
    assert SECRET not in result.error["message"]
    assert result.output is None
    assert not result.artifacts


@pytest.mark.parametrize(
    "response", ['{"findings": []', '{"findings": [{"severity":"low"}]}']
)
def test_late_malformed_angle_discards_partial_findings(
    monkeypatch, clean_review, response
):
    responses = iter(['{"findings": []}', response])
    monkeypatch.setattr(polish, "_chat", lambda *a: next(responses))
    with pytest.raises(RuntimeError, match="angle domain"):
        polish.manuscript_polish(manuscript=TEXT)


@pytest.mark.parametrize(
    "severity,readiness", [(None, "ready"), ("medium", "needs_revision")]
)
def test_public_cli_records_only_completed_report(
    monkeypatch, tmp_path, db, severity, readiness
):
    from research_harness.cli import main
    from research_harness.orchestrator import OrchestratorService

    manuscript = tmp_path / "manuscript.md"
    manuscript.write_text(TEXT)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.path))
    findings = (
        []
        if severity is None
        else [
            {
                "severity": severity,
                "location": "Methods",
                "issue": "report uncertainty",
                "fix": "add intervals",
            }
        ]
    )
    calls = []
    recorded = []

    def chat(*a):
        calls.append(a)
        return json.dumps({"findings": findings})

    def record(*a, **kw):
        recorded.append(kw)
        return SimpleNamespace(id=1, version=1)

    monkeypatch.setattr(polish, "_chat", chat)
    monkeypatch.setattr(OrchestratorService, "record_artifact", record)
    result = CliRunner().invoke(
        main,
        [
            "polish",
            "run",
            "--manuscript-file",
            str(manuscript),
            "--topic",
            "1",
            "--no-consistency",
            "--no-deterministic",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 3
    assert len(recorded) == 1
    assert recorded[0]["artifact_type"] == "manuscript_polish_report"
    assert recorded[0]["payload"]["submission_readiness"] == readiness


def test_public_cli_enabled_check_failure_records_no_report(
    monkeypatch, clean_review, tmp_path, db
):
    from research_harness.cli import main
    from research_harness.orchestrator import OrchestratorService

    manuscript = tmp_path / "manuscript.md"
    manuscript.write_text(TEXT)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.path))
    recorded = []
    monkeypatch.setattr(
        OrchestratorService, "record_artifact", lambda *a, **kw: recorded.append(kw)
    )

    def boom(*a):
        raise OSError(SECRET)

    monkeypatch.setattr(finish_form_contract, "finish_form_findings", boom)
    result = CliRunner().invoke(
        main,
        [
            "polish",
            "run",
            "--manuscript-file",
            str(manuscript),
            "--topic",
            "1",
            "--no-consistency",
        ],
    )
    assert len(clean_review) == 3
    assert result.exit_code != 0
    assert "did not complete" in result.output.lower()
    assert SECRET not in result.output
    assert recorded == []
