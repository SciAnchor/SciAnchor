"""SPC 2.0 持久后台作业内核。

Job 只管理生命周期。业务结果由命令通过 ``write_output`` 的进程内捕获通道
显式提交，原子写入 ``result.json``；worker 永不解析 stdout 或人类日志。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - 1.0/2.0 产品运行面是 Linux
    fcntl = None

from paperfetch.core.contracts_v1 import (
    BusinessStatus,
    CommandItem,
    CommandResult,
    CommandSummary,
    EntityRef,
    ErrorInfo,
    JobLifecycle,
    JobRecord,
)
from paperfetch.core.config_v1 import runtime_state_root


DETACHABLE_COMMANDS = {
    "dataset",
    "paper",
    "seed-pack",
}
TERMINAL_LIFECYCLES = {
    JobLifecycle.FINISHED.value,
    JobLifecycle.CANCELLED.value,
    JobLifecycle.ORPHANED.value,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def job_root() -> Path:
    from paperfetch.core.settings import get_settings

    configured = (get_settings().text("SPC_JOB_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return runtime_state_root() / "jobs"


def _job_dir(job_id: str) -> Path:
    if not job_id or any(character not in "0123456789abcdef" for character in job_id):
        raise ValueError("无效 job_id")
    return job_root() / job_id


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _state_path(job_id: str) -> Path:
    return _job_dir(job_id) / "job.json"


def _result_path(job_id: str) -> Path:
    return _job_dir(job_id) / "result.json"


@contextmanager
def _job_lock(job_id: str):
    """串行化同一 Job 的跨进程状态更新。"""
    path = _job_dir(job_id) / "job.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _state_payload(record: JobRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _load_record(job_id: str) -> JobRecord:
    payload = _read_json(_state_path(job_id))
    if not isinstance(payload, dict):
        raise FileNotFoundError(f"未找到作业：{job_id}")
    return JobRecord.model_validate(payload)


def _finish_from_written_result(record: JobRecord) -> JobRecord | None:
    """识别 worker 已提交业务结果但尚未更新 job.json 的竞态窗口。"""
    path = Path(record.result_ref) if record.result_ref else _result_path(record.job_id)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    try:
        CommandResult.model_validate(payload)
    except ValueError:
        return None
    return record.model_copy(
        update={
            "lifecycle": JobLifecycle.FINISHED,
            "finished_at": record.finished_at or _now(),
            "heartbeat_at": record.heartbeat_at or _now(),
            "result_ref": str(path),
            "revision": record.revision + 1,
        }
    )


def _latest_event(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 131_072))
            chunk = handle.read().decode("utf-8", errors="ignore")
        for line in reversed(chunk.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(payload, dict)
                and payload.get("schema_version") == "spc.event.v1"
            ):
                return payload
    except OSError:
        pass
    return None


def _process_identity(pid: int) -> str | None:
    if pid <= 0 or os.name == "nt":
        return None
    try:
        stat = (
            Path(f"/proc/{pid}/stat")
            .read_text(encoding="utf-8")
            .rsplit(")", 1)[1]
            .split()
        )
        return stat[19]
    except (OSError, UnicodeError, ValueError, IndexError):
        return None


def _pid_alive(pid: int, expected_identity: str | None = None) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=False,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return (
            completed.returncode == 0 and f'"{pid}"'.encode("ascii") in completed.stdout
        )
    try:
        suffix = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1]
        if suffix.split()[0] == "Z":
            return False
        if (
            expected_identity is not None
            and _process_identity(pid) != expected_identity
        ):
            return False
        os.kill(pid, 0)
        return True
    except (OSError, SystemError, UnicodeError, ValueError, IndexError):
        return False


def _remove_flag(arguments: Sequence[str], flag: str) -> list[str]:
    return [argument for argument in arguments if argument != flag]


def _command_name(argv: Sequence[str]) -> str:
    if (
        argv
        and argv[0] in {"paper", "seed-pack", "dataset", "workflow"}
        and len(argv) > 1
    ):
        return f"{argv[0]}.{argv[1]}"
    return argv[0] if argv else "unknown"


def detach(arguments: Sequence[str], *, cwd: str | None = None) -> dict[str, Any]:
    argv = _remove_flag(list(arguments), "--detach")
    if not argv or argv[0] not in DETACHABLE_COMMANDS:
        raise ValueError("该命令不支持 detached job")
    if argv[0] == "dataset" and argv[1:3] not in (
        ["archive", "download"],
        ["geo", "download"],
    ):
        raise ValueError(
            "dataset 当前仅 archive download 与 geo download 支持 detached job"
        )
    if argv[0] == "paper" and argv[1:2] not in (
        ["lookup"],
        ["download"],
        ["parse"],
        ["search"],
        ["graph"],
    ):
        raise ValueError(
            "paper 当前仅 lookup、download、parse、search 与 graph 支持 detached job"
        )
    if "--output-format" not in argv:
        argv.extend(["--output-format", "json"])
    if "--no-progress" not in argv:
        argv.append("--no-progress")

    job_id = uuid.uuid4().hex
    run_id = uuid.uuid4().hex
    directory = _job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=False)
    command_path = directory / "command.json"
    event_path = directory / "events.jsonl"
    stderr_path = directory / "stderr.log"
    if "--event-file" not in argv:
        argv.extend(["--event-file", str(event_path)])

    command_payload = {
        "schema_version": "spc.job-command.v1",
        "job_id": job_id,
        "run_id": run_id,
        "command": _command_name(argv),
        "argv": argv,
        "cwd": str(Path(cwd or os.getcwd()).resolve()),
    }
    _atomic_json(command_path, command_payload)
    record = JobRecord(
        job_id=job_id,
        command=command_payload["command"],
        lifecycle=JobLifecycle.QUEUED,
        run_id=run_id,
        command_ref=str(command_path),
        event_ref=str(event_path),
        stderr_ref=str(stderr_path),
        audit_ref=str(directory / "audit"),
    )
    _atomic_json(_state_path(job_id), _state_payload(record))

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_BREAKAWAY_FROM_JOB
        )
    with stderr_path.open("ab") as stderr:
        popen_kwargs = {
            "cwd": command_payload["cwd"],
            "stdout": subprocess.DEVNULL,
            "stderr": stderr,
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
            "creationflags": creationflags,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "paperfetch.jobs", "--worker", job_id],
                **popen_kwargs,
            )
        except OSError:
            if os.name != "nt":
                raise
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "paperfetch.jobs", "--worker", job_id],
                **popen_kwargs,
            )
    with _job_lock(job_id):
        latest = _load_record(job_id)
        if latest.lifecycle == JobLifecycle.QUEUED.value and not latest.worker_id:
            latest = latest.model_copy(
                update={
                    "worker_id": str(process.pid),
                    "worker_identity": _process_identity(process.pid),
                    "revision": latest.revision + 1,
                }
            )
            _atomic_json(_state_path(job_id), _state_payload(latest))
    return _state_payload(latest)


def _orphan_record(record: JobRecord) -> JobRecord:
    return record.model_copy(
        update={
            "lifecycle": JobLifecycle.ORPHANED,
            "finished_at": _now(),
            "revision": record.revision + 1,
            "error": ErrorInfo(
                code="job_process_disappeared",
                error_class="process_error",
                stage="job",
                message="作业进程已退出，但没有写入最终业务结果",
            ),
        }
    )


def read_job(job_id: str, *, refresh: bool = True) -> dict[str, Any]:
    record = _load_record(job_id)
    command = _read_json(Path(record.command_ref)) or {}
    if refresh and record.lifecycle in {
        JobLifecycle.QUEUED.value,
        JobLifecycle.RUNNING.value,
        JobLifecycle.CANCELLING.value,
    }:
        with _job_lock(job_id):
            record = _load_record(job_id)
            worker_id = int(record.worker_id or 0)
            if (
                record.lifecycle
                in {
                    JobLifecycle.QUEUED.value,
                    JobLifecycle.RUNNING.value,
                    JobLifecycle.CANCELLING.value,
                }
                and worker_id
                and not _pid_alive(worker_id, record.worker_identity)
            ):
                finished = _finish_from_written_result(record)
                if finished is not None:
                    record = finished
                else:
                    record = _orphan_record(record)
                _atomic_json(_state_path(job_id), _state_payload(record))
    payload = _state_payload(record)
    payload["progress"] = _latest_event(Path(record.event_ref))
    payload["cwd"] = command.get("cwd")
    return payload


def cancel(job_id: str) -> dict[str, Any]:
    with _job_lock(job_id):
        record = _load_record(job_id)
        if record.lifecycle in TERMINAL_LIFECYCLES:
            return show(job_id)
        record = record.model_copy(
            update={
                "lifecycle": JobLifecycle.CANCELLING,
                "revision": record.revision + 1,
            }
        )
        _atomic_json(_state_path(job_id), _state_payload(record))
    pid = int(record.worker_id or 0)
    if pid and _pid_alive(pid, record.worker_identity):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=False,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 10.0
    while (
        pid and _pid_alive(pid, record.worker_identity) and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    if pid and _pid_alive(pid, record.worker_identity):
        raise RuntimeError("作业进程树在取消预算内未退出，未写入 cancelled 终局")
    with _job_lock(job_id):
        latest = _load_record(job_id)
        finished = _finish_from_written_result(latest)
        if finished is not None:
            _atomic_json(_state_path(job_id), _state_payload(finished))
            return show(job_id)
        latest = latest.model_copy(
            update={
                "lifecycle": JobLifecycle.CANCELLED,
                "finished_at": _now(),
                "revision": latest.revision + 1,
                "error": ErrorInfo(
                    code="job_cancelled",
                    error_class="cancelled",
                    stage="job",
                    message="作业已由调用方取消",
                ),
            }
        )
        _atomic_json(_state_path(job_id), _state_payload(latest))
    return {
        "schema": "spc.result.v2",
        "status": "cancelled",
        "job_id": job_id,
    }


def watch(job_id: str, timeout_seconds: float = 0.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        state = read_job(job_id)
        if state["lifecycle"] in TERMINAL_LIFECYCLES or time.monotonic() >= deadline:
            return state
        time.sleep(0.5)


def _public_progress(record: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "spc.result.v2",
        "status": record["lifecycle"],
        "job_id": record["job_id"],
        "data": {"command": record["command"]},
    }
    event = record.get("progress")
    if isinstance(event, dict):
        progress = {
            key: event[key]
            for key in ("stage", "action", "progress", "message")
            if event.get(key) is not None
        }
        if progress:
            payload["data"]["progress"] = progress
    return payload


def show(job_id: str) -> dict[str, Any]:
    """返回紧凑快照；终止时直接返回原命令业务结果。"""
    record = read_job(job_id)
    if record["lifecycle"] == JobLifecycle.FINISHED.value and record.get("result_ref"):
        from paperfetch.core.public_result import to_public_result

        terminal = to_public_result(result(job_id))
        terminal["job_id"] = job_id
        return terminal
    if record["lifecycle"] == JobLifecycle.CANCELLED.value:
        return {"schema": "spc.result.v2", "status": "cancelled", "job_id": job_id}
    if record["lifecycle"] == JobLifecycle.ORPHANED.value:
        return {
            "schema": "spc.result.v2",
            "status": "failed",
            "job_id": job_id,
            "error": {
                "code": "job_process_disappeared",
                "message": "作业进程已退出，但没有生成最终结果",
            },
        }
    return _public_progress(record)


def wait(job_id: str, timeout_seconds: float = 300.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        payload = show(job_id)
        if payload["status"] not in {"queued", "running", "cancelling"}:
            return payload
        if time.monotonic() >= deadline:
            payload.setdefault("data", {})["timed_out"] = True
            return payload
        time.sleep(0.5)


def list_jobs(limit: int = 20) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    root = job_root()
    if root.is_dir():
        directories = sorted(
            (path for path in root.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for directory in directories[: max(1, limit)]:
            try:
                current = show(directory.name)
            except (FileNotFoundError, ValueError):
                continue
            jobs.append(
                {
                    "job_id": directory.name,
                    "status": current["status"],
                    **({"data": current["data"]} if current.get("data") else {}),
                }
            )
    return {
        "schema": "spc.result.v2",
        "status": "completed",
        "data": {"jobs": jobs},
    }


def result(job_id: str) -> dict[str, Any]:
    record = _load_record(job_id)
    if not record.result_ref:
        raise FileNotFoundError(f"作业尚无最终业务结果：{job_id}")
    payload = _read_json(Path(record.result_ref))
    if not isinstance(payload, dict):
        raise ValueError(f"作业最终业务结果损坏：{job_id}")
    return CommandResult.model_validate(payload).model_dump(mode="json")


def _normalize_error(payload: dict[str, Any], *, exit_code: int) -> ErrorInfo:
    raw = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(
        raw.get("code")
        or raw.get("error_code")
        or raw.get("error_class")
        or f"command_exit_{exit_code}"
    )
    return ErrorInfo(
        code=code,
        error_class=str(raw.get("error_class") or "business_operation_failed"),
        stage=str(raw.get("stage") or "command"),
        retryable=bool(raw.get("retryable", False)),
        message=str(raw.get("message") or f"命令未满足请求契约，退出码={exit_code}"),
        next=raw.get("next"),
        remediation=raw.get("remediation"),
        audit_ref=raw.get("audit_ref"),
    )


def _normalize_business_output(
    payload: Any,
    *,
    command: str,
    run_id: str,
    job_id: str,
    exit_code: int,
    elapsed_ms: int,
) -> CommandResult:
    if isinstance(payload, CommandResult):
        return payload.model_copy(update={"job_id": job_id, "run_id": run_id})
    if (
        isinstance(payload, dict)
        and payload.get("schema_version") == "spc.command-result.v1"
    ):
        return CommandResult.model_validate(
            {**payload, "job_id": job_id, "run_id": run_id}
        )
    raw = payload if isinstance(payload, dict) else {"value": payload}
    succeeded = exit_code == 0
    error = None if succeeded else _normalize_error(raw, exit_code=exit_code)
    return CommandResult(
        command=command,
        run_id=run_id,
        job_id=job_id,
        status=BusinessStatus.COMPLETED if succeeded else BusinessStatus.FAILED,
        summary=CommandSummary(
            selected=1,
            succeeded=1 if succeeded else 0,
            failed=0 if succeeded else 1,
            elapsed_ms=elapsed_ms,
        ),
        items=[
            CommandItem(
                entity=EntityRef(type="command", id=command),
                status=BusinessStatus.COMPLETED if succeeded else BusinessStatus.FAILED,
                data={"legacy_output": raw},
                error=error,
            )
        ],
        error=error,
    )


def _worker(job_id: str) -> int:
    with _job_lock(job_id):
        record = _load_record(job_id)
        if record.lifecycle in {
            JobLifecycle.CANCELLING.value,
            JobLifecycle.CANCELLED.value,
        }:
            return 130
        if record.lifecycle in TERMINAL_LIFECYCLES:
            return 0 if record.lifecycle == JobLifecycle.FINISHED.value else 1
        command_payload = _read_json(Path(record.command_ref))
        if not isinstance(command_payload, dict):
            raise RuntimeError("job command artifact is missing")
        record = record.model_copy(
            update={
                "lifecycle": JobLifecycle.RUNNING,
                "worker_id": str(os.getpid()),
                "worker_identity": _process_identity(os.getpid()),
                "started_at": record.started_at or _now(),
                "heartbeat_at": _now(),
                "revision": record.revision + 1,
            }
        )
        _atomic_json(_state_path(job_id), _state_payload(record))
    os.environ["SPC_JOB_ID"] = job_id
    os.environ["SPC_RUN_ID"] = record.run_id or uuid.uuid4().hex
    started = time.perf_counter()
    heartbeat_stop = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(2.0):
            try:
                with _job_lock(job_id):
                    current = _load_record(job_id)
                    if current.lifecycle != JobLifecycle.RUNNING.value:
                        return
                    current = current.model_copy(
                        update={
                            "heartbeat_at": _now(),
                            "revision": current.revision + 1,
                        }
                    )
                    _atomic_json(_state_path(job_id), _state_payload(current))
            except (OSError, ValueError, FileNotFoundError):
                return

    heartbeat_thread = threading.Thread(
        target=heartbeat, name=f"spc-job-heartbeat-{job_id[:8]}", daemon=True
    )
    heartbeat_thread.start()
    captured: list[Any] = []
    exit_code = 1
    worker_error: ErrorInfo | None = None
    try:
        from paperfetch.cli import run
        from paperfetch.observability import bind_output_capture

        with bind_output_capture(captured.append):
            exit_code = int(run(command_payload["argv"]))
    except BaseException as exc:
        worker_error = ErrorInfo(
            code="job_worker_failed",
            error_class="internal_error",
            stage="job",
            message=f"作业执行器异常：{type(exc).__name__}",
        )
    heartbeat_stop.set()
    heartbeat_thread.join(timeout=3.0)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if worker_error is not None:
        business = CommandResult(
            command=record.command,
            run_id=record.run_id or os.environ["SPC_RUN_ID"],
            job_id=job_id,
            status=BusinessStatus.FAILED,
            summary=CommandSummary(selected=1, failed=1, elapsed_ms=elapsed_ms),
            error=worker_error,
        )
    elif len(captured) != 1:
        capture_error = ErrorInfo(
            code="business_result_cardinality_invalid",
            error_class="contract_error",
            stage="job",
            message=f"命令必须提交一个最终业务结果，实际提交 {len(captured)} 个",
        )
        business = CommandResult(
            command=record.command,
            run_id=record.run_id or os.environ["SPC_RUN_ID"],
            job_id=job_id,
            status=BusinessStatus.FAILED,
            summary=CommandSummary(selected=1, failed=1, elapsed_ms=elapsed_ms),
            error=capture_error,
        )
        exit_code = 1
    else:
        business = _normalize_business_output(
            captured[0],
            command=record.command,
            run_id=record.run_id or os.environ["SPC_RUN_ID"],
            job_id=job_id,
            exit_code=exit_code,
            elapsed_ms=elapsed_ms,
        )
        expected_exit_codes = {
            BusinessStatus.COMPLETED.value: {0},
            BusinessStatus.PARTIAL.value: {2},
            BusinessStatus.FAILED.value: {1, 2},
            BusinessStatus.REJECTED.value: {1},
        }[business.status]
        if exit_code not in expected_exit_codes:
            mismatch = ErrorInfo(
                code="business_exit_code_mismatch",
                error_class="contract_error",
                stage="job",
                message=(
                    f"最终业务结果 status={business.status} 与命令退出码 {exit_code} 不一致"
                ),
            )
            business = CommandResult(
                command=record.command,
                run_id=record.run_id or os.environ["SPC_RUN_ID"],
                job_id=job_id,
                status=BusinessStatus.FAILED,
                summary=CommandSummary(selected=1, failed=1, elapsed_ms=elapsed_ms),
                error=mismatch,
            )
            exit_code = 1
    result_path = _result_path(job_id)
    _atomic_json(result_path, business.model_dump(mode="json"))
    with _job_lock(job_id):
        latest = _load_record(job_id)
        if latest.lifecycle not in {
            JobLifecycle.CANCELLING.value,
            JobLifecycle.CANCELLED.value,
        }:
            latest = latest.model_copy(
                update={
                    "lifecycle": JobLifecycle.FINISHED,
                    "finished_at": _now(),
                    "heartbeat_at": _now(),
                    "result_ref": str(result_path),
                    "error": worker_error,
                    "revision": latest.revision + 1,
                }
            )
            _atomic_json(_state_path(job_id), _state_payload(latest))
    return exit_code


def main(arguments: Sequence[str] | None = None) -> int:
    argv = list(arguments if arguments is not None else sys.argv[1:])
    if len(argv) == 2 and argv[0] == "--worker":
        return _worker(argv[1])
    raise SystemExit("jobs 模块仅供 SPC 内部 worker 使用")


if __name__ == "__main__":
    raise SystemExit(main())
