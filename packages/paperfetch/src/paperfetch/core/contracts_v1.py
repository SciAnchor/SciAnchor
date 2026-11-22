"""SPC 1.0 跨域公共结果、事件与作业契约。

本模块只定义 Agent、CLI、API 和后台作业共同消费的稳定边界，不承载
论文、数据集或稿件等领域实现细节。领域实现应把详细诊断写入 audit，
公共结果只保留最终状态、已验证文件引用和可行动错误。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


COMMAND_RESULT_SCHEMA = "spc.command-result.v1"
EVENT_SCHEMA = "spc.event.v1"
JOB_SCHEMA = "spc.job.v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictContract(BaseModel):
    """禁止静默接收拼错或已删除的公共字段。"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class BusinessStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"


class JobLifecycle(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"


class EventOutcome(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_EVENT_OUTCOMES = frozenset(
    {
        EventOutcome.SUCCEEDED.value,
        EventOutcome.SKIPPED.value,
        EventOutcome.BLOCKED.value,
        EventOutcome.PARTIAL.value,
        EventOutcome.FAILED.value,
        EventOutcome.CANCELLED.value,
    }
)


class ErrorInfo(StrictContract):
    """公共结果中的唯一稳定错误。逐下载方式尝试明细属于 audit。"""

    code: str = Field(min_length=1)
    error_class: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    retryable: bool = False
    message: str = Field(min_length=1)
    next: str | None = None
    remediation: str | None = None
    audit_ref: str | None = None


class EntityRef(StrictContract):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class ArtifactRef(StrictContract):
    """已验证文件的最小公共引用；实际文件明细由 manifest 管理。"""

    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    manifest_ref: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)


class CommandItem(StrictContract):
    entity: EntityRef
    status: BusinessStatus
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    audit_ref: str | None = None

    @model_validator(mode="after")
    def validate_terminal_error(self) -> "CommandItem":
        if self.status == BusinessStatus.COMPLETED.value and self.error is not None:
            raise ValueError("completed item must not contain error")
        if (
            self.status
            in {
                BusinessStatus.PARTIAL.value,
                BusinessStatus.FAILED.value,
                BusinessStatus.REJECTED.value,
            }
            and self.error is None
        ):
            raise ValueError("partial, failed, or rejected item must contain error")
        return self


class CommandSummary(StrictContract):
    selected: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "CommandSummary":
        if self.succeeded + self.partial + self.failed + self.skipped > self.selected:
            raise ValueError("summary outcome counts exceed selected")
        return self


class CommandResult(StrictContract):
    """同步 CLI、API 与 detached job 共享的唯一最终业务结果。"""

    schema_version: Literal["spc.command-result.v1"] = COMMAND_RESULT_SCHEMA
    command: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    job_id: str | None = None
    status: BusinessStatus
    summary: CommandSummary = Field(default_factory=CommandSummary)
    items: list[CommandItem] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    metrics: dict[str, int | float] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    audit_ref: str | None = None

    @model_validator(mode="after")
    def validate_business_terminal(self) -> "CommandResult":
        if self.status == BusinessStatus.COMPLETED.value and self.error is not None:
            raise ValueError("completed result must not contain error")
        if (
            self.status
            in {
                BusinessStatus.PARTIAL.value,
                BusinessStatus.FAILED.value,
                BusinessStatus.REJECTED.value,
            }
            and self.error is None
        ):
            raise ValueError("partial, failed, or rejected result must contain error")
        if (
            self.summary.selected
            and self.items
            and self.summary.selected != len(self.items)
        ):
            raise ValueError(
                "summary.selected must equal item count when items are projected"
            )
        return self


class Event(StrictContract):
    """单个 run/job 内有序、脱敏的唯一机器时间线事件。"""

    schema_version: Literal["spc.event.v1"] = EVENT_SCHEMA
    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    job_id: str | None = None
    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=_utc_now)
    domain: str = Field(min_length=1)
    entity: EntityRef | None = None
    stage: str = Field(min_length=1)
    action: str = Field(min_length=1)
    outcome: EventOutcome
    terminal: bool = False
    elapsed_ms: int | None = Field(default=None, ge=0)
    source: str | None = None
    route: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    error: ErrorInfo | None = None
    details_ref: str | None = None

    @model_validator(mode="after")
    def validate_transition(self) -> "Event":
        if self.terminal and self.outcome not in TERMINAL_EVENT_OUTCOMES:
            raise ValueError("terminal event has a non-terminal outcome")
        if (
            self.outcome
            in {
                EventOutcome.PARTIAL.value,
                EventOutcome.FAILED.value,
                EventOutcome.BLOCKED.value,
            }
            and self.error is None
        ):
            raise ValueError("partial, failed, or blocked event must contain error")
        if self.outcome == EventOutcome.SUCCEEDED.value and self.error is not None:
            raise ValueError("succeeded event must not contain error")
        return self


class JobRecord(StrictContract):
    """后台作业生命周期；业务成功与否只读取 result_ref。"""

    schema_version: Literal["spc.job.v1"] = JOB_SCHEMA
    job_id: str = Field(min_length=1)
    command: str = Field(min_length=1)
    lifecycle: JobLifecycle = JobLifecycle.QUEUED
    run_id: str | None = None
    worker_id: str | None = None
    worker_identity: str | None = None
    heartbeat_at: datetime | None = None
    revision: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    command_ref: str = Field(min_length=1)
    result_ref: str | None = None
    event_ref: str = Field(min_length=1)
    stderr_ref: str = Field(min_length=1)
    audit_ref: str | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "JobRecord":
        if self.lifecycle == JobLifecycle.RUNNING.value and self.started_at is None:
            raise ValueError("running job must contain started_at")
        if self.lifecycle == JobLifecycle.FINISHED.value:
            if self.finished_at is None or self.result_ref is None:
                raise ValueError("finished job must contain finished_at and result_ref")
        if self.lifecycle in {
            JobLifecycle.CANCELLED.value,
            JobLifecycle.ORPHANED.value,
        }:
            if self.finished_at is None or self.error is None:
                raise ValueError(
                    "cancelled or orphaned job must contain terminal error"
                )
        return self
