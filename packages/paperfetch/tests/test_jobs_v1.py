"""SPC 1.0 detached job 生命周期与业务结果契约。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from paperfetch import jobs
from paperfetch.core.contracts_v1 import JobLifecycle
from paperfetch.observability import write_output
from paperfetch.cli.root import main as cli_main


pytestmark = [pytest.mark.unit, pytest.mark.contract]


@pytest.mark.skipif(os.name == "nt", reason="Linux /proc process-state contract")
def test_job_pid_alive_treats_linux_zombie_as_exited(monkeypatch):
    class ZombieStat:
        def read_text(self, **_kwargs):
            return "4321 (python) Z 1 4321 4321 0"

    monkeypatch.setattr(jobs, "Path", lambda _value: ZombieStat())
    monkeypatch.setattr(
        jobs.os, "kill", lambda *_args: pytest.fail("zombie must not be probed")
    )

    assert jobs._pid_alive(4321) is False


class _FakeProcess:
    pid = 4321


def _detach(monkeypatch, tmp_path: Path) -> dict:
    monkeypatch.setenv("SPC_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setattr(
        jobs.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess()
    )
    return jobs.detach(
        [
            "paper",
            "lookup",
            "--doi",
            "10.1000/example",
            "--detach",
            "--output-format",
            "json",
        ],
        cwd=str(tmp_path),
    )


def test_detach_persists_only_lifecycle_command_event_and_log_contract(
    monkeypatch, tmp_path
):
    state = _detach(monkeypatch, tmp_path)
    directory = tmp_path / "jobs" / state["job_id"]

    assert state["schema_version"] == "spc.job.v1"
    assert state["lifecycle"] == "queued"
    assert Path(state["command_ref"]).name == "command.json"
    assert Path(state["event_ref"]).name == "events.jsonl"
    assert Path(state["stderr_ref"]).name == "stderr.log"
    assert state["result_ref"] is None
    assert (directory / "command.json").is_file()
    assert not (directory / "stdout.txt").exists()
    assert "business_summary" not in state
    command = json.loads((directory / "command.json").read_text(encoding="utf-8"))
    assert "--output-format" in command["argv"]
    assert "--no-progress" in command["argv"]


def test_linux_worker_has_an_independent_process_group(monkeypatch, tmp_path):
    if jobs.os.name == "nt":
        pytest.skip("Linux process-group contract")
    captured = {}
    monkeypatch.setenv("SPC_JOB_ROOT", str(tmp_path / "jobs"))

    def fake_popen(_argv, **kwargs):
        captured.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(jobs.subprocess, "Popen", fake_popen)
    jobs.detach(
        ["paper", "lookup", "--doi", "10.1000/example", "--detach"], cwd=str(tmp_path)
    )
    assert captured["start_new_session"] is True


def test_all_long_paper_commands_can_detach(monkeypatch, tmp_path):
    monkeypatch.setenv("SPC_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setattr(
        jobs.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess()
    )
    state = jobs.detach(
        [
            "paper",
            "parse",
            "--pdf",
            "/tmp/a.pdf",
            "--output-dir",
            "/tmp/out",
            "--detach",
        ],
        cwd=str(tmp_path),
    )
    command = json.loads(Path(state["command_ref"]).read_text(encoding="utf-8"))
    assert command["command"] == "paper.parse"
    search = jobs.detach(
        ["paper", "search", "--query", "climate", "--detach"],
        cwd=str(tmp_path),
    )
    assert (
        json.loads(Path(search["command_ref"]).read_text(encoding="utf-8"))["command"]
        == "paper.search"
    )
    graph = jobs.detach(
        ["paper", "graph", "--doi", "10.1000/x", "--detach"],
        cwd=str(tmp_path),
    )
    assert (
        json.loads(Path(graph["command_ref"]).read_text(encoding="utf-8"))["command"]
        == "paper.graph"
    )
    download = jobs.detach(
        [
            "paper",
            "download",
            "--doi",
            "10.1000/x",
            "--output-dir",
            "/tmp/out",
            "--detach",
        ],
        cwd=str(tmp_path),
    )
    assert (
        json.loads(Path(download["command_ref"]).read_text(encoding="utf-8"))["command"]
        == "paper.download"
    )


def test_worker_captures_one_business_object_without_reading_stdout(
    monkeypatch, tmp_path
):
    state = _detach(monkeypatch, tmp_path)

    def fake_run(_argv):
        write_output(
            {
                "schema_version": "spc.lookup-result.v0",
                "doi": "10.1000/example",
                "status": "completed",
            }
        )
        return 0

    monkeypatch.setattr("paperfetch.cli.run", fake_run)
    assert jobs._worker(state["job_id"]) == 0

    terminal = jobs.result(state["job_id"])
    watched = jobs.read_job(state["job_id"], refresh=False)
    assert terminal["schema_version"] == "spc.command-result.v1"
    assert terminal["status"] == "completed"
    assert terminal["job_id"] == state["job_id"]
    assert terminal["items"][0]["data"]["legacy_output"]["doi"] == "10.1000/example"
    assert watched["lifecycle"] == "finished"
    assert Path(watched["result_ref"]).is_file()
    public = jobs.wait(state["job_id"], timeout_seconds=0)
    assert public["schema"] == "spc.result.v2"
    assert public["status"] == "completed"
    assert public["job_id"] == state["job_id"]


def test_business_failure_finishes_job_and_preserves_business_failure(
    monkeypatch, tmp_path
):
    state = _detach(monkeypatch, tmp_path)

    def fake_run(_argv):
        write_output(
            {
                "status": "failed",
                "error": {
                    "error_code": "publisher_challenge",
                    "error_class": "access_blocked",
                    "stage": "transfer",
                    "message": "出版社返回挑战页",
                },
            }
        )
        return 2

    monkeypatch.setattr("paperfetch.cli.run", fake_run)
    assert jobs._worker(state["job_id"]) == 2

    terminal = jobs.result(state["job_id"])
    lifecycle = jobs.read_job(state["job_id"], refresh=False)
    assert lifecycle["lifecycle"] == "finished"
    assert lifecycle["error"] is None
    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "publisher_challenge"
    assert terminal["error"]["error_class"] == "access_blocked"


def test_worker_rejects_missing_or_multiple_business_results(monkeypatch, tmp_path):
    for outputs, expected in (([], 0), ([{"a": 1}, {"b": 2}], 2)):
        state = _detach(monkeypatch, tmp_path / f"case-{expected}")

        def fake_run(_argv, values=outputs):
            for value in values:
                write_output(value)
            return 0

        monkeypatch.setattr("paperfetch.cli.run", fake_run)
        assert jobs._worker(state["job_id"]) == 1
        terminal = jobs.result(state["job_id"])
        assert terminal["error"]["code"] == "business_result_cardinality_invalid"
        assert str(expected) in terminal["error"]["message"]


def test_worker_exception_is_job_error_and_still_writes_result(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)

    def fake_run(_argv):
        raise RuntimeError("secret internal details")

    monkeypatch.setattr("paperfetch.cli.run", fake_run)
    assert jobs._worker(state["job_id"]) == 1
    terminal = jobs.result(state["job_id"])
    lifecycle = jobs.read_job(state["job_id"], refresh=False)
    assert terminal["error"]["code"] == "job_worker_failed"
    assert "secret internal details" not in json.dumps(terminal)
    assert lifecycle["lifecycle"] == "finished"
    assert lifecycle["error"]["code"] == "job_worker_failed"


def test_worker_rejects_exit_code_and_business_status_mismatch(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)

    def fake_run(_argv):
        write_output(
            {
                "schema_version": "spc.command-result.v1",
                "command": "paper.lookup",
                "run_id": "run-1",
                "status": "completed",
                "summary": {"selected": 1, "succeeded": 1},
                "items": [],
            }
        )
        return 2

    monkeypatch.setattr("paperfetch.cli.run", fake_run)
    assert jobs._worker(state["job_id"]) == 1
    assert (
        jobs.result(state["job_id"])["error"]["code"] == "business_exit_code_mismatch"
    )


def test_worker_accepts_partial_business_result_with_quality_gate_exit(
    monkeypatch, tmp_path
):
    state = _detach(monkeypatch, tmp_path)

    def fake_run(_argv):
        write_output(
            {
                "schema_version": "spc.command-result.v1",
                "command": "seed-pack.enrich",
                "run_id": "run-1",
                "status": "partial",
                "summary": {"selected": 1, "partial": 1},
                "items": [],
                "error": {
                    "code": "mineru_parse_failed",
                    "error_class": "parse_failed",
                    "stage": "parse",
                    "message": "PDF 已验证，但正文解析失败",
                },
            }
        )
        return 2

    monkeypatch.setattr("paperfetch.cli.run", fake_run)
    assert jobs._worker(state["job_id"]) == 2
    assert jobs.result(state["job_id"])["status"] == "partial"


def test_read_marks_disappeared_process_without_result_as_orphan(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)
    record = jobs._load_record(state["job_id"]).model_copy(
        update={
            "lifecycle": JobLifecycle.RUNNING,
            "worker_id": "999999",
            "started_at": jobs._now(),
        }
    )
    jobs._atomic_json(jobs._state_path(state["job_id"]), jobs._state_payload(record))
    monkeypatch.setattr(jobs, "_pid_alive", lambda _pid, _identity=None: False)

    refreshed = jobs.read_job(state["job_id"])
    assert refreshed["lifecycle"] == "orphaned"
    assert refreshed["error"]["code"] == "job_process_disappeared"


def test_cancel_terminates_process_tree_and_has_no_fake_business_result(
    monkeypatch, tmp_path
):
    state = _detach(monkeypatch, tmp_path)
    record = jobs._load_record(state["job_id"]).model_copy(
        update={
            "lifecycle": JobLifecycle.RUNNING,
            "worker_id": "4321",
            "started_at": jobs._now(),
        }
    )
    jobs._atomic_json(jobs._state_path(state["job_id"]), jobs._state_payload(record))
    monkeypatch.setattr(jobs, "_pid_alive", lambda _pid, _identity=None: False)

    cancelled = jobs.cancel(state["job_id"])
    assert cancelled == {
        "schema": "spc.result.v2",
        "status": "cancelled",
        "job_id": state["job_id"],
    }


def test_job_result_never_falls_back_to_human_or_stdout_files(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)
    directory = tmp_path / "jobs" / state["job_id"]
    (directory / "stdout.txt").write_text('{"status":"completed"}', encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="尚无最终业务结果"):
        jobs.result(state["job_id"])


def test_job_action_accepts_common_flags_after_job_id(monkeypatch, tmp_path, capsys):
    state = _detach(monkeypatch, tmp_path)
    monkeypatch.setattr(
        jobs,
        "read_job",
        lambda _job_id: {
            **state,
            "progress": None,
        },
    )
    assert (
        cli_main(
            ["job", "show", state["job_id"], "--output-format", "json", "--no-progress"]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["job_id"] == state["job_id"]
    assert payload["status"] == "queued"


def test_job_root_defaults_to_runtime_state_root(monkeypatch, tmp_path):
    monkeypatch.delenv("SPC_JOB_ROOT", raising=False)
    monkeypatch.setattr(jobs, "runtime_state_root", lambda: tmp_path / "state")

    assert jobs.job_root() == tmp_path / "state" / "jobs"


def test_cancel_does_not_overwrite_already_finished_result(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)

    def fake_run(_argv):
        write_output(
            {
                "schema_version": "spc.command-result.v1",
                "command": "paper.lookup",
                "run_id": "run",
                "status": "completed",
                "summary": {"selected": 0},
                "items": [],
            }
        )
        return 0

    monkeypatch.setattr("paperfetch.cli.run", fake_run)
    assert jobs._worker(state["job_id"]) == 0
    cancelled = jobs.cancel(state["job_id"])
    assert cancelled["status"] == "completed"
    assert jobs._load_record(state["job_id"]).lifecycle == "finished"


def test_cancel_recovers_result_written_before_terminal_state(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)
    record = jobs._load_record(state["job_id"]).model_copy(
        update={
            "lifecycle": JobLifecycle.RUNNING,
            "worker_id": "4321",
            "worker_identity": "identity",
            "started_at": jobs._now(),
        }
    )
    jobs._atomic_json(jobs._state_path(state["job_id"]), jobs._state_payload(record))
    business = {
        "schema_version": "spc.command-result.v1",
        "command": "paper.lookup",
        "run_id": "run",
        "status": "completed",
        "summary": {"selected": 0},
        "items": [],
    }
    jobs._atomic_json(jobs._result_path(state["job_id"]), business)
    monkeypatch.setattr(jobs, "_pid_alive", lambda _pid, _identity=None: False)

    terminal = jobs.cancel(state["job_id"])

    assert terminal["status"] == "completed"
    latest = jobs._load_record(state["job_id"])
    assert latest.lifecycle == "finished"
    assert latest.result_ref == str(jobs._result_path(state["job_id"]))


def test_worker_does_not_restart_job_already_cancelling(monkeypatch, tmp_path):
    state = _detach(monkeypatch, tmp_path)
    record = jobs._load_record(state["job_id"]).model_copy(
        update={
            "lifecycle": JobLifecycle.CANCELLING,
        }
    )
    jobs._atomic_json(jobs._state_path(state["job_id"]), jobs._state_payload(record))

    assert jobs._worker(state["job_id"]) == 130
    assert jobs._load_record(state["job_id"]).lifecycle == "cancelling"
