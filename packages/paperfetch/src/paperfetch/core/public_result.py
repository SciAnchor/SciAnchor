"""SPC 2.0 最小公共结果投影。领域内核可继续使用更丰富的内部契约。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PUBLIC_SCHEMA = "spc.result.v2"
PUBLIC_STATUSES = {
    "queued",
    "running",
    "cancelling",
    "completed",
    "partial",
    "failed",
    "cancelled",
}


def _compact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact(item)
            for key, item in value.items()
            if item is not None
            and (
                str(key) in {"default", "checks", "blockers"}
                or (item != [] and item != {})
            )
        }
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


def _status(value: Any) -> str:
    raw = str(value or "completed")
    if raw in {
        "complete",
        "available",
        "ready",
        "planned",
        "passed",
        "allowed",
        "satisfied",
        "manifest_ready",
        "payload_ready",
    }:
        return "completed"
    if raw == "conditional":
        return "partial"
    if raw in {"blocked", "invalid", "not_downloaded", "unavailable", "not_assessable"}:
        return "failed"
    if raw == "rejected":
        return "failed"
    if raw in PUBLIC_STATUSES:
        return raw
    if raw == "finished":
        return "completed"
    if raw == "orphaned":
        return "failed"
    return "failed"


def _error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    code = value.get("code") or value.get("error_code") or value.get("error_class")
    message = value.get("message")
    if not message and isinstance(value.get("error"), str):
        message = value["error"]
    message = message or "SPC 未完成请求"
    result = {
        "code": str(code or "operation_failed"),
        "message": str(message),
    }
    if value.get("retryable"):
        result["retryable"] = True
    stage = value.get("stage")
    if stage:
        result["stage"] = str(stage)
    nxt = value.get("next")
    if nxt:
        result["next"] = str(nxt)
    return result


def _file(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    path = value.get("path")
    if not path:
        return None
    raw_type = str(value.get("kind") or value.get("type") or "file")
    result = {
        "type": {"paper_pdf": "pdf", "mineru_fulltext": "markdown"}.get(
            raw_type, raw_type
        ),
        "path": str(path),
    }
    size = (
        value.get("size") if value.get("size") is not None else value.get("size_bytes")
    )
    if size is not None:
        result["size"] = int(size)
    if value.get("sha256"):
        result["sha256"] = str(value["sha256"])
    return result


def _files(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [item for value in values if (item := _file(value)) is not None]


def _route(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value)
    return {
        "local_cache": "local",
        "global_cache": "local",
        "elsevier_api": "publisher_api",
        "publisher_api_springer": "publisher_api",
        "public_browser": "public_http",
        "trusted_direct": "public_http",
    }.get(raw, raw)


def _data(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    # Search/graph candidates carry flat bibliographic fields plus paper_id.
    # They are not full paper records with nested citation/identifiers.
    if (
        "title" in value
        and "citation" not in value
        and "download" not in value
        and "parse" not in value
    ):
        return value
    if "paper_id" not in value and "download" not in value and "parse" not in value:
        return value
    citation = (
        value.get("citation") if isinstance(value.get("citation"), Mapping) else {}
    )
    identifiers = (
        value.get("identifiers")
        if isinstance(value.get("identifiers"), Mapping)
        else {}
    )
    paper = {
        **identifiers,
        **({"title": citation.get("title")} if citation.get("title") else {}),
    }
    result: dict[str, Any] = {"paper": paper}
    if citation:
        result["citation"] = dict(citation)
    download = (
        value.get("download") if isinstance(value.get("download"), Mapping) else None
    )
    if download is not None:
        route = _route(download.get("route"))
        result["download"] = {
            **({"route": route} if route else {}),
            **({"access": "local" if route == "local" else "public"} if route else {}),
            "identity_verified": bool(download.get("identity_verified")),
        }
    parse = value.get("parse")
    if isinstance(parse, Mapping):
        result["parse"] = {
            "available": parse.get("status") == "available",
            "identity_bound": bool(parse.get("identity_bound")),
        }
    return _compact(result)


def _generic_item(value: Mapping[str, Any]) -> dict[str, Any]:
    """投影 GEO/Dryad 等领域批结果，保留业务事实但不暴露旧错误平铺字段。"""
    raw_status = value.get("status")
    result: dict[str, Any] = {"status": _status(raw_status)}
    identifier = (
        value.get("doi")
        or value.get("gse_id")
        or value.get("identifier")
        or value.get("identity")
        or value.get("id")
    )
    if identifier is not None:
        result["id"] = str(identifier)
    excluded = {
        "schema",
        "schema_version",
        "status",
        "error",
        "error_code",
        "error_class",
        "message",
        "retryable",
    }
    data = {str(key): item for key, item in value.items() if key not in excluded}
    if data:
        result["data"] = data
    error = _error(value) if result["status"] == "failed" else None
    if error:
        result["error"] = error
    return _compact(result)


def _generic_batch_result(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_results = [
        item for item in value.get("results", []) if isinstance(item, Mapping)
    ]
    results = [_generic_item(item) for item in raw_results]
    statuses = {item["status"] for item in results}
    if not results or statuses <= {"completed"}:
        status = "completed"
    elif statuses <= {"failed"}:
        status = "failed"
    else:
        status = "partial"
    data = {
        str(key): item
        for key, item in value.items()
        if key not in {"schema", "schema_version", "status", "results", "error"}
    }
    result: dict[str, Any] = {
        "schema": PUBLIC_SCHEMA,
        "status": status,
        **({"data": data} if data else {}),
        **({"results": results} if results else {}),
    }
    error = _error(value.get("error"))
    if error:
        result["error"] = error
    return _compact(result)


def _generic_result(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_status = (
        value.get("status") or value.get("resource_status") or value.get("signal")
    )
    status = _status(raw_status)
    data = {
        str(key): item
        for key, item in value.items()
        if key
        not in {
            "schema",
            "schema_version",
            "status",
            "error",
            "error_code",
            "error_class",
            "message",
            "retryable",
            "artifacts",
        }
    }
    files: list[dict[str, Any]] = []
    artifacts = value.get("artifacts")
    if isinstance(artifacts, Mapping):
        files = [
            {"type": str(kind), "path": str(path)}
            for kind, path in artifacts.items()
            if path
        ]
    result: dict[str, Any] = {
        "schema": PUBLIC_SCHEMA,
        "status": status,
        **({"data": data} if data else {}),
        **({"files": files} if files else {}),
    }
    if status == "failed":
        if value.get("signal") == "blocked" and not value.get("error_code"):
            error = {"code": "readiness_blocked", "message": "资源就绪条件未通过"}
        else:
            error = _error(value)
        if error:
            result["error"] = error
    return _compact(result)


def _item(value: Mapping[str, Any]) -> dict[str, Any]:
    entity = value.get("entity") if isinstance(value.get("entity"), Mapping) else {}
    result: dict[str, Any] = {
        "id": str(entity.get("id") or value.get("id") or "item"),
        "status": _status(value.get("status")),
    }
    if isinstance(value.get("data"), Mapping) and value["data"]:
        result["data"] = _data(value["data"])
    files = _files(value.get("artifacts") or value.get("files"))
    if files:
        result["files"] = files
    error = _error(value.get("error"))
    if error:
        result["error"] = error
    return _compact(result)


def _command_result(value: Mapping[str, Any]) -> dict[str, Any]:
    items = [item for item in value.get("items", []) if isinstance(item, Mapping)]
    status = _status(value.get("status"))
    result: dict[str, Any] = {"schema": PUBLIC_SCHEMA, "status": status}
    if value.get("job_id"):
        result["job_id"] = value["job_id"]
    if len(items) == 1:
        item = _item(items[0])
        if item.get("data"):
            result["data"] = item["data"]
        if item.get("files"):
            result["files"] = item["files"]
        if not value.get("error") and item.get("error"):
            result["error"] = item["error"]
    elif items:
        result["results"] = [_item(item) for item in items]
    files = _files(value.get("artifacts"))
    if files:
        result["files"] = [*result.get("files", []), *files]
    error = _error(value.get("error"))
    if error:
        result["error"] = error
    return _compact(result)


def _job_result(value: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle = str(value.get("lifecycle") or "queued")
    status = {
        "finished": "completed",
        "orphaned": "failed",
    }.get(lifecycle, lifecycle)
    result: dict[str, Any] = {
        "schema": PUBLIC_SCHEMA,
        "status": _status(status),
        "job_id": value.get("job_id"),
    }
    if value.get("command"):
        result["data"] = {"command": value["command"]}
    error = _error(value.get("error"))
    if error:
        result["error"] = error
    return _compact(result)


def to_public_result(value: Any) -> Any:
    """将内部结果投影为唯一的最小 SPC 2.0 公共结果。"""
    if not isinstance(value, Mapping):
        return value
    if value.get("schema") == PUBLIC_SCHEMA:
        return _compact(value)
    schema = value.get("schema_version")
    if schema == "spc.command-result.v1":
        return _command_result(value)
    if schema == "spc.job.v1":
        return _job_result(value)
    if isinstance(value.get("results"), list):
        return _generic_batch_result(value)
    return _generic_result(value)
