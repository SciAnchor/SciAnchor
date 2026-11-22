"""Multi-route paper review integration.

The external reviewers remain external. This module only provides RH glue:
deterministic AAAI/PDF hard-gates, route availability checks, and an
artifact-ready report shape that can later be persisted by the orchestrator.
"""

from __future__ import annotations

import json
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .._core.config import state_path
from typing import Any, Callable, Mapping, Sequence


ModuleAvailable = Callable[[str], bool]
ExecutableFinder = Callable[[str], str | None]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

_PROXY_REVIEW_ROUTE_PROFILES: dict[str, str] = {
    "ai_scientist_reviewer": (
        "AI Scientist-style paper review: judge novelty, technical soundness, "
        "experimental adequacy, presentation quality, limitations, and reject "
        "reasons as if running the external AI-Scientist reviewer."
    ),
    "openjudge_paper_review": (
        "OpenJudge-style paper review: emphasize correctness, review quality, "
        "criticality, format/safety checks, and BibTeX/citation verification."
    ),
    "openaireview": (
        "OpenAIReview-style paper review: emulate a strict conference-review "
        "panel with numeric scores, weakness-first critique, and clear accept/"
        "reject recommendation."
    ),
    "rh_adversarial_review": (
        "RH adversarial-review-style critique: actively challenge novelty, "
        "evidence coverage, baseline completeness, scope discipline, and "
        "claim falsifiability."
    ),
}


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    category: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
        }


@dataclass(frozen=True)
class DeterministicReviewRouteResult:
    route: str
    status: str
    source: str
    summary: dict[str, Any] = field(default_factory=dict)
    findings: tuple[ReviewFinding, ...] = ()
    verdict: str = "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "status": self.status,
            "source": self.source,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class ExecutedReviewRouteResult:
    route: str
    status: str
    source: str
    verdict: str = ""
    issues: tuple[dict[str, Any], ...] = ()
    scores: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    raw_output: str = ""
    error: str = ""
    missing: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "route": self.route,
            "status": self.status,
            "source": self.source,
            "verdict": self.verdict,
            "issues": list(self.issues),
            "scores": self.scores,
            "notes": self.notes,
            "missing": list(self.missing),
        }
        if self.raw_output:
            payload["raw_output"] = self.raw_output
        if self.error:
            payload["error"] = self.error
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(frozen=True)
class ReviewRouteAvailability:
    route: str
    source: str
    status: str
    missing: tuple[str, ...] = ()
    integration_note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "route": self.route,
            "source": self.source,
            "status": self.status,
            "missing": list(self.missing),
            "integration_note": self.integration_note,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(frozen=True)
class MultiRouteReviewConfig:
    """Environment and dependency probes for reviewer routes."""

    module_available: ModuleAvailable | None = None
    executable_finder: ExecutableFinder | None = None
    command_runner: CommandRunner | None = None
    env: Mapping[str, str] | None = None
    python_version: tuple[int, int] | None = None

    def has_module(self, name: str) -> bool:
        if self.module_available is not None:
            return self.module_available(name)
        return _module_available(name)

    def getenv(self, name: str) -> str:
        if self.env is not None:
            return self.env.get(name, "")
        return os.environ.get(name, "")

    def find_executable(self, name: str) -> str | None:
        if self.executable_finder is not None:
            return self.executable_finder(name)
        return shutil.which(name)

    def run_command(
        self,
        cmd: Sequence[str],
        *,
        timeout: int,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if self.command_runner is not None:
            return self.command_runner(
                list(cmd),
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
            )
        return subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
        )

    @property
    def version(self) -> tuple[int, int]:
        if self.python_version is not None:
            return self.python_version
        return (sys.version_info.major, sys.version_info.minor)


@dataclass(frozen=True)
class MultiRouteReviewReport:
    candidate_path: str
    deterministic: DeterministicReviewRouteResult
    route_availability: tuple[ReviewRouteAvailability, ...] = ()
    executed_routes: tuple[ExecutedReviewRouteResult, ...] = ()
    topic_id: int = 0
    candidate_label: str = ""

    def to_artifact_payload(self) -> dict[str, Any]:
        external_routes = {
            route.route: {
                "status": route.status,
                "missing": list(route.missing),
                "source": route.source,
                "integration_note": route.integration_note,
                **({"metadata": route.metadata} if route.metadata else {}),
            }
            for route in self.route_availability
        }
        return {
            "topic_id": self.topic_id,
            "candidate_label": self.candidate_label,
            "candidate_path": self.candidate_path,
            "deterministic_route": self.deterministic.to_dict(),
            "external_routes": external_routes,
            "executed_routes": {
                route.route: route.to_dict() for route in self.executed_routes
            },
            "decision": (
                "Do not redevelop reviewer logic now. Build RH-specific "
                "aggregation, provenance, and AAAI hard-gate glue around "
                "external reviewer routes first."
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate_path,
            "deterministic_route": self.deterministic.to_dict(),
            "route_availability": [
                route.to_dict() for route in self.route_availability
            ],
            "executed_routes": [route.to_dict() for route in self.executed_routes],
        }


def run_multi_route_review_probe(
    candidate_path: str | Path,
    *,
    topic_id: int = 0,
    candidate_label: str = "",
    config: MultiRouteReviewConfig | None = None,
    ai_scientist_root: str | Path | None = None,
    execute_host_agents: bool = False,
    workspace_path: str | Path | None = None,
    host_agent_timeout_seconds: int = 180,
) -> MultiRouteReviewReport:
    candidate = Path(candidate_path).expanduser().resolve()
    effective_config = config or MultiRouteReviewConfig()
    deterministic = run_deterministic_aaai_pdf_gate(candidate)
    routes = detect_review_route_availability(
        ai_scientist_root=ai_scientist_root,
        config=effective_config,
    )
    executed_routes: tuple[ExecutedReviewRouteResult, ...] = ()
    if execute_host_agents:
        executed_routes = run_host_agent_reviews(
            candidate,
            config=effective_config,
            workspace_path=workspace_path,
            timeout_seconds=host_agent_timeout_seconds,
            candidate_label=candidate_label,
            deterministic_summary=deterministic.summary,
        )
    return MultiRouteReviewReport(
        candidate_path=str(candidate),
        deterministic=deterministic,
        route_availability=tuple(routes),
        executed_routes=executed_routes,
        topic_id=topic_id,
        candidate_label=candidate_label,
    )


def run_deterministic_aaai_pdf_gate(
    candidate_path: str | Path,
) -> DeterministicReviewRouteResult:
    candidate = Path(candidate_path).expanduser().resolve()
    summary = {
        "pdf": _count_pdf_pages_and_words(candidate / "paper.pdf"),
        "tex_bib": _scan_tex_and_bib(candidate),
        "log": _scan_log(_read(candidate / "paper.log")),
    }

    findings = _build_deterministic_findings(summary)
    verdict = (
        "not_aaai_ready"
        if any(finding.severity == "critical" for finding in findings)
        else "needs_review"
    )
    return DeterministicReviewRouteResult(
        route="deterministic_aaai_pdf_gate",
        status="completed",
        source="RH deterministic hard-gates inspired by ACLPubCheck/Banal",
        summary=summary,
        findings=tuple(findings),
        verdict=verdict,
    )


def _select_host_agent_fallback(
    config: MultiRouteReviewConfig,
) -> tuple[str, str] | None:
    preferred = (
        (
            config.getenv("RESEARCH_HARNESS_REVIEW_HOST_AGENT")
            or config.getenv("RH_REVIEW_HOST_AGENT")
        )
        .strip()
        .lower()
    )
    if preferred:
        selected = _host_agent_tuple(preferred, config)
        if selected is not None:
            return selected
    cursor_agent = config.find_executable("agent")
    if cursor_agent:
        return ("cursor_agent_review", cursor_agent)
    codex = config.find_executable("codex")
    if codex:
        return ("codex_agent_review", codex)
    return None


def _host_agent_tuple(
    host_route: str,
    config: MultiRouteReviewConfig,
) -> tuple[str, str] | None:
    normalized = host_route.strip().lower()
    if normalized in {"cursor", "cursor_agent", "cursor_agent_review", "agent"}:
        agent = config.find_executable("agent")
        return ("cursor_agent_review", agent) if agent else None
    if normalized in {"codex", "codex_agent", "codex_agent_review"}:
        codex = config.find_executable("codex")
        return ("codex_agent_review", codex) if codex else None
    return None


def _with_host_agent_fallback(
    *,
    route: str,
    source: str,
    native_status: str,
    native_missing: tuple[str, ...],
    native_note: str,
    fallback_route: tuple[str, str] | None,
    allow_fallback: bool,
) -> ReviewRouteAvailability:
    metadata: dict[str, Any] = {
        "native_status": native_status,
        "native_missing": list(native_missing),
    }
    if native_status == "runnable" or fallback_route is None or not allow_fallback:
        return ReviewRouteAvailability(
            route=route,
            source=source,
            status=native_status,
            missing=native_missing,
            integration_note=native_note,
            metadata=metadata,
        )

    fallback_name, fallback_source = fallback_route
    metadata.update(
        {
            "fallback_route": fallback_name,
            "fallback_source": fallback_source,
        }
    )
    return ReviewRouteAvailability(
        route=route,
        source=source,
        status="runnable_via_host_agent",
        missing=(),
        integration_note=(
            f"{native_note} Native route is {native_status} in this environment; "
            f"RH will run a {fallback_name} proxy instead."
        ),
        metadata=metadata,
    )


def detect_review_route_availability(
    *,
    ai_scientist_root: str | Path | None = None,
    config: MultiRouteReviewConfig | None = None,
) -> tuple[ReviewRouteAvailability, ...]:
    effective_config = config or MultiRouteReviewConfig()
    root = (
        Path(ai_scientist_root).expanduser().resolve()
        if ai_scientist_root is not None
        else _default_ai_scientist_root()
    )
    has_llm_key = _has_llm_key(effective_config)

    ai_missing = _missing_modules(
        effective_config,
        ("numpy", "pypdf", "pymupdf4llm", "openai"),
    )
    if not has_llm_key:
        ai_missing.append("LLM_API_KEY")
    if not root.exists():
        ai_status = "missing_source"
    else:
        ai_status = "runnable" if not ai_missing else "blocked"

    openjudge_missing = _missing_modules(
        effective_config,
        (
            "openjudge",
            "cookbooks.paper_review",
            "openai",
            "loguru",
            "json_repair",
            "fire",
        ),
    )
    if not has_llm_key:
        openjudge_missing.append("LLM_API_KEY")
    openjudge_status = "runnable" if not openjudge_missing else "blocked"

    openaireview_missing: list[str] = []
    if effective_config.version < (3, 12):
        openaireview_missing.append("python>=3.12")
    elif not effective_config.has_module("openaireview"):
        openaireview_missing.append("openaireview")
    if effective_config.version >= (3, 12) and not has_llm_key:
        openaireview_missing.append("LLM_API_KEY")
    if openaireview_missing == ["openaireview"]:
        openaireview_status = "installable"
    elif not openaireview_missing:
        openaireview_status = "runnable"
    elif effective_config.version >= (3, 12) and openaireview_missing == [
        "openaireview",
        "LLM_API_KEY",
    ]:
        openaireview_status = "installable"
    else:
        openaireview_status = "blocked"
    if effective_config.version >= (3, 12) and "openaireview" in openaireview_missing:
        openaireview_status = "installable"

    rh_missing = (
        [] if has_llm_key else ["KIMI_API_KEY or ANTHROPIC_API_KEY or OPENAI_API_KEY"]
    )
    codex_path = effective_config.find_executable("codex")
    cursor_agent_path = effective_config.find_executable("agent")
    fallback_route = _select_host_agent_fallback(effective_config)

    ai_route = _with_host_agent_fallback(
        route="ai_scientist_reviewer",
        source=str(root),
        native_status=ai_status,
        native_missing=tuple(ai_missing),
        native_note=(
            "Use AI Scientist perform_review after installing reviewer deps "
            "and setting an OpenAI-compatible key."
        ),
        fallback_route=fallback_route,
        allow_fallback=ai_status in {"blocked", "missing_source"},
    )
    openjudge_route = _with_host_agent_fallback(
        route="openjudge_paper_review",
        source="py-openjudge / cookbooks.paper_review",
        native_status=openjudge_status,
        native_missing=tuple(openjudge_missing),
        native_note=(
            "Best external route: safety, correctness, review, criticality, "
            "and BibTeX verification."
        ),
        fallback_route=fallback_route,
        allow_fallback=openjudge_status == "blocked",
    )
    openaireview_route = _with_host_agent_fallback(
        route="openaireview",
        source="openaireview PyPI package",
        native_status=openaireview_status,
        native_missing=tuple(openaireview_missing),
        native_note="Use as an optional route in a Python 3.12 environment.",
        fallback_route=fallback_route,
        allow_fallback=openaireview_status in {"blocked", "installable"},
    )
    rh_route = _with_host_agent_fallback(
        route="rh_adversarial_review",
        source="existing RH MCP/adversarial reviewer route",
        native_status="runnable" if not rh_missing else "blocked",
        native_missing=tuple(rh_missing),
        native_note=(
            "Useful as a control route, not a replacement for OpenJudge or "
            "AI Scientist."
        ),
        fallback_route=fallback_route,
        allow_fallback=bool(rh_missing),
    )

    return (
        ai_route,
        openjudge_route,
        openaireview_route,
        ReviewRouteAvailability(
            route="codex_agent_review",
            source=codex_path or "codex CLI",
            status="runnable" if codex_path else "blocked",
            missing=() if codex_path else ("codex",),
            integration_note=(
                "Host-agent fallback via `codex exec`; no direct LLM API key is "
                "required when the local Codex CLI is already authenticated."
            ),
        ),
        ReviewRouteAvailability(
            route="cursor_agent_review",
            source=cursor_agent_path or "Cursor Agent CLI",
            status="runnable" if cursor_agent_path else "blocked",
            missing=() if cursor_agent_path else ("agent",),
            integration_note=(
                "Host-agent fallback via `agent -p`; no direct LLM API key is "
                "required when the local Cursor Agent is already authenticated."
            ),
        ),
        rh_route,
    )


def build_aaai_review_prompt(
    candidate_path: str | Path,
    *,
    candidate_label: str = "",
    deterministic_summary: Mapping[str, Any] | None = None,
    focus: str = "",
    route_profile: str = "",
) -> str:
    candidate = Path(candidate_path).expanduser().resolve()
    label = candidate_label or candidate.name
    summary_json = json.dumps(
        dict(deterministic_summary or {}),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    extra_focus = focus.strip() or (
        "Judge whether this PDF is ready for a top-tier AAAI main track "
        "submission, and identify the highest-leverage fixes."
    )
    return f"""\
You are an independent paper-review route for Research Harness.

Review the candidate as a strict AAAI main track reviewer. Work read-only:
inspect local files if your host agent can access them, but do not edit files.

Candidate label: {label}
Candidate path: {candidate}
Primary PDF if present: {candidate / "paper.pdf"}

Focus:
{extra_focus}

Reviewer route profile:
{route_profile.strip() or "Generic independent AAAI-main paper review."}

Deterministic RH hard-gate summary:
{summary_json}

Evaluate these dimensions at a top AAAI-main standard:
- AAAI style and submission-format compliance.
- Content novelty, technical contribution, and scope discipline.
- Method soundness, falsifiability, and reproducibility.
- Experimental record richness, ablations, baselines, and quantitative evidence.
- Figure quality, visual/table complexity, and whether visuals carry real evidence.
- Citation quality, quantity, recency, venue strength, and citation hygiene.
- Expression precision, logical flow, claim calibration, and reviewer confidence.

Return only strict JSON, with no markdown and no prose outside the JSON object:
{{
  "verdict": "approve|revise|reject",
  "route": "host_agent_review",
  "issues": [
    {{
      "severity": "critical|high|medium|low",
      "category": "format|evidence|visual|citation|novelty|clarity|reproducibility|scope",
      "target": "specific file/section/figure/table/claim",
      "reasoning": "why this blocks or weakens AAAI-main readiness",
      "suggested_fix": "concrete fix"
    }}
  ],
  "scores": {{
    "aaai_readiness": 1,
    "content": 1,
    "evidence": 1,
    "visuals": 1,
    "citations": 1,
    "expression": 1,
    "format": 1
  }},
  "notes": "overall assessment"
}}
"""


def run_host_agent_reviews(
    candidate_path: str | Path,
    *,
    config: MultiRouteReviewConfig | None = None,
    workspace_path: str | Path | None = None,
    timeout_seconds: int = 180,
    candidate_label: str = "",
    deterministic_summary: Mapping[str, Any] | None = None,
) -> tuple[ExecutedReviewRouteResult, ...]:
    effective_config = config or MultiRouteReviewConfig()
    fallback_route = _select_host_agent_fallback(effective_config)
    if fallback_route is None:
        return (
            run_cursor_agent_review(
                candidate_path,
                config=effective_config,
                workspace_path=workspace_path,
                timeout_seconds=timeout_seconds,
                candidate_label=candidate_label,
                deterministic_summary=deterministic_summary,
            ),
            run_codex_agent_review(
                candidate_path,
                config=effective_config,
                workspace_path=workspace_path,
                timeout_seconds=timeout_seconds,
                candidate_label=candidate_label,
                deterministic_summary=deterministic_summary,
            ),
        )

    selected_host = (
        run_cursor_agent_review
        if fallback_route[0] == "cursor_agent_review"
        else run_codex_agent_review
    )
    results: list[ExecutedReviewRouteResult] = [
        selected_host(
            candidate_path,
            config=effective_config,
            workspace_path=workspace_path,
            timeout_seconds=timeout_seconds,
            candidate_label=candidate_label,
            deterministic_summary=deterministic_summary,
        )
    ]
    availability = detect_review_route_availability(config=effective_config)
    for route in availability:
        if route.status != "runnable_via_host_agent":
            continue
        results.append(
            run_host_agent_proxy_review(
                candidate_path,
                source_route=route.route,
                config=effective_config,
                workspace_path=workspace_path,
                timeout_seconds=timeout_seconds,
                candidate_label=candidate_label,
                deterministic_summary=deterministic_summary,
                preferred_host_route=fallback_route[0],
            )
        )
    return tuple(results)


def run_host_agent_proxy_review(
    candidate_path: str | Path,
    *,
    source_route: str,
    config: MultiRouteReviewConfig | None = None,
    workspace_path: str | Path | None = None,
    timeout_seconds: int = 180,
    candidate_label: str = "",
    deterministic_summary: Mapping[str, Any] | None = None,
    preferred_host_route: str = "",
) -> ExecutedReviewRouteResult:
    effective_config = config or MultiRouteReviewConfig()
    fallback_route = (
        _host_agent_tuple(preferred_host_route, effective_config)
        if preferred_host_route
        else _select_host_agent_fallback(effective_config)
    )
    if fallback_route is None:
        return ExecutedReviewRouteResult(
            route=f"{source_route}_via_host_agent",
            status="blocked",
            source="host agent proxy",
            missing=("agent or codex",),
            error="No host-agent CLI is available for reviewer proxy execution",
            metadata={"source_route": source_route},
        )

    candidate = Path(candidate_path).expanduser().resolve()
    workspace = _resolve_workspace(candidate, workspace_path)
    summary = (
        deterministic_summary or run_deterministic_aaai_pdf_gate(candidate).summary
    )
    route_profile = _PROXY_REVIEW_ROUTE_PROFILES.get(
        source_route,
        f"{source_route}-style paper review.",
    )
    prompt = build_aaai_review_prompt(
        candidate,
        candidate_label=candidate_label,
        deterministic_summary=summary,
        focus=(
            f"Run this as a proxy for `{source_route}` because the native route "
            "is not currently runnable in this environment."
        ),
        route_profile=route_profile,
    )
    host_route, host_source = fallback_route
    result_route = f"{source_route}_via_{host_route.removesuffix('_review')}"
    if host_route == "cursor_agent_review":
        return _run_cursor_agent_prompt(
            route=result_route,
            agent=host_source,
            prompt=prompt,
            workspace=workspace,
            timeout_seconds=timeout_seconds,
            config=effective_config,
            metadata={"source_route": source_route, "fallback_route": host_route},
        )
    return _run_codex_agent_prompt(
        route=result_route,
        codex=host_source,
        prompt=prompt,
        workspace=workspace,
        timeout_seconds=timeout_seconds,
        config=effective_config,
        metadata={"source_route": source_route, "fallback_route": host_route},
    )


def run_codex_agent_review(
    candidate_path: str | Path,
    *,
    config: MultiRouteReviewConfig | None = None,
    workspace_path: str | Path | None = None,
    timeout_seconds: int = 180,
    candidate_label: str = "",
    deterministic_summary: Mapping[str, Any] | None = None,
) -> ExecutedReviewRouteResult:
    effective_config = config or MultiRouteReviewConfig()
    codex = effective_config.find_executable("codex")
    if not codex:
        return ExecutedReviewRouteResult(
            route="codex_agent_review",
            status="blocked",
            source="codex CLI",
            missing=("codex",),
            error="codex CLI not found in PATH",
        )

    candidate = Path(candidate_path).expanduser().resolve()
    workspace = _resolve_workspace(candidate, workspace_path)
    summary = (
        deterministic_summary or run_deterministic_aaai_pdf_gate(candidate).summary
    )
    prompt = build_aaai_review_prompt(
        candidate,
        candidate_label=candidate_label,
        deterministic_summary=summary,
        focus="Run a strict independent PDF-quality review via codex exec.",
    )
    out_path = _temporary_output_path(prefix="rh_codex_review_")
    cmd = [
        codex,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "-C",
        str(workspace),
    ]
    model = effective_config.getenv(
        "RESEARCH_HARNESS_CODEX_REVIEW_MODEL"
    ) or effective_config.getenv("CODEX_REVIEW_MODEL")
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-o", str(out_path), prompt])

    try:
        result = effective_config.run_command(
            cmd,
            timeout=timeout_seconds,
            cwd=workspace,
        )
        raw = _read(out_path).strip() or (result.stdout or "").strip()
        out_path.unlink(missing_ok=True)
        if result.returncode != 0:
            return ExecutedReviewRouteResult(
                route="codex_agent_review",
                status="failed",
                source=codex,
                raw_output=raw,
                error=(result.stderr or "")[:2000],
                metadata={"returncode": result.returncode, "workspace": str(workspace)},
            )
        return _executed_review_from_raw(
            route="codex_agent_review",
            source=codex,
            raw=raw,
            metadata={"workspace": str(workspace)},
        )
    except subprocess.TimeoutExpired:
        out_path.unlink(missing_ok=True)
        return ExecutedReviewRouteResult(
            route="codex_agent_review",
            status="failed",
            source=codex,
            error=f"codex exec timed out after {timeout_seconds}s",
            metadata={"workspace": str(workspace)},
        )
    except Exception as exc:
        out_path.unlink(missing_ok=True)
        return ExecutedReviewRouteResult(
            route="codex_agent_review",
            status="failed",
            source=codex,
            error=f"{type(exc).__name__}: {exc}",
            metadata={"workspace": str(workspace)},
        )


def run_cursor_agent_review(
    candidate_path: str | Path,
    *,
    config: MultiRouteReviewConfig | None = None,
    workspace_path: str | Path | None = None,
    timeout_seconds: int = 180,
    candidate_label: str = "",
    deterministic_summary: Mapping[str, Any] | None = None,
) -> ExecutedReviewRouteResult:
    effective_config = config or MultiRouteReviewConfig()
    agent = effective_config.find_executable("agent")
    if not agent:
        return ExecutedReviewRouteResult(
            route="cursor_agent_review",
            status="blocked",
            source="Cursor Agent CLI",
            missing=("agent",),
            error="Cursor Agent CLI (`agent`) not found in PATH",
        )

    candidate = Path(candidate_path).expanduser().resolve()
    workspace = _resolve_workspace(candidate, workspace_path)
    summary = (
        deterministic_summary or run_deterministic_aaai_pdf_gate(candidate).summary
    )
    prompt = build_aaai_review_prompt(
        candidate,
        candidate_label=candidate_label,
        deterministic_summary=summary,
        focus="Run a strict independent PDF-quality review via Cursor Agent.",
    )
    cmd = [
        agent,
        "-p",
        "--output-format",
        "text",
        "--workspace",
        str(workspace),
        "--trust",
        "--mode",
        "ask",
    ]
    model = effective_config.getenv(
        "RESEARCH_HARNESS_CURSOR_AGENT_MODEL"
    ) or effective_config.getenv("CURSOR_AGENT_MODEL")
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    try:
        result = effective_config.run_command(
            cmd,
            timeout=timeout_seconds,
            cwd=workspace,
        )
        raw = (result.stdout or "").strip()
        if result.returncode != 0:
            return ExecutedReviewRouteResult(
                route="cursor_agent_review",
                status="failed",
                source=agent,
                raw_output=raw,
                error=(result.stderr or "")[:2000],
                metadata={"returncode": result.returncode, "workspace": str(workspace)},
            )
        return _executed_review_from_raw(
            route="cursor_agent_review",
            source=agent,
            raw=raw,
            metadata={"workspace": str(workspace)},
        )
    except subprocess.TimeoutExpired:
        return ExecutedReviewRouteResult(
            route="cursor_agent_review",
            status="failed",
            source=agent,
            error=f"Cursor Agent timed out after {timeout_seconds}s",
            metadata={"workspace": str(workspace)},
        )
    except Exception as exc:
        return ExecutedReviewRouteResult(
            route="cursor_agent_review",
            status="failed",
            source=agent,
            error=f"{type(exc).__name__}: {exc}",
            metadata={"workspace": str(workspace)},
        )


def _run_cursor_agent_prompt(
    *,
    route: str,
    agent: str,
    prompt: str,
    workspace: Path,
    timeout_seconds: int,
    config: MultiRouteReviewConfig,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutedReviewRouteResult:
    cmd = [
        agent,
        "-p",
        "--output-format",
        "text",
        "--workspace",
        str(workspace),
        "--trust",
        "--mode",
        "ask",
    ]
    model = config.getenv("RESEARCH_HARNESS_CURSOR_AGENT_MODEL") or config.getenv(
        "CURSOR_AGENT_MODEL"
    )
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    merged_metadata = {"workspace": str(workspace), **dict(metadata or {})}
    try:
        result = config.run_command(cmd, timeout=timeout_seconds, cwd=workspace)
        raw = (result.stdout or "").strip()
        if result.returncode != 0:
            return ExecutedReviewRouteResult(
                route=route,
                status="failed",
                source=agent,
                raw_output=raw,
                error=(result.stderr or "")[:2000],
                metadata={
                    **merged_metadata,
                    "returncode": result.returncode,
                },
            )
        return _executed_review_from_raw(
            route=route,
            source=agent,
            raw=raw,
            metadata=merged_metadata,
        )
    except subprocess.TimeoutExpired:
        return ExecutedReviewRouteResult(
            route=route,
            status="failed",
            source=agent,
            error=f"Cursor Agent timed out after {timeout_seconds}s",
            metadata=merged_metadata,
        )
    except Exception as exc:
        return ExecutedReviewRouteResult(
            route=route,
            status="failed",
            source=agent,
            error=f"{type(exc).__name__}: {exc}",
            metadata=merged_metadata,
        )


def _run_codex_agent_prompt(
    *,
    route: str,
    codex: str,
    prompt: str,
    workspace: Path,
    timeout_seconds: int,
    config: MultiRouteReviewConfig,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutedReviewRouteResult:
    out_path = _temporary_output_path(prefix="rh_codex_review_")
    cmd = [
        codex,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "-C",
        str(workspace),
    ]
    model = config.getenv("RESEARCH_HARNESS_CODEX_REVIEW_MODEL") or config.getenv(
        "CODEX_REVIEW_MODEL"
    )
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-o", str(out_path), prompt])

    merged_metadata = {"workspace": str(workspace), **dict(metadata or {})}
    try:
        result = config.run_command(cmd, timeout=timeout_seconds, cwd=workspace)
        raw = _read(out_path).strip() or (result.stdout or "").strip()
        out_path.unlink(missing_ok=True)
        if result.returncode != 0:
            return ExecutedReviewRouteResult(
                route=route,
                status="failed",
                source=codex,
                raw_output=raw,
                error=(result.stderr or "")[:2000],
                metadata={
                    **merged_metadata,
                    "returncode": result.returncode,
                },
            )
        return _executed_review_from_raw(
            route=route,
            source=codex,
            raw=raw,
            metadata=merged_metadata,
        )
    except subprocess.TimeoutExpired:
        out_path.unlink(missing_ok=True)
        return ExecutedReviewRouteResult(
            route=route,
            status="failed",
            source=codex,
            error=f"codex exec timed out after {timeout_seconds}s",
            metadata=merged_metadata,
        )
    except Exception as exc:
        out_path.unlink(missing_ok=True)
        return ExecutedReviewRouteResult(
            route=route,
            status="failed",
            source=codex,
            error=f"{type(exc).__name__}: {exc}",
            metadata=merged_metadata,
        )


def _executed_review_from_raw(
    *,
    route: str,
    source: str,
    raw: str,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutedReviewRouteResult:
    if not raw:
        return ExecutedReviewRouteResult(
            route=route,
            status="failed",
            source=source,
            error="host agent returned empty output",
            metadata=dict(metadata or {}),
        )
    parsed = _parse_agent_review_output(raw)
    return ExecutedReviewRouteResult(
        route=route,
        status="completed",
        source=source,
        verdict=parsed["verdict"],
        issues=tuple(parsed["issues"]),
        scores=parsed["scores"],
        notes=parsed["notes"],
        raw_output=raw,
        metadata=dict(metadata or {}),
    )


def _parse_agent_review_output(raw: str) -> dict[str, Any]:
    data = _extract_json_object(raw)
    if data is None:
        return {
            "verdict": _infer_verdict(raw),
            "issues": [],
            "scores": {},
            "notes": raw[:2000],
        }
    return {
        "verdict": _normalize_verdict(data.get("verdict", "")),
        "issues": tuple(
            _normalize_issue(item) for item in _as_list(data.get("issues"))
        ),
        "scores": data.get("scores", {})
        if isinstance(data.get("scores"), dict)
        else {},
        "notes": str(data.get("notes", "")),
    }


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
    return None


def _normalize_issue(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "severity": "medium",
            "category": "review",
            "target": "",
            "reasoning": str(item),
            "suggested_fix": "",
        }
    return {
        "severity": str(item.get("severity", "")).lower() or "medium",
        "category": str(item.get("category", "")).lower() or "review",
        "target": str(item.get("target", "")),
        "reasoning": str(item.get("reasoning", "")),
        "suggested_fix": str(item.get("suggested_fix", "")),
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_verdict(value: Any) -> str:
    verdict = str(value).strip().lower()
    if verdict in {"accept", "accepted"}:
        return "approve"
    if verdict in {"major_revision", "minor_revision", "revise_and_resubmit"}:
        return "revise"
    if verdict in {"reject", "revise", "approve"}:
        return verdict
    return verdict


def _infer_verdict(raw: str) -> str:
    lower = raw.lower()
    if "verdict" in lower and "approve" in lower:
        return "approve"
    if "verdict" in lower and "reject" in lower:
        return "reject"
    if "verdict" in lower and "revise" in lower:
        return "revise"
    return ""


def _resolve_workspace(candidate: Path, workspace_path: str | Path | None) -> Path:
    if workspace_path is not None:
        return Path(workspace_path).expanduser().resolve()
    return candidate if candidate.is_dir() else candidate.parent


def _temporary_output_path(*, prefix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        suffix=".txt",
        prefix=prefix,
        delete=False,
    )
    try:
        return Path(handle.name)
    finally:
        handle.close()


def _build_deterministic_findings(summary: dict[str, Any]) -> list[ReviewFinding]:
    tex_bib = summary.get("tex_bib", {})
    log = summary.get("log", {})
    findings: list[ReviewFinding] = []
    if not tex_bib.get("official_aaai_style_detected"):
        findings.append(
            ReviewFinding(
                severity="critical",
                category="format",
                message=(
                    "Official AAAI style was not detected; candidate uses a "
                    "custom article-style route."
                ),
            )
        )
    if int(tex_bib.get("tables", 0)) == 0:
        findings.append(
            ReviewFinding(
                severity="high",
                category="evidence",
                message=(
                    "No table environments detected; evidence density is too "
                    "narrative for an AAAI-main systems paper."
                ),
            )
        )
    if int(tex_bib.get("figures", 0)) < 2:
        findings.append(
            ReviewFinding(
                severity="medium",
                category="visual_evidence",
                message=(
                    "Only one figure detected; add result/coverage or ablation "
                    "visuals before more micro-typography."
                ),
            )
        )
    if any(
        int(log.get(key, 0)) > 0
        for key in ("latex_errors", "undefined_citations", "overfull_hbox")
    ):
        findings.append(
            ReviewFinding(
                severity="high",
                category="compile",
                message=(
                    "Compile log contains LaTeX errors, undefined citations, "
                    "or overfull boxes."
                ),
            )
        )
    font_warnings = int(log.get("font_warnings", 0))
    if font_warnings:
        findings.append(
            ReviewFinding(
                severity="medium",
                category="pdf_technical",
                message=f"{font_warnings} font warning(s) remain in the LaTeX log.",
            )
        )
    return findings


def _scan_tex_and_bib(candidate: Path) -> dict[str, Any]:
    tex = _read(candidate / "paper.tex")
    bib = _read(candidate / "references.bib")
    figure_count = len(re.findall(r"\\begin\{figure\*?\}", tex))
    table_count = len(re.findall(r"\\begin\{table\*?\}", tex))
    algorithm_count = len(re.findall(r"\\begin\{algorithm", tex))
    caption_count = len(re.findall(r"\\caption\{", tex))
    cite_groups = re.findall(r"\\cite[pt]?\{([^}]+)\}", tex)
    cite_keys = {
        key.strip() for group in cite_groups for key in group.split(",") if key.strip()
    }
    bib_entries = set(re.findall(r"^@\w+\{([^,]+),", bib, flags=re.MULTILINE))
    years = re.findall(r"\byear\s*=\s*\{([^}]+)\}", bib, flags=re.IGNORECASE)
    official_aaai_style = bool(
        re.search(r"\\documentclass(?:\[[^]]*\])?\{aaai", tex)
        or re.search(r"\\usepackage(?:\[[^]]*\])?\{aaai", tex)
        or list(candidate.glob("aaai*.sty"))
    )
    style_risks = tuple(
        label
        for marker, label in (
            ("geometry", "custom geometry package"),
            ("titlesec", "custom titlesec package"),
            ("plainnat", "plainnat bibliography style"),
        )
        if marker in tex
    )
    arxiv_marker_count = len(
        re.findall(r"arxiv|arXiv|arXiv\.org|arXiv \(Cornell University\)", bib)
    )
    return {
        "official_aaai_style_detected": official_aaai_style,
        "style_risks": style_risks,
        "figures": figure_count,
        "tables": table_count,
        "algorithms": algorithm_count,
        "captions": caption_count,
        "bib_entries": len(bib_entries),
        "citation_keys_used": len(cite_keys),
        "unused_bib_entries_estimate": max(0, len(bib_entries - cite_keys)),
        "reference_year_histogram": dict(Counter(years)),
        "arxiv_marker_count": arxiv_marker_count,
    }


def _scan_log(log_text: str) -> dict[str, Any]:
    return {
        "latex_errors": log_text.count("! LaTeX Error"),
        "undefined_citations": log_text.count("Undefined citation"),
        "overfull_hbox": len(re.findall(r"Overfull \\hbox", log_text)),
        "underfull_hbox": len(re.findall(r"Underfull \\hbox", log_text)),
        "underfull_line_ranges": tuple(
            re.findall(
                r"Underfull \\hbox(?: \(badness \d+\))? in paragraph at lines "
                r"(\d+(?:--\d+)?)",
                log_text,
            )
        ),
        "font_warnings": len(re.findall(r"LaTeX Font Warning", log_text)),
        "missing_characters": len(re.findall(r"Missing character:", log_text)),
    }


def _count_pdf_pages_and_words(pdf_path: Path) -> dict[str, Any]:
    if not pdf_path.exists():
        return {"available": False, "error": f"missing PDF: {pdf_path}"}
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    image_count = sum(len(page.get_images(full=True)) for page in doc)
    return {
        "available": True,
        "pages": doc.page_count,
        "pdf_text_words": len(words),
        "embedded_image_instances": image_count,
    }


def _missing_modules(
    config: MultiRouteReviewConfig,
    names: tuple[str, ...],
) -> list[str]:
    return [name for name in names if not config.has_module(name)]


def _has_llm_key(config: MultiRouteReviewConfig) -> bool:
    return any(
        config.getenv(name)
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DASHSCOPE_API_KEY",
            "KIMI_API_KEY",
        )
    )


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _default_ai_scientist_root() -> Path:
    return state_path("competitive_src", "AI-Scientist")


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")
