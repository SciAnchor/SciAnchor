"""Private advisory validation for Research Wiki exports."""

from __future__ import annotations

from dataclasses import dataclass

from .research_wiki import (
    ResearchWikiExport,
    ResearchWikiPage,
    WIKI_PAGE_SCHEMA_VERSION,
    _normalize_link_target,
    extract_wikilinks,
)


@dataclass(frozen=True)
class ResearchWikiValidationIssue:
    code: str
    severity: str
    page_path: str
    message: str
    target: str = ""


@dataclass(frozen=True)
class ResearchWikiValidationReport:
    topic_id: int
    page_count: int
    issues: tuple[ResearchWikiValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def counts_by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return {key: counts[key] for key in sorted(counts)}


def validate_research_wiki_export(
    export: ResearchWikiExport,
) -> ResearchWikiValidationReport:
    """Return a private advisory validation report for a Research Wiki export."""

    issues: list[ResearchWikiValidationIssue] = []
    available = {page.relative_path for page in export.pages}
    seen_paths: set[str] = set()
    duplicate_paths: set[str] = set()
    for page in export.pages:
        if page.relative_path in seen_paths:
            duplicate_paths.add(page.relative_path)
        seen_paths.add(page.relative_path)

    for relative_path in sorted(duplicate_paths):
        issues.append(
            ResearchWikiValidationIssue(
                code="duplicate_page_path",
                severity="error",
                page_path=relative_path,
                message="duplicate page path",
            )
        )

    for page in export.pages:
        issues.extend(_frontmatter_schema_issues(export.topic_id, page))
        issues.extend(_evidence_anchor_issues(page))
        issues.extend(_wikilink_issues(page, available))

    ordered = tuple(
        sorted(
            issues,
            key=lambda issue: (
                issue.code,
                issue.page_path,
                issue.target,
                issue.message,
                issue.severity,
            ),
        )
    )
    return ResearchWikiValidationReport(
        topic_id=export.topic_id,
        page_count=len(export.pages),
        issues=ordered,
    )


def render_research_wiki_validation_report_markdown(
    report: ResearchWikiValidationReport,
) -> str:
    """Render a deterministic Markdown validation report."""

    lines = [
        "# Research Wiki Validation",
        "",
        f"- Topic id: {report.topic_id}",
        f"- Page count: {report.page_count}",
        f"- Valid: {'yes' if report.valid else 'no'}",
        f"- Issue count: {report.issue_count}",
        "",
        "## Issue Counts",
        "",
    ]
    if not report.counts_by_code:
        lines.extend(["- none", ""])
    else:
        for code, count in report.counts_by_code.items():
            lines.append(f"- `{code}`: {count}")
        lines.append("")

    lines.extend(["## Issues", ""])
    if not report.issues:
        lines.extend(["- none", ""])
    else:
        for issue in report.issues:
            lines.append(
                f"- `{issue.code}` ({issue.severity}) "
                f"`{issue.page_path}`: {issue.message}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _frontmatter_schema_issues(
    topic_id: int,
    page: ResearchWikiPage,
) -> list[ResearchWikiValidationIssue]:
    issues: list[ResearchWikiValidationIssue] = []
    metadata = page.frontmatter
    if metadata.get("schema_version") != WIKI_PAGE_SCHEMA_VERSION:
        issues.append(
            _validation_issue(
                "frontmatter_schema",
                page.relative_path,
                f"schema_version must be {WIKI_PAGE_SCHEMA_VERSION}",
            )
        )
    if metadata.get("topic_id") != topic_id:
        issues.append(
            _validation_issue(
                "frontmatter_schema",
                page.relative_path,
                "topic_id must match export topic_id",
            )
        )
    if metadata.get("page_type") != page.page_type:
        issues.append(
            _validation_issue(
                "frontmatter_schema",
                page.relative_path,
                "page_type must match page.page_type",
            )
        )
    if metadata.get("title") != page.title or not str(metadata.get("title") or ""):
        issues.append(
            _validation_issue(
                "frontmatter_schema",
                page.relative_path,
                "title must be non-empty and match page title",
            )
        )
    if not isinstance(metadata.get("sources"), list):
        issues.append(
            _validation_issue(
                "frontmatter_schema",
                page.relative_path,
                "sources must be a list",
            )
        )
    return issues


def _evidence_anchor_issues(
    page: ResearchWikiPage,
) -> list[ResearchWikiValidationIssue]:
    sources = page.frontmatter.get("sources")
    if not isinstance(sources, list) or not sources:
        return [
            _validation_issue(
                "missing_evidence_anchor",
                page.relative_path,
                "missing evidence anchor",
            )
        ]

    issues: list[ResearchWikiValidationIssue] = []
    required = ("source_type", "source_id", "source_hash", "evidence_snippet")
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            issues.append(
                _validation_issue(
                    "missing_evidence_anchor",
                    page.relative_path,
                    f"source {index} is not an evidence anchor object",
                )
            )
            continue
        missing = [key for key in required if not str(source.get(key) or "")]
        if missing:
            issues.append(
                _validation_issue(
                    "missing_evidence_anchor",
                    page.relative_path,
                    f"source {index} missing {', '.join(missing)}",
                )
            )
    return issues


def _wikilink_issues(
    page: ResearchWikiPage,
    available: set[str],
) -> list[ResearchWikiValidationIssue]:
    issues: list[ResearchWikiValidationIssue] = []
    for link in extract_wikilinks(page.body):
        normalized = _normalize_link_target(link.target)
        if normalized and normalized not in available:
            issues.append(
                _validation_issue(
                    "unresolved_wikilink",
                    page.relative_path,
                    f"unresolved wikilink `{link.target}`",
                    target=link.target,
                )
            )
    return issues


def _validation_issue(
    code: str,
    page_path: str,
    message: str,
    *,
    target: str = "",
) -> ResearchWikiValidationIssue:
    return ResearchWikiValidationIssue(
        code=code,
        severity="error",
        page_path=page_path,
        message=message,
        target=target,
    )
