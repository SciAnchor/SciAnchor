#!/usr/bin/env python3
"""Check release-facing docs for MCP/service coverage drift."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs" / "STATUS.md"
AUDIT_PATH = ROOT / "docs" / "mcp-tool-audit.md"
COVERAGE_PATH = ROOT / "docs" / "contracts" / "service-coverage.md"
README_PATH = ROOT / "README.md"
README_EN_PATH = ROOT / "README.en.md"
QUICKSTART_PATH = ROOT / "docs" / "quickstart.md"
QUICKSTART_ZH_PATH = ROOT / "docs" / "quickstart.zh.md"
RELEASE_BOUNDARY_PATH = ROOT / "docs" / "contracts" / "release-boundary.md"
PYTHON_API_PATH = ROOT / "docs" / "python-api.md"
KNOWLEDGE_HTTP_PATH = ROOT / "docs" / "knowledge-http-api.md"
SERVICE_PLAN_PATH = ROOT / "docs" / "service-layer-plan.md"
RFB_RESULTS_PATH = ROOT / "docs" / "researchflowbench-results-autoresearchbench-v0.md"
BENCHMARK_FEEDBACK_GLOBS = (
    ".rh-selfdev/slices.md",
    ".rh-selfdev/handoffs/S*_RFB*.md",
    ".rh-selfdev/gates/S*_RFB*.md",
    ".rh-selfdev/rh-s72-benchmark-diagnostic-unblock-plan-20260615.md",
)

STATUS_PUBLIC_RE = re.compile(r"\b(\d+)\s+public contracted tools\b")
STATUS_SERVICE_RE = re.compile(r"\b(\d+)\s+service-backed MCP tools\b")
AUDIT_PUBLIC_RE = re.compile(
    r"^- Public advertised MCP tools:\s*(\d+)\s*$",
    re.MULTILINE,
)
AUDIT_SERVICE_RE = re.compile(
    r"Service dispatcher coverage:\s*(?:all\s+)?(\d+)\s+(?:of the \d+\s+)?"
    r"public tools route\s+through\s+`ResearchService`\s+in the MCP adapter",
)
# Convenience surfaces the audit doc explicitly declares as NOT service-backed.
# Every name here must appear in docs/mcp-tool-audit.md with its direct call
# path; an undeclared gap still fails the full-coverage assertion below.
DECLARED_CONVENIENCE_SURFACES = frozenset({"deposit_zenodo"})
COVERAGE_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)
STALE_WORDING = (
    "Service dispatcher coverage: skeleton active.",
    "other public tools stay on existing paths until later migration slices",
    "routes those ten commands through the service layer",
    "25-tool coverage matrix",
)
RELEASE_BOUNDARY_LINK = "docs/contracts/release-boundary.md"
PUBLIC_HTTP_DEPLOYMENT_POLICY_PHRASE = (
    "Public HTTP deployment requires RESEARCH_HARNESS_HTTP_API_TOKEN plus "
    "reviewed TLS/proxy, network allowlist, scoped CORS origins, "
    "private/no-store cache policy, rollback, and monitoring plan."
)
REQUIRED_BOUNDARY_PHRASES = (
    "Stable public/local CLI-MCP-skill workflow.",
    "Local/internal HTTP bridge only.",
    "Stable Zotero push dry-run validation only.",
    "Fake/sandbox Zotero pull/both and apply evidence is local-only.",
    "Private benchmark/performance regression governance only.",
    "Stable external API release: deferred.",
    "Real Zotero network sync/apply remains deferred.",
    "Public benchmark/performance claims remain deferred.",
)
REQUIRED_QUICKSTART_ZH_BOUNDARY_PHRASES = (
    "非 loopback HTTP 绑定不受支持，也未获 release approval。",
    "Stable external API release：deferred。",
    "Real Zotero network sync/apply 仍然 deferred。",
    "Public benchmark/performance claims 仍然 deferred。",
)
OVERCLAIM_PATTERNS = (
    (
        re.compile(
            r"\bstable external API release:\s*(approved|ready|stable)\b",
            re.IGNORECASE,
        ),
        "stable external API release overclaim",
    ),
    (
        re.compile(
            r"\breal Zotero network sync/apply\s+"
            r"(is stable|is approved|is ready|approved|ready)\b",
            re.IGNORECASE,
        ),
        "real Zotero sync/apply overclaim",
    ),
    (
        re.compile(
            r"\bpublic benchmark/performance claims\s+"
            r"(are approved|are ready|are stable|approved|ready)\b",
            re.IGNORECASE,
        ),
        "public benchmark/performance overclaim",
    ),
)
RFB_RESULT_OVERCLAIM_PATTERNS = (
    re.compile(r"\bfirst positive evidence\b", re.IGNORECASE),
    re.compile(r"\bcan improve recall\b", re.IGNORECASE),
    re.compile(r"\bpositive model-free retrieval evidence\b", re.IGNORECASE),
)
STATUS_BENCHMARK_OVERCLAIM_PATTERNS = (
    re.compile(r"\bpositive but small metrics\b", re.IGNORECASE),
    re.compile(r"\bfull1000\b.*\bpositive\b.*\bmetrics\b", re.IGNORECASE),
)
AR_TASK_REF = r"(?:task\s+)?`?autoresearchbench\.[A-Za-z0-9_.-]+`?"
AR_TASK_SCORE_COLUMN_RE = (
    r"(?:Deep\s+accuracy|Wide\s+(?:IoU|precision|recall)|"
    r"Selected(?:-|\s+)sample\s+(?:score|IoU|precision|recall)|"
    r"deep_accuracy|wide_(?:iou|precision|recall)|"
    r"selected_sample_(?:score|iou|precision|recall))"
)
RFB_GOLD_LEAK_PATTERNS = (
    (
        re.compile(r"\|\s*Task\s*\|[^\n]*\|\s*Gold\s*\|", re.IGNORECASE),
        "benchmark gold-derived task table",
    ),
    (
        re.compile(r"\bMatched arXiv IDs\b", re.IGNORECASE),
        "benchmark matched gold identifiers",
    ),
    (
        re.compile(
            r"^\|\s*(?:Task|Task ID|AutoResearchBench task)\s*\|"
            rf"[^\n]*\b{AR_TASK_SCORE_COLUMN_RE}\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "benchmark task-level selected-sample score table",
    ),
    (
        re.compile(
            rf"^\|\s*`?autoresearchbench\.\d+`?\s*\|[^\n]*\b\d+\.\d+\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "benchmark task-level selected-sample score row",
    ),
    (
        re.compile(
            rf"{AR_TASK_REF}[\s\S]{{0,240}}\b(?:predicted|selected|returned)\b"
            r"[\s\S]{0,80}\b\d+\b[\s\S]{0,80}\bgold\b"
            r"[\s\S]{0,80}\b(?:papers|answers|items)?\b",
            re.IGNORECASE,
        ),
        "benchmark task-level gold-count prose",
    ),
    (
        re.compile(
            rf"{AR_TASK_REF}[\s\S]{{0,240}}\bmatched\s+"
            r"(?:arxiv\s+ids?|answer\s+identifiers?|ids?)\b"
            r"[\s\S]{0,160}(?:\b\d{4}\.\d{4,5}\b|\b\d+\s+of\s+\d+\b)",
            re.IGNORECASE,
        ),
        "benchmark task-level matched-identifier prose",
    ),
    (
        re.compile(
            rf"{AR_TASK_REF}[\s\S]{{0,240}}\b{AR_TASK_SCORE_COLUMN_RE}\b"
            r"[\s\S]{0,80}\b\d+\.\d+\b",
            re.IGNORECASE,
        ),
        "benchmark task-level score prose",
    ),
    (
        re.compile(
            r"\b(?:agent|model|runner|Codex)\b[\s\S]{0,80}\bpredicted\b"
            r"[\s\S]{0,240}\barXiv\s+id\b\s*:?\s*`?\d{4}\.\d{4,5}`?",
            re.IGNORECASE,
        ),
        "benchmark task-level predicted-output prose",
    ),
)


def benchmark_feedback_doc_paths() -> list[Path]:
    paths: dict[str, Path] = {}
    for pattern in BENCHMARK_FEEDBACK_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file():
                paths[str(path.relative_to(ROOT))] = path
    return [paths[key] for key in sorted(paths)]


def read_benchmark_feedback_docs_text() -> str:
    chunks: list[str] = []
    for path in benchmark_feedback_doc_paths():
        relative = path.relative_to(ROOT)
        chunks.append(f"\n\n<!-- {relative} -->\n")
        chunks.append(path.read_text(encoding="utf-8"))
    return "".join(chunks)


def _status_row(status_text: str, subsystem: str) -> str:
    prefix = f"| {subsystem} |"
    for line in status_text.splitlines():
        if line.startswith(prefix):
            return line
    return ""


def _first_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    if match is None:
        return None
    return int(match.group(1))


def parse_status_public_count(status_text: str) -> int | None:
    return _first_int(STATUS_PUBLIC_RE, _status_row(status_text, "MCP surface"))


def parse_status_service_backed_count(status_text: str) -> int | None:
    return _first_int(STATUS_SERVICE_RE, _status_row(status_text, "Service layer"))


def parse_audit_public_count(audit_text: str) -> int | None:
    return _first_int(AUDIT_PUBLIC_RE, audit_text)


def parse_audit_service_backed_count(audit_text: str) -> int | None:
    return _first_int(AUDIT_SERVICE_RE, audit_text)


def parse_service_coverage_counts(coverage_text: str) -> tuple[int, int]:
    public_count = 0
    service_backed_count = 0
    for _name, status, _current_path, _next_slice in COVERAGE_ROW_RE.findall(
        coverage_text
    ):
        normalized_status = status.strip()
        if normalized_status in {"Status", "---"}:
            continue
        public_count += 1
        if normalized_status == "service-backed-mcp":
            service_backed_count += 1
    return public_count, service_backed_count


def _append_missing_or_mismatch(
    errors: list[str],
    *,
    label: str,
    observed: int | None,
    expected: int,
) -> None:
    if observed is None:
        errors.append(f"{label} is missing")
    elif observed != expected:
        errors.append(f"{label} {observed} != expected count {expected}")


def validate_release_doc_consistency(
    *,
    status_text: str,
    audit_text: str,
    coverage_text: str,
    readme_text: str,
    readme_en_text: str,
    quickstart_text: str,
    quickstart_zh_text: str,
    boundary_text: str,
    python_api_text: str,
    knowledge_http_text: str,
    service_plan_text: str,
    rfb_results_text: str,
    benchmark_feedback_text: str = "",
) -> list[str]:
    errors: list[str] = []

    status_public = parse_status_public_count(status_text)
    status_service_backed = parse_status_service_backed_count(status_text)
    audit_public = parse_audit_public_count(audit_text)
    audit_service_backed = parse_audit_service_backed_count(audit_text)
    coverage_public, coverage_service_backed = parse_service_coverage_counts(
        coverage_text
    )

    if audit_public is None:
        errors.append("MCP audit public MCP count is missing")
        expected_public = coverage_public
    else:
        expected_public = audit_public

    _append_missing_or_mismatch(
        errors,
        label="STATUS.md public MCP count",
        observed=status_public,
        expected=expected_public,
    )
    if coverage_public != expected_public:
        errors.append(
            "service coverage matrix public tool count "
            f"{coverage_public} != expected count {expected_public}"
        )

    if audit_service_backed is None:
        errors.append("audit service-backed MCP count is missing")
        expected_service_backed = coverage_service_backed
    else:
        expected_service_backed = audit_service_backed

    _append_missing_or_mismatch(
        errors,
        label="STATUS.md service-backed MCP count",
        observed=status_service_backed,
        expected=expected_service_backed,
    )
    if coverage_service_backed != expected_service_backed:
        errors.append(
            "service coverage matrix service-backed MCP count "
            f"{coverage_service_backed} != expected count {expected_service_backed}"
        )
    declared_gap = len(DECLARED_CONVENIENCE_SURFACES)
    if expected_service_backed + declared_gap != expected_public:
        errors.append(
            "release docs no longer describe full public MCP service coverage: "
            f"public={expected_public} service_backed={expected_service_backed} "
            f"declared_convenience={declared_gap}"
        )
    for name in DECLARED_CONVENIENCE_SURFACES:
        if f"`{name}`" not in audit_text:
            errors.append(
                f"declared convenience surface `{name}` is not documented in "
                "the MCP audit"
            )

    for phrase in STALE_WORDING:
        if phrase in status_text or phrase in audit_text:
            errors.append(f"stale release doc wording remains: {phrase}")

    for label, text in (
        ("README.md", readme_text),
        ("README.en.md", readme_en_text),
        ("docs/quickstart.md", quickstart_text),
        ("docs/quickstart.zh.md", quickstart_zh_text),
        ("docs/STATUS.md", status_text),
    ):
        if RELEASE_BOUNDARY_LINK not in text:
            errors.append(f"{label} is missing release boundary link")

    for phrase in REQUIRED_BOUNDARY_PHRASES:
        if phrase not in boundary_text:
            if phrase.startswith("Fake/sandbox Zotero"):
                errors.append(f"Zotero sandbox boundary missing: {phrase}")
            else:
                errors.append(f"release boundary doc missing required phrase: {phrase}")

    normalized_quickstart_zh_text = " ".join(quickstart_zh_text.split())
    for phrase in REQUIRED_QUICKSTART_ZH_BOUNDARY_PHRASES:
        if phrase not in normalized_quickstart_zh_text:
            errors.append(
                f"docs/quickstart.zh.md localized release boundary missing: {phrase}"
            )

    scanned_text = "\n".join(
        (
            status_text,
            readme_text,
            readme_en_text,
            quickstart_text,
            quickstart_zh_text,
            boundary_text,
        )
    )
    for pattern, message in OVERCLAIM_PATTERNS:
        if pattern.search(scanned_text):
            errors.append(message)

    for pattern in RFB_RESULT_OVERCLAIM_PATTERNS:
        match = pattern.search(rfb_results_text)
        if match is not None:
            errors.append(f"benchmark result overclaim: {match.group(0)}")

    for pattern in STATUS_BENCHMARK_OVERCLAIM_PATTERNS:
        match = pattern.search(status_text)
        if match is not None:
            errors.append(f"STATUS benchmark overclaim: {match.group(0)}")

    benchmark_leak_text = "\n".join((rfb_results_text, benchmark_feedback_text))
    for pattern, message in RFB_GOLD_LEAK_PATTERNS:
        match = pattern.search(benchmark_leak_text)
        if match is not None:
            errors.append(f"{message}: {match.group(0)}")

    if "partial/programmatic facade" not in python_api_text:
        errors.append("Python API doc must qualify the facade as partial/programmatic")

    non_loopback_phrase = (
        "Non-loopback HTTP binding is unsupported and not release-approved."
    )
    if (
        non_loopback_phrase not in boundary_text
        or non_loopback_phrase not in knowledge_http_text
    ):
        errors.append(
            "HTTP docs must state non-loopback is unsupported/not release-approved"
        )
    normalized_boundary_text = " ".join(boundary_text.split())
    normalized_knowledge_http_text = " ".join(knowledge_http_text.split())
    if (
        PUBLIC_HTTP_DEPLOYMENT_POLICY_PHRASE not in normalized_boundary_text
        or PUBLIC_HTTP_DEPLOYMENT_POLICY_PHRASE not in normalized_knowledge_http_text
    ):
        errors.append(
            "HTTP docs must state public deployment auth/TLS/proxy/allowlist/"
            "CORS/cache policy"
        )

    normalized_service_plan = " ".join(service_plan_text.split())
    if (
        "CLI `topic list` and `paper list` consume complete service output "
        "without legacy SQL fallback." not in normalized_service_plan
    ):
        errors.append("service plan must document current CLI list convergence")

    return errors


def main() -> int:
    missing_paths = [
        path
        for path in (
            STATUS_PATH,
            AUDIT_PATH,
            COVERAGE_PATH,
            README_PATH,
            README_EN_PATH,
            QUICKSTART_PATH,
            QUICKSTART_ZH_PATH,
            RELEASE_BOUNDARY_PATH,
            PYTHON_API_PATH,
            KNOWLEDGE_HTTP_PATH,
            SERVICE_PLAN_PATH,
            RFB_RESULTS_PATH,
        )
        if not path.is_file()
    ]
    if missing_paths:
        for path in missing_paths:
            print(f"FAIL: missing document: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1

    errors = validate_release_doc_consistency(
        status_text=STATUS_PATH.read_text(encoding="utf-8"),
        audit_text=AUDIT_PATH.read_text(encoding="utf-8"),
        coverage_text=COVERAGE_PATH.read_text(encoding="utf-8"),
        readme_text=README_PATH.read_text(encoding="utf-8"),
        readme_en_text=README_EN_PATH.read_text(encoding="utf-8"),
        quickstart_text=QUICKSTART_PATH.read_text(encoding="utf-8"),
        quickstart_zh_text=QUICKSTART_ZH_PATH.read_text(encoding="utf-8"),
        boundary_text=RELEASE_BOUNDARY_PATH.read_text(encoding="utf-8"),
        python_api_text=PYTHON_API_PATH.read_text(encoding="utf-8"),
        knowledge_http_text=KNOWLEDGE_HTTP_PATH.read_text(encoding="utf-8"),
        service_plan_text=SERVICE_PLAN_PATH.read_text(encoding="utf-8"),
        rfb_results_text=RFB_RESULTS_PATH.read_text(encoding="utf-8"),
        benchmark_feedback_text=read_benchmark_feedback_docs_text(),
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    public_count, service_backed_count = parse_service_coverage_counts(
        COVERAGE_PATH.read_text(encoding="utf-8")
    )
    print(
        "Release docs consistency guard passed; "
        f"public_tools={public_count} "
        f"service_backed_mcp={service_backed_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
