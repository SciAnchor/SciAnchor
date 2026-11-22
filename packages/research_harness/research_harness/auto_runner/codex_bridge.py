"""Codex bridge — invoke codex review/exec and parse responses.

Codex is an independent CLI (OpenAI API) that works regardless of
ANTHROPIC_* env vars. Used for adversarial review at quality gates.

Backends (tried in order):
  1. ``codex`` CLI — preferred, independent cross-model review
  2. headless ``claude -p`` — the host ``claude`` wrapper owns model routing
     and provider failover, so this module keeps no route chain of its own

Stability hardening:
  - Pre-flight check skips codex when binary is missing or breaker is tripped,
    avoiding ``timeout_seconds`` stalls on obviously-dead paths.
  - ``stdin=subprocess.DEVNULL`` prevents ``codex exec`` from hanging waiting
    for stdin in environments that don't close it automatically.
  - A per-backend circuit breaker trips after ``_BREAKER_THRESHOLD`` consecutive
    failures and cools off for ``_BREAKER_COOL_OFF_SECONDS``. Only codex is
    skipped when tripped; claude is always attempted as last resort.
  - The claude reviewer runs ``--restricted --strict-mcp-config`` with no
    tools, so user hooks, settings and MCP servers never reach it.

Set RESEARCH_HARNESS_ADVERSARIAL_BACKEND=claude to skip codex.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Per-backend timeouts. Both are CLI agents with cold starts.
_BACKEND_TIMEOUTS: dict[str, int] = {
    "codex": int(
        os.environ.get("RESEARCH_HARNESS_ADVERSARIAL_CODEX_TIMEOUT", "180") or "180"
    ),
    "claude": int(
        os.environ.get("RESEARCH_HARNESS_ADVERSARIAL_CLAUDE_TIMEOUT", "300") or "300"
    ),
}

# Circuit breaker config: trip after N consecutive failures, cool off for T s.
_BREAKER_THRESHOLD = 3
_BREAKER_COOL_OFF_SECONDS = 60.0

# Default codex review prompt template
# API-backend blindness guard: codex CLI reads {artifact_path} from disk
# itself, but the tool-less claude backend cannot open files —
# they MUST get the content inlined or every persona reviews a filename and
# the parser falls back to generic revise/score-1 output (found in E0c).
_ARTIFACT_INLINE_MAX_CHARS = 70000


@functools.lru_cache(maxsize=8)
def _codex_exec_supports(codex: str, flag: str) -> bool:
    """Whether this codex build accepts ``flag`` on ``codex exec``.

    The CLI's flags move between releases, and an unsupported one makes the
    call exit non-zero with the prompt unread — which the caller then reports
    as a fallback rather than as a misconfiguration. Probing is cheap and
    cached; a probe that cannot run answers False so behaviour degrades to the
    flagless invocation rather than to a hard failure.
    """
    try:
        result = subprocess.run(
            [codex, "exec", "--help"],
            capture_output=True,
            text=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return flag in (result.stdout or "") + (result.stderr or "")


def _artifact_content_block(artifact_path: Path) -> str:
    try:
        text = Path(artifact_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.strip():
        return ""
    clipped = text[:_ARTIFACT_INLINE_MAX_CHARS]
    suffix = (
        "\n[... truncated for length ...]"
        if len(text) > _ARTIFACT_INLINE_MAX_CHARS
        else ""
    )
    return f"\n\nARTIFACT CONTENT (verbatim):\n{clipped}{suffix}"


ADVERSARIAL_REVIEW_TEMPLATE = """\
Review the research artifact at: {artifact_path}

Stage: {stage}
Focus: {focus}

Evidence summary:
{evidence_summary}

Evaluate on these dimensions:
- novelty: Is the contribution genuinely new?
- evidence_coverage: Are claims supported by sufficient evidence?
- method_validity: Is the methodology sound?
- baseline_completeness: Are key baselines included?
- scope_discipline: Is the scope well-bounded?
- falsifiability: Can claims be tested/refuted?
- clarity: Is the writing clear and precise?

Return your review as structured JSON:
{{
  "verdict": "approve" or "revise",
  "issues": [
    {{
      "severity": "critical|major|minor",
      "category": "<dimension>",
      "target": "<what specifically>",
      "reasoning": "<why this is a problem>",
      "suggested_fix": "<how to fix>"
    }}
  ],
  "scores": {{
    "novelty": <1-5>,
    "evidence_coverage": <1-5>,
    "method_validity": <1-5>,
    "baseline_completeness": <1-5>,
    "scope_discipline": <1-5>,
    "falsifiability": <1-5>,
    "clarity": <1-5>
  }},
  "notes": "<overall assessment>"
}}
"""


# ---------------------------------------------------------------------------
# Circuit breaker (per-backend)
# ---------------------------------------------------------------------------


@dataclass
class _BackendState:
    failures: int = 0
    tripped_until: float = 0.0


class _CircuitBreaker:
    """Track consecutive failures per backend and skip tripped backends.

    Thread-safe. State is process-local; restarts reset everything.
    """

    def __init__(
        self,
        threshold: int = _BREAKER_THRESHOLD,
        cool_off_seconds: float = _BREAKER_COOL_OFF_SECONDS,
    ) -> None:
        self._threshold = threshold
        self._cool_off = cool_off_seconds
        self._state: dict[str, _BackendState] = {}
        self._lock = threading.Lock()

    def is_open(self, backend: str) -> bool:
        """True while the backend is in cool-off."""
        with self._lock:
            s = self._state.get(backend)
            if s is None:
                return False
            return s.tripped_until > time.time()

    def record_success(self, backend: str) -> None:
        with self._lock:
            self._state[backend] = _BackendState()

    def record_failure(self, backend: str) -> None:
        with self._lock:
            s = self._state.setdefault(backend, _BackendState())
            s.failures += 1
            if s.failures >= self._threshold:
                s.tripped_until = time.time() + self._cool_off

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


_BREAKER = _CircuitBreaker()


def _reset_breaker_for_tests() -> None:
    """Reset the module-level breaker. Intended for pytest fixtures only."""
    _BREAKER.reset()


# ---------------------------------------------------------------------------
# Codex discovery + pre-flight
# ---------------------------------------------------------------------------


def _find_codex() -> str | None:
    """Find the codex CLI binary."""
    try:
        result = subprocess.run(
            ["which", "codex"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _codex_preflight() -> tuple[bool, str]:
    """Cheap check before spending a 180s timeout on ``codex exec``.

    Returns ``(ok, reason)``. When ``ok`` is False, callers should fall
    through to the claude backend without invoking the subprocess.
    """
    if _BREAKER.is_open("codex"):
        return False, "codex circuit breaker open (recent failures)"
    if _find_codex() is None:
        return False, "codex CLI not found in PATH"
    return True, ""


# ---------------------------------------------------------------------------
# Claude backend (fallback and RESEARCH_HARNESS_ADVERSARIAL_BACKEND=claude)
# ---------------------------------------------------------------------------


def _adversarial_via_claude(
    *,
    artifact_path: Path,
    stage: str,
    focus: str,
    evidence_summary: str = "",
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Run adversarial review through headless ``claude -p``.

    Model choice and provider failover belong to the ``claude`` wrapper on the
    host, so this backend does not pick a model or carry its own route chain.
    """
    claude = shutil.which(os.environ.get("RESEARCH_HARNESS_CLAUDE_BIN", "claude"))
    if claude is None:
        _BREAKER.record_failure("claude")
        return _failed("claude", "claude CLI not found in PATH")

    prompt = ADVERSARIAL_REVIEW_TEMPLATE.format(
        artifact_path=artifact_path,
        stage=stage,
        focus=focus,
        evidence_summary=evidence_summary[:3000],
    ) + _artifact_content_block(artifact_path)

    try:
        result = subprocess.run(
            [
                claude,
                "-p",
                "--restricted",
                "--strict-mcp-config",
                "--tools",
                "",
                "--output-format",
                "text",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_seconds or _BACKEND_TIMEOUTS["claude"],
        )
    except subprocess.TimeoutExpired:
        _BREAKER.record_failure("claude")
        return _failed("claude", "claude -p timed out")
    except OSError as exc:
        _BREAKER.record_failure("claude")
        return _failed("claude", f"claude -p failed to start: {exc}")

    raw = (result.stdout or "").strip()
    if result.returncode != 0 or not raw:
        _BREAKER.record_failure("claude")
        return _failed(
            "claude",
            f"claude -p exited {result.returncode}: {(result.stderr or '')[:500]}",
        )
    parsed = _parse_codex_output(raw)
    parsed["success"] = True
    parsed["raw_output"] = raw
    parsed["backend"] = "claude"
    _BREAKER.record_success("claude")
    logger.info("Adversarial review completed via claude -p")
    return parsed


def _failed(backend: str, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": error,
        "verdict": "",
        "issues": [],
        "scores": {},
        "notes": "",
        "raw_output": "",
        "backend": backend,
    }


# ---------------------------------------------------------------------------
# Main entry: run_codex_review
# ---------------------------------------------------------------------------


def run_codex_review(
    *,
    artifact_path: Path,
    stage: str,
    focus: str,
    evidence_summary: str = "",
    cwd: Path | None = None,
    timeout_seconds: int | None = None,
    effort: str = "medium",
) -> dict[str, Any]:
    """Run adversarial review on an artifact and return parsed response.

    Backends:
      1. ``codex`` CLI — independent cross-model review (preferred)
      2. headless ``claude -p`` — when codex is missing, tripped or fails

    Set ``RESEARCH_HARNESS_ADVERSARIAL_BACKEND`` to any value other than
    ``codex`` to go straight to ``claude -p``.

    ``timeout_seconds`` overrides both per-backend defaults. When None, each
    backend uses its entry in ``_BACKEND_TIMEOUTS``.

    Returns a dict with keys: success, verdict, issues, scores, notes,
    raw_output, backend.
    """
    backend_env = os.environ.get("RESEARCH_HARNESS_ADVERSARIAL_BACKEND", "").lower()

    if backend_env and backend_env != "codex":
        return _adversarial_via_claude(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
            timeout_seconds=timeout_seconds,
        )

    ok, reason = _codex_preflight()
    if not ok:
        logger.info(
            "codex pre-flight failed (%s) — using fallback chain for adversarial review",
            reason,
        )
        return _adversarial_via_claude(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )

    # _codex_preflight already verified the binary exists.
    codex = _find_codex()
    if codex is None:
        # Race: binary disappeared between preflight and here. Treat as fallback.
        _BREAKER.record_failure("codex")
        return _adversarial_via_claude(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )

    prompt = ADVERSARIAL_REVIEW_TEMPLATE.format(
        artifact_path=artifact_path,
        stage=stage,
        focus=focus,
        evidence_summary=evidence_summary[:3000],
    )

    codex_timeout = timeout_seconds or _BACKEND_TIMEOUTS["codex"]

    import tempfile

    out_file = tempfile.NamedTemporaryFile(
        suffix=".txt", prefix="codex_review_", delete=False
    )
    out_path = out_file.name
    out_file.close()

    # `--full-auto` was removed from `codex exec` (present through ~0.1.x, gone
    # by 0.147). Passing it makes every call exit 2 and fall back silently, so
    # the review runs without codex while still reporting that it ran. Probe
    # the installed CLI instead of assuming either spelling.
    cmd = [codex, "exec"]
    if _codex_exec_supports(codex, "--full-auto"):
        cmd.append("--full-auto")
    elif _codex_exec_supports(codex, "--sandbox"):
        cmd += ["--sandbox", "workspace-write"]
    cmd += ["--skip-git-repo-check", "-o", out_path, prompt]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=codex_timeout,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
        )
        try:
            raw = Path(out_path).read_text(encoding="utf-8").strip()
        except OSError:
            raw = result.stdout.strip()
        finally:
            Path(out_path).unlink(missing_ok=True)

        if result.returncode != 0 and not raw:
            _BREAKER.record_failure("codex")
            logger.warning(
                "codex exited with code %s: %s — falling back to adversarial review chain",
                result.returncode,
                (result.stderr or "")[:500],
            )
            return _adversarial_via_claude(
                artifact_path=artifact_path,
                stage=stage,
                focus=focus,
                evidence_summary=evidence_summary,
            )

        parsed = _parse_codex_output(raw)
        parsed["success"] = True
        parsed["raw_output"] = raw
        parsed["backend"] = "codex"
        _BREAKER.record_success("codex")
        return parsed

    except subprocess.TimeoutExpired:
        Path(out_path).unlink(missing_ok=True)
        _BREAKER.record_failure("codex")
        logger.warning(
            "codex timed out after %ds — falling back to adversarial review chain",
            codex_timeout,
        )
        return _adversarial_via_claude(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )
    except Exception as exc:
        Path(out_path).unlink(missing_ok=True)
        _BREAKER.record_failure("codex")
        logger.warning(
            "codex subprocess failed: %s — falling back to adversarial review chain",
            exc,
        )
        return _adversarial_via_claude(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )


def _parse_codex_output(raw: str) -> dict[str, Any]:
    """Parse codex output, trying JSON extraction."""
    # Try direct JSON parse
    try:
        data = json.loads(raw)
        return _normalize_review(data)
    except json.JSONDecodeError:
        pass

    extracted = _extract_first_json_object(raw)
    if extracted:
        try:
            data = json.loads(extracted)
            return _normalize_review(data)
        except json.JSONDecodeError:
            pass

    # Try extracting JSON from markdown fences
    for marker in ("```json", "```"):
        start = raw.find(marker)
        if start < 0:
            continue
        start += len(marker)
        end = raw.find("```", start)
        block = raw[start:] if end < 0 else raw[start:end]
        try:
            data = json.loads(block.strip())
            return _normalize_review(data)
        except json.JSONDecodeError:
            continue

    # Fallback: extract verdict from text
    verdict = ""
    lower = raw.lower()
    if "verdict: approve" in lower or '"verdict": "approve"' in lower:
        verdict = "approve"
    elif "verdict: revise" in lower or '"verdict": "revise"' in lower:
        verdict = "revise"

    return {
        "verdict": verdict,
        "issues": [],
        "scores": {},
        "notes": raw[:1000],
    }


def _extract_first_json_object(raw: str) -> str:
    """Return the first balanced JSON object embedded in text, if present."""

    start = raw.find("{")
    if start < 0:
        return ""

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        char = raw[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]
    return ""


def _normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize parsed review data to expected schema."""
    return {
        "verdict": str(data.get("verdict", "")).strip().lower(),
        "issues": data.get("issues", [])
        if isinstance(data.get("issues"), list)
        else [],
        "scores": data.get("scores", {})
        if isinstance(data.get("scores"), dict)
        else {},
        "notes": str(data.get("notes", "")),
    }


def save_handoff_request(
    handoff_dir: Path,
    *,
    stage: str,
    artifact_path: str,
    focus: str,
    evidence_summary: str,
) -> Path:
    """Write handoff request file for codex."""
    handoff_dir.mkdir(parents=True, exist_ok=True)
    request_path = handoff_dir / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "stage": stage,
                "artifact_path": artifact_path,
                "focus": focus,
                "evidence_summary": evidence_summary[:3000],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return request_path


def save_handoff_response(handoff_dir: Path, response: dict[str, Any]) -> Path:
    """Write codex response to handoff file."""
    handoff_dir.mkdir(parents=True, exist_ok=True)
    response_path = handoff_dir / "response.json"
    response_path.write_text(
        json.dumps(response, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return response_path


def load_handoff_response(handoff_dir: Path) -> dict[str, Any] | None:
    """Load a previously saved codex response."""
    response_path = handoff_dir / "response.json"
    if not response_path.exists():
        return None
    try:
        return json.loads(response_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def codex_issues_to_objections(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert codex review issues to orchestrator adversarial objections format."""
    objections = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        objections.append(
            {
                "category": str(issue.get("category", "general")),
                "severity": str(issue.get("severity", "minor")),
                "target": str(issue.get("target", "")),
                "reasoning": str(issue.get("reasoning", "")),
                "suggested_fix": str(issue.get("suggested_fix", "")),
            }
        )
    return objections
