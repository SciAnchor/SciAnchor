"""hub CLI entrypoint."""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import click
from paperindex.cards.schema import PaperCard, PaperCardSchemaError

from . import __version__ as _RH_VERSION
from . import cli_registration as _cli_registration
from . import path_jail
from .cli_domain import CS_DOMAIN_SEED
from .config import load_runtime_config
from .env_bootstrap import load_default_env_files as _load_default_env_files
from .service import ResearchService
from .storage.db import Database
from .storage.models import Paper

__all__ = ["CS_DOMAIN_SEED", "main"]

REQUIRED_ANNOTATION_SECTIONS = ("summary", "methodology", "experiments", "limitations")
NOTE_TYPES = ("relevance", "comparison", "usage_plan", "critique")
BACKEND_CHOICES = ("local", "claude_code", "research_harness")


def get_runtime_config(ctx: click.Context):
    runtime_config = ctx.obj.get("runtime_config")
    if runtime_config is None:
        runtime_config = load_runtime_config(
            ctx.obj.get("db_path"),
            explicit_backend=ctx.obj.get("backend_override"),
        )
        ctx.obj["runtime_config"] = runtime_config
    return runtime_config


def get_db(ctx: click.Context) -> Database:
    db = ctx.obj.get("db")
    if db is None:
        runtime_config = get_runtime_config(ctx)
        db = Database(runtime_config.db_path)
        db.migrate()
        ctx.obj["db"] = db
    return db


def _invoke_service_or_exit(
    ctx: click.Context,
    command_name: str,
    arguments: dict[str, object] | None = None,
) -> object:
    result = ResearchService(db=get_db(ctx)).invoke(command_name, arguments or {})
    if result.status == "success":
        return result.output
    error = result.error or {}
    message = error.get("message") or result.summary or f"{command_name} failed"
    raise click.ClickException(str(message))


def _legacy_topic_list_rows(ctx: click.Context) -> list[dict[str, object]]:
    db = get_db(ctx)
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM topics ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _topic_paper_count(ctx: click.Context, topic_id: int) -> int:
    db = get_db(ctx)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM paper_topics WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return int(row["cnt"] if row is not None else 0)
    finally:
        conn.close()


def _strip_service_topic_fields(topic_payload: dict[str, object]) -> dict[str, object]:
    payload = dict(topic_payload)
    payload.pop("days_since_last_search", None)
    payload.pop("freshness_status", None)
    return payload


def _topic_list_payload_for_cli(
    ctx: click.Context, service_output: object
) -> list[dict[str, object]]:
    del ctx
    if not isinstance(service_output, dict):
        raise click.ClickException("topic_list returned an invalid service payload")
    topics = service_output.get("topics", [])
    if not isinstance(topics, list):
        raise click.ClickException("topic_list returned an invalid topics payload")
    required_fields = {
        "id",
        "name",
        "description",
        "status",
        "created_at",
        "paper_count",
    }
    if not all(
        isinstance(topic_row, dict) and required_fields <= set(topic_row)
        for topic_row in topics
    ):
        raise click.ClickException(
            "topic_list returned incomplete service topic payload"
        )
    return [_strip_service_topic_fields(topic_row) for topic_row in topics]


def _topic_show_payload_for_cli(
    ctx: click.Context, service_output: object
) -> dict[str, object]:
    if not isinstance(service_output, dict):
        raise click.ClickException("topic_show returned an invalid service payload")
    payload = _strip_service_topic_fields(service_output)
    topic_id = payload.get("id")
    if "paper_count" not in payload and isinstance(topic_id, int):
        payload["paper_count"] = _topic_paper_count(ctx, topic_id)
    return payload


def _legacy_paper_list_payload_for_cli(
    ctx: click.Context,
    topic_name: str | None,
    status: str | None,
) -> list[dict[str, object]]:
    from .core.paper_pool import PaperPool

    db = get_db(ctx)
    conn = db.connect()
    try:
        topic_id = _topic_id_or_exit(conn, topic_name) if topic_name else None
        papers = PaperPool(conn).list_papers(topic_id=topic_id, status=status)
        return [dataclasses.asdict(paper_obj) for paper_obj in papers]
    finally:
        conn.close()


def _paper_list_payload_for_cli(
    ctx: click.Context,
    service_output: object,
    topic_name: str | None,
    status: str | None,
) -> list[dict[str, object]]:
    del ctx, topic_name
    if not isinstance(service_output, dict):
        raise click.ClickException("paper_list returned an invalid service payload")
    papers = service_output.get("papers", [])
    if not isinstance(papers, list):
        raise click.ClickException("paper_list returned an invalid papers payload")
    if not all(
        isinstance(paper_row, dict) and "status" in paper_row for paper_row in papers
    ):
        raise click.ClickException(
            "paper_list returned incomplete service paper payload"
        )
    payload = [dict(paper_row) for paper_row in papers]
    if status is not None:
        return [paper_row for paper_row in payload if paper_row.get("status") == status]
    return payload


def _legacy_provenance_summary_payload_for_cli(
    ctx: click.Context,
    topic: int | None,
    backend_name: str | None,
) -> dict[str, object]:
    from .provenance import ProvenanceRecorder

    summary = ProvenanceRecorder(get_db(ctx)).summarize(
        topic_id=topic, backend=backend_name
    )
    return dataclasses.asdict(summary)


def _provenance_summary_payload_for_cli(service_output: object) -> dict[str, object]:
    if not isinstance(service_output, dict):
        raise click.ClickException(
            "provenance_summary returned an invalid service payload"
        )
    return dict(service_output)


def _legacy_provenance_export_records_for_cli(
    ctx: click.Context,
    topic_id: int | None,
) -> list[object]:
    from .provenance import ProvenanceRecorder

    return ProvenanceRecorder(get_db(ctx)).list_records(topic_id=topic_id, limit=10000)


def _provenance_export_records_for_cli(service_output: object) -> list[object]:
    if not isinstance(service_output, dict):
        raise click.ClickException(
            "provenance_export returned an invalid service payload"
        )
    records = service_output.get("records", [])
    if not isinstance(records, list):
        raise click.ClickException(
            "provenance_export returned an invalid records payload"
        )
    return records


def _orchestrator_status_payload_for_cli(service_output: object) -> dict[str, object]:
    if not isinstance(service_output, dict):
        raise click.ClickException(
            "orchestrator_status returned an invalid service payload"
        )
    payload = dict(service_output)
    payload.pop("db_path", None)
    return payload


def _orchestrator_gate_check_payload_for_cli(
    service_output: object,
    stage: str | None,
) -> dict[str, object]:
    if not isinstance(service_output, dict):
        raise click.ClickException(
            "orchestrator_gate_check returned an invalid service payload"
        )
    if "gate_decision" not in service_output:
        raise click.ClickException(
            "orchestrator_gate_check returned an invalid gate payload"
        )
    return {
        "gate_decision": service_output["gate_decision"],
        "stage": stage or "current",
    }


def _create_backend(ctx: click.Context):
    from .execution import create_backend

    return create_backend(ctx.obj["backend_name"], db=get_db(ctx))


def _echo(ctx: click.Context, result: object, text: str | None = None) -> None:
    if ctx.obj.get("json"):
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
    elif text is not None:
        click.echo(text)


def _json_requested(ctx: click.Context, command_json: bool = False) -> bool:
    return bool(command_json or ctx.obj.get("json"))


def _exit_with_public_error(
    ctx: click.Context,
    *,
    code: str,
    message: str,
    exit_code: int,
    command_json: bool = False,
) -> None:
    if _json_requested(ctx, command_json):
        click.echo(
            json.dumps(
                {"error": {"code": code, "message": message}},
                ensure_ascii=False,
                default=str,
            )
        )
        ctx.exit(exit_code)
    raise click.ClickException(message)


def _positive_topic_id_or_exit(
    ctx: click.Context,
    raw_topic_id: str,
    *,
    command_json: bool = False,
) -> int:
    try:
        topic_id = int(raw_topic_id)
    except (TypeError, ValueError):
        topic_id = 0
    if topic_id > 0:
        return topic_id
    _exit_with_public_error(
        ctx,
        code="invalid_topic_id",
        message="topic_id must be a positive integer",
        exit_code=2,
        command_json=command_json,
    )
    raise click.ClickException("topic_id must be a positive integer")


def _write_text_output(output: str | None, content: str) -> None:
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
        return
    sys.stdout.write(content)


def _provenance_record_payload(record: object) -> dict[str, object]:
    if isinstance(record, dict):
        return dict(record)
    return dataclasses.asdict(record)


def _serialize_provenance_export(records: list[object], fmt: str) -> str:
    payload = [_provenance_record_payload(record) for record in records]
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, default=str)

    fieldnames = [
        "timestamp",
        "primitive_name",
        "backend",
        "model",
        "cost_usd",
        "success",
        "duration_ms",
    ]
    rows: list[dict[str, object]] = []
    for item in payload:
        duration_ms = 0
        started_at = item.get("started_at")
        finished_at = item.get("finished_at")
        if (
            isinstance(started_at, str)
            and isinstance(finished_at, str)
            and started_at
            and finished_at
        ):
            try:
                started = datetime.fromisoformat(started_at)
                finished = datetime.fromisoformat(finished_at)
                duration_ms = int((finished - started).total_seconds() * 1000)
            except ValueError:
                duration_ms = 0
        rows.append(
            {
                "timestamp": item.get("started_at", ""),
                "primitive_name": item.get("primitive", ""),
                "backend": item.get("backend", ""),
                "model": item.get("model_used", ""),
                "cost_usd": item.get("cost_usd", 0.0),
                "success": item.get("success", False),
                "duration_ms": duration_ms,
            }
        )

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _topic_id_or_exit(conn: sqlite3.Connection, topic_name: str) -> int:
    row = conn.execute("SELECT id FROM topics WHERE name = ?", (topic_name,)).fetchone()
    if row:
        return int(row[0])
    # Fall back to numeric topic id so agents can pass `--topic 49` instead
    # of a long topic name (name match above wins on collision).
    if topic_name.strip().isdigit():
        row = conn.execute(
            "SELECT id FROM topics WHERE id = ?", (int(topic_name.strip()),)
        ).fetchone()
        if row:
            return int(row[0])
    raise click.ClickException(f"topic '{topic_name}' not found")


def _decode_artifact_metadata(metadata: object) -> object:
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except json.JSONDecodeError:
            return {"raw": metadata}
    return metadata


def _paper_artifact_or_exit(
    conn: sqlite3.Connection, paper_id: int, artifact_type: str
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT artifact_type, path, metadata, created_at
        FROM paper_artifacts
        WHERE paper_id = ? AND artifact_type = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (paper_id, artifact_type),
    ).fetchone()
    if row is not None:
        return row
    if artifact_type == "paperindex_card":
        raise click.ClickException(
            f"paper {paper_id} has no paper card artifact; run 'paper annotate {paper_id}' first"
        )
    raise click.ClickException(
        f"artifact '{artifact_type}' for paper {paper_id} not found"
    )


def _load_json_artifact_or_exit(path: str | Path, artifact_label: str) -> object:
    artifact_path = Path(path)
    if not artifact_path.exists():
        raise click.ClickException(
            f"{artifact_label} artifact file not found: {artifact_path}"
        )
    try:
        return json.loads(artifact_path.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"{artifact_label} artifact at {artifact_path} is not valid JSON"
        ) from exc


def _card_text(card: dict[str, object], key: str) -> str:
    value = card.get(key, "")
    if isinstance(value, str):
        return value.strip()
    return ""


def _card_items(card: dict[str, object], key: str) -> list[str]:
    value = card.get(key, [])
    if isinstance(value, list):
        return [text for text in (str(item).strip() for item in value) if text]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def _join_or_fallback(values: list[str], fallback: str, limit: int = 3) -> str:
    selected = [item for item in values if item][:limit]
    return "; ".join(selected) if selected else fallback


def _topic_note_next_action(artifact_status: dict[str, object]) -> str:
    return (
        "draft_topic_note_from_card"
        if artifact_status["has_card"]
        else "write_topic_note"
    )


def _draft_topic_note_from_card(
    paper_obj: Paper,
    topic_name: str,
    note_type: str,
    card: dict[str, object],
    topic_relevance: str = "",
) -> str:
    try:
        parsed_card = PaperCard.from_dict(card)
    except PaperCardSchemaError as exc:
        raise click.ClickException(str(exc)) from exc
    if card.get("schema_version") == "papercard/v3":
        card = parsed_card.to_dict()
    open_fields = [
        (
            str(item.get("name") or "").strip(),
            str(item.get("value") or "").strip(),
        )
        for item in card.get("fields", [])
        if isinstance(item, dict) and str(item.get("value") or "").strip()
    ]

    def open_values(*names: str) -> list[str]:
        return [value for name, value in open_fields if name in names]

    title = paper_obj.title or _card_text(card, "title") or f"Paper {paper_obj.id}"
    core_idea = (
        _card_text(card, "core_idea")
        or next(iter(open_values("core_method", "core_idea")), "")
        or "No summary extracted yet. Review the PDF and card manually."
    )
    method_summary = (
        _card_text(card, "method_summary")
        or next(iter(open_values("method_component", "method_summary")), "")
        or "Method details were not extracted yet."
    )
    key_results = _card_items(card, "key_results") or open_values(
        "key_result", "key_results", "result", "results"
    )
    limitations = _card_items(card, "limitations") or open_values(
        "self_declared_limitation"
    )
    evidence_sections = [
        str(item.get("section")).strip()
        for item in card.get("evidence", [])
        if isinstance(item, dict) and str(item.get("section", "")).strip()
    ]
    evidence_sections.extend(
        str(item.get("quote") or "").strip()
        for key in ("fields", "relations", "independent_defects")
        for item in card.get(key, [])
        if isinstance(item, dict) and str(item.get("quote") or "").strip()
    )
    results_line = _join_or_fallback(key_results, "No key results were extracted yet.")
    limitations_line = _join_or_fallback(
        limitations, "No explicit limitations were extracted yet."
    )
    evidence_line = _join_or_fallback(
        evidence_sections, "No evidence sections were extracted.", limit=4
    )
    relevance_line = topic_relevance or "not specified"

    if note_type == "relevance":
        lines = [
            f"Topic: {topic_name}",
            f"Paper: {title}",
            f"Linked relevance: {relevance_line}",
            f"Why it matters: {core_idea}",
            f"Method signal: {method_summary}",
            f"Evidence worth citing: {results_line}",
            f"Watch-outs: {limitations_line}",
        ]
    elif note_type == "comparison":
        lines = [
            f"Topic: {topic_name}",
            f"Paper: {title}",
            f"Comparison focus: {core_idea}",
            f"Method to compare against our work: {method_summary}",
            f"Reported outcomes: {results_line}",
            f"Sections to inspect manually: {evidence_line}",
        ]
    elif note_type == "usage_plan":
        lines = [
            f"Topic: {topic_name}",
            f"Paper: {title}",
            f"Planned use: Reuse or verify the following idea for this topic: {core_idea}",
            f"Implementation angle: {method_summary}",
            f"What to extract next: {results_line}",
            f"Validation checklist: {limitations_line}",
        ]
    else:
        lines = [
            f"Topic: {topic_name}",
            f"Paper: {title}",
            f"Main claim to scrutinize: {core_idea}",
            f"Method risk: {method_summary}",
            f"Evidence coverage: {results_line}",
            f"Potential weaknesses: {limitations_line}",
        ]
    return "\n".join(lines)


def _paper_status_payload(
    conn: sqlite3.Connection, paper_obj: Paper
) -> dict[str, object]:
    from .core.paper_pool import PaperPool

    pool = PaperPool(conn)
    annotations = pool.get_annotations(paper_obj.id or 0)
    topics = conn.execute(
        """
        SELECT t.id AS topic_id, t.name, pt.relevance
        FROM paper_topics pt
        JOIN topics t ON pt.topic_id = t.id
        WHERE pt.paper_id = ?
        ORDER BY t.name, t.id
        """,
        (paper_obj.id,),
    ).fetchall()
    artifacts = conn.execute(
        "SELECT artifact_type, path, metadata, created_at FROM paper_artifacts WHERE paper_id = ? ORDER BY created_at DESC, id DESC",
        (paper_obj.id,),
    ).fetchall()
    notes = conn.execute(
        """
        SELECT t.name AS topic_name, n.topic_id, n.note_type, n.source, n.created_at
        FROM topic_paper_notes n
        JOIN topics t ON n.topic_id = t.id
        WHERE n.paper_id = ?
        ORDER BY t.name, n.note_type
        """,
        (paper_obj.id,),
    ).fetchall()

    current_hash = paper_obj.pdf_hash
    completed_sections = sorted(
        item.section
        for item in annotations
        if item.content
        and (not current_hash or item.pdf_hash_at_extraction == current_hash)
    )
    stale_sections = sorted(
        item.section
        for item in annotations
        if current_hash
        and item.pdf_hash_at_extraction
        and item.pdf_hash_at_extraction != current_hash
    )
    missing_sections = sorted(
        section
        for section in REQUIRED_ANNOTATION_SECTIONS
        if section not in completed_sections
    )
    artifact_rows = [dict(row) for row in artifacts]
    artifact_types = sorted({item["artifact_type"] for item in artifact_rows})
    artifact_details = [
        {
            "artifact_type": item["artifact_type"],
            "path": item["path"],
            "created_at": item["created_at"],
            "metadata": _decode_artifact_metadata(item["metadata"]),
        }
        for item in artifact_rows
    ]
    notes_by_topic: dict[str, list[str]] = {}
    for row in notes:
        notes_by_topic.setdefault(row["topic_name"], []).append(row["note_type"])
    for topic_name in list(notes_by_topic):
        notes_by_topic[topic_name] = sorted(notes_by_topic[topic_name])

    return {
        "paper": dataclasses.asdict(paper_obj),
        "linked_topics": [dict(row) for row in topics],
        "annotation_status": {
            "completed_sections": completed_sections,
            "missing_sections": missing_sections,
            "stale_sections": stale_sections,
            "count": len(completed_sections),
            "total_expected": len(REQUIRED_ANNOTATION_SECTIONS),
        },
        "artifact_status": {
            "count": len(artifact_details),
            "types": artifact_types,
            "has_structure": "paperindex_structure" in artifact_types,
            "has_card": "paperindex_card" in artifact_types,
            "items": artifact_details,
        },
        "topic_note_status": {
            "count": len(notes),
            "by_topic": notes_by_topic,
        },
        "ready": {
            "has_pdf": bool(paper_obj.pdf_path),
            "needs_annotation": bool(missing_sections),
            "can_export_card": "paperindex_card" in artifact_types,
        },
    }


def _paper_queue_entry(
    topic_name: str,
    status_payload: dict[str, object],
    conn: sqlite3.Connection | None = None,
    topic_id: int | None = None,
) -> dict[str, object]:
    paper = status_payload["paper"]
    annotation_status = status_payload["annotation_status"]
    artifact_status = status_payload["artifact_status"]
    topic_note_status = status_payload["topic_note_status"]
    ready = status_payload["ready"]
    topic_notes = sorted(topic_note_status["by_topic"].get(topic_name, []))

    next_actions: list[str] = []
    if not ready["has_pdf"]:
        bucket = "missing_pdf"
        next_actions.append("attach_pdf")
    elif annotation_status["stale_sections"]:
        bucket = "stale_annotations"
        next_actions.append("refresh_stale_annotations")
    elif annotation_status["missing_sections"]:
        bucket = "missing_sections"
        next_actions.append("annotate_sections")
    elif not topic_notes:
        bucket = "missing_topic_note"
        next_actions.append(_topic_note_next_action(artifact_status))
    else:
        bucket = "ready"
        next_actions.append("ready")

    if ready["has_pdf"] and not topic_notes and bucket != "missing_topic_note":
        next_actions.append(_topic_note_next_action(artifact_status))

    priority_rank = {
        "missing_pdf": 0,
        "stale_annotations": 1,
        "missing_sections": 2,
        "missing_card": 3,
        "missing_topic_note": 4,
        "ready": 5,
    }[bucket]

    has_pending_task = False
    if conn is not None and topic_id is not None:
        pending_row = conn.execute(
            "SELECT 1 FROM tasks WHERE topic_id = ? AND paper_id = ? AND status IN ('pending', 'in_progress') LIMIT 1",
            (topic_id, paper["id"]),
        ).fetchone()
        has_pending_task = pending_row is not None

    return {
        "paper_id": paper["id"],
        "title": paper["title"],
        "status": paper["status"],
        "queue_bucket": bucket,
        "priority_rank": priority_rank,
        "has_pdf": ready["has_pdf"],
        "completed_sections": annotation_status["completed_sections"],
        "missing_sections": annotation_status["missing_sections"],
        "stale_sections": annotation_status["stale_sections"],
        "artifact_types": artifact_status["types"],
        "topic_notes": topic_notes,
        "next_actions": next_actions,
        "has_pending_task": has_pending_task,
    }


def _check_review_ready(conn: sqlite3.Connection, topic_id: int) -> bool:
    """Return True when topic has no open tasks and at least one done task."""
    open_tasks = conn.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE topic_id = ? AND status IN ('pending', 'in_progress')",
        (topic_id,),
    ).fetchone()["cnt"]
    done_tasks = conn.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE topic_id = ? AND status = 'done'",
        (topic_id,),
    ).fetchone()["cnt"]
    return open_tasks == 0 and done_tasks > 0


def _cli_registration_deps() -> dict[str, object]:
    return {
        "check_review_ready": _check_review_ready,
        "create_backend": lambda ctx: _create_backend(ctx),
        "decode_artifact_metadata": _decode_artifact_metadata,
        "draft_topic_note_from_card": _draft_topic_note_from_card,
        "echo": lambda ctx, result, text=None: _echo(ctx, result, text),
        "exit_with_public_error": lambda ctx, **kwargs: _exit_with_public_error(
            ctx, **kwargs
        ),
        "export_records_for_cli": _provenance_export_records_for_cli,
        "get_db": lambda ctx: get_db(ctx),
        "get_runtime_config": lambda ctx: get_runtime_config(ctx),
        "invoke_service_or_exit": (
            lambda ctx, command_name, arguments: _invoke_service_or_exit(
                ctx, command_name, arguments
            )
        ),
        "json_requested": lambda ctx, command_json=False: _json_requested(
            ctx, command_json
        ),
        "legacy_export_records_for_cli": (
            lambda ctx, topic_id: _legacy_provenance_export_records_for_cli(
                ctx, topic_id
            )
        ),
        "legacy_summary_payload_for_cli": (
            lambda ctx, topic, backend_name: _legacy_provenance_summary_payload_for_cli(
                ctx, topic, backend_name
            )
        ),
        "load_json_artifact_or_exit": _load_json_artifact_or_exit,
        "note_types": NOTE_TYPES,
        "orchestrator_gate_check_payload_for_cli": (
            _orchestrator_gate_check_payload_for_cli
        ),
        "orchestrator_status_payload_for_cli": _orchestrator_status_payload_for_cli,
        "paper_artifact_or_exit": _paper_artifact_or_exit,
        "paper_list_payload_for_cli": _paper_list_payload_for_cli,
        "paper_queue_entry": _paper_queue_entry,
        "paper_status_payload": _paper_status_payload,
        "positive_topic_id_or_exit": _positive_topic_id_or_exit,
        "serialize_export": _serialize_provenance_export,
        "summary_payload_for_cli": _provenance_summary_payload_for_cli,
        "topic_id_or_exit": _topic_id_or_exit,
        "topic_list_payload_for_cli": _topic_list_payload_for_cli,
        "topic_show_payload_for_cli": _topic_show_payload_for_cli,
        "write_text_output": _write_text_output,
    }


@click.group()
@click.version_option(version=_RH_VERSION, prog_name="rh")
@click.option(
    "--db", "db_path", default=None, help="SQLite database path (explicit override)"
)
@click.option("--json", "json_output", is_flag=True, default=False, help="JSON output")
@click.option(
    "--backend",
    type=click.Choice(BACKEND_CHOICES),
    default=None,
    help="Execution backend",
)
@click.pass_context
def main(
    ctx: click.Context, db_path: str | None, json_output: bool, backend: str | None
) -> None:
    """Research Hub - agent-first research workflow platform."""
    # Shared hosts confine callers to their own tree; no-op when RH_PATH_JAIL is
    # unset. Scans sys.argv so subcommand flags are covered too, in both the
    # "--opt V" and "--opt=V" spellings.
    try:
        path_jail.check_argv(sys.argv[1:])
    except path_jail.PathJailError as exc:
        raise click.UsageError(str(exc)) from exc
    loaded_env = _load_default_env_files()
    ctx.ensure_object(dict)
    ctx.obj["loaded_env_files"] = loaded_env
    ctx.obj["db_path"] = db_path
    ctx.obj["backend_override"] = backend
    ctx.obj["json"] = json_output
    ctx.obj["runtime_config"] = load_runtime_config(db_path, explicit_backend=backend)
    ctx.obj["backend_name"] = ctx.obj["runtime_config"].execution_backend


_cli_registration.register_main_before_topic(main, _cli_registration_deps())


@main.group()
def topic() -> None:
    """Manage research topics."""


_cli_registration.register_topic(topic, _cli_registration_deps())
_cli_registration.register_main_between_topic_and_paper(main, _cli_registration_deps())


@main.group()
def paper() -> None:
    """Manage papers."""


_cli_registration.register_paper_and_remaining(
    main, topic, paper, _cli_registration_deps()
)


def _inject_global_json_flag(command: click.Command) -> None:
    """Accept the global ``--json`` flag after the subcommand too (BUG-010).

    ``--json`` is a group-level option, so Click rejected ``rh topic state
    --json`` with "No such option: --json". Append a non-exposed ``--json`` flag
    to every leaf command that does not already define one, folding it into
    ``ctx.obj["json"]``. Commands with their own ``--json``
    are left untouched.
    """
    if isinstance(command, click.Group):
        for sub in command.commands.values():
            _inject_global_json_flag(sub)
        return
    for param in command.params:
        if isinstance(param, click.Option) and "--json" in param.opts:
            return

    def _set_json(ctx: click.Context, _param: click.Parameter, value: bool) -> bool:
        if value:
            if ctx.obj is None:
                ctx.obj = {}
            ctx.obj["json"] = True
        return value

    command.params.append(
        click.Option(
            ["--json"],
            is_flag=True,
            default=False,
            expose_value=False,
            help="Emit JSON output.",
            callback=_set_json,
        )
    )


_inject_global_json_flag(main)


if __name__ == "__main__":
    main()
