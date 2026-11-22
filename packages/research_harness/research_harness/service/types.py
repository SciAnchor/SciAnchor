"""Service-layer command and result contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

from research_harness.storage.db import Database


ServiceStatus = Literal["success", "error"]
ValidationPolicy = Literal["compat", "strict"]
ServiceHandler = Callable[["ServiceContext", dict[str, Any]], Any]


@dataclass(frozen=True)
class ServiceContext:
    db: Database | None


@dataclass(frozen=True)
class ServiceCommand:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    visibility: tuple[str, ...]
    handler: ServiceHandler
    requires_db: bool = True
    validation_policy: ValidationPolicy = "compat"


@dataclass(frozen=True)
class ServiceResult:
    command: str
    status: ServiceStatus
    summary: str
    output: Any
    error: dict[str, str] | None = None
    next_actions: tuple[str, ...] = ()
    artifacts: tuple[Any, ...] = ()
    recovery_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "status": self.status,
            "summary": self.summary,
            "output": _to_jsonable(self.output),
            "error": dict(self.error) if self.error is not None else None,
            "next_actions": list(self.next_actions),
            "artifacts": [_to_jsonable(artifact) for artifact in self.artifacts],
            "recovery_hint": self.recovery_hint,
            "metadata": _to_jsonable(self.metadata),
        }


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value
