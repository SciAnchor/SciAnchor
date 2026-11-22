"""FastAPI route registration for report generation and sharing endpoints."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel


class ReportGenerateRequest(BaseModel):
    template: str = "abstract_only"
    title: str = ""
    draft_missing: bool = True
    extra_instructions: str = ""


class ReportBatchGenerateRequest(BaseModel):
    templates: list[str]
    title: str = ""
    draft_missing: bool = True
    extra_instructions: str = ""


def _resolve_db_service(db_path_provider: Callable[[], Path]):
    from research_harness.storage.db import Database as _DB

    return _DB(Path(str(db_path_provider())))


def register_report_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Path],
    logger: logging.Logger | None = None,
) -> None:
    """Register report routes on an existing FastAPI app."""

    route_logger = logger or logging.getLogger(__name__)

    @app.get("/api/topics/{topic_id}/reports")
    def list_topic_reports(topic_id: int):
        """Sprint 1 - list all reports for a topic."""
        from research_harness.reports import list_reports

        try:
            db = _resolve_db_service(db_path_provider)
            reports = list_reports(db, topic_id)
        except Exception as exc:
            route_logger.error(
                "list_reports failed: %s\n%s", exc, traceback.format_exc()
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "topic_id": topic_id,
            "reports": [
                {
                    "id": r.id,
                    "template": r.template,
                    "title": r.title,
                    "sections": r.sections,
                    "version_major": r.version_major,
                    "version_minor": r.version_minor,
                    "has_share": r.has_share,
                    "share_expires_at": r.share_expires_at,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                    "word_count": r.word_count,
                    "metadata": r.metadata,
                }
                for r in reports
            ],
        }

    @app.post("/api/topics/{topic_id}/reports")
    def create_topic_report(topic_id: int, body: ReportGenerateRequest):
        """Sprint 1 - generate a new report version."""
        from research_harness.reports import generate_report

        try:
            db = _resolve_db_service(db_path_provider)
            report = generate_report(
                db,
                topic_id,
                template=body.template,
                title=body.title,
                draft_missing=body.draft_missing,
                extra_instructions=body.extra_instructions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            route_logger.error(
                "generate_report failed: %s\n%s", exc, traceback.format_exc()
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "id": report.id,
            "topic_id": report.topic_id,
            "template": report.template,
            "version_minor": report.version_minor,
            "word_count": report.word_count,
            "metadata": report.metadata,
        }

    @app.post("/api/topics/{topic_id}/reports:batch")
    def create_topic_reports_batch(topic_id: int, body: ReportBatchGenerateRequest):
        """Composer-style batch - generate several templates in one request.

        Each template runs through the standard generate_report flow with the same
        ``extra_instructions``. Returns per-template success/error so the UI can
        render a partial-success table without losing the good ones.
        """
        from research_harness.reports import generate_report

        if not body.templates:
            raise HTTPException(status_code=400, detail="templates must not be empty")

        db = _resolve_db_service(db_path_provider)
        results: list[dict[str, Any]] = []
        for template in body.templates:
            try:
                report = generate_report(
                    db,
                    topic_id,
                    template=template,
                    title=body.title,
                    draft_missing=body.draft_missing,
                    extra_instructions=body.extra_instructions,
                )
                results.append(
                    {
                        "template": template,
                        "ok": True,
                        "id": report.id,
                        "version_minor": report.version_minor,
                        "word_count": report.word_count,
                    }
                )
            except ValueError as exc:
                results.append({"template": template, "ok": False, "error": str(exc)})
            except Exception as exc:
                route_logger.error(
                    "batch generate_report[%s] failed: %s\n%s",
                    template,
                    exc,
                    traceback.format_exc(),
                )
                results.append({"template": template, "ok": False, "error": str(exc)})

        return {"topic_id": topic_id, "results": results}

    @app.get("/api/reports/templates")
    def list_report_templates_v2():
        """Metadata for the four built-in report templates.

        Registered BEFORE the /{report_id} dynamic route so 'templates' is not
        parsed as an integer path param.
        """
        from research_harness.reports import REPORT_TEMPLATES

        return {"templates": REPORT_TEMPLATES}

    @app.get("/api/reports/{report_id}")
    def get_report_detail(report_id: int):
        from research_harness.reports import get_report

        try:
            db = _resolve_db_service(db_path_provider)
            rep = get_report(db, report_id)
        except Exception as exc:
            route_logger.error("get_report failed: %s\n%s", exc, traceback.format_exc())
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if rep is None:
            raise HTTPException(status_code=404, detail="report not found")
        rep.pop("share_token", None)
        return rep

    @app.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
    def get_report_html(report_id: int):
        from research_harness.reports import get_report

        db = _resolve_db_service(db_path_provider)
        rep = get_report(db, report_id)
        if rep is None:
            raise HTTPException(status_code=404, detail="report not found")
        return HTMLResponse(content=rep.get("content_html") or "", status_code=200)

    @app.get("/api/reports/{report_id}/markdown", response_class=PlainTextResponse)
    def get_report_markdown(report_id: int):
        from research_harness.reports import get_report

        db = _resolve_db_service(db_path_provider)
        rep = get_report(db, report_id)
        if rep is None:
            raise HTTPException(status_code=404, detail="report not found")
        return PlainTextResponse(rep.get("content_md") or "")

    @app.post("/api/reports/{report_id}/share")
    def share_report(report_id: int, body: dict[str, Any] | None = None):
        from research_harness.reports import create_share_token

        expires = 14
        if body and "expires_in_days" in body:
            try:
                expires = int(body["expires_in_days"])
            except (TypeError, ValueError):
                expires = 14
        try:
            db = _resolve_db_service(db_path_provider)
            out = create_share_token(db, report_id, expires_in_days=expires)
        except Exception as exc:
            route_logger.error(
                "share_report failed: %s\n%s", exc, traceback.format_exc()
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return out

    @app.get("/api/shared/reports/{token}")
    def get_shared_report(token: str):
        """Public read-only endpoint advisors hit via the share link."""
        from research_harness.reports.service import get_report_by_share_token

        db = _resolve_db_service(db_path_provider)
        rep = get_report_by_share_token(db, token)
        if rep is None:
            raise HTTPException(status_code=404, detail="share link not found")
        if isinstance(rep, dict) and rep.get("error"):
            raise HTTPException(status_code=410, detail=rep["error"])
        return {
            "id": rep.get("id"),
            "topic_name": rep.get("topic_name"),
            "title": rep.get("title"),
            "template": rep.get("template"),
            "sections": rep.get("sections"),
            "content_md": rep.get("content_md"),
            "content_html": rep.get("content_html"),
            "version_minor": rep.get("version_minor"),
            "created_at": rep.get("created_at"),
        }
