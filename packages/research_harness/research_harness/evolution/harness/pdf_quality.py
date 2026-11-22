"""PDF/LaTeX quality signals for project-level self-evolution."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import (
    EvidenceReference,
    EvolutionFinding,
    PDFQualityIssue,
    PDFQualitySignal,
    RecommendedAction,
)


_MALFORMED_COMMAND_RE = re.compile(
    r"(?P<prefix>^|[^\w\\])\t(?P<command>extbf|extit|exttt|citep|citet|ref|label)\{"
)
_OVERFULL_RE = re.compile(
    r"Overfull \\hbox \((?P<points>[0-9.]+)pt too wide\)"
    r"(?: in paragraph at lines (?P<start>\d+)(?:--(?P<end>\d+))?)?"
)
_UNDERFULL_RE = re.compile(
    r"Underfull \\hbox"
    r"(?: \(badness (?P<badness>\d+)\))?"
    r"(?: in paragraph at lines (?P<start>\d+)(?:--(?P<end>\d+))?)?"
)
_RECOMPILE_REPAIRABLE_CATEGORIES = {
    "invalid_utf8",
    "latex_error",
    "malformed_latex_command",
    "missing_pdf",
    "missing_tex",
    "undefined_citation",
    "undefined_control_sequence",
}
_LAYOUT_CATEGORIES = {"overfull_hbox", "underfull_hbox"}
_ENCODING_CATEGORIES = {"invalid_utf8"}


def scan_pdf_quality_bundle(
    *,
    tex_path: str,
    pdf_path: str = "",
    log_path: str = "",
    topic_id: int = 0,
    target_profile: str = "",
    artifact_id: int = 0,
) -> PDFQualitySignal:
    """Scan a final bundle for deterministic PDF/TeX quality issues."""
    issues: list[PDFQualityIssue] = []
    tex_file = Path(tex_path) if tex_path else None
    log_file = Path(log_path) if log_path else None
    tex_lines: tuple[str, ...] = ()

    if tex_file and tex_file.exists():
        tex_text = tex_file.read_text(encoding="utf-8", errors="replace")
        tex_lines = tuple(tex_text.splitlines())
        issues.extend(_scan_tex(tex_file, tex_text=tex_text))
    elif tex_path:
        issues.append(
            PDFQualityIssue(
                category="missing_tex",
                severity="critical",
                message=f"TeX file not found: {tex_path}",
                source_path=tex_path,
            )
        )

    if log_file and log_file.exists():
        issues.extend(_scan_log(log_file, tex_lines=tex_lines))
    elif log_path:
        issues.append(
            PDFQualityIssue(
                category="missing_log",
                severity="medium",
                message=f"LaTeX log not found: {log_path}",
                source_path=log_path,
            )
        )

    if pdf_path and not Path(pdf_path).exists():
        issues.append(
            PDFQualityIssue(
                category="missing_pdf",
                severity="critical",
                message=f"Compiled PDF not found: {pdf_path}",
                source_path=pdf_path,
            )
        )

    issue_count = len(issues)
    blocking_issue_count = sum(
        1 for issue in issues if issue.severity in {"critical", "high"}
    )
    recompile_repairable_issue_count = _count_categories(
        issues,
        _RECOMPILE_REPAIRABLE_CATEGORIES,
    )
    layout_issue_count = _count_categories(issues, _LAYOUT_CATEGORIES)
    encoding_issue_count = _count_categories(issues, _ENCODING_CATEGORIES)
    artifact_size_bytes = _artifact_size_bytes(
        tex_path=tex_path,
        pdf_path=pdf_path,
        log_path=log_path,
    )

    return PDFQualitySignal(
        topic_id=topic_id,
        target_profile=target_profile,
        tex_path=tex_path,
        pdf_path=pdf_path,
        log_path=log_path,
        artifact_id=artifact_id,
        issues=tuple(issues),
        transcript_ref=(
            f"project_artifacts:{artifact_id}:final_bundle"
            if artifact_id
            else f"pdf_quality:{topic_id}:{target_profile}"
        ),
        metadata={
            "issue_count": issue_count,
            "blocking_issue_count": blocking_issue_count,
            "recompile_repairable_issue_count": recompile_repairable_issue_count,
            "layout_issue_count": layout_issue_count,
            "encoding_issue_count": encoding_issue_count,
            "artifact_size_bytes": artifact_size_bytes,
            "cost_quality_telemetry": {
                "schema_version": 1,
                "artifact_id": artifact_id,
                "topic_id": topic_id,
                "target_profile": target_profile,
                "issue_count": issue_count,
                "blocking_issue_count": blocking_issue_count,
                "recompile_repairable_issue_count": recompile_repairable_issue_count,
                "layout_issue_count": layout_issue_count,
                "encoding_issue_count": encoding_issue_count,
                "artifact_size_bytes": artifact_size_bytes,
            },
        },
    )


def triage_pdf_quality_signal(signal: PDFQualitySignal) -> EvolutionFinding:
    """Convert PDF quality scan results into a project-level finding."""
    priority = _priority(signal.issues)
    summary = _summary(signal)
    surfaces = _surfaces(signal)
    return EvolutionFinding(
        finding_id=_finding_id(signal),
        source_kind="pdf_quality_signal",
        category=_finding_category(signal),
        priority=priority,
        summary=summary,
        affected_surfaces=surfaces,
        evidence_refs=(
            EvidenceReference(ref=signal.transcript_ref, source_type="local"),
        ),
        recommended_actions=_actions(signal),
        metadata={
            "topic_id": signal.topic_id,
            "target_profile": signal.target_profile,
            "artifact_id": signal.artifact_id,
            "tex_path": signal.tex_path,
            "pdf_path": signal.pdf_path,
            "log_path": signal.log_path,
            "issue_count": len(signal.issues),
            "issues": tuple(
                {
                    "category": issue.category,
                    "severity": issue.severity,
                    "message": issue.message,
                    "source_path": issue.source_path,
                    "line_number": issue.line_number,
                    "metadata": issue.metadata,
                }
                for issue in signal.issues
            ),
            **signal.metadata,
        },
    )


def _scan_tex(tex_file: Path, *, tex_text: str = "") -> list[PDFQualityIssue]:
    issues: list[PDFQualityIssue] = []
    text = tex_text or tex_file.read_text(encoding="utf-8", errors="replace")
    for line_number, line in enumerate(text.splitlines(), 1):
        for match in _MALFORMED_COMMAND_RE.finditer(line):
            command = match.group("command")
            issues.append(
                PDFQualityIssue(
                    category="malformed_latex_command",
                    severity="high",
                    message=(
                        f"Possible escaped LaTeX command lost its backslash: "
                        f"tab + {command}{{ at line {line_number}."
                    ),
                    source_path=str(tex_file),
                    line_number=line_number,
                    metadata={"command": command},
                )
            )
    return issues


def _scan_log(
    log_file: Path,
    *,
    tex_lines: tuple[str, ...] = (),
) -> list[PDFQualityIssue]:
    log_text = log_file.read_text(encoding="utf-8", errors="replace")
    issues: list[PDFQualityIssue] = []

    overfull_matches = list(_OVERFULL_RE.finditer(log_text))
    overfull_points = [float(match.group("points")) for match in overfull_matches]
    if overfull_points:
        severity = "medium" if max(overfull_points) < 20 else "high"
        max_index = max(range(len(overfull_points)), key=overfull_points.__getitem__)
        max_match = overfull_matches[max_index]
        issues.append(
            PDFQualityIssue(
                category="overfull_hbox",
                severity=severity,
                message=(
                    f"{len(overfull_points)} overfull hbox warning(s), "
                    f"max {max(overfull_points):.2f}pt."
                ),
                source_path=str(log_file),
                metadata={
                    "count": len(overfull_points),
                    "max_points": max(overfull_points),
                    "max_line_range": _line_range(max_match),
                    "max_source_excerpt": _source_excerpt(tex_lines, max_match),
                    "line_ranges": tuple(
                        line_range
                        for line_range in (
                            _line_range(match) for match in overfull_matches
                        )
                        if line_range
                    ),
                },
            )
        )

    underfull_matches = list(_UNDERFULL_RE.finditer(log_text))
    underfull_count = len(underfull_matches)
    if underfull_count:
        issues.append(
            PDFQualityIssue(
                category="underfull_hbox",
                severity="low",
                message=f"{underfull_count} underfull hbox warning(s).",
                source_path=str(log_file),
                metadata={
                    "count": underfull_count,
                    "line_ranges": tuple(
                        line_range
                        for line_range in (
                            _line_range(match) for match in underfull_matches
                        )
                        if line_range
                    ),
                    "source_excerpts": tuple(
                        excerpt
                        for excerpt in (
                            _source_excerpt(tex_lines, match)
                            for match in underfull_matches
                        )
                        if excerpt
                    ),
                },
            )
        )

    for marker, category, severity in (
        ("Invalid UTF-8 byte or sequence", "invalid_utf8", "medium"),
        ("Undefined citation", "undefined_citation", "critical"),
        ("undefined", "undefined_citation", "critical"),
        ("! LaTeX Error", "latex_error", "critical"),
        ("! Undefined control sequence", "undefined_control_sequence", "critical"),
    ):
        if marker == "undefined":
            count = len(
                re.findall(
                    r"Citation\s+`[^`]+'.{0,80}\bundefined\b",
                    log_text,
                    flags=re.IGNORECASE,
                )
            )
        else:
            count = log_text.count(marker)
        if count:
            issues.append(
                PDFQualityIssue(
                    category=category,
                    severity=severity,
                    message=f"{count} log occurrence(s): {marker}.",
                    source_path=str(log_file),
                    metadata={"count": count},
                )
            )
    return issues


def _count_categories(
    issues: list[PDFQualityIssue],
    categories: set[str],
) -> int:
    return sum(1 for issue in issues if issue.category in categories)


def _artifact_size_bytes(
    *,
    tex_path: str,
    pdf_path: str,
    log_path: str,
) -> dict[str, int]:
    return {
        key: size
        for key, size in (
            ("tex", _file_size(tex_path)),
            ("pdf", _file_size(pdf_path)),
            ("log", _file_size(log_path)),
        )
        if size >= 0
    }


def _file_size(path: str) -> int:
    if not path:
        return -1
    file_path = Path(path)
    if not file_path.exists():
        return -1
    return file_path.stat().st_size


def _line_range(match: re.Match[str]) -> str:
    start = match.groupdict().get("start")
    if not start:
        return ""
    end = match.groupdict().get("end") or start
    return f"{start}--{end}" if end != start else start


def _source_excerpt(tex_lines: tuple[str, ...], match: re.Match[str]) -> str:
    if not tex_lines:
        return ""
    start_text = match.groupdict().get("start")
    if not start_text:
        return ""
    start = max(int(start_text), 1)
    end = int(match.groupdict().get("end") or start)
    selected = tex_lines[start - 1 : end]
    collapsed = " ".join(line.strip() for line in selected if line.strip())
    return collapsed[:500]


def _finding_category(signal: PDFQualitySignal) -> str:
    if not signal.issues:
        return "pdf_quality_observation"
    categories = {issue.category for issue in signal.issues}
    if categories.intersection(_RECOMPILE_REPAIRABLE_CATEGORIES):
        return "pdf_quality_regression"
    if categories.intersection(_LAYOUT_CATEGORIES):
        return "pdf_layout_quality_gap"
    if categories.intersection(_ENCODING_CATEGORIES):
        return "pdf_encoding_quality_gap"
    return "pdf_quality_regression"


def _priority(issues: tuple[PDFQualityIssue, ...]) -> str:
    severities = {issue.severity for issue in issues}
    if "critical" in severities:
        return "P0"
    if "high" in severities:
        return "P1"
    if "medium" in severities:
        return "P2"
    return "P3" if issues else "P3"


def _summary(signal: PDFQualitySignal) -> str:
    if not signal.issues:
        return "PDF quality scan found no deterministic issues."
    counts: dict[str, int] = {}
    for issue in signal.issues:
        counts[issue.category] = counts.get(issue.category, 0) + 1
    parts = ", ".join(
        f"{category}={count}" for category, count in sorted(counts.items())
    )
    return f"PDF quality scan found {len(signal.issues)} issue(s): {parts}."


def _surfaces(signal: PDFQualitySignal) -> tuple[str, ...]:
    surfaces = [
        "self_evolution",
        "final_bundle",
        "latex_compiler",
        "skills/publication-pack",
        "tests",
    ]
    if signal.target_profile:
        surfaces.append(f"target_profile:{signal.target_profile}")
    return tuple(surfaces)


def _actions(signal: PDFQualitySignal) -> tuple[RecommendedAction, ...]:
    categories = {issue.category for issue in signal.issues}
    has_recompile_repairable = bool(
        categories.intersection(_RECOMPILE_REPAIRABLE_CATEGORIES)
    )
    actions = [
        RecommendedAction(
            action_type="test",
            description="Add a regression test for PDF quality scan findings.",
            target_surface="tests",
            required_before_patch=True,
        ),
        RecommendedAction(
            action_type="skill",
            description="Update publication-pack/finalization guidance to preserve LaTeX escapes.",
            target_surface="skills/publication-pack",
        ),
    ]
    if has_recompile_repairable:
        actions.append(
            RecommendedAction(
                action_type="gate",
                description=(
                    "Fail final-bundle quality gates on recompile-repairable "
                    "PDF quality issues."
                ),
                target_surface="final_bundle",
                required_before_patch=True,
            )
        )
    if any(issue.category == "malformed_latex_command" for issue in signal.issues):
        actions.append(
            RecommendedAction(
                action_type="latex_compiler",
                description=(
                    "Normalize or reject tab-prefixed malformed LaTeX commands "
                    "before compile."
                ),
                target_surface="latex_compiler",
                required_before_patch=True,
            )
        )
    if categories.intersection(_LAYOUT_CATEGORIES):
        actions.append(
            RecommendedAction(
                action_type="layout_diagnosis",
                description=(
                    "Track overfull/underfull line ranges and tune layout only "
                    "against a held-out page-count baseline."
                ),
                target_surface="latex_layout",
                required_before_patch=True,
            )
        )
    if "invalid_utf8" in categories:
        actions.append(
            RecommendedAction(
                action_type="encoding_sanitization",
                description=(
                    "Remove nonessential LaTeX packages or sanitize inputs that "
                    "produce Invalid UTF-8 compiler warnings."
                ),
                target_surface="latex_compiler",
                required_before_patch=True,
            )
        )
    return tuple(actions)


def _finding_id(signal: PDFQualitySignal) -> str:
    identity = signal.transcript_ref or f"{signal.tex_path}:{signal.log_path}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"finding:pdf:{digest}"
