"""Private local Research Wiki bundle materialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .research_wiki import ResearchWikiExport
from .research_wiki_insights import (
    ResearchWikiInsightReport,
    find_research_wiki_insights,
    render_research_wiki_insight_report_markdown,
    research_wiki_insight_report_to_dict,
)
from .research_wiki_validation import (
    ResearchWikiValidationReport,
    render_research_wiki_validation_report_markdown,
    validate_research_wiki_export,
)


RESEARCH_WIKI_BUNDLE_SCHEMA_VERSION = "research_wiki_bundle.v1"


@dataclass(frozen=True)
class ResearchWikiBundleExport:
    topic_id: int
    bundle_path: Path
    manifest: dict[str, Any]
    written_relative_paths: tuple[str, ...]


def materialize_research_wiki_bundle(
    export: ResearchWikiExport,
    *,
    bundle_path: str | Path,
    insight_report: ResearchWikiInsightReport | None = None,
    validation_report: ResearchWikiValidationReport | None = None,
) -> ResearchWikiBundleExport:
    """Write a private local Research Wiki bundle to a caller-provided path."""

    path = Path(bundle_path)
    path.mkdir(parents=True, exist_ok=True)
    insights = insight_report or find_research_wiki_insights(export)
    validation = validation_report or validate_research_wiki_export(export)
    _validate_report_topic(export, insights, validation)

    written: list[str] = []
    for page in sorted(export.pages, key=lambda item: item.relative_path):
        relative_path = f"vault/{page.relative_path}"
        page_path = _safe_output_path(path, relative_path)
        _write_text(page_path, page.markdown)
        written.append(relative_path)

    insights_path = path / "insights.md"
    validation_path = path / "validation.md"
    manifest_path = path / "manifest.json"
    _write_text(insights_path, render_research_wiki_insight_report_markdown(insights))
    _write_text(
        validation_path,
        render_research_wiki_validation_report_markdown(validation),
    )
    written.extend(["insights.md", "validation.md"])

    manifest = _bundle_manifest(
        export=export,
        insight_report=insights,
        validation_report=validation,
        vault_pages=sorted(
            written_path
            for written_path in written
            if written_path.startswith("vault/")
        ),
    )
    _write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    written.append("manifest.json")

    return ResearchWikiBundleExport(
        topic_id=export.topic_id,
        bundle_path=path,
        manifest=manifest,
        written_relative_paths=tuple(sorted(written)),
    )


def _bundle_manifest(
    *,
    export: ResearchWikiExport,
    insight_report: ResearchWikiInsightReport,
    validation_report: ResearchWikiValidationReport,
    vault_pages: list[str],
) -> dict[str, Any]:
    insight_data = research_wiki_insight_report_to_dict(insight_report)
    return {
        "schema_version": RESEARCH_WIKI_BUNDLE_SCHEMA_VERSION,
        "topic_id": export.topic_id,
        "page_count": len(export.pages),
        "insight_count": len(insight_report.insights),
        "validation_issue_count": validation_report.issue_count,
        "files": {
            "vault_root": "vault",
            "vault_pages": vault_pages,
            "insights": "insights.md",
            "validation": "validation.md",
            "manifest": "manifest.json",
        },
        "insights": {
            "insight_count": insight_data["insight_count"],
            "types": sorted(
                {str(insight["insight_type"]) for insight in insight_data["insights"]}
            ),
        },
        "validation": {
            "valid": validation_report.valid,
            "issue_count": validation_report.issue_count,
            "counts_by_code": validation_report.counts_by_code,
        },
    }


def _validate_report_topic(
    export: ResearchWikiExport,
    insight_report: ResearchWikiInsightReport,
    validation_report: ResearchWikiValidationReport,
) -> None:
    if insight_report.topic_id != export.topic_id:
        raise ValueError("insight report topic_id must match export topic_id")
    if validation_report.topic_id != export.topic_id:
        raise ValueError("validation report topic_id must match export topic_id")


def _safe_output_path(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe wiki page path: {relative_path}")
    return root.joinpath(path)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
