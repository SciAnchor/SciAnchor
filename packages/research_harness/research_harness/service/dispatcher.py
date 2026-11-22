"""Service dispatcher entry point."""

from __future__ import annotations

import re
import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from research_harness.config import load_runtime_config
from research_harness.storage.db import Database

from .registry import COMMANDS, COMMANDS_BY_NAME
from .types import ServiceCommand, ServiceContext, ServiceResult, ValidationPolicy


LOGGER = logging.getLogger(__name__)


class ResearchService:
    """Invoke registered Research Harness commands independent of transport."""

    def __init__(self, db: Database | str | Path | None = None) -> None:
        self._db_source = db
        if isinstance(db, Database):
            self._db = db
            self._db.migrate()
        else:
            self._db = None

    @property
    def db(self) -> Database:
        if self._db is None:
            if self._db_source is None:
                self._db = Database(load_runtime_config().db_path)
            else:
                self._db = Database(Path(self._db_source))
            self._db.migrate()
        return self._db

    def list_commands(self, visibility: str | None = None) -> list[ServiceCommand]:
        if visibility is None:
            return list(COMMANDS)
        return [command for command in COMMANDS if visibility in command.visibility]

    def invoke(
        self,
        command_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ServiceResult:
        command = COMMANDS_BY_NAME.get(command_name)
        if command is None:
            return self._error(
                command=command_name,
                code="UNKNOWN_COMMAND",
                message=f"Unknown service command: {command_name}",
            )

        if arguments is None:
            payload = {}
        elif isinstance(arguments, Mapping):
            payload = dict(arguments)
        else:
            return self._error(
                command=command.name,
                code="INVALID_ARGUMENT",
                message=f"Invalid arguments for {command.name}: payload must be object",
            )
        # BUG-011: `background: true` runs any command on a background thread and
        # returns a job_id immediately, so a slow call does not block past the
        # MCP transport timeout. Poll it with the `job_status` command.
        run_background = bool(payload.pop("background", False))
        validation_error = self._validate(command, payload)
        if validation_error is not None:
            return validation_error

        if run_background:
            return self._invoke_background(command, payload)

        db = self.db if command.requires_db else None
        try:
            raw = command.handler(ServiceContext(db=db), payload)
        except Exception as exc:
            LOGGER.exception("Service command %s failed", command.name)
            return self._error(
                command=command.name,
                code="COMMAND_FAILED",
                message=f"{command.name} failed during service execution",
                output={"exception_type": type(exc).__name__},
            )
        if isinstance(raw, ServiceResult):
            return raw
        if isinstance(raw, Mapping) and raw.get("error"):
            return self._error(
                command=command.name,
                code=str(raw.get("error_code", "COMMAND_FAILED")),
                message=str(raw["error"]),
                output=raw,
            )
        return ServiceResult(
            command=command.name,
            status="success",
            summary=f"{command.name} completed successfully.",
            output=raw,
        )

    def _invoke_background(
        self,
        command: ServiceCommand,
        payload: dict[str, Any],
    ) -> ServiceResult:
        from research_harness.jobs import start_job

        job_db = self.db  # the job registry always needs a db

        def _work(_handle: Any) -> Any:
            ctx_db = job_db if command.requires_db else None
            raw = command.handler(ServiceContext(db=ctx_db), payload)
            if isinstance(raw, ServiceResult):
                return raw.output
            return raw

        job_id = start_job(job_db, command.name, _work)
        return ServiceResult(
            command=command.name,
            status="success",
            summary=(
                f"{command.name} started in the background; "
                f"poll job_status(job_id='{job_id}')."
            ),
            output={"job_id": job_id, "status": "running", "background": True},
        )

    def _validate(
        self,
        command: ServiceCommand,
        arguments: dict[str, Any],
    ) -> ServiceResult | None:
        schema_error = _validate_schema_value(
            arguments,
            command.input_schema,
            policy=command.validation_policy,
        )
        if schema_error:
            return self._error(
                command=command.name,
                code="INVALID_ARGUMENT",
                message=f"Invalid arguments for {command.name}: {schema_error}",
            )
        return None

    @staticmethod
    def _error(
        *,
        command: str,
        code: str,
        message: str,
        output: dict[str, Any] | None = None,
    ) -> ServiceResult:
        return ServiceResult(
            command=command,
            status="error",
            summary=message,
            output=output or {},
            error={"code": code, "message": message},
        )


def _validate_schema_value(
    value: Any,
    schema: dict[str, Any],
    *,
    policy: ValidationPolicy = "compat",
    path: str = "",
) -> str | None:
    expected_type = schema.get("type")
    if expected_type and not _matches_json_schema_type(value, expected_type):
        return f"{path or 'payload'} must be {_json_schema_type_label(expected_type)}"

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        allowed = ", ".join(str(item) for item in enum_values)
        return f"{path or 'payload'} must be one of: {allowed}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            return f"{path or 'payload'} must be >= {minimum}"
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            return f"{path or 'payload'} must be <= {maximum}"

    if policy == "strict" and isinstance(value, str):
        string_error = _validate_strict_string_keywords(value, schema, path=path)
        if string_error:
            return string_error

    if expected_type == "object":
        required = schema.get("required") or []
        for name in required:
            if name not in value or value[name] is None:
                return f"missing required argument: {_join_path(path, name)}"

        properties = schema.get("properties") or {}
        for name, property_schema in properties.items():
            if name not in value or (value[name] is None and policy != "strict"):
                continue
            error = _validate_schema_value(
                value[name],
                property_schema,
                policy=policy,
                path=_join_path(path, name),
            )
            if error:
                return error

        if policy == "strict":
            additional_properties = schema.get("additionalProperties")
            for name, item in value.items():
                if name in properties:
                    continue
                item_path = _join_path(path, str(name))
                if additional_properties is True:
                    continue
                if isinstance(additional_properties, dict):
                    error = _validate_schema_value(
                        item,
                        additional_properties,
                        policy=policy,
                        path=item_path,
                    )
                    if error:
                        return error
                    continue
                return f"unexpected argument: {item_path}"

    if expected_type == "array" and "items" in schema:
        if policy == "strict":
            min_items = schema.get("minItems")
            if min_items is not None and len(value) < min_items:
                return f"{path or 'payload'} must contain at least {min_items} items"
            max_items = schema.get("maxItems")
            if max_items is not None and len(value) > max_items:
                return f"{path or 'payload'} must contain at most {max_items} items"
        for index, item in enumerate(value):
            error = _validate_schema_value(
                item,
                schema["items"],
                policy=policy,
                path=f"{path}[{index}]" if path else f"payload[{index}]",
            )
            if error:
                return error

    return None


def _validate_strict_string_keywords(
    value: str,
    schema: dict[str, Any],
    *,
    path: str,
) -> str | None:
    label = path or "payload"
    min_length = schema.get("minLength")
    if min_length is not None and len(value) < min_length:
        return f"{label} length must be >= {min_length}"
    max_length = schema.get("maxLength")
    if max_length is not None and len(value) > max_length:
        return f"{label} length must be <= {max_length}"

    pattern = schema.get("pattern")
    if pattern is not None and re.search(str(pattern), value) is None:
        return f"{label} must match pattern: {pattern}"

    format_name = schema.get("format")
    if format_name is not None and not _matches_strict_format(value, str(format_name)):
        return f"{label} must be valid {format_name}"
    return None


def _matches_strict_format(value: str, format_name: str) -> bool:
    if format_name == "uri":
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)
    if format_name == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    return True


def _matches_json_schema_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_schema_type(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _json_schema_type_label(expected_type: Any) -> str:
    if isinstance(expected_type, list):
        return " or ".join(str(item) for item in expected_type)
    return str(expected_type)


def _join_path(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name
