"""LLM-backed primitive implementations using the shared paperindex client."""

from __future__ import annotations

from research_harness.acquisition.spc_bridge import SPCAcquisitionError

import collections
import hashlib
import json
import logging
import os
import re
import threading as _threading
from typing import Any

from llm_router.client import (
    BudgetAuthorization,
    LLMClient,
    ProviderUsageReceipt,
    TaskTier,
    get_last_usage,
    resolve_llm_config,
)

from research_harness._selfdev.writing_logic_gate_runtime import (
    _active_paper_plan,
    ensure_section_draft_logic_gate,
)
from research_harness.primitives.types import (
    AlgorithmCandidateGenerateOutput,
    AccountedPrimitiveOutput,
    AlgorithmDesignLoopOutput,
    AlgorithmDesignRefineOutput,
    Baseline,
    BaselineIdentifyOutput,
    Claim,
    ClaimExtractOutput,
    CodeGenerationOutput,
    CompetitiveLearningOutput,
    ConsistencyCheckOutput,
    ConsistencyIssue,
    ContradictionDetectOutput,
    CoverageCheckOutput,
    CoverageItem,
    CrossPaperLink,
    DeepReadingNote,
    DeepReadingOutput,
    DesignBriefOutput,
    DesignGapProbeOutput,
    DeterministicCheck,
    DirectionRankingOutput,
    DraftText,
    EvidenceMatrixOutput,
    FigureGenerateOutput,
    FigureInterpretOutput,
    FigurePlanOutput,
    Gap,
    GapDetectOutput,
    GapGroundVerifyOutput,
    GroundedPriorArt,
    IndustrialFeasibility,
    IterativeRetrievalLoopOutput,
    LessonExtractOutput,
    MethodLayerExpansionOutput,
    MethodQuery,
    MethodTaxonomyOutput,
    OriginalityBoundaryCheckOutput,
    OutlineGenerateOutput,
    OutlineSectionItem,
    QueryCandidate,
    QueryRefineOutput,
    RankedDirection,
    RebuttalFormatOutput,
    RetrievalRoundRecord,
    ReviewDimension,
    SectionDraftOutput,
    SectionPlan,
    SectionReviewOutput,
    SectionReviseOutput,
    SummaryOutput,
    TableExtractOutput,
    TopicFramingOutput,
    WritingArchitectureOutput,
    WritingPattern,
    WritingPatternExtractOutput,
)
from research_harness.storage.db import Database
from . import prompts
from .paper_context import (
    PaperContext,
    build_paper_context,
    render_paper_context,
    render_paper_context_full,
)
from .writing_rigor import normalize_section_key, resolve_domain_key


def _record_context_drop(
    *,
    kind: str,
    source_id: str,
    offered: int,
    kept: int,
    reason: str = "",
) -> None:
    """Report one context source to the telemetry scope, if one is open (P-6).

    Lazily imported and fully swallowed: instrumentation must never alter or
    break an assembly path. Outside a scope this is a no-op.
    """
    try:
        from research_harness.runtime.context_telemetry import record_source

        record_source(
            kind=kind,
            source_id=source_id,
            offered=offered,
            kept=kept,
            reason=reason,
        )
    except Exception:  # noqa: BLE001 - telemetry must never break a run
        return


logger = logging.getLogger(__name__)


class AccountedAttemptNotStarted(RuntimeError):
    """The accounted transport was rejected before any provider side effect."""


_SUMMARY_SECTIONS = ("summary", "methodology", "experiments", "limitations")

# Task tier mapping: each primitive gets a complexity tier for auto-routing
_PRIMITIVE_TIERS: dict[str, TaskTier] = {
    "paper_summarize": "light",
    "claim_extract": "medium",
    "gap_detect": "medium",
    "paper_coverage_check": "medium",
    "baseline_identify": "medium",
    "query_refine": "light",
    # WRITING LINE: manuscript prose runs on the writing tier (frontier
    # Claude/GPT only, no silent degradation) — see llm_router RED LINE docs.
    "section_draft": "writing",
    "consistency_check": "writing",
    "deep_read_pass1": "medium",
    "deep_read_pass2": "heavy",
    "outline_generate": "writing",
    "section_review": "writing",
    "section_revise": "writing",
    "compiled_summary": "light",
    "topic_overview": "medium",
    "method_taxonomy": "medium",
    "evidence_matrix": "medium",
    "contradiction_detect": "medium",
    "table_extract": "medium",
    "figure_interpret": "medium",
    "competitive_learning": "medium",
    "topic_framing": "medium",
    "direction_ranking": "medium",
    "method_layer_expansion": "medium",
    "writing_architecture": "writing",
    "writing_pattern_extract": "light",
    "rebuttal_format": "medium",
    "lesson_extract": "light",
    "strategy_distill": "light",
    "strategy_quality_gate": "medium",
    "design_brief_expand": "medium",
    "design_gap_probe": "light",
    "algorithm_candidate_generate": "heavy",
    "originality_boundary_check": "heavy",
    "algorithm_design_refine": "heavy",
    "algorithm_design_loop": "heavy",
}

# RED LINE: primitives that must NEVER use Anthropic API.
# These are bulk paper-reading tasks where basic models suffice.
# The blocklist in client.py enforces at routing level; this set
# is used for assertion-level defense in _get_client.
_ANTHROPIC_BLOCKED_PRIMITIVES: frozenset[str] = frozenset(
    {
        "paper_summarize",
        "claim_extract",
        "gap_detect",
        "paper_coverage_check",
        "baseline_identify",
        "deep_read_pass1",
        "compiled_summary",
        "method_taxonomy",
        "evidence_matrix",
        "table_extract",
        "figure_interpret",
        "lesson_extract",
        "strategy_distill",
        "writing_pattern_extract",
    }
)

FIGURE_MODEL_ENV = "RESEARCH_HARNESS_FIGURE_MODEL"
DEFAULT_FIGURE_MODEL = "gpt-image-2"


_provider_override_local = _threading.local()


def set_provider_override(provider: str | None) -> None:
    """Thread-local override that pins `_get_client` to a specific LLM provider.

    Used by parallel workers (e.g. the expansion deep-read pool) to spread
    requests across every available agent in the pool (anthropic proxy,
    cursor_agent, openai, kimi, …) rather than hammering the single
    tier-routed default. Pass ``None`` to clear. Only in-process; does not
    survive across threads.
    """
    if provider:
        _provider_override_local.provider = provider
    else:
        _provider_override_local.provider = None


def _current_provider_override() -> str | None:
    return getattr(_provider_override_local, "provider", None)


def _describe_client(client: LLMClient) -> str:
    """Return ``provider:model`` for logging / model_used fields.

    Plugin providers may resolve with ``model=''`` and substitute
    their own default inside the chat fn. In that case we emit ``provider:*``
    so downstream displays show *which* backend was used, not an empty string.
    """
    provider = getattr(client, "provider", "") or "?"
    model = getattr(client, "model", "") or "*"
    override = getattr(client, "_override_provider", None)
    if override and override != provider:
        provider = override
    return f"{provider}:{model}"


def _get_client(
    model_override: str | None = None,
    tier: TaskTier | None = None,
    task_name: str = "",
    *,
    accounted: bool = False,
) -> LLMClient:
    if tier == "writing" and not accounted:
        # Accounted calls must resolve exactly once during their explicit
        # preflight. Legacy writing calls keep the daily freshness refresh.
        try:
            from llm_router.model_freshness import maybe_refresh_writing_route

            maybe_refresh_writing_route()
        except Exception:
            logger.debug("writing-tier model freshness check skipped", exc_info=True)
    overrides: dict[str, Any] = {}
    if model_override:
        overrides["model"] = model_override
    provider_hint = _current_provider_override()
    if provider_hint:
        overrides["provider"] = provider_hint
        # A per-call provider override should not inherit a model intended for
        # a different provider (e.g. LLM_ROUTE_MEDIUM pointing at openai:gpt-4o
        # while the thread pinned a different provider).
        overrides.pop("model", None)
    client = LLMClient(resolve_llm_config(overrides or None))
    client._default_tier = tier  # type: ignore[attr-defined]
    # Stash the provider override on the client so _client_chat can bypass
    # tier routing (which would otherwise read LLM_ROUTE_* / built-in default
    # routes and can silently route a Cursor-Agent-backed RH run back to
    # OpenAI/Anthropic). CLI providers authenticate out-of-band and should be
    # honoured as the concrete provider for RH primitives.
    cli_provider = (
        client.provider if client.provider in {"cursor_agent", "codex"} else ""
    )
    client._override_provider = provider_hint or cli_provider  # type: ignore[attr-defined]
    if accounted:
        client = LLMClient(client.preflight_accounted(tier=tier))
    return client


# ---------------------------------------------------------------------------
# Per-primitive token accumulator (thread-local).
#
# A single primitive may call ``_client_chat`` multiple times (e.g. deep_read
# runs two passes, claim_extract may chunk over snippets). The backend resets
# the accumulator before dispatching the primitive impl and reads the totals
# after it returns, then injects them into the emitted ``PrimitiveResult``.
# ---------------------------------------------------------------------------

_token_acc_local = _threading.local()
_accounted_provider_local = _threading.local()


def _set_accounted_provider_context(value):
    previous = getattr(_accounted_provider_local, "value", None)
    _accounted_provider_local.value = value
    return previous


def _get_topic_contributions(db: Database, topic_id: int) -> str:
    """Return stored ``topics.contributions`` for a topic_id, or empty.

    Used by writing primitives (outline_generate, writing_architecture,
    figure_plan, competitive_learning) as a fallback when the caller omits
    the ``contributions`` argument. Makes contributions a topic-level
    config rather than a repeated per-call parameter.
    """
    if not topic_id:
        return ""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    return (row["contributions"] or "").strip()


def _get_topic_latest_project_contributions(db: Database, topic_id: int) -> str:
    """Return contributions from the topic.

    Used when the primitive only has ``topic_id`` — reads directly from
    the ``topics.contributions`` column.
    """
    if not topic_id:
        return ""
    return _get_topic_contributions(db, topic_id)


def _reset_token_accumulator() -> None:
    _token_acc_local.prompt = 0
    _token_acc_local.completion = 0
    _token_acc_local.observed = False


def _reset_last_reply() -> None:
    _token_acc_local.reply = ""


def _last_reply() -> str:
    """The model's last reply, for a refusal raised after it was already paid for.

    The backend turns any exception out of a primitive into ``success=False,
    output=None``, so a primitive that validates the model's answer destroys the
    answer it refused. csmopen12's architecture step paid 21803 completion tokens
    and left artifact 6921 holding a hash and a field name: the refusal could not
    be replayed offline, so the only way to see the offending value again was to
    buy the round a second time.
    """
    return str(getattr(_token_acc_local, "reply", "") or "")


def _accumulated_tokens() -> tuple[int | None, int | None]:
    """Return (prompt, completion) summed across all LLM calls since reset.

    Returns (None, None) if no provider reported usage, so callers cannot tell
    between "zero observed tokens" and "provider does not expose usage".
    """
    if not getattr(_token_acc_local, "observed", False):
        return (None, None)
    return (
        int(getattr(_token_acc_local, "prompt", 0)),
        int(getattr(_token_acc_local, "completion", 0)),
    )


def _client_chat(client: LLMClient, prompt: str | tuple[str, str]) -> str:
    """Call client.chat with tier if available and accumulate token usage.

    ``prompt`` may be a single string or a ``(system, user)`` tuple (from
    algorithm-design prompts). Tuples are joined into one string because
    the generic chat interface only takes a flat prompt; this loses the
    system-vs-user boundary but keeps the single-call path simple.
    """
    if isinstance(prompt, tuple):
        prompt = prompt[0] + "\n\n---\n\n" + prompt[1]
    tier = getattr(client, "_default_tier", None)
    override_provider = getattr(client, "_override_provider", None)
    # Only honour a real non-empty string — MagicMock in tests, etc. should
    # fall through to the standard tier path.
    if isinstance(override_provider, str) and override_provider:
        # Thread-local provider pinning. Skip tier routing entirely — chat()'s
        # tier branch calls resolve_route(tier) which reads LLM_ROUTE_* env
        # vars and would silently route us back to the default provider.
        from llm_router.client import get_provider, _clear_usage

        _clear_usage()
        fn = get_provider(override_provider)
        text = fn(
            prompt,
            client.model or "",
            api_key=client._config.api_key,  # type: ignore[attr-defined]
            base_url=client._config.base_url,  # type: ignore[attr-defined]
            temperature=0.0,
        )
    else:
        text = client.chat(prompt, tier=tier)
    _token_acc_local.reply = text
    usage = get_last_usage()
    if usage is not None and (
        usage.prompt_tokens is not None or usage.completion_tokens is not None
    ):
        _token_acc_local.prompt = getattr(_token_acc_local, "prompt", 0) + (
            usage.prompt_tokens or 0
        )
        _token_acc_local.completion = getattr(_token_acc_local, "completion", 0) + (
            usage.completion_tokens or 0
        )
        _token_acc_local.observed = True
    return text


def _close_truncated(raw: str) -> str | None:
    """Close the containers a response left open when it stopped mid-value.

    Returns the prefix ending at the last completed nested item followed by the
    closers for everything still open there, or None when nothing completed —
    a response that produced no whole item still parses to nothing.
    """
    stack: list[str] = []
    in_string = escaped = False
    cut: int | None = None
    closers = ""
    for index, char in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append("]" if char == "[" else "}")
        elif char in "]}":
            if not stack or stack[-1] != char:
                return None
            stack.pop()
            if stack:
                cut, closers = index + 1, "".join(reversed(stack))
    return None if cut is None else raw[:cut] + closers


def _parse_json(text: str, *, primitive: str = "", context: str = "") -> Any:
    reasons: list[str] = []

    def _loads_with_repairs(raw: str) -> Any | None:
        stripped = raw.strip()
        attempts = [stripped]

        # Cursor Agent / other CLI models sometimes put literal line breaks
        # inside quoted JSON strings. That is invalid JSON even though the
        # intended object is usually recoverable, so escape those control
        # characters before giving up.
        repaired_chars: list[str] = []
        in_string = False
        escaped = False
        changed = False
        for ch in stripped:
            if escaped:
                if in_string and ch not in {
                    '"',
                    "\\",
                    "/",
                    "b",
                    "f",
                    "n",
                    "r",
                    "t",
                    "u",
                }:
                    # LLMs often emit LaTeX-ish sequences such as \( or \tau
                    # inside JSON strings. Preserve the literal backslash by
                    # escaping it, then process the current character normally.
                    repaired_chars.append("\\")
                    changed = True
                else:
                    repaired_chars.append(ch)
                    escaped = False
                    continue
            if escaped:
                repaired_chars.append(ch)
                escaped = False
                continue
            if ch == "\\":
                repaired_chars.append(ch)
                escaped = True
                continue
            if ch == '"':
                repaired_chars.append(ch)
                in_string = not in_string
                continue
            if in_string and ch in {"\n", "\r", "\t"}:
                repaired_chars.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[ch])
                changed = True
                continue
            repaired_chars.append(ch)
        if changed:
            attempts.append("".join(repaired_chars))

        for candidate_text in attempts:
            try:
                parsed = json.loads(candidate_text)
                return parsed if isinstance(parsed, (dict, list)) else {}
            except json.JSONDecodeError as exc:
                reasons.append(f"{exc.msg} (line {exc.lineno} col {exc.colno})")
                continue
        return None

    candidate = text.strip()
    if not candidate:
        return {}
    repaired = _loads_with_repairs(candidate)
    if repaired is not None:
        return repaired

    blocks = [candidate]
    for marker in ("```json", "```"):
        start = candidate.find(marker)
        if start < 0:
            continue
        start += len(marker)
        end = candidate.find("```", start)
        blocks.append(candidate[start:] if end < 0 else candidate[start:end])

    for block in blocks:
        repaired = _loads_with_repairs(block)
        if repaired is not None:
            return repaired
        # Some models emit truncated / unterminated JSON when hitting
        # max_tokens, fenced or not. Keep the items that did arrive by
        # closing whatever was still open at the last complete one.
        closed = _close_truncated(block.strip())
        if closed is not None:
            repaired = _loads_with_repairs(closed)
            if repaired is not None:
                return repaired
    # Both ends, because where a response broke is the whole diagnosis and the
    # head alone never shows it: a cut mid-value, a stray character, and a
    # complete-but-invalid document all open identically.
    logger.warning(
        "JSON parse failed for %s [%s]: %d chars, %s; head %.200s ... tail %.200s",
        primitive or "unknown",
        context or "no context",
        len(candidate),
        "; ".join(dict.fromkeys(reasons)) or "no decoder error",
        candidate,
        candidate[-200:],
    )
    return {}


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _paper_label(paper_id: int, title: str) -> str:
    return title or f"Paper #{paper_id}"


def _get_paper_text(db: Database, paper_id: int) -> tuple[str, str]:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, title, abstract, compiled_summary FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return (f"Paper #{paper_id}", "")

        title = row["title"] or f"Paper #{paper_id}"

        # Fast path: use compiled summary if available
        compiled_raw = row["compiled_summary"] or ""
        if compiled_raw:
            try:
                from .compiled_summary import format_compiled_as_text

                compiled = json.loads(compiled_raw)
                text = format_compiled_as_text(compiled)
                if text:
                    return (title, text)
            except Exception:
                logger.debug(
                    "compiled_summary unusable for paper %s; falling back to annotations",
                    paper_id,
                    exc_info=True,
                )

        parts: list[str] = []

        annotations = conn.execute(
            """
            SELECT section, content
            FROM paper_annotations
            WHERE paper_id = ? AND COALESCE(content, '') != ''
            ORDER BY CASE section
                WHEN 'summary' THEN 0
                WHEN 'methodology' THEN 1
                WHEN 'experiments' THEN 2
                WHEN 'limitations' THEN 3
                ELSE 99
            END, id
            """,
            (paper_id,),
        ).fetchall()
        for annotation in annotations:
            section = annotation["section"] or "note"
            content = (annotation["content"] or "").strip()
            if content:
                parts.append(f"[{section}]\n{content}")

        if not parts:
            notes = conn.execute(
                """
                SELECT note_type, content
                FROM topic_paper_notes
                WHERE paper_id = ? AND COALESCE(content, '') != ''
                ORDER BY id
                """,
                (paper_id,),
            ).fetchall()
            for note in notes:
                note_type = note["note_type"] or "note"
                content = (note["content"] or "").strip()
                if content:
                    parts.append(f"[{note_type}]\n{content}")

        if not parts:
            abstract = (
                (row["abstract"] or "").strip() if "abstract" in row.keys() else ""
            )
            if abstract:
                parts.append(f"[abstract]\n{abstract}")

        return (title, "\n\n".join(parts).strip())
    finally:
        conn.close()


TASK_QUERIES: dict[str, str] = {
    "gap_detect": "limitations, future work, open problems, challenges, shortcomings",
    "claim_extract": "contributions, key findings, we propose, we show, our method achieves",
    "baseline_identify": "baseline, comparison, benchmark, state-of-the-art, competing methods",
    "section_draft": "methodology, approach, results, contributions, related work",
    # Per-section retrieval keys: each drafted section pulls the snippets it
    # actually argues from, instead of one generic query for the whole paper.
    "section_draft:introduction": "motivation, failure, limitation, open problem, challenge",
    "section_draft:related_work": "approach, contribution, limitation, comparison",
    "section_draft:method": "methodology, algorithm, formulation, architecture",
    "section_draft:experiments": "baseline, benchmark, metric, ablation, results",
    "consistency_check": "claims, results, methodology, conclusions",
    "deep_read": "methodology, algorithm, limitations, reproducibility, novelty",
}

MAX_SNIPPETS_PER_PAPER = 3
MAX_SNIPPET_CHARS = 600
# Minimum body-text length before a paper may drive claim extraction. Below this
# we only have a title-level match; feeding it to the LLM produces fabricated
# "the paper does not report X" (unreported) conclusions (BUG-007).
_MIN_CLAIM_EVIDENCE_CHARS = 160


def _get_paperindex_context(db: Database, paper_id: int, task_type: str) -> str | None:
    """Try to retrieve task-relevant snippets from paperindex for a paper."""
    conn = db.connect()
    try:
        artifact = conn.execute(
            """
            SELECT path FROM paper_artifacts
            WHERE paper_id = ? AND artifact_type = 'paperindex_structure'
            """,
            (paper_id,),
        ).fetchone()
        if artifact is None:
            return None
    finally:
        conn.close()

    try:
        query = TASK_QUERIES.get(task_type, "methodology, results, contributions")

        structure_path = artifact["path"]
        from pathlib import Path

        if not Path(structure_path).exists():
            return None

        import json as _json

        structure_data = _json.loads(Path(structure_path).read_text())
        from paperindex.types import SectionNode, StructureResult

        structure = StructureResult(
            doc_name=structure_data.get("doc_name", ""),
            tree=[
                SectionNode.from_dict(n) for n in structure_data.get("structure", [])
            ],
            pdf_hash=structure_data.get("pdf_hash", ""),
            page_count=int(structure_data.get("page_count", 0) or 0),
            raw=structure_data.get("raw", {}),
        )

        from paperindex.retrieval import find_structure_matches
        from paperindex.types import PaperRecord as PIRecord

        record = PIRecord(
            paper_id=f"paper_{paper_id}",
            title="",
            doc_name="",
            pdf_hash=structure.pdf_hash,
            page_count=structure.page_count,
            structure=structure,
            sections={},
            card=None,
            source_path="",
            indexed_at="",
        )
        matches = find_structure_matches(record, query, limit=MAX_SNIPPETS_PER_PAPER)

        if not matches:
            return None

        parts: list[str] = []
        for match in matches:
            snippet = (match.snippet or "")[:MAX_SNIPPET_CHARS]
            if snippet:
                parts.append(f"[Section: {match.title}] {snippet}")
        return "\n".join(parts) if parts else None
    except Exception:
        logger.debug("paperindex lookup failed for paper %d", paper_id, exc_info=True)
        return None


def _get_topic_literature_summary(
    db: Database,
    topic_id: int,
    task_type: str = "",
) -> tuple[str, list[int]]:
    """Build topic literature summary using compiled summary cache.

    Uses top-K sampling + contradiction candidates instead of iterating all
    papers. Falls back to per-paper annotation joining for uncached papers.
    """
    # Deep-read pass2 only needs coarse cross-paper context. Do not trigger
    # lazy compilation of 20+ paper summaries here: in a 100-paper deep-read
    # batch that makes the first read fan out into dozens of extra Cursor/API
    # calls before the target paper is even stored. Use a lightweight
    # metadata/existing-cache context instead.
    if task_type == "deep_read":
        conn = db.connect()
        try:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.year, p.venue, p.compiled_summary,
                       p.citation_count, pt.relevance
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                  AND pt.screening_status = 'screened_in'
                  AND pt.manuscript_eligible = 1
                  AND COALESCE(pt.relevance, '') NOT LIKE 'dismissed%'
                  AND COALESCE(pt.relevance, '') NOT LIKE 'excluded%'
                  AND TRIM(COALESCE(p.title, '')) != ''
                  AND (
                      TRIM(COALESCE(p.abstract, '')) != ''
                      OR TRIM(COALESCE(p.compiled_summary, '')) != ''
                      OR (p.status = 'annotated' AND TRIM(COALESCE(p.pdf_path, '')) != '')
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM topic_paper_notes tpn
                      WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                        AND tpn.note_type = 'user_dismissed'
                  )
                ORDER BY
                    CASE pt.relevance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    COALESCE(p.citation_count, 0) DESC,
                    p.year DESC,
                    p.id DESC
                LIMIT 30
                """,
                (topic_id,),
            ).fetchall()
        finally:
            conn.close()

        entries: list[str] = []
        paper_ids: list[int] = []
        for row in rows:
            pid = int(row["id"])
            paper_ids.append(pid)
            header = f"- [{pid}] {row['title'] or f'Paper #{pid}'}"
            if row["year"]:
                header += f" ({row['year']})"
            if row["venue"]:
                header += f" [{row['venue']}]"
            if row["relevance"]:
                header += f" relevance={row['relevance']}"
            snippet = ""
            compiled_raw = row["compiled_summary"] or ""
            if compiled_raw:
                try:
                    compiled = json.loads(compiled_raw)
                    overview = compiled.get("overview", "")
                    if overview:
                        snippet = f"\n  {str(overview)[:300]}"
                except Exception:
                    snippet = ""
            entries.append(header + snippet)
        return ("\n".join(entries) if entries else "(no papers in topic)", paper_ids)

    from .compiled_summary import get_topic_summary_cached

    try:
        return get_topic_summary_cached(db, topic_id)
    except Exception:
        logger.warning(
            "Compiled topic summary failed for topic %d, falling back to legacy",
            topic_id,
            exc_info=True,
        )

    # Legacy fallback: iterate all papers (original behavior)
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND pt.screening_status = 'screened_in'
              AND pt.manuscript_eligible = 1
              AND COALESCE(pt.relevance, '') NOT LIKE 'dismissed%'
              AND COALESCE(pt.relevance, '') NOT LIKE 'excluded%'
              AND TRIM(COALESCE(p.title, '')) != ''
              AND (
                  TRIM(COALESCE(p.abstract, '')) != ''
                  OR TRIM(COALESCE(p.compiled_summary, '')) != ''
                  OR (p.status = 'annotated' AND TRIM(COALESCE(p.pdf_path, '')) != '')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY p.year DESC, p.id DESC
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    paper_ids: list[int] = []
    entries: list[str] = []
    for row in rows:
        paper_id = int(row["id"])
        header = f"- {_paper_label(paper_id, row['title'] or f'Paper #{paper_id}')}"
        if row["year"]:
            header += f" ({row['year']})"
        if row["venue"]:
            header += f" [{row['venue']}]"

        context = None
        if task_type:
            try:
                context = _get_paperindex_context(db, paper_id, task_type)
            except Exception:
                logger.debug("paperindex context failed for paper %d", paper_id)

        if context:
            entry = f"{header}\n  {context}"
        else:
            try:
                title, text = _get_paper_text(db, paper_id)
            except Exception:
                logger.warning("Skipping paper %d: corrupted or unreadable", paper_id)
                continue
            if text:
                entry = f"{header}\n  {text[:500]}"
            else:
                entry = header

        paper_ids.append(paper_id)
        entries.append(entry)

    if not entries:
        return ("(no papers in topic)", [])
    return ("\n".join(entries), paper_ids)


def _parse_authors_for_display(raw: str) -> list[str]:
    """Parse DB authors field for display in evidence prompts.

    Reuses ``parse_authors_field`` from latex_compiler to handle all
    four DB format variants ([], "", JSON array, double-escaped JSON).
    """
    from .latex_compiler import parse_authors_field

    return parse_authors_field(raw)


def _coerce_paper_id_list(values: Any) -> list[int]:
    """Parse paper ids out of an ``evidence_ids`` list.

    Accepts ints, digit strings, and ``paper_<id>`` markers; anything else
    (claim ids, free text) is skipped rather than guessed.
    """
    out: list[int] = []
    for value in values or []:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out.append(value)
            continue
        text = str(value).strip().lower()
        if text.isdigit():
            out.append(int(text))
        elif text.startswith("paper_") and text[len("paper_") :].isdigit():
            out.append(int(text[len("paper_") :]))
    return out


def _topic_claim_notes(db: Database, topic_id: int) -> dict[int, list[str]]:
    """Extracted claims from claim_extract, grouped by paper id."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT paper_id, content FROM topic_paper_notes
            WHERE topic_id = ? AND note_type = 'claim'
              AND TRIM(COALESCE(content, '')) != ''
            ORDER BY id DESC LIMIT 150
            """,
            (topic_id,),
        ).fetchall()
    except Exception:
        logger.debug("claim note lookup failed for topic %d", topic_id, exc_info=True)
        return {}
    finally:
        conn.close()

    grouped: dict[int, list[str]] = {}
    for row in rows:
        try:
            paper_id = int(row["paper_id"])
        except (TypeError, ValueError):
            continue
        grouped.setdefault(paper_id, []).append(str(row["content"]).strip())
    return grouped


def _build_numbered_evidence(
    db: Database,
    topic_id: int,
    max_papers: int = 50,
    task_type: str = "",
    section: str = "",
    priority_paper_ids: list[int] | None = None,
    rich_top_k: int = 15,
    char_budget: int = 26000,
    restrict_to_priority: bool = False,
) -> tuple[str, list[int]]:
    """Build a numbered evidence list for citation injection.

    Returns ``(evidence_text, paper_ids)`` where evidence_text lists each paper
    prefixed with ``[N]`` so the LLM can use ``[N]`` markers consistently.
    Enforces a minimum of 30 papers when available, up to ``max_papers``.

    Ordering: ``priority_paper_ids`` first (outline evidence for this section),
    then high-relevance papers, then by citation count, then by year. With
    ``restrict_to_priority`` those papers are the whole list: a caller that
    names its evidence is the caller writing the bibliography, and a paper
    outside that set can only be cited as a key the bibliography does not hold.

    The first ``rich_top_k`` papers additionally carry a compiled-summary
    digest (claims with strength, metrics with baseline numbers, one
    limitation), extracted claim notes, and a section-targeted paperindex
    snippet — until ``char_budget`` is reached. Later papers keep the compact
    abstract format so the ``[N]`` range and citation audit stay intact.
    """
    priority = [
        int(pid) for pid in (priority_paper_ids or []) if str(pid).lstrip("-").isdigit()
    ]
    restricted = restrict_to_priority and bool(priority)
    # Restriction also settles which rows are fetched at all: the broad query keeps
    # the topic's best ``max_papers``, and a named paper outside that window would
    # otherwise drop out of its own evidence list without a word.
    scope = f"AND p.id IN ({','.join('?' * len(priority))})" if restricted else ""
    conn = db.connect()
    try:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.year, p.venue, p.authors, p.abstract,
                   p.compiled_summary, p.citation_count, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              {scope}
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY
                CASE pt.relevance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                COALESCE(p.citation_count, 0) DESC,
                p.year DESC,
                p.id DESC
            LIMIT ?
            """,
            (topic_id, *priority, max(max_papers, len(priority)))
            if restricted
            else (topic_id, max_papers),
        ).fetchall()
    finally:
        conn.close()

    rows_by_id: dict[int, Any] = {int(row["id"]): row for row in rows}
    ordered: list[Any] = []
    for pid in priority_paper_ids or []:
        row = rows_by_id.pop(int(pid), None) if str(pid).lstrip("-").isdigit() else None
        if row is not None:
            ordered.append(row)
    ordered.extend(rows_by_id.values())

    section_key = (section or "").strip().lower().replace(" ", "_")
    scoped_task = f"{task_type}:{section_key}" if task_type and section_key else ""
    effective_task = scoped_task if scoped_task in TASK_QUERIES else task_type

    enrich = rich_top_k > 0
    claims_by_paper: dict[int, list[str]] = (
        _topic_claim_notes(db, topic_id) if enrich else {}
    )

    paper_ids: list[int] = []
    lines: list[str] = []
    total_chars = 0
    for i, row in enumerate(ordered, start=1):
        paper_id = int(row["id"])
        title = row["title"] or f"Paper #{paper_id}"
        year = row["year"] or "n.d."
        venue = row["venue"] or ""
        authors_raw = row["authors"] or ""
        authors_list = _parse_authors_for_display(authors_raw)
        authors = authors_list[0] if authors_list else "Unknown"
        citation_key = f"ref{i}"

        header = f'[{i}] {authors} et al. "{title}" ({year})'
        if venue and venue not in ("arXiv.org", "arXiv"):
            header += f" — {venue}"
        header += f"  [cite key: {citation_key}, paper_id={paper_id}]"

        abstract = (row["abstract"] or "").strip()
        if abstract:
            header += f"\n    Abstract: {abstract[:400]}"

        if enrich and i <= rich_top_k and total_chars < char_budget:
            compiled_raw = (
                row["compiled_summary"] if "compiled_summary" in row.keys() else ""
            ) or ""
            if compiled_raw:
                # Local import: compiled_summary imports llm_primitives lazily,
                # so a top-level import here would be circular.
                from .compiled_summary import format_compiled_for_evidence

                try:
                    digest = format_compiled_for_evidence(json.loads(compiled_raw))
                except (ValueError, TypeError):
                    digest = ""
                if digest:
                    header += "\n    " + digest.replace("\n", "\n    ")
            for claim_text in claims_by_paper.get(paper_id, [])[:2]:
                header += f"\n    Extracted claim: {claim_text[:220]}"
            snippet = _get_paperindex_context(db, paper_id, effective_task)
            if snippet:
                first_line = snippet.splitlines()[0][:MAX_SNIPPET_CHARS]
                header += f"\n    {first_line}"

        total_chars += len(header)
        lines.append(header)
        paper_ids.append(paper_id)

    if not lines:
        return ("(no papers in topic)", [])

    return ("\n\n".join(lines), paper_ids)


def _audit_draft_citations(content: str, evidence_count: int) -> list[str]:
    """Check [N] citation markers in drafted text against evidence pool size.

    Returns a list of warning strings for out-of-range or suspicious citations.
    """
    if evidence_count <= 0:
        return []

    warnings: list[str] = []
    seen: set[int] = set()

    for m in re.finditer(r"\[(\d+)\]", content):
        n = int(m.group(1))
        if n < 1 or n > evidence_count:
            warnings.append(
                f"[{n}] is out of range (evidence pool has [{1}]-[{evidence_count}])"
            )
        seen.add(n)

    return warnings


def _load_writing_lessons(
    db: Database,
    topic_id: int,
    stage: str = "section_draft",
) -> str:
    """Load recent writing lessons and format as prompt overlay.

    Returns empty string if no lessons or DB lacks lessons table.
    """
    try:
        from research_harness.evolution.topic.store import DBLessonStore

        store = DBLessonStore(db)
        overlay = store.build_overlay(stage, top_k=5, topic_id=topic_id)
        return overlay
    except Exception:
        return ""


def _topic_venue(db: Database, topic_id: int) -> str:
    """The topic's target venue, when the pool records one."""
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT target_venue FROM topics WHERE id=?", (topic_id,)
            ).fetchone()
    except Exception:
        return ""
    return str((row[0] if row else "") or "")


def _record_writing_lessons_from_draft(
    db: Database,
    topic_id: int,
    section: str,
    content: str,
    audit_warnings: list[str],
    target_words: int = 0,
) -> None:
    """Run deterministic writing checks on drafted content and record failures as lessons.

    This is the "discover problems" wire of the self-evolution loop: every time
    section_draft produces output, we automatically detect quality issues and
    persist them so future drafts can learn from past mistakes.

    V2 path: routes through ExperienceStore.ingest(source_kind="self_review")
    which internally bridges to V1 DBLessonStore. Falls back to V1 direct path
    if V2 is unavailable.
    """
    try:
        from .writing_checks import run_all_checks
    except Exception:
        return

    issues: list[str] = []

    try:
        check_results = run_all_checks(
            content, section, target_words, venue=_topic_venue(db, topic_id)
        )
        for c in check_results:
            if not c.passed:
                issues.append(f"[{section}] Check '{c.check_name}' failed: {c.details}")
    except Exception as exc:
        logger.debug("Writing checks unavailable: %s", exc)

    for w in audit_warnings:
        issues.append(f"[{section}] Citation audit: {w}")

    if not issues:
        return

    # V2 path: unified experience pipeline
    try:
        from research_harness.evolution.topic.experience import (
            ExperienceRecord,
            ExperienceStore,
        )

        store = ExperienceStore(db)
        for issue in issues[:10]:
            store.ingest(
                ExperienceRecord(
                    source_kind="self_review",
                    stage="section_draft",
                    section=section,
                    diff_summary=issue,
                    topic_id=topic_id,
                    metadata={"auto_review": True},
                )
            )
        logger.info(
            "Recorded %d experience(s) for section '%s' via V2 pipeline",
            min(len(issues), 10),
            section,
        )
        return
    except Exception as exc:
        logger.debug("V2 experience pipeline unavailable (%s), falling back to V1", exc)

    # V1 fallback
    try:
        from research_harness.evolution.topic.store import DBLessonStore, Lesson

        store_v1 = DBLessonStore(db)
        for issue in issues[:10]:
            store_v1.append(
                Lesson(
                    stage="section_draft",
                    content=issue,
                    lesson_type="failure",
                    tags=["auto_review", section],
                ),
                source="auto_review",
                topic_id=topic_id,
            )
        logger.info(
            "Recorded %d writing lesson(s) for section '%s'",
            min(len(issues), 10),
            section,
        )
    except Exception as exc:
        logger.debug("Could not record writing lessons: %s", exc)


_STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "again",
    "against",
    "algorithm",
    "algorithms",
    "among",
    "and",
    "approach",
    "approaches",
    "are",
    "based",
    "between",
    "beyond",
    "budget",
    "bidding",
    "channel",
    "channels",
    "data",
    "deep",
    "for",
    "from",
    "into",
    "learning",
    "method",
    "methods",
    "model",
    "models",
    "multi",
    "neural",
    "online",
    "paper",
    "papers",
    "research",
    "results",
    "study",
    "system",
    "systems",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "using",
    "with",
}


def _tokenize_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower())
    return [token for token in tokens if token not in _STOPWORDS]


def _collect_topic_query_context(
    db: Database,
    topic_id: int,
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.title, p.abstract, p.authors, p.venue
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        query_rows = conn.execute(
            "SELECT query FROM search_query_registry WHERE topic_id = ? ORDER BY created_at",
            (topic_id,),
        ).fetchall()
        artifact_rows = conn.execute(
            """
            SELECT payload_json FROM project_artifacts
            WHERE topic_id = ? AND artifact_type IN ('gap_analysis', 'evidence_pack', 'claim_candidate_set')
              AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 6
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    keyword_counter: collections.Counter[str] = collections.Counter()
    author_counter: collections.Counter[str] = collections.Counter()
    venue_counter: collections.Counter[str] = collections.Counter()

    for row in rows:
        text = " ".join(
            part for part in (row["title"] or "", row["abstract"] or "") if part
        )
        keyword_counter.update(_tokenize_keywords(text))
        venue = str(row["venue"] or "").strip()
        if venue:
            venue_counter.update([venue])
        try:
            authors = json.loads(row["authors"]) if row["authors"] else []
        except (TypeError, json.JSONDecodeError):
            authors = []
        for author in authors[:8]:
            name = str(author).strip()
            if name:
                author_counter.update([name])

    gaps: list[str] = []
    for row in artifact_rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        for gap in payload.get("gaps", []):
            if isinstance(gap, dict) and gap.get("description"):
                gaps.append(str(gap["description"]).strip())

    known_queries = [str(row["query"]).strip() for row in query_rows if row["query"]]
    return (
        [term for term, _ in keyword_counter.most_common(12)],
        [author for author, _ in author_counter.most_common(6)],
        [venue for venue, _ in venue_counter.most_common(6)],
        known_queries,
        gaps[:10],
    )


def paper_summarize(
    *,
    db: Database,
    paper_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> SummaryOutput:
    title, text = _get_paper_text(db, paper_id)
    if not text:
        return SummaryOutput(
            paper_id=paper_id,
            summary="(no text available for summarization)",
            focus=focus,
            confidence=0.0,
            model_used="none",
        )

    client = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("paper_summarize"),
        task_name="paper_summarize",
    )
    raw = _client_chat(client, prompts.paper_summarize_prompt(title, text, focus))
    parsed = _parse_json(raw, primitive="paper_summarize")
    return SummaryOutput(
        paper_id=paper_id,
        summary=str(parsed.get("summary") or raw[:2000]).strip(),
        focus=focus,
        confidence=_coerce_float(parsed.get("confidence"), 0.5),
        model_used=client.model,
    )


def claim_extract(
    *,
    db: Database,
    paper_ids: list[int],
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> ClaimExtractOutput:
    del topic_id
    snippets: list[str] = []
    skipped: list[int] = []
    insufficient: list[int] = []
    for paper_id in paper_ids:
        try:
            title, text = _get_paper_text(db, paper_id)
            # Try paperindex for richer context
            pi_context = _get_paperindex_context(db, paper_id, "claim_extract")
        except Exception:
            logger.warning(
                "Skipping paper %d in claim_extract: corrupted or unreadable", paper_id
            )
            skipped.append(paper_id)
            continue
        # BUG-007: pick real body text over a title-level paperindex match.
        # The reported failure was claim_extract reading only a title-level
        # snippet (and emitting fabricated "unreported" conclusions) even though
        # the paper had a full annotation. Any stored body (abstract/annotation/
        # notes) is valid evidence regardless of length; only when there is NO
        # body do we require the paperindex match to carry real content beyond
        # the title, otherwise we skip so nothing is invented from a title.
        body = (text or "").strip()
        pi = (pi_context or "").strip()
        title_norm = (title or "").strip().lower()
        if body:
            evidence = pi if len(pi) > len(body) else body
        elif len(pi) >= _MIN_CLAIM_EVIDENCE_CHARS and pi.lower() != title_norm:
            evidence = pi
        else:
            insufficient.append(paper_id)
            continue
        snippets.append(
            f"[Paper {paper_id}] {_paper_label(paper_id, title)}\n{evidence}"
        )

    if not snippets:
        logger.warning(
            "claim_extract: no input paper had enough body text "
            "(skipped=%s insufficient=%s); returning no claims instead of "
            "title-only 'unreported' guesses",
            skipped,
            insufficient,
        )
        return ClaimExtractOutput(claims=[], papers_processed=len(paper_ids))

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("claim_extract"))
    raw = _client_chat(
        client, prompts.claim_extract_prompt("\n\n".join(snippets), focus)
    )
    parsed = _parse_json(raw, primitive="claim_extract")

    from research_harness.primitives.types import EvidenceSpan

    valid_paper_ids = {int(p) for p in paper_ids}
    default_paper_id = paper_ids[0] if paper_ids else None

    claims: list[Claim] = []
    for item in parsed.get("claims", []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue

        # Per-claim paper attribution (ADR-001 Decision 3).
        claim_paper_ids: list[int] = []
        raw_pid = item.get("paper_id")
        if raw_pid is not None:
            try:
                pid = int(raw_pid)
                if pid in valid_paper_ids:
                    claim_paper_ids = [pid]
            except (TypeError, ValueError):
                pass
        if not claim_paper_ids and default_paper_id is not None:
            # Fallback when LLM omits paper_id; use first input paper instead
            # of the v1 behavior of assigning ALL input papers.
            claim_paper_ids = [default_paper_id]

        # Modality — default to "text" when the LLM doesn't specify.
        raw_modality = str(item.get("modality", "")).strip().lower()
        if raw_modality not in {"text", "figure", "table", "equation", "mixed"}:
            raw_modality = "text"

        # Evidence spans — best-effort parse; silently drop malformed entries.
        spans: list[EvidenceSpan] = []
        raw_spans = item.get("evidence_spans")
        if isinstance(raw_spans, list):
            for span in raw_spans[:3]:
                if not isinstance(span, dict):
                    continue
                try:
                    spans.append(
                        EvidenceSpan(
                            paper_id=int(span.get("paper_id", claim_paper_ids[0])),
                            section=str(span.get("section", "")).strip(),
                            snippet=str(span.get("snippet", "")).strip()[:500],
                        )
                    )
                except (TypeError, ValueError):
                    continue

        claims.append(
            Claim(
                claim_id="",
                content=content,
                paper_ids=claim_paper_ids,
                evidence_type=str(item.get("evidence_type", "")).strip(),
                confidence=_coerce_float(item.get("confidence"), 0.5),
                modality=raw_modality,
                evidence_spans=spans,
            )
        )

    return ClaimExtractOutput(claims=claims, papers_processed=len(paper_ids))


def gap_detect(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    analysis_substrate: dict[str, Any] | None = None,
    _model: str | None = None,
    _dag_bypass: bool = False,
    **_: Any,
) -> GapDetectOutput:
    # v2 Step 10 — opt-in DAG pilot. Gated by RESEARCH_HARNESS_GAP_DAG=1.
    # _dag_bypass=True lets the DAG layer call this leaf function without
    # triggering infinite recursion.
    if not _dag_bypass:
        from .dag_reasoning import is_dag_enabled

        if is_dag_enabled():
            from .dag_reasoning import gap_detect_dag

            def _leaf(**kwargs: Any) -> GapDetectOutput:
                return gap_detect(**kwargs, _dag_bypass=True)

            dag_result = gap_detect_dag(
                db=db,
                topic_id=topic_id,
                focus=focus,
                leaf_fn=lambda **kwargs: _leaf(
                    **kwargs, analysis_substrate=analysis_substrate
                ),
            )
            gaps_out: list[Gap] = [
                Gap(
                    gap_id="",
                    description=g.description,
                    gap_type=g.gap_type,
                    severity=g.severity,
                    related_paper_ids=g.related_paper_ids,
                    confidence=g.confidence,
                )
                for g in dag_result.gaps
            ]
            return GapDetectOutput(
                gaps=gaps_out, papers_analyzed=dag_result.papers_analyzed
            )

    summary, related_paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="gap_detect"
    )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("gap_detect"))
    substrate_text = (
        json.dumps(analysis_substrate, sort_keys=True, default=str)
        if analysis_substrate
        else ""
    )
    raw = _client_chat(
        client,
        prompts.gap_detect_prompt(summary, focus, substrate_text),
    )
    parsed = _parse_json(raw, primitive="gap_detect")

    gaps: list[Gap] = []
    for item in parsed.get("gaps", []):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        gaps.append(
            Gap(
                gap_id="",
                description=description,
                gap_type=str(item.get("gap_type", "")).strip(),
                severity=str(item.get("severity", "medium")).strip() or "medium",
                related_paper_ids=related_paper_ids,
                confidence=max(
                    0.0, min(1.0, _coerce_float(item.get("confidence"), 0.0))
                ),
            )
        )

    # Persist to DB so direction_ranking / query_refine can consume.
    # INSERT OR IGNORE keeps (topic_id, description) unique — re-running
    # gap_detect on the same topic won't create duplicates.
    if gaps:
        conn = db.connect()
        try:
            related_ids_json = json.dumps(related_paper_ids)
            for gap in gaps:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO gaps
                        (topic_id, description, gap_type, severity,
                         related_paper_ids, focus, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        topic_id,
                        gap.description,
                        gap.gap_type,
                        gap.severity,
                        related_ids_json,
                        focus,
                        gap.confidence,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    return GapDetectOutput(gaps=gaps, papers_analyzed=len(related_paper_ids))


def _merge_capture_candidates(
    per_query: list[tuple[str, list[Any]]],
    max_candidates: int,
) -> tuple[list[Any], int]:
    """Merge per-query retrieval results into a ranked, deduped candidate list.

    Each decorrelated query is an independent "capture attempt" on the hidden
    pre-empting literature. Returns (top candidates ranked by best relevance,
    number of queries that captured >=1 candidate). Pure — unit-testable.
    """

    def _score(paper: Any) -> float:
        return getattr(paper, "relevance_score", 0.0) or 0.0

    best: dict[str, Any] = {}
    per_query_keys: list[list[str]] = []
    capture_queries = 0
    for _query, papers in per_query:
        if papers:
            capture_queries += 1
        keys: list[str] = []
        for paper in sorted(papers, key=_score, reverse=True):
            key = (
                (getattr(paper, "arxiv_id", "") or "").strip().lower()
                or (getattr(paper, "doi", "") or "").strip().lower()
                or (getattr(paper, "title", "") or "").strip().lower()
            )
            if not key:
                continue
            prev = best.get(key)
            if prev is None or _score(paper) > _score(prev):
                best[key] = paper
            keys.append(key)
        per_query_keys.append(keys)

    # Every capture attempt places one candidate before any attempt places two.
    # Ranking the union by score instead lets the densest query family spend the
    # whole budget, which is the decomposition's own purpose thrown away: the
    # queries that named the cohort came back unread under twenty-five generic
    # method papers, and the panel could not establish vacancy from them.
    # Scores are not comparable across providers and queries anyway.
    pointers = [0] * len(per_query_keys)
    picked: list[str] = []
    taken: set[str] = set()
    advancing = True
    while advancing and len(picked) < max_candidates:
        advancing = False
        for index, keys in enumerate(per_query_keys):
            while pointers[index] < len(keys) and keys[pointers[index]] in taken:
                pointers[index] += 1
            if pointers[index] >= len(keys):
                continue
            key = keys[pointers[index]]
            pointers[index] += 1
            taken.add(key)
            picked.append(key)
            advancing = True
            if len(picked) >= max_candidates:
                break
    return [best[key] for key in picked], capture_queries


def _apply_gap_governance(
    verdict: str,
    confidence: float,
    capture_queries: int,
    judge_model: str,
    alpha: float,
) -> tuple[str, float, str, float, str]:
    """Gate a gap verdict with the correlation-aware governance_gate.

    The gap claim and its judgment come from the same LLM backend (worst-case
    self-graded regime); each decorrelated query that independently captured
    real candidates counts as one external anchor. A positive "open" verdict
    with too few anchors is downgraded or confidence-discounted per r(rho).
    Returns (verdict, confidence, governance_action, trust_adjusted, note).
    """
    from research_harness.primitives.evolution_impls import governance_gate

    gate = governance_gate(
        verdict=verdict,
        judge_confidence=confidence,
        generator_model=judge_model,
        judge_model=judge_model,
        external_anchors=capture_queries,
        alpha=alpha,
    )
    note = f" [governance: {gate.action}; {gate.rationale}]"
    if verdict == "open" and gate.action == "abstain_pending_external":
        return (
            "inconclusive",
            gate.trust_adjusted_confidence,
            gate.action,
            gate.trust_adjusted_confidence,
            note,
        )
    if verdict == "open" and gate.action == "require_external":
        # Sparse independent capture (<=1 query succeeded) means coverage is
        # effectively single-shot — too weak to assert a negative existence.
        if capture_queries <= 1:
            return (
                "inconclusive",
                gate.trust_adjusted_confidence,
                gate.action,
                gate.trust_adjusted_confidence,
                note,
            )
        return (
            verdict,
            min(confidence, gate.trust_adjusted_confidence),
            gate.action,
            gate.trust_adjusted_confidence,
            note,
        )
    return verdict, confidence, gate.action, gate.trust_adjusted_confidence, note


_GAP_VERDICTS = {"open", "occupied", "partially_occupied", "inconclusive"}

#: occupying-item strength ranking used when merging panel judgements.
_OCCUPYING_RANK = {"preempts": 2, "overlaps": 1}


def _coerce_narrowness(value: Any) -> dict[str, str]:
    """Normalize the additive ``narrowness`` field to {title: explanation}.

    Accepts the dict form asked for in the prompt or a tolerated list of
    {title, narrowness|explanation} items; anything else yields {}. Pure.
    """
    if isinstance(value, dict):
        return {
            str(k).strip(): str(v).strip()
            for k, v in value.items()
            if str(k).strip() and str(v).strip()
        }
    if isinstance(value, list):
        out: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            note = str(item.get("narrowness", item.get("explanation", ""))).strip()
            if title and note:
                out[title] = note
        return out
    return {}


def _merge_panel_judgements(
    judgements: list[tuple[str, dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Aggregate per-perspective panel judgements into one parsed-shaped dict.

    Vote rule (NOV02 judge arm): >=2 "occupied" votes -> occupied; else any
    "partially_occupied" -> partially_occupied; else all "open" -> open;
    anything else (inconclusive votes, empty panel) -> inconclusive.
    Occupying lists are merged deduped by title keeping the strongest item
    verdict; narrowness dicts are merged; confidence is the panel mean. Pure.
    """
    votes: list[dict[str, str]] = []
    occupying_by_title: dict[str, dict[str, Any]] = {}
    narrowness: dict[str, str] = {}
    confidences: list[float] = []
    coverage_note = ""
    for perspective, parsed in judgements:
        verdict = str(parsed.get("verdict", "open")).strip().lower()
        if verdict not in _GAP_VERDICTS:
            verdict = "open"
        votes.append(
            {
                "perspective": perspective,
                "verdict": verdict,
                "reason": str(parsed.get("reason", "")).strip(),
            }
        )
        confidences.append(_coerce_float(parsed.get("grounded_confidence"), 0.0))
        coverage_note = coverage_note or str(parsed.get("coverage_note", "")).strip()
        narrowness.update(_coerce_narrowness(parsed.get("narrowness")))
        for item in parsed.get("occupying", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            item_verdict = str(item.get("verdict", "unrelated")).strip().lower()
            prev = occupying_by_title.get(title.lower())
            if prev is None or _OCCUPYING_RANK.get(
                item_verdict, 0
            ) > _OCCUPYING_RANK.get(str(prev.get("verdict", "")).strip().lower(), 0):
                occupying_by_title[title.lower()] = item

    verdicts = [vote["verdict"] for vote in votes]
    if verdicts.count("occupied") >= 2:
        aggregate = "occupied"
    elif "partially_occupied" in verdicts:
        aggregate = "partially_occupied"
    elif verdicts and all(v == "open" for v in verdicts):
        aggregate = "open"
    else:
        aggregate = "inconclusive"

    merged = {
        "verdict": aggregate,
        "grounded_confidence": (
            sum(confidences) / len(confidences) if confidences else 0.0
        ),
        "coverage_note": coverage_note,
        "occupying": list(occupying_by_title.values()),
        "narrowness": narrowness,
    }
    return merged, votes


_ARXIV_YYMM = re.compile(r"^(\d{2})(\d{2})\.")


def _published_no_later(paper: Any, cutoff: str) -> bool:
    """True when ``paper`` is not provably published after ``cutoff`` (YYYY-MM).

    arXiv IDs carry YYMM, giving month precision; otherwise only the year is
    known and a same-year paper is kept (month unknown). Papers with no date
    metadata are kept: the temporal split guards against future leakage in
    calibration replays, it is not a coverage claim, so it fails open.
    """
    match = _ARXIV_YYMM.match(str(getattr(paper, "arxiv_id", "") or ""))
    if match:
        return f"20{match.group(1)}-{match.group(2)}" <= cutoff
    year = getattr(paper, "year", None)
    if year:
        return str(int(year)) <= cutoff[:4]
    return True


def _capture_prior_art(
    *,
    db: Database,
    topic_id: int,
    client: Any,
    gap: str,
    focus: str,
    max_candidates: int,
    queries: list[str] | None = None,
) -> dict[str, Any]:
    """Decomposed prior-art capture for one claim: queries, per-query hits, merged candidates.

    Shared by ``gap_ground_verify`` and ``originality_boundary_check`` so both
    judges retrieve under the same lanes, hygiene and coverage accounting.
    """
    from research_harness.primitives import impls as _impls
    from research_harness.retrieval_hygiene import (
        expand_synonym_queries,
        is_query_shaped,
        provider_allowlist_for_text,
    )

    # -- v1.1: contribution-level query decomposition (fallback: whole gap) --
    decompose = queries is None  # a caller that names its queries skips the model call
    queries = list(queries or [])
    if decompose:
        try:
            raw_q = _client_chat(client, prompts.gap_query_decompose_prompt(gap, focus))
            parsed_q = _parse_json(raw_q, primitive="gap_ground_verify")
            queries = [
                str(q).strip() for q in parsed_q.get("queries", []) if str(q).strip()
            ][:7]
        except Exception:  # noqa: BLE001 — decompose is best-effort
            logger.warning(
                "gap_query_decompose failed; falling back to whole-gap query"
            )

    # Include the raw gap as one capture round: guarantees v1.1 recall is a
    # superset of v1.0, and guards against the decomposer aliasing away the
    # gap's canonical terms entirely (observed: all 6 queries avoided
    # "sycophancy"/"feedback" and re-missed FB-Bench). A gap stated as a
    # paragraph cannot carry that guarantee — an index rejects it rather than
    # searching it — and the rejection then withdraws the verdict the round was
    # meant to support, so the decomposition stands alone for those.
    long_gap_note = ""
    if gap not in queries:
        if is_query_shaped(gap):
            queries.append(gap)
        else:
            long_gap_note = (
                " Whole-claim capture round skipped: the claim is stated at "
                "paragraph length, which an index rejects rather than searches; "
                "recall rests on the decomposed queries."
            )

    # E5: expand known lexicon collapses before retrieval, not only after zeros.
    queries = expand_synonym_queries(queries)
    # E4: pin providers to the domain primary(+secondary) indexes when known.
    provider_allowlist = provider_allowlist_for_text(f"{gap} {focus or ''}")

    per_query: list[tuple[str, list[Any]]] = []
    provider_errors: list[str] = []
    providers_seen: list[str] = []
    providers_answered: list[str] = []
    for query in queries:
        try:
            search_kwargs: dict[str, Any] = {
                "db": db,
                "query": query,
                "topic_id": topic_id,
                "max_results": max_candidates,
                # W1: local pool uses embed rerank when available; external
                # providers unchanged. Default paper_search stays BM25-only.
                "local_embed_rerank": True,
            }
            if provider_allowlist:
                search_kwargs["provider_allowlist"] = provider_allowlist
            result = _impls.paper_search(**search_kwargs)
            per_query.append((query, list(result.papers)))
            for err in getattr(result, "provider_errors", None) or []:
                text = str(err).strip()
                # An index intentionally outside the domain route did not fail.
                provider, separator, reason = text.partition(": ")
                if provider and separator and reason == "excluded_by_search_policy":
                    continue
                if text and text not in provider_errors:
                    provider_errors.append(text)
            errored = {
                str(err).partition(": ")[0].strip()
                for err in getattr(result, "provider_errors", None) or []
            }
            for prov in getattr(result, "providers_queried", None) or []:
                text = str(prov).strip()
                if text and text not in providers_seen:
                    providers_seen.append(text)
                if text and text not in errored and text not in providers_answered:
                    providers_answered.append(text)
            top = str(getattr(result, "provider", "") or "").strip()
            if top and top not in providers_seen:
                providers_seen.append(top)
        except SPCAcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001 — one failed provider round is a miss
            per_query.append((query, []))
            err = f"query_round: {exc}"
            if err not in provider_errors:
                provider_errors.append(err)

    candidates, capture_queries = _merge_capture_candidates(per_query, max_candidates)
    return {
        "queries": queries,
        "long_gap_note": long_gap_note,
        "per_query": per_query,
        "provider_errors": provider_errors,
        "providers_seen": providers_seen,
        "providers_answered": providers_answered,
        "candidates": candidates,
        "capture_queries": capture_queries,
    }


def gap_ground_verify(
    *,
    db: Database,
    topic_id: int,
    gap: str = "",
    max_candidates: int = 25,
    focus: str = "",
    governance_alpha: float = 0.1,
    published_before: str = "",
    judge_mode: str = "single",
    _model: str | None = None,
    **_: Any,
) -> GapGroundVerifyOutput:
    """Grounded verification of a candidate gap against retrieved REAL prior art.

    Unlike ``gap_detect`` — a single subjective LLM call over the pool summary,
    which cannot tell a real gap from an artifact of incomplete pool coverage —
    this retrieves external prior art for the gap claim and performs
    contribution-level grounded comparison, returning a verdict plus an explicit
    retrieval-coverage caveat.

    v1.1: the gap is first DECOMPOSED into ~6 contribution-level queries
    (pre-empting work hides under different terminology — the whole-sentence
    query is what missed FB-Bench), each query is an independent capture
    attempt, and the final verdict is gated by governance_gate: an "open"
    (negative-existence) claim backed by too few independent captures is
    confidence-discounted or downgraded per the r(rho) rule.

    NOV02 judge arm (opt-in, ``judge_mode="panel"``): the same candidate block
    is judged by one independent judge per perspective. Coverage /
    mechanism_equivalence / narrowness ask whether the residual is still empty,
    under an explicit residual-narrowness assessment and a
    core-mechanism+core-question decision rule; residual_depth asks the reverse
    question -- whether occupying that residual requires building anything --
    under a decision rule of its own, since the default one files residual
    reasoning away from the verdict. Votes are aggregated (>=2 occupied ->
    occupied). Retrieval is unchanged; ``judge_mode="single"`` (default) is the
    exact prior behavior.
    """
    gap = (gap or "").strip()
    if not gap:
        return GapGroundVerifyOutput(
            gap="",
            verdict="inconclusive",
            grounded_confidence=0.0,
            coverage_note="No gap text supplied; provide `gap` to verify.",
        )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("gap_ground_verify"))

    from research_harness.retrieval_hygiene import (
        sanitize_numeric_evidence_items,
        synonym_family_zero_hits,
        uncovered_index_note,
    )

    captured = _capture_prior_art(
        db=db,
        topic_id=topic_id,
        client=client,
        gap=gap,
        focus=focus,
        max_candidates=max_candidates,
    )
    queries, long_gap_note, per_query = (
        captured["queries"],
        captured["long_gap_note"],
        captured["per_query"],
    )
    provider_errors, providers_seen = (
        captured["provider_errors"],
        captured["providers_seen"],
    )
    candidates, capture_queries = captured["candidates"], captured["capture_queries"]

    temporal_note = ""
    if published_before:
        before = len(candidates)
        candidates = [p for p in candidates if _published_no_later(p, published_before)]
        excluded = before - len(candidates)
        temporal_note = (
            f" Temporal cutoff {published_before}: {excluded} candidate(s) "
            "published after the cutoff were excluded from comparison."
        )

    # E1/E4/E5/E9 hygiene for the gap_ground_verify path (not just panorama harvest).
    failure_note = ""
    if provider_errors:
        shown = "; ".join(provider_errors[:6])
        more = (
            f" (+{len(provider_errors) - 6} more)" if len(provider_errors) > 6 else ""
        )
        failure_note = (
            f" Provider/source failure(s) during retrieval: {shown}{more}."
            " Failed sources must not be read as empty searches."
        )
    lag_note = (
        " Index lag: zero hits on mainstream indexes for work submitted within "
        "~12 months is not negative evidence — require arXiv direct + web "
        "confirmation before treating a name/term as absent."
    )

    route_note = uncovered_index_note(f"{gap} {focus or ''}", providers_seen)
    family_hits = {q: len(papers) for q, papers in per_query}
    synonym_note = synonym_family_zero_hits(family_hits).get("note") or ""

    if not candidates:
        return GapGroundVerifyOutput(
            gap=gap,
            verdict="inconclusive",
            grounded_confidence=0.0,
            candidates_examined=0,
            query_used=gap,
            queries_used=queries,
            capture_queries=0,
            governance_action="abstain_pending_external",
            providers_queried=providers_seen,
            providers_answered=captured["providers_answered"],
            provider_errors=provider_errors,
            coverage_note=(
                "No prior-art candidates retrieved across "
                f"{len(queries)} decomposed queries — retrieval may have failed "
                "or the gap terms are off-distribution; verdict withheld."
                + long_gap_note
                + failure_note
                + lag_note
                + route_note
                + synonym_note
            ),
        )

    lines: list[str] = []
    for idx, paper in enumerate(candidates, 1):
        body = (paper.abstract or paper.snippet or "").strip()
        lines.append(
            f"[{idx}] {paper.title} "
            f"({paper.year or 'n.d.'}, {paper.venue or 'n/a'})\n{body[:600]}"
        )
    candidates_block = "\n\n".join(lines)

    judge_votes: list[dict[str, str]] = []
    if judge_mode == "panel":
        judgements: list[tuple[str, dict[str, Any]]] = []
        for perspective in prompts.GAP_JUDGE_PERSPECTIVES:
            raw = _client_chat(
                client,
                prompts.gap_ground_verify_panel_prompt(
                    gap, candidates_block, perspective, focus
                ),
            )
            judgements.append(
                (perspective, _parse_json(raw, primitive="gap_ground_verify"))
            )
        parsed, judge_votes = _merge_panel_judgements(judgements)
    else:
        raw = _client_chat(
            client, prompts.gap_ground_verify_prompt(gap, candidates_block, focus)
        )
        parsed = _parse_json(raw, primitive="gap_ground_verify")

    by_title = {paper.title.strip().lower(): paper for paper in candidates}
    occupying: list[GroundedPriorArt] = []
    # E10: structured numeric claims must carry admissible extraction methods.
    numeric_rows = [
        item
        for item in list(parsed.get("occupying", []))
        + list(parsed.get("numeric_evidence", []) or [])
        if isinstance(item, dict)
    ]
    numeric_guard = sanitize_numeric_evidence_items(numeric_rows)
    rejected_numeric = {id(item) for item in numeric_guard["rejected"]}
    e10_note = str(numeric_guard.get("note") or "")
    for item in parsed.get("occupying", []):
        if not isinstance(item, dict):
            continue
        if id(item) in rejected_numeric:
            continue
        item_verdict = str(item.get("verdict", "unrelated")).strip().lower()
        if item_verdict == "unrelated":
            continue
        title = str(item.get("title", "")).strip()
        src = by_title.get(title.lower())
        occupying.append(
            GroundedPriorArt(
                title=title or (src.title if src else ""),
                verdict=item_verdict,
                evidence=str(item.get("evidence", "")).strip(),
                year=(src.year if src else None),
                venue=(src.venue if src else ""),
                arxiv_id=(src.arxiv_id if src else ""),
                doi=(src.doi if src else ""),
                relevance_score=(src.relevance_score if src else 0.0),
            )
        )

    verdict = str(parsed.get("verdict", "open")).strip().lower()
    if verdict not in {"open", "occupied", "partially_occupied", "inconclusive"}:
        verdict = "open"
    confidence = max(
        0.0, min(1.0, _coerce_float(parsed.get("grounded_confidence"), 0.0))
    )

    # -- governed acceptance: same backend produced and judged the gap --
    judge = getattr(client, "model", "") or (_model or "rh-backend")
    (
        verdict,
        confidence,
        governance_action,
        trust_adjusted,
        gate_note,
    ) = _apply_gap_governance(
        verdict, confidence, capture_queries, str(judge), governance_alpha
    )

    # Source failures make positive "open" claims untrustworthy (E1).
    if provider_errors and verdict == "open":
        verdict = "inconclusive"
        confidence = min(confidence, 0.3)
        if governance_action in {"", "accept", "accept_verdict"}:
            governance_action = "abstain_pending_external"

    return GapGroundVerifyOutput(
        gap=gap,
        verdict=verdict,
        grounded_confidence=confidence,
        candidates_examined=len(candidates),
        occupying=occupying,
        retrieved=[
            GroundedPriorArt(
                title=paper.title,
                year=paper.year,
                venue=(paper.venue or ""),
                arxiv_id=(paper.arxiv_id or ""),
                doi=(paper.doi or ""),
                relevance_score=(paper.relevance_score or 0.0),
            )
            for paper in candidates
        ],
        coverage_note=(
            str(parsed.get("coverage_note", "")).strip()
            + long_gap_note
            + temporal_note
            + gate_note
            + failure_note
            + (lag_note if verdict in {"open", "inconclusive"} else "")
            + route_note
            + (synonym_note if verdict in {"open", "inconclusive"} else "")
            + e10_note
        ),
        query_used=gap,
        queries_used=queries,
        capture_queries=capture_queries,
        governance_action=governance_action,
        trust_adjusted_confidence=trust_adjusted,
        providers_queried=providers_seen,
        providers_answered=captured["providers_answered"],
        provider_errors=provider_errors,
        judge_votes=judge_votes,
        # panel-only: the single-mode prompt/contract is intentionally
        # untouched, so its output surface stays exactly as before.
        narrowness=(
            _coerce_narrowness(parsed.get("narrowness"))
            if judge_mode == "panel"
            else {}
        ),
    )


def query_refine(
    *,
    db: Database,
    topic_id: int,
    max_candidates: int = 8,
    _model: str | None = None,
    **_: Any,
) -> QueryRefineOutput:
    summary, _ = _get_topic_literature_summary(db, topic_id, task_type="gap_detect")
    top_keywords, frequent_authors, venues, known_queries, gaps = (
        _collect_topic_query_context(db, topic_id)
    )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("query_refine"))
    raw = _client_chat(
        client,
        prompts.query_refine_prompt(
            topic_summary=summary,
            top_keywords=top_keywords,
            frequent_authors=frequent_authors,
            venues=venues,
            known_queries=known_queries,
            gaps=gaps,
            max_candidates=max_candidates,
        ),
    )
    parsed = _parse_json(raw, primitive="query_refine")

    candidates: list[QueryCandidate] = []
    seen_queries = {query.casefold() for query in known_queries}
    for item in parsed.get("candidates", []):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        lowered = query.casefold()
        if lowered in seen_queries:
            continue
        seen_queries.add(lowered)
        candidates.append(
            QueryCandidate(
                query=query,
                rationale=str(item.get("rationale", "")).strip(),
                coverage_direction=str(item.get("coverage_direction", "")).strip(),
                priority=str(item.get("priority", "medium")).strip() or "medium",
            )
        )

    return QueryRefineOutput(
        topic_id=topic_id,
        candidates=candidates[:max_candidates],
        top_keywords=top_keywords,
        frequent_authors=frequent_authors,
        venue_distribution=venues,
        known_queries=known_queries,
        gaps_considered=gaps,
        model_used=client.model,
    )


def paper_coverage_check(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> CoverageCheckOutput:
    conn = db.connect()
    try:
        # Fetch topic context
        topic_row = conn.execute(
            "SELECT name, description FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        topic_context = ""
        if topic_row:
            name = topic_row["name"] or ""
            desc = topic_row["description"] or ""
            topic_context = f"{name}\n{desc}".strip()

        # Fetch all papers for this topic (excluding already-dismissed ones)
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.arxiv_id, p.doi, p.url, p.pdf_path, p.status
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()

        # Check which papers have abstract annotations
        abstract_by_paper: dict[int, str] = {}
        for row in rows:
            pid = row["id"]
            ann = conn.execute(
                """
                SELECT content FROM paper_annotations
                WHERE paper_id = ? AND section IN ('abstract', 'summary')
                  AND COALESCE(content, '') != ''
                LIMIT 1
                """,
                (pid,),
            ).fetchone()
            if ann:
                abstract_by_paper[pid] = (ann["content"] or "").strip()

        # Fetch past dismissal reasons to calibrate LLM scoring
        dismissed_rows = conn.execute(
            """
            SELECT p.title, tpn.content as reason
            FROM topic_paper_notes tpn
            JOIN papers p ON p.id = tpn.paper_id
            WHERE tpn.topic_id = ? AND tpn.note_type = 'user_dismissed'
              AND COALESCE(tpn.content, '') != ''
            ORDER BY tpn.created_at DESC
            LIMIT 20
            """,
            (topic_id,),
        ).fetchall()
        dismissal_history = [(r["title"], r["reason"]) for r in dismissed_rows]

    finally:
        conn.close()

    # Filter to papers without PDF (meta_only or no pdf_path)
    meta_papers = [r for r in rows if not r["pdf_path"] or r["status"] == "meta_only"]

    if not meta_papers:
        return CoverageCheckOutput(items=[], total_meta_only=0, high_necessity_count=0)

    # Build prompt input: id | title | has_abstract | snippet
    lines = []
    for r in meta_papers:
        pid = r["id"]
        title = r["title"] or f"Paper #{pid}"
        has_abs = pid in abstract_by_paper
        snippet = abstract_by_paper.get(pid, "")[:200] if has_abs else "(no abstract)"
        lines.append(f"{pid} | {title} | {'yes' if has_abs else 'no'} | {snippet}")
    papers_text = "\n".join(lines)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("paper_coverage_check"))
    raw = _client_chat(
        client,
        prompts.paper_coverage_check_prompt(
            topic_context, papers_text, focus, dismissal_history
        ),
    )
    parsed = _parse_json(raw, primitive="paper_coverage_check")

    # Build necessity lookup from LLM response
    necessity_map: dict[int, tuple[str, str]] = {}
    for item in parsed.get("assessments", []):
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item["paper_id"])
        except (KeyError, ValueError, TypeError):
            continue
        level = str(item.get("necessity_level", "medium")).strip() or "medium"
        reason = str(item.get("reason", "")).strip()
        necessity_map[pid] = (level, reason)

    # Build download hints and CoverageItems
    items: list[CoverageItem] = []
    for r in meta_papers:
        pid = r["id"]
        arxiv_id = r["arxiv_id"] or ""
        doi = r["doi"] or ""
        url = r["url"] or ""

        if arxiv_id:
            hint = f"https://arxiv.org/abs/{arxiv_id}"
        elif doi:
            hint = f"https://doi.org/{doi}"
        elif url:
            hint = url
        else:
            hint = ""

        necessity_level, reason = necessity_map.get(pid, ("medium", ""))
        items.append(
            CoverageItem(
                paper_id=pid,
                title=r["title"] or f"Paper #{pid}",
                has_abstract=pid in abstract_by_paper,
                has_pdf=bool(r["pdf_path"]),
                necessity_level=necessity_level,
                reason=reason,
                download_hint=hint,
                arxiv_id=arxiv_id,
                doi=doi,
            )
        )

    # Sort: high first, then medium, then low
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (order.get(x.necessity_level, 1), x.paper_id))

    high_count = sum(1 for it in items if it.necessity_level == "high")
    return CoverageCheckOutput(
        items=items,
        total_meta_only=len(meta_papers),
        high_necessity_count=high_count,
    )


def _stamp_external_year(
    metrics: dict, paper_ids: list[int], db: Database, topic_id: int
) -> dict:
    """Fill year and external from the topic's papers when the model omits them.

    The IPM gate reads metrics.year and metrics.external. A baseline the model
    named but did not date is still an external comparator if a linked paper
    has a year. A year the model already wrote is kept.
    """
    stamped = dict(metrics)
    if stamped.get("external") is True and isinstance(
        stamped.get("year"), (int, float)
    ):
        return stamped
    if not paper_ids:
        return stamped
    placeholders = ",".join("?" * len(paper_ids))
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT MAX(p.year) FROM papers p JOIN paper_topics pt ON pt.paper_id=p.id "
            f"WHERE pt.topic_id=? AND p.id IN ({placeholders}) AND p.year IS NOT NULL",
            (topic_id, *paper_ids),
        ).fetchone()
    year = row[0] if row else None
    if isinstance(year, (int, float)):
        stamped.setdefault("external", True)
        stamped.setdefault("year", int(year))
    return stamped


def baseline_identify(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> BaselineIdentifyOutput:
    summary, related_paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="baseline_identify"
    )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("baseline_identify"))
    raw = _client_chat(client, prompts.baseline_identify_prompt(summary, focus))
    parsed = _parse_json(raw, primitive="baseline_identify")

    baselines: list[Baseline] = []
    for item in parsed.get("baselines", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        metrics = _stamp_external_year(metrics, related_paper_ids, db, topic_id)
        facets = item.get("facets")
        if not isinstance(facets, list):
            facets = item.get("covered_facets")
        facet_values = [
            str(value).strip() for value in facets or [] if str(value).strip()
        ]
        baseline_id = str(item.get("baseline_id") or item.get("id") or "").strip()
        if not baseline_id:
            baseline_id = "-".join(
                part
                for part in "".join(
                    ch.lower() if ch.isalnum() else "-" for ch in name
                ).split("-")
                if part
            )
        baselines.append(
            Baseline(
                name=name,
                baseline_id=baseline_id,
                method_family=str(
                    item.get("method_family")
                    or item.get("baseline_family")
                    or item.get("family")
                    or ""
                ).strip(),
                facets=facet_values,
                relationship_to_proposal=str(
                    item.get("relationship_to_proposal") or ""
                ).strip(),
                paper_ids=related_paper_ids,
                source_paper_ids=related_paper_ids,
                metrics=metrics,
                notes=str(item.get("notes", "")).strip(),
            )
        )

    return BaselineIdentifyOutput(baselines=baselines)


# ---------------------------------------------------------------------------
# Venue writing profiles — persistent competitive_learning cache
# ---------------------------------------------------------------------------

_VENUE_PROFILE_MAX_AGE_DAYS = 180


def _load_cached_venue_profiles(
    db: Database, venue: str
) -> CompetitiveLearningOutput | None:
    """Return cached CompetitiveLearningOutput if venue profiles are fresh enough."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT dimension, top_pattern, examples, paper_count, updated_at
               FROM venue_writing_profiles
               WHERE venue = ?
               ORDER BY dimension""",
            (venue,),
        ).fetchall()
    except Exception:
        return None
    finally:
        conn.close()
    if not rows:
        return None
    # Check freshness: all rows share roughly the same updated_at
    from datetime import datetime, timedelta, timezone

    try:
        oldest = min(datetime.fromisoformat(r["updated_at"]) for r in rows)
    except (ValueError, TypeError):
        return None
    if datetime.now(timezone.utc).replace(tzinfo=None) - oldest > timedelta(
        days=_VENUE_PROFILE_MAX_AGE_DAYS
    ):
        return None
    patterns: list[WritingPattern] = []
    for r in rows:
        patterns.append(
            WritingPattern(
                dimension=r["dimension"],
                pattern=r["top_pattern"],
                example="",
                source_paper="",
            )
        )
    return CompetitiveLearningOutput(
        venue=venue,
        exemplar_count=rows[0]["paper_count"] if rows else 0,
        patterns=patterns,
        model_used="cache",
    )


def _persist_venue_profiles(
    db: Database,
    venue: str,
    patterns: list[WritingPattern],
    paper_count: int,
) -> None:
    """Upsert venue writing profiles from competitive_learning results."""
    if not patterns:
        return
    conn = db.connect()
    try:
        for p in patterns:
            conn.execute(
                """INSERT INTO venue_writing_profiles
                   (venue, dimension, top_pattern, paper_count, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(venue, dimension) DO UPDATE SET
                     top_pattern = excluded.top_pattern,
                     paper_count = excluded.paper_count,
                     updated_at = excluded.updated_at""",
                (venue, p.dimension, p.pattern, paper_count),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist venue profiles for %s: %s", venue, exc)
    finally:
        conn.close()


def competitive_learning(
    *,
    db: Database,
    topic_id: int,
    venue: str,
    paper_ids: list[int] | None = None,
    contributions: str = "",
    _model: str | None = None,
    **_: Any,
) -> CompetitiveLearningOutput:
    """Analyze exemplar papers from a venue to extract writing patterns.

    If paper_ids is provided, uses those specific papers as exemplars.
    Otherwise, selects the highest-cited recent papers from the topic pool
    that match the target venue.

    ``contributions`` is optional: if omitted, auto-loaded from the
    ``topics.contributions`` for this topic.
    """
    if not contributions.strip():
        contributions = _get_topic_latest_project_contributions(db, topic_id)

    # Check freshness cache: skip LLM if venue profiles are < 180 days old
    cached = _load_cached_venue_profiles(db, venue)
    if cached is not None:
        return cached

    conn = db.connect()
    try:
        # Select exemplar papers: user-specified or auto-selected by venue + citations
        if paper_ids:
            placeholders = ",".join("?" * len(paper_ids))
            rows = conn.execute(
                f"SELECT id, title, abstract, venue, year FROM papers WHERE id IN ({placeholders})",
                paper_ids,
            ).fetchall()
        else:
            # Auto-select: recent high-cited papers matching venue keyword
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.abstract, p.venue, p.year
                FROM papers p
                JOIN paper_topics pt ON p.id = pt.paper_id
                WHERE pt.topic_id = ?
                  AND p.year >= strftime('%Y', 'now', '-2 years')
                  AND (p.venue LIKE ? OR p.venue LIKE ?)
                ORDER BY p.citation_count DESC NULLS LAST
                LIMIT 8
                """,
                (topic_id, f"%{venue}%", f"%{venue.split()[0]}%"),
            ).fetchall()

        if not rows:
            # Retrieve through the managed lane, then verify venue membership.
            try:
                from research_harness.paper_source_clients import build_provider_suite
                from research_harness.paper_sources import SearchAggregator, SearchQuery

                outcome = SearchAggregator(build_provider_suite()).search(
                    SearchQuery(query=venue, limit=20)
                )
                oa_records = [
                    r
                    for r in outcome.results
                    if r.venue.strip().casefold() == venue.strip().casefold()
                ][:8]
                if oa_records:
                    rows = [
                        {
                            "id": 0,
                            "title": r.title,
                            "abstract": r.abstract,
                            "venue": r.venue,
                            "year": r.year,
                        }
                        for r in oa_records
                    ]
            except SPCAcquisitionError:
                raise
            except Exception as exc:
                logger.debug("OpenAlex venue_papers fallback failed: %s", exc)

        if not rows:
            # Fallback 3: just pick top-cited recent papers from topic
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.abstract, p.venue, p.year
                FROM papers p
                JOIN paper_topics pt ON p.id = pt.paper_id
                WHERE pt.topic_id = ?
                  AND p.year >= strftime('%Y', 'now', '-2 years')
                ORDER BY p.citation_count DESC NULLS LAST
                LIMIT 5
                """,
                (topic_id,),
            ).fetchall()
    finally:
        conn.close()

    # Build exemplar text block
    exemplar_parts: list[str] = []
    for r in rows:
        parts = [
            f"### {r['title']} ({r['venue'] or 'unknown venue'}, {r['year'] or '?'})"
        ]
        if r["abstract"]:
            parts.append(f"Abstract: {r['abstract'][:800]}")
        exemplar_parts.append("\n".join(parts))

    exemplar_text = "\n\n".join(exemplar_parts)
    if not exemplar_text.strip():
        return CompetitiveLearningOutput(venue=venue, exemplar_count=0)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("competitive_learning"))
    raw = _client_chat(
        client,
        prompts.competitive_learning_prompt(venue, exemplar_text, contributions),
    )
    parsed = _parse_json(raw, primitive="competitive_learning")

    patterns: list[WritingPattern] = []
    for item in parsed.get("patterns", []):
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension", "")).strip()
        pat = str(item.get("pattern", "")).strip()
        if dim and pat:
            patterns.append(
                WritingPattern(
                    dimension=dim,
                    pattern=pat,
                    example=str(item.get("example", "")).strip(),
                    source_paper=str(item.get("source_paper", "")).strip(),
                )
            )

    section_norms = parsed.get("section_length_norms", {})
    if not isinstance(section_norms, dict):
        section_norms = {}
    section_norms = {
        str(k): int(v) for k, v in section_norms.items() if isinstance(v, (int, float))
    }

    result = CompetitiveLearningOutput(
        venue=venue,
        exemplar_count=len(rows),
        patterns=patterns,
        section_length_norms=section_norms,
        narrative_guidance=str(parsed.get("narrative_guidance", "")).strip(),
        model_used=client.model,
    )

    _persist_venue_profiles(db, venue, patterns, len(rows))

    return result


_DEFAULT_WORD_TARGETS: dict[str, int] = {
    "abstract": 220,
    "introduction": 1500,
    "related_work": 2500,
    "related work": 2500,
    "method": 3000,
    "methodology": 3000,
    "experiments": 3500,
    "experiment": 3500,
    "results": 1500,
    "discussion": 900,
    "conclusion": 350,
    "conclusions": 350,
    "limitations": 350,
    "appendix": 3000,
}


def _default_citation_quota(section: str) -> int:
    from .writing_checks import SECTION_CITATION_QUOTA

    return SECTION_CITATION_QUOTA.get(normalize_section_key(section), 0)


# v2 Step 3.3: sentence-level evidence map for section_draft sidecar.

_CITATION_PATTERNS = (
    # LaTeX \cite{foo,bar}
    re.compile(r"\\cite[pt]?\{([^}]+)\}"),
    # Numeric [1] or [1, 2, 3]
    re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]"),
    # Author-year style (Smith, 2024) or (Smith et al., 2024)
    re.compile(r"\(([A-Z][A-Za-z]+(?: et al\.?)?(?:,\s*\d{4}))\)"),
)


def _split_sentences(text: str) -> list[str]:
    """Lightweight sentence splitter — good enough for citation auditing.

    Splits on ., !, ? followed by whitespace. Keeps URLs and abbreviations
    intact for the common cases we encounter in drafts.
    """
    # Preserve \cite{} tokens from splitting by ".": mask them first.
    masked = re.sub(
        r"\\cite[pt]?\{[^}]+\}", lambda m: m.group(0).replace(".", "§DOT§"), text
    )
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\\\[\(])", masked)
    return [p.replace("§DOT§", ".").strip() for p in parts if p.strip()]


def _sentence_citations(sentence: str, paper_ids: list[int]) -> list[int]:
    """Return source paper IDs cited in this sentence.

    Maps numeric [N] markers to paper_ids by index (1-based, matching how
    _build_numbered_evidence renders them). Non-numeric markers are grouped
    as a symbolic citation (we cannot resolve author-year without a bibmap).
    """
    cited_ids: list[int] = []
    for pattern in _CITATION_PATTERNS:
        for match in pattern.finditer(sentence):
            token = match.group(1)
            for part in re.split(r"[,;]\s*", token):
                part = part.strip()
                if not part:
                    continue
                # Numeric index -> map via paper_ids list
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(paper_ids):
                        cited_ids.append(paper_ids[idx])
    # Deduplicate while preserving order
    seen: set[int] = set()
    result: list[int] = []
    for pid in cited_ids:
        if pid not in seen:
            seen.add(pid)
            result.append(pid)
    return result


def _has_any_citation(sentence: str) -> bool:
    return any(p.search(sentence) for p in _CITATION_PATTERNS)


def _classify_relation(sentence: str) -> str:
    """Heuristic: quoted text -> quotation; hedged language -> inference;
    otherwise -> compression (paraphrased summary).
    """
    if '"' in sentence or "“" in sentence or "”" in sentence:
        return "quotation"
    lowered = sentence.lower()
    if any(
        kw in lowered
        for kw in (
            " suggest ",
            " imply ",
            " indicate ",
            " likely ",
            " may ",
            " could ",
            " appears ",
            " seems ",
        )
    ):
        return "inference"
    return "compression"


def _extract_evidence_map(content: str, paper_ids: list[int]):
    """Build EvidenceMapping entries, one per citation-marked sentence.

    Uses a local import for the dataclass to avoid a module-level circular
    import between primitives.types and execution.llm_primitives.
    """
    from research_harness.primitives.types import EvidenceMapping

    entries: list[EvidenceMapping] = []
    sentences = _split_sentences(content)
    for idx, sent in enumerate(sentences):
        if not _has_any_citation(sent):
            continue
        sources = _sentence_citations(sent, paper_ids)
        relation = _classify_relation(sent)
        if sources:
            for pid in sources:
                entries.append(
                    EvidenceMapping(
                        sentence_index=idx,
                        sentence_text=sent[:500],
                        source_paper_id=pid,
                        relation_type=relation,
                        source_span="",
                        confidence=0.7,
                    )
                )
        else:
            # Sentence has a citation we cannot resolve to a paper_id
            # (e.g., author-year without bib map). Still emit an entry
            # with source_paper_id=0 so coverage accounting fires.
            entries.append(
                EvidenceMapping(
                    sentence_index=idx,
                    sentence_text=sent[:500],
                    source_paper_id=0,
                    relation_type=relation,
                    source_span="",
                    confidence=0.3,
                )
            )
    return entries


SECTION_EVIDENCE_UNSUPPORTED_CODE = "SECTION_EVIDENCE_UNSUPPORTED"


class SectionEvidenceUnsupportedError(RuntimeError):
    """Raised in strict mode when a drafted section cites unsupported evidence.

    Default behaviour stays warn-only. Strict mode (the ``strict_evidence``
    argument, or the ``RH_SECTION_DRAFT_STRICT_EVIDENCE`` env var) turns
    out-of-range citation markers into a hard block so unsupported prose is not
    silently accepted.
    """

    def __init__(self, *, section: Any, topic_id: Any, warnings: list[str]) -> None:
        self.section = section
        self.topic_id = topic_id
        self.warnings = list(warnings)
        super().__init__(
            json.dumps(
                {
                    "code": SECTION_EVIDENCE_UNSUPPORTED_CODE,
                    "message": (
                        f"section_draft {section} has unsupported citations; "
                        "attach evidence or disable strict evidence mode"
                    ),
                    "section": section,
                    "topic_id": topic_id,
                    "unsupported_citations": list(warnings),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def _section_draft_strict_evidence(explicit: bool | None) -> bool:
    """Resolve strict-evidence mode from the explicit arg then the env var."""
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("RH_SECTION_DRAFT_STRICT_EVIDENCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# EAG L1 arc contracts: which exemplar plan artifact drives which section's
# outline when the caller supplies none. experiments/results share one arc;
# limitations/conclusion share the discussion arc.
_ARC_PLAN_FOR_SECTION = {
    # The abstract carries venue register at its first sentence: a
    # Nature-family abstract opens on the problem and pivots on "Here we ...",
    # a conference abstract opens on "We introduce ...". Without an arc entry
    # the abstract silently fell back to the generic formula and drafted in
    # the wrong register, which is what shipped before 2026-08-17.
    "abstract": "exemplar_plan_abstract_arc",
    "introduction": "exemplar_plan_intro_arc",
    "related_work": "exemplar_plan_related_work_arc",
    "method": "exemplar_plan_method_arc",
    "experiments": "exemplar_plan_experiment_arc",
    "results": "exemplar_plan_experiment_arc",
    "limitations": "exemplar_plan_discussion_arc",
    "conclusion": "exemplar_plan_discussion_arc",
}

_MOVE_PLAN_FOR_SECTION = {
    "abstract": "exemplar_plan_abstract_moves",
    "introduction": "exemplar_plan_intro_moves",
    "discussion": "exemplar_plan_discussion_moves",
    "limitations": "exemplar_plan_discussion_moves",
    "conclusion": "exemplar_plan_discussion_moves",
}


def _section_arc_artifact(db, topic_id, section):
    from research_harness.orchestrator import OrchestratorService
    from research_harness.primitives.exemplar_impls import _valid_moves

    service = OrchestratorService(db)
    move_kind = _MOVE_PLAN_FOR_SECTION.get(section)
    if move_kind:
        artifact = service.get_latest_artifact(topic_id, "write", move_kind)
        if artifact is not None:
            if not isinstance(artifact.payload, dict) or not _valid_moves(
                artifact.payload.get("plan")
            ):
                raise ValueError(f"E-WRITE-EAG-PLAN-INVALID: {move_kind}")
            return artifact
    legacy_kind = _ARC_PLAN_FOR_SECTION.get(section)
    return (
        service.get_latest_artifact(topic_id, "write", legacy_kind)
        if legacy_kind
        else None
    )


def _eag_paragraph_craft_block(db, topic_id) -> str:
    """L2 paragraph-craft contract as a guidance block (opt-in, batch 2)."""
    if os.environ.get("RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES", "0").strip() != "1":
        return ""
    if db is None or topic_id is None:
        return ""
    try:
        from research_harness.orchestrator import OrchestratorService

        artifact = OrchestratorService(db).get_latest_artifact(
            topic_id, "write", "exemplar_plan_paragraph_moves"
        )
        plan = (
            artifact.payload.get("plan", {})
            if (artifact and isinstance(artifact.payload, dict))
            else {}
        )
        if not plan:
            return ""
        return (
            "## PARAGRAPH CRAFT (form contract — organize every paragraph by "
            "these templates; never copy exemplar wording)\n"
            + json.dumps(plan, ensure_ascii=False)[:2200]
        )
    except Exception:
        logger.debug("paragraph craft contract unavailable", exc_info=True)
        return ""


def _verify_artifact_ref(service, topic_id, reference, *, stage="write"):
    """Return the active artifact an exact reference names; refuse a missing, stale or changed one.

    The reference is ``{"id", "version", "sha256", "artifact_type"}``; ``sha256`` is the canonical
    JSON hash of the payload (sorted keys, compact separators), the same encoding used when the
    reference was minted.
    """

    def refuse(message):
        raise ValueError(f"WRITE validation: {message}")

    if not (
        isinstance(reference, dict)
        and set(reference) == {"id", "version", "sha256", "artifact_type"}
    ):
        refuse("invalid writing artifact reference")
    if not all(
        type(reference[key]) is int and reference[key] > 0 for key in ("id", "version")
    ):
        refuse("invalid writing artifact identity")
    artifact = service.get_latest_artifact(topic_id, stage, reference["artifact_type"])
    if artifact is None or artifact.status != "active" or artifact.stale:
        refuse("writing upstream artifact is missing or stale")
    digest = hashlib.sha256(
        json.dumps(
            artifact.payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    current = {
        "id": artifact.id,
        "version": artifact.version,
        "sha256": digest,
        "artifact_type": artifact.artifact_type,
    }
    if current != reference:
        refuse("writing upstream artifact version or bytes changed")
    return artifact


def _bound_eag_plans(db, topic_id, paper_plan):
    """Resolve exact DB-backed references, never trust caller-supplied plan bytes."""
    from research_harness.orchestrator import OrchestratorService
    from research_harness.primitives.exemplar_impls import _valid_moves

    plan = paper_plan or {}
    if "_eag_plans" in plan:
        raise ValueError("EAG embedded plans are not a verified artifact contract")
    if "_eag_refs" not in plan:
        return None
    refs = plan["_eag_refs"]
    if (
        db is None
        or type(topic_id) is not int
        or not isinstance(refs, list)
        or not refs
    ):
        raise ValueError("EAG references require a topic and nonempty artifact list")
    kinds = [ref.get("artifact_type") for ref in refs if isinstance(ref, dict)]
    if len(kinds) != len(refs) or not all(isinstance(kind, str) for kind in kinds):
        raise ValueError("EAG references require string artifact types")
    base = {"exemplar_plan_skeleton", "exemplar_plan_style", "figure_suite_plan"}
    moves = {
        "exemplar_plan_abstract_moves",
        "exemplar_plan_intro_moves",
        "exemplar_plan_discussion_moves",
    }
    expected = base | (
        moves
        if moves.intersection(kinds)
        else {"exemplar_plan_intro_arc", "exemplar_plan_abstract"}
    )
    if (
        len(kinds) != len(refs)
        or len(set(kinds)) != len(kinds)
        or set(kinds) != expected
    ):
        raise ValueError("EAG references must be one complete legacy or moves contract")
    service, plans = OrchestratorService(db), {}
    for ref in refs:
        artifact = _verify_artifact_ref(service, topic_id, ref)
        kind = ref["artifact_type"]
        payload = artifact.payload.get(
            "spec" if kind == "figure_suite_plan" else "plan"
        )
        if not isinstance(payload, dict) or (
            kind in moves and not _valid_moves(payload)
        ):
            raise ValueError(f"EAG invalid plan payload: {kind}")
        plans[
            "figure_suite"
            if kind == "figure_suite_plan"
            else kind.removeprefix("exemplar_plan_")
        ] = payload
    return plans


def _frozen_arc_plan(plans, section):
    from research_harness.primitives.exemplar_impls import _valid_moves

    move = _MOVE_PLAN_FOR_SECTION.get(section, "").removeprefix("exemplar_plan_")
    if move in plans:
        if not _valid_moves(plans[move]):
            raise ValueError(f"E-WRITE-EAG-PLAN-INVALID: {move}")
        return plans[move]
    legacy = _ARC_PLAN_FOR_SECTION.get(section, "").removeprefix("exemplar_plan_")
    return plans.get(legacy, plans.get("abstract", {}) if section == "abstract" else {})


def _arc_contract_block(db, topic_id, sec_lower: str, frozen_plans=None) -> str:
    """Exemplar arc plan rendered as a marked structure-authority contract.

    "" when no arc contract applies. Introduction is always on; the other
    section arcs share RESEARCH_HARNESS_EAG_SECTION_ARCS (default ON).
    """
    arc_artifact = _MOVE_PLAN_FOR_SECTION.get(sec_lower) or _ARC_PLAN_FOR_SECTION.get(
        sec_lower
    )
    arc_enabled = sec_lower in {"introduction", "abstract"} or (
        os.environ.get("RESEARCH_HARNESS_EAG_SECTION_ARCS", "1").strip() != "0"
    )
    if not arc_artifact or not arc_enabled or db is None or topic_id is None:
        return ""
    try:
        from research_harness.primitives.exemplar_impls import render_arc_plan

        if frozen_plans is not None:
            plan = _frozen_arc_plan(frozen_plans, sec_lower)
        else:
            pa = _section_arc_artifact(db, topic_id, sec_lower)
            plan = (
                pa.payload.get("plan", {})
                if (pa and isinstance(pa.payload, dict))
                else {}
            )
        rendered = render_arc_plan(plan).strip() if plan else ""
        if not rendered:
            return ""
        return (
            f"## EXEMPLAR {sec_lower.upper()} CONTRACT (structure "
            "authority — FORM abstracted from target-venue exemplars; "
            "follow the paragraph and sentence moves in order, "
            "re-instantiated with THIS paper's content; never copy "
            "exemplar wording)\n" + rendered
        )
    except ValueError:
        raise
    except Exception:
        logger.debug("arc contract unavailable", exc_info=True)
        return ""


def _style_card_block(db, topic_id) -> str:
    """STYLE CARD block from the exemplar_plan_style artifact; "" if none."""
    if db is None or topic_id is None:
        return ""
    try:
        from research_harness.orchestrator import OrchestratorService

        artifact = OrchestratorService(db).get_latest_artifact(
            topic_id, "write", "exemplar_plan_style"
        )
        plan = (
            artifact.payload.get("plan", {})
            if (artifact and isinstance(artifact.payload, dict))
            else {}
        )
        if not plan:
            return ""
        return (
            "## STYLE CARD (form only — abstracted from target-venue exemplars; "
            "imitate structure/rhythm/register, NEVER copy wording or claims)\n"
            + json.dumps(plan, ensure_ascii=False)[:3000]
        )
    except Exception:
        logger.debug("style card unavailable", exc_info=True)
        return ""


def eag_revision_guidance(db, topic_id, section: str, frozen_plans=None) -> str:
    """The EAG target contract for REVISION surfaces (section_revise, polish):
    arc contract + style card + venue polish.

    Revisions must adjust content WITHIN the exemplar-derived structure — the
    contract is restated so review loops cannot drift the draft back to a
    generic register (user mandate: never lose the EAG target during
    adversarial revision).
    """
    sec_lower = normalize_section_key(section)
    if frozen_plans is not None:
        sections = (
            ("abstract", "introduction", "discussion")
            if section == "full_manuscript"
            else (sec_lower,)
        )
        return "\n\n".join(
            [
                *(
                    _arc_contract_block(db, topic_id, sec, frozen_plans)
                    for sec in sections
                ),
                "## STYLE CARD\n"
                + json.dumps(frozen_plans.get("style", {}), ensure_ascii=False),
            ]
        )
    blocks = [
        _arc_contract_block(db, topic_id, sec_lower),
        _style_card_block(db, topic_id),
        _venue_polish_block(db, topic_id),
    ]
    return "\n\n".join(b for b in blocks if b)


def _arc_conformance_check(
    db, topic_id, section: str, content: str, frozen_plans=None
) -> tuple[bool, str] | None:
    """Deterministic EAG arc conformance: draft paragraph count vs contract.

    None when no exemplar arc contract applies to this section.
    """
    # ponytail: paragraph-count proxy only; move-order conformance needs an
    # LLM judge — the adversarial/polish loop covers that today.
    sec = normalize_section_key(section)
    artifact_type = _MOVE_PLAN_FOR_SECTION.get(sec) or _ARC_PLAN_FOR_SECTION.get(sec)
    enabled = sec == "introduction" or (
        os.environ.get("RESEARCH_HARNESS_EAG_SECTION_ARCS", "1").strip() != "0"
    )
    if not artifact_type or not enabled or db is None or topic_id is None:
        return None
    try:
        if frozen_plans is not None:
            plan = _frozen_arc_plan(frozen_plans, sec)
        else:
            pa = _section_arc_artifact(db, topic_id, sec)
            plan = (
                pa.payload.get("plan", {})
                if (pa and isinstance(pa.payload, dict))
                else {}
            )
        paras = plan.get("paragraphs") if isinstance(plan, dict) else None
        planned = (
            len([p for p in paras if isinstance(p, dict)])
            if isinstance(paras, list) and paras
            else int(plan.get("n_paragraphs") or 0)
            if isinstance(plan, dict)
            else 0
        )
        if planned <= 0:
            return None
        observed = len([p for p in re.split(r"\n\s*\n", content or "") if p.strip()])
        passed = abs(observed - planned) <= 1
        return passed, (
            f"exemplar arc contract plans {planned} paragraph(s); draft has {observed}"
        )
    except Exception:
        logger.debug("arc conformance check unavailable", exc_info=True)
        return None


def _venue_quality_targets(db, topic_id) -> dict[str, Any]:
    """Serialized venue polish contract for a topic; {} if unresolved."""
    if db is None or topic_id is None:
        return {}
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT target_venue FROM topics WHERE id=?", (int(topic_id),)
            ).fetchone()
        finally:
            conn.close()
        venue = (row["target_venue"] if row else "") or ""
        if not str(venue).strip():
            return {}
        from research_harness.primitives.venue_prescription import (
            resolve_venue_prescription,
        )

        return resolve_venue_prescription(target_venue=str(venue)).to_dict()
    except Exception:
        logger.debug("venue quality targets unavailable", exc_info=True)
        return {}


def _venue_polish_block(db, topic_id) -> str:
    """First-impression polish contract as a draft guidance block (goal 1)."""
    doc = _venue_quality_targets(db, topic_id)
    if not doc:
        return ""
    try:
        from research_harness.primitives.exemplar_impls import _target_state_string

        body = _target_state_string(doc).strip()
    except Exception:
        return ""
    if not body:
        return ""
    return "## VENUE POLISH CONTRACT (meet every entry; form only)\n" + body


def _logic_obligations_block(db, topic_id, section: str) -> str:
    """Logic-tree obligations for this section (opt-in, batch 2)."""
    if os.environ.get("RESEARCH_HARNESS_EAG_LOGIC_TREE", "0").strip() != "1":
        return ""
    if db is None or topic_id is None:
        return ""
    try:
        from research_harness.orchestrator import OrchestratorService
        from research_harness.primitives.logic_impls import (
            obligations_for_section,
            render_obligations_block,
        )

        artifact = OrchestratorService(db).get_latest_artifact(
            topic_id, "write", "logic_tree"
        )
        payload = (
            artifact.payload
            if (artifact and isinstance(artifact.payload, dict))
            else {}
        )
        obligations = obligations_for_section(payload, section)
        block = render_obligations_block(obligations)
        return f"## {block}" if block else ""
    except Exception:
        logger.debug("logic obligations unavailable", exc_info=True)
        return ""


def section_draft(
    *,
    db: Database,
    section: str,
    topic_id: int,
    evidence_ids: list[str] | None = None,
    outline: str = "",
    writing_patterns: str = "",
    max_words: int = 0,
    citation_quota: int = -1,
    extra_instructions: str = "",
    paper_plan: dict[str, Any] | None = None,
    strict_evidence: bool | None = None,
    paper_context: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> SectionDraftOutput:
    sec_lower = normalize_section_key(section)
    # EAG auto-trigger: follow the recorded exemplar-derived arc plan for this
    # section. The plan is rendered into a marked guidance CONTRACT block —
    # never into ``outline`` — so a caller-supplied topic outline no longer
    # silently suppresses the exemplar arc (the outline stays as content
    # hints; the arc is the structure authority). The introduction path is
    # the shipped default; the other section arcs share one switch
    # (RESEARCH_HARNESS_EAG_SECTION_ARCS, default ON) so the whole-paper
    # top-level rhetorical system is imitated, not just the introduction.
    frozen_plans = _bound_eag_plans(db, topic_id, paper_plan)
    _arc_contract = _arc_contract_block(db, topic_id, sec_lower, frozen_plans)
    ensure_section_draft_logic_gate(
        db=db,
        section=section,
        topic_id=topic_id,
        paper_plan=paper_plan,
    )

    # Use richer numbered evidence list (citation-aware) instead of legacy
    # summary. Outline evidence_ids for this section become priority papers.
    evidence_text, _paper_ids = _build_numbered_evidence(
        db,
        topic_id,
        max_papers=50,
        task_type="section_draft",
        section=sec_lower,
        priority_paper_ids=_coerce_paper_id_list(evidence_ids),
        # A0114's introduction cited ref1..ref50 against a 40-entry bibliography: the
        # caller had named its 40 papers and the list it was shown held the topic's 50.
        restrict_to_priority=True,
    )
    if not evidence_text or evidence_text == "(no papers in topic)":
        # fallback to legacy
        evidence_text, _ = _get_topic_literature_summary(
            db, topic_id, task_type="section_draft"
        )

    # Default word target if caller did not specify
    if max_words <= 0:
        max_words = _DEFAULT_WORD_TARGETS.get(sec_lower, 2000)

    # Default citation quota if caller did not specify
    if citation_quota < 0:
        citation_quota = _default_citation_quota(section)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_draft"))

    # Auto-inject Universal Writing Skill guidance for this section
    section_guidance = ""
    try:
        from research_harness.evolution.topic.writing_skill import (
            WritingSkillAggregator,
        )

        aggregator = WritingSkillAggregator(db)
        section_guidance = aggregator.get_section_guidance(sec_lower.replace(" ", "_"))
    except Exception as exc:
        logger.debug("Writing skill guidance unavailable: %s", exc)

    # Wire 1: Auto-inject writing lessons from previous runs
    lesson_overlay = _load_writing_lessons(db, topic_id, stage="section_draft")
    if lesson_overlay:
        section_guidance = (
            f"{section_guidance}\n\n{lesson_overlay}"
            if section_guidance
            else lesson_overlay
        )

    # EAG style card: inject via the guidance block so it reaches EVERY
    # section prompt (the dedicated abstract/intro/related/method/experiments
    # prompts have no separate writing_patterns argument). When the caller
    # supplied no patterns, fall back to the recorded style-card artifact.
    if writing_patterns and writing_patterns.strip():
        style_block = (
            "## STYLE CARD (form only — abstracted from target-venue exemplars; "
            "imitate structure/rhythm/register, NEVER copy wording or claims)\n"
            + writing_patterns.strip()[:3000]
        )
        writing_patterns = ""  # consumed via guidance; avoid double insertion
    elif frozen_plans is not None:
        style_block = "## STYLE CARD\n" + json.dumps(
            frozen_plans.get("style", {}), ensure_ascii=False
        )
    else:
        style_block = _style_card_block(db, topic_id)
    if style_block:
        section_guidance = (
            f"{section_guidance}\n\n{style_block}" if section_guidance else style_block
        )

    # Exemplar arc contract first (structure authority), then EAG-Ladder
    # batch 2 (both opt-in until E2 evidence): L2 paragraph craft contract +
    # logic-tree obligations for this section. Venue polish contract (goal 1):
    # always-on when the topic has a target_venue.
    for block in (
        _arc_contract,
        _eag_paragraph_craft_block(db, topic_id),
        _logic_obligations_block(db, topic_id, sec_lower),
        _venue_polish_block(db, topic_id),
    ):
        if block:
            section_guidance = (
                f"{section_guidance}\n\n{block}" if section_guidance else block
            )

    # Domain overlay: prefer the caller-supplied plan, else the active
    # PAPER_PLAN artifact (guaranteed present — the logic gate above passed).
    plan_for_domain = paper_plan or _active_paper_plan(db, topic_id)
    domain_key = resolve_domain_key(plan_for_domain)

    # finish_rulebook P1: inject exhibit content scaffold for results/experiments
    # (and appendix-like sections) so section_draft seats case-trace the same
    # way the downstream WRITE stage does — not only a figure role name.
    try:
        from research_harness._workflow.execution.finish_form_contract import (
            build_exhibit_blueprint,
            exhibit_blueprint_as_prompt_block,
            infer_domain_family,
        )

        _sec_for_exhibit = sec_lower.replace("-", "_")
        if _sec_for_exhibit in {
            "experiments",
            "experiment",
            "results",
            "evaluation",
            "appendix",
            "supplementary",
            "case_study",
            "case-study",
        }:
            _hint_bits = [
                str(outline or ""),
                str(domain_key or ""),
                str(section or ""),
            ]
            if isinstance(plan_for_domain, dict):
                for k in ("discipline", "domain", "paper_type", "title", "topic"):
                    v = plan_for_domain.get(k)
                    if v:
                        _hint_bits.append(str(v))
            _hint = " ".join(_hint_bits)
            _family = {
                "biomedical": "medicine",
                "biomed": "medicine",
                "medicine": "medicine",
                "clinical": "medicine",
                "social": "hss",
                "social_science": "hss",
                "hss": "hss",
                "humanities": "hss",
            }.get(str(domain_key or "").lower(), "") or infer_domain_family(_hint)
            _bp = build_exhibit_blueprint(domain_family=_family, manuscript_hint=_hint)
            _ex_block = exhibit_blueprint_as_prompt_block(_bp)
            section_guidance = (
                f"{section_guidance}\n\n{_ex_block}" if section_guidance else _ex_block
            )
    except Exception as exc:
        logger.debug("exhibit blueprint guidance unavailable: %s", exc)

    # Shared paper context: caller-supplied (section loop threads one context
    # across all sections) or built fresh from the plan and topic artifacts.
    if isinstance(paper_context, dict) and paper_context:
        ctx = PaperContext.from_dict(paper_context)
    else:
        ctx = build_paper_context(
            db, topic_id, paper_plan=plan_for_domain, outline=outline
        )
    rendered_context = render_paper_context(ctx, sec_lower)

    # Dispatch to section-specific prompt (abstract/intro/related_work/method/
    # experiments use custom prompts)
    prompt_text = prompts.build_section_draft_prompt(
        section=sec_lower,
        outline=outline,
        evidence_text=evidence_text,
        max_words=max_words,
        section_guidance=section_guidance,
        citation_quota=citation_quota,
        writing_patterns=writing_patterns,
        evidence_count=len(_paper_ids),
        domain_key=domain_key,
        paper_context=rendered_context,
    )
    # User-supplied "custom requirements" from the advisor-report composer get
    # appended as an extra instruction block so they steer THIS draft without
    # overwriting the section-specific prompt scaffolding.
    if extra_instructions.strip():
        prompt_text = (
            prompt_text
            + "\n\nAdditional author instructions (apply on top of everything above):\n"
            + extra_instructions.strip()
        )
    raw = _client_chat(client, prompt_text)

    parsed = _parse_json(raw, primitive="section_draft", context=section)
    content = str(parsed.get("content") or raw[: max_words * 8]).strip()

    # Post-draft citation audit: flag out-of-range [N] markers
    audit_warnings = _audit_draft_citations(content, len(_paper_ids))
    if audit_warnings:
        logger.warning(
            "Citation audit for section '%s': %d issue(s) — %s",
            section,
            len(audit_warnings),
            "; ".join(audit_warnings[:5]),
        )

    # Wire 2: Run deterministic checks and record failures as writing lessons
    _record_writing_lessons_from_draft(
        db, topic_id, sec_lower, content, audit_warnings, max_words
    )

    # Strict evidence mode (opt-in): turn unsupported/out-of-range citations from
    # a warning into a hard block so unsupported prose is not silently accepted.
    # The lesson above is recorded first so the failure stays in provenance.
    if audit_warnings and _section_draft_strict_evidence(strict_evidence):
        raise SectionEvidenceUnsupportedError(
            section=section, topic_id=topic_id, warnings=audit_warnings
        )

    # v2 Step 3.3: sidecar evidence map (every citation-marked sentence gets
    # at least one EvidenceMapping entry).
    evidence_map = _extract_evidence_map(content, _paper_ids)

    return SectionDraftOutput(
        draft=DraftText(
            section=section,
            content=content,
            citations_used=_coerce_int_list(parsed.get("citations_used")),
            evidence_ids=evidence_ids or [],
            word_count=_coerce_int(parsed.get("word_count"), len(content.split())),
        ),
        evidence_map=evidence_map,
    )


_DRAFT_WITH_REVIEW_LOOP_WARNED = False


def draft_with_review_loop(
    *,
    db: Database,
    section: str,
    topic_id: int,
    evidence_ids: list[str] | None = None,
    outline: str = "",
    writing_patterns: str = "",
    max_words: int = 0,
    citation_quota: int = -1,
    max_revisions: int = 2,
    _model: str | None = None,
    **_: Any,
) -> SectionDraftOutput:
    """DEPRECATED. Use research_harness.execution.loops.run_section_loop instead.

    Draft a section with automatic review-revise loop.

    This is the "self-correct" wire of the self-evolution loop:
    1. Draft via section_draft
    2. Run deterministic checks
    3. If checks fail, build feedback and revise (up to max_revisions times)
    4. Return the best version

    Lessons are recorded automatically by section_draft (Wire 2).

    ADR-001 Decision 1 (v2 Step 5): this function is superseded by
    ``run_section_loop`` which folds run_all_checks in as a sub-check and is
    wired through tool_dispatch by default (opt out with
    ``RESEARCH_HARNESS_SECTION_LOOP=0``).
    """
    global _DRAFT_WITH_REVIEW_LOOP_WARNED
    if not _DRAFT_WITH_REVIEW_LOOP_WARNED:
        import warnings

        warnings.warn(
            "draft_with_review_loop() is deprecated; use "
            "research_harness.execution.loops.run_section_loop instead "
            "(ADR-001 Decision 1).",
            DeprecationWarning,
            stacklevel=2,
        )
        _DRAFT_WITH_REVIEW_LOOP_WARNED = True

    from .writing_checks import run_all_checks

    # Initial draft
    result = section_draft(
        db=db,
        section=section,
        topic_id=topic_id,
        evidence_ids=evidence_ids,
        outline=outline,
        writing_patterns=writing_patterns,
        max_words=max_words,
        citation_quota=citation_quota,
        _model=_model,
    )
    content = result.draft.content

    for revision_round in range(max_revisions):
        # Run deterministic review checks
        check_results = run_all_checks(
            content, section, max_words, venue=_topic_venue(db, topic_id)
        )
        failed = [c for c in check_results if not c.passed]

        if not failed:
            logger.info(
                "Section '%s' passed all checks after %d revision(s)",
                section,
                revision_round,
            )
            break

        # Build feedback from failed checks
        feedback_lines = [f"- {c.check_name}: {c.details}" for c in failed]
        feedback = (
            f"Revision round {revision_round + 1}/{max_revisions}. "
            f"The following checks failed:\n" + "\n".join(feedback_lines)
        )

        logger.info(
            "Section '%s' has %d failed check(s), starting revision %d/%d",
            section,
            len(failed),
            revision_round + 1,
            max_revisions,
        )

        # Revise
        client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_revise"))
        revise_prompt = (
            f"You are revising the {section} section of an academic paper.\n\n"
            f"## Review feedback\n{feedback}\n\n"
            f"## Current content\n{content}\n\n"
            f"Fix ALL flagged issues. Return the revised section in the same "
            f"LaTeX format. Preserve all citation markers [N] and equations. "
            f"Target ~{max_words} words.\n\n"
            f'Return JSON: {{"content": "...", "changes_made": ["..."]}}'
        )

        raw = _client_chat(client, revise_prompt)
        parsed = _parse_json(raw, primitive="section_revise", context=section)
        revised = str(parsed.get("content") or raw[: max_words * 8]).strip()
        if revised:
            content = revised
    else:
        logger.warning(
            "Section '%s' still has issues after %d revision(s)",
            section,
            max_revisions,
        )

    # v2 Step 3.3: refresh evidence_map against the final revised content.
    _ev_text, _pids = _build_numbered_evidence(
        db, topic_id, max_papers=50, task_type="section_draft"
    )
    evidence_map = _extract_evidence_map(content, _pids)

    return SectionDraftOutput(
        draft=DraftText(
            section=section,
            content=content,
            citations_used=result.draft.citations_used,
            evidence_ids=evidence_ids or [],
            word_count=len(content.split()),
        ),
        evidence_map=evidence_map,
    )


def outline_generate(
    *,
    db: Database,
    topic_id: int,
    template: str = "neurips",
    contributions: str = "",
    _model: str | None = None,
    **_: Any,
) -> OutlineGenerateOutput:
    """Generate paper outline from topic literature, claims, and contributions.

    ``contributions`` fallback order:
      1. Explicit argument (caller-provided).
      2. ``topics.contributions`` for this topic_id (topic-level config).
      3. Latest ``writing_architecture`` artifact for this topic.
    If none of the above yield a non-empty string, this primitive REFUSES to
    run rather than letting the LLM invent a paper from topic literature.
    """
    summary, _ = _get_topic_literature_summary(db, topic_id, task_type="section_draft")

    # Fallback 2: topic-level config
    if not contributions.strip():
        contributions = _get_topic_contributions(db, topic_id)

    # Gather claims if available
    conn = db.connect()
    try:
        claims_rows = conn.execute(
            """
            SELECT content FROM topic_paper_notes
            WHERE topic_id = ? AND note_type = 'claim'
            ORDER BY id DESC LIMIT 30
            """,
            (topic_id,),
        ).fetchall()
        # Fallback 3: read from writing_architecture artifact if still empty.
        if not contributions.strip():
            arch_rows = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ?
                  AND artifact_type = 'writing_architecture'
                  AND status = 'active'
                ORDER BY created_at DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchall()
            if arch_rows:
                try:
                    payload = json.loads(arch_rows[0]["payload_json"])
                    parts: list[str] = []
                    title = str(payload.get("paper_title", "")).strip()
                    if title:
                        parts.append(f"Paper title: {title}")
                    narr = str(payload.get("narrative_strategy", "")).strip()
                    if narr:
                        parts.append(f"Narrative strategy: {narr}")
                    for sec in payload.get("sections", []) or []:
                        if not isinstance(sec, dict):
                            continue
                        arg = str(sec.get("argument_strategy", "")).strip()
                        if arg:
                            parts.append(f"- {sec.get('section', '?')}: {arg}")
                    if parts:
                        contributions = "\n".join(parts)
                except (json.JSONDecodeError, TypeError):
                    pass
    finally:
        conn.close()
    claims_text = (
        "\n".join(r["content"] for r in claims_rows if r["content"])
        if claims_rows
        else "(no claims extracted yet)"
    )

    if not contributions.strip():
        raise ValueError(
            "outline_generate requires paper contributions but none were found. "
            "Resolution order checked: (1) `contributions` argument, "
            f"(2) topics.contributions for topic_id={topic_id}, "
            "(3) writing_architecture artifact. "
            "Fix by calling `topic_set_contributions(topic_id, contributions=...)` "
            "or running `writing_architecture` first, or pass contributions explicitly. "
            "Refusing to generate to avoid hallucinating an unrelated paper from topic literature."
        )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("outline_generate"))
    raw = _client_chat(
        client,
        prompts.outline_generate_prompt(summary, claims_text, template, contributions),
    )
    parsed = _parse_json(raw, primitive="outline_generate")

    sections: list[OutlineSectionItem] = []
    for item in parsed.get("sections", []):
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section", "")).strip()
        if not section_id:
            continue
        sections.append(
            OutlineSectionItem(
                section=section_id,
                title=str(item.get("title", section_id)).strip(),
                target_words=_coerce_int(item.get("target_words"), 800),
                key_points=[str(p) for p in (item.get("key_points") or []) if p],
                evidence_ids=[str(e) for e in (item.get("evidence_ids") or []) if e],
            )
        )

    # Fallback to default sections if LLM returned empty
    if not sections:
        sections = [
            OutlineSectionItem(
                section="introduction", title="Introduction", target_words=1500
            ),
            OutlineSectionItem(
                section="related_work", title="Related Work", target_words=2500
            ),
            OutlineSectionItem(section="method", title="Method", target_words=3000),
            OutlineSectionItem(
                section="experiments", title="Experiments", target_words=3500
            ),
            OutlineSectionItem(
                section="discussion", title="Discussion", target_words=900
            ),
            OutlineSectionItem(
                section="conclusion", title="Conclusion", target_words=350
            ),
            OutlineSectionItem(
                section="limitations", title="Limitations", target_words=350
            ),
            OutlineSectionItem(section="appendix", title="Appendix", target_words=3000),
        ]

    total = sum(s.target_words for s in sections)
    return OutlineGenerateOutput(
        title=str(parsed.get("title", "")).strip(),
        abstract_draft=str(parsed.get("abstract_draft", "")).strip(),
        sections=sections,
        total_target_words=total,
        model_used=client.model,
    )


def section_review(
    *,
    db: Database,
    section: str,
    content: str,
    target_words: int = 0,
    paper_context: dict[str, Any] | str | None = None,
    topic_id: int | None = None,
    _model: str | None = None,
    **_: Any,
) -> SectionReviewOutput:
    """Review a paper section: LLM 13-dim scoring + deterministic checks."""
    from .writing_checks import REVIEW_DIMENSIONS as DIM_NAMES
    from .writing_checks import CheckResult, run_all_checks

    frozen_plans = _bound_eag_plans(db, topic_id, _.get("paper_plan"))

    # 1. Run deterministic checks
    check_results = list(run_all_checks(content, section, target_words))
    # Venue polish (goal 1): fold EAG quality_critique failures into the same
    # deterministic channel the section loop already revises on.
    qt = _venue_quality_targets(db, topic_id)
    if qt:
        try:
            from research_harness.primitives.exemplar_impls import _quality_critique

            qcrit = _quality_critique(content, qt, section=section)
            for fail in qcrit.get("failures") or []:
                if not isinstance(fail, dict):
                    continue
                dim = str(fail.get("dimension") or "venue_polish")
                rem = str(fail.get("remediation") or "")
                obs = fail.get("observed")
                check_results.append(
                    CheckResult(
                        check_name=f"venue_polish_{dim}",
                        passed=False,
                        details=f"{dim}: observed={obs}; {rem}".strip("; "),
                        items_found=[str(obs)] if obs is not None else [],
                    )
                )
        except Exception:
            logger.debug("venue polish critique unavailable", exc_info=True)
    # EAG arc conformance: the drafted section must track the exemplar
    # contract's paragraph plan (imitate → verify, same revision channel).
    arc_conf = _arc_conformance_check(db, topic_id, section, content, frozen_plans)
    if arc_conf is not None:
        check_results.append(
            CheckResult(
                check_name="eag_arc_conformance",
                passed=arc_conf[0],
                details=arc_conf[1],
                items_found=[],
            )
        )
    deterministic_checks = [
        DeterministicCheck(
            check_name=c.check_name,
            passed=c.passed,
            details=c.details,
            items_found=c.items_found,
        )
        for c in check_results
    ]

    if isinstance(paper_context, dict):
        rendered_context = render_paper_context(
            PaperContext.from_dict(paper_context), section
        )
    else:
        rendered_context = paper_context or ""

    # 2. LLM scoring
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_review"))
    raw = _client_chat(
        client,
        prompts.section_review_prompt(
            section, content, target_words, paper_context=rendered_context
        ),
    )
    parsed = _parse_json(raw, primitive="section_review", context=section)

    # Parse dimensions from LLM response
    dim_map: dict[str, tuple[float, str]] = {}
    for item in parsed.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        dim_name = str(item.get("dimension", "")).strip()
        if dim_name:
            dim_map[dim_name] = (
                _coerce_float(item.get("score"), 0.0),
                str(item.get("comment", "")).strip(),
            )

    # Build dimension list — use LLM scores where available, 0.0 otherwise
    dimensions: list[ReviewDimension] = []
    for dim_name in DIM_NAMES:
        score, comment = dim_map.get(dim_name, (0.0, ""))
        dimensions.append(
            ReviewDimension(dimension=dim_name, score=score, comment=comment)
        )

    # Calculate overall score
    overall = _coerce_float(parsed.get("overall_score"), 0.0)
    if overall == 0.0 and dimensions:
        scores = [d.score for d in dimensions if d.score > 0]
        overall = sum(scores) / len(scores) if scores else 0.0

    # Suggestions from LLM + deterministic failures
    suggestions: list[str] = [str(s) for s in (parsed.get("suggestions") or []) if s]
    failed_checks = [c for c in check_results if not c.passed]
    for c in failed_checks:
        suggestions.append(f"[{c.check_name}] {c.details}")

    needs_revision = overall < 0.6 or len(failed_checks) > 0

    return SectionReviewOutput(
        section=section,
        overall_score=round(overall, 3),
        dimensions=dimensions,
        deterministic_checks=deterministic_checks,
        suggestions=suggestions,
        needs_revision=needs_revision,
        model_used=client.model,
    )


def adversarial_section_review(
    *,
    db: Database,
    section: str,
    content: str,
    target_words: int = 0,
    _model: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """v2 Step 5.2: adversarial second-pass review with skeptical persona.

    Runs AFTER section_review() to catch weaknesses the cooperative reviewer
    misses. Returns structured weaknesses with categories + evidence. The
    caller (orchestrator) is responsible for merging these with the positive
    review and auto-opening review_issues rows for severity=critical items.
    """
    # Use a different tier/model if available to avoid same-model bias.
    client = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("section_review", "medium"),
        task_name="adversarial_section_review",
    )
    raw = _client_chat(
        client,
        prompts.adversarial_section_review_prompt(section, content, target_words),
    )
    parsed = _parse_json(raw, primitive="adversarial_section_review", context=section)

    weaknesses: list[dict[str, Any]] = []
    for item in parsed.get("weaknesses", []) or []:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category", "")).strip().lower()
        desc = str(item.get("description", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        sev = str(item.get("severity", "minor")).strip().lower()
        if sev not in {"critical", "major", "minor"}:
            sev = "minor"
        if not desc or not evidence:
            # Enforce the prompt contract: no evidence -> drop.
            continue
        weaknesses.append(
            {
                "category": cat or "general",
                "description": desc,
                "evidence": evidence,
                "severity": sev,
            }
        )

    return {
        "section": section,
        "weaknesses": weaknesses,
        "critical_count": sum(1 for w in weaknesses if w["severity"] == "critical"),
        "major_count": sum(1 for w in weaknesses if w["severity"] == "major"),
        "minor_count": sum(1 for w in weaknesses if w["severity"] == "minor"),
        "model_used": client.model,
    }


def _strict_manuscript_json(raw: str, *, limit: int) -> dict[str, Any]:
    """Require complete JSON for manuscript operations that cannot salvage text."""
    # Two different failures shared one sentence, and neither said by how much: a
    # writing_architecture attempt on the A0114 line died here three times before the
    # measurement that decides whether the ceiling or the response is wrong.
    if not isinstance(raw, str):
        raise ValueError(f"manuscript response is {type(raw).__name__}, not text")
    if len(raw) > limit:
        raise ValueError(
            f"manuscript response is {len(raw)} characters, above its JSON size limit of {limit}"
        )

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("manuscript JSON contains duplicate keys")
        return dict(pairs)

    def reject_constant(value: str) -> Any:
        raise ValueError("manuscript JSON must contain finite values")

    try:
        parsed = json.loads(
            raw, object_pairs_hook=unique_object, parse_constant=reject_constant
        )
    except (ValueError, RecursionError) as exc:
        raise ValueError("manuscript response must be complete strict JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("manuscript response must be a JSON object")
    return parsed


def _full_manuscript_edits(content: str, parsed: dict[str, Any]) -> str:
    if not {"edits", "changes_made"} <= set(parsed) or set(parsed) - {
        "edits",
        "changes_made",
        "repair_deferred",
    }:
        raise ValueError(
            "full manuscript response requires edits, changes_made and optional repair_deferred"
        )
    edits, changes = parsed["edits"], parsed["changes_made"]
    deferred = parsed.get("repair_deferred", [])
    if (
        not isinstance(deferred, list)
        or len(deferred) > 32
        or any(
            not isinstance(item, dict)
            or set(item) != {"finding_id", "reason"}
            or any(
                not isinstance(text, str) or not text.strip() for text in item.values()
            )
            for item in deferred
        )
    ):
        raise ValueError("full manuscript deferred repairs need finding_id and reason")
    if not isinstance(edits, list) or len(edits) > 32 or (not edits and not deferred):
        raise ValueError(
            "full manuscript requires exact edits or explicitly deferred findings"
        )
    if (
        not isinstance(changes, list)
        or (edits and not changes)
        or (not edits and changes)
        or any(not isinstance(change, str) or not change.strip() for change in changes)
    ):
        raise ValueError("full manuscript changes_made must be nonempty strings")
    spans: list[tuple[int, int, str]] = []
    edit_size = 0
    for edit in edits:
        if (
            not isinstance(edit, dict)
            or not {"old_text", "new_text"} <= set(edit)
            or set(edit) - {"old_text", "new_text", "finding_id"}
        ):
            raise ValueError(
                "full manuscript edit requires old_text, new_text and optional finding_id"
            )
        if "finding_id" in edit and (
            not isinstance(edit["finding_id"], str) or not edit["finding_id"].strip()
        ):
            raise ValueError("full manuscript edit finding_id must be nonempty text")
        old, new = edit["old_text"], edit["new_text"]
        if not isinstance(old, str) or not old.strip() or not isinstance(new, str):
            raise ValueError("full manuscript edit text is invalid")
        start = content.find(old)
        if start < 0 or content.find(old, start + 1) >= 0 or old == new:
            raise ValueError(
                "full manuscript edit must uniquely match and change original text"
            )
        edit_size += len(old) + len(new)
        spans.append((start, start + len(old), new))
    if edit_size > 16000:
        raise ValueError("full manuscript exact edits exceed 16000 characters")
    ordered = sorted(spans)
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("full manuscript exact edits overlap")
    revised = content
    for start, end, replacement in reversed(ordered):
        revised = revised[:start] + replacement + revised[end:]
    if len(revised) > 250000:
        raise ValueError("revised full manuscript exceeds 250000 characters")
    return revised


def _full_manuscript_damage(original: str, revised: str) -> list[str]:
    from .writing_checks import _NUMBER_RE, check_manuscript_math

    damage = check_manuscript_math(original, revised)
    document_start = r"\begin{document}"
    if (
        document_start in original
        and original.partition(document_start)[0]
        != revised.partition(document_start)[0]
    ):
        damage.append("manuscript preamble changed")
    protected_commands = re.compile(
        r"\\(?:includegraphics\*?|input|include|bibliography|bibliographystyle|"
        r"addbibresource|label|(?:[a-zA-Z]*cite[a-zA-Z]*|[a-zA-Z]*ref)\*?|begin|end)"
        r"(?:\s*\[[^\]]*\])*\s*\{[^{}]*\}|\\appendix\b"
    )
    if collections.Counter(protected_commands.findall(original)) != collections.Counter(
        protected_commands.findall(revised)
    ):
        damage.append("manuscript assets, citations, labels or structure changed")
    if collections.Counter(_NUMBER_RE.findall(original)) != collections.Counter(
        _NUMBER_RE.findall(revised)
    ):
        damage.append("manuscript number inventory changed")
    return damage


def section_revise(
    *,
    db: Database,
    section: str,
    content: str,
    review_feedback: str,
    target_words: int = 0,
    topic_id: int | None = None,
    paper_plan: dict[str, Any] | None = None,
    paper_context: dict[str, Any] | str | None = None,
    evidence_text: str = "",
    full_manuscript: bool = False,
    budget_authorization: dict[str, Any] | BudgetAuthorization | None = None,
    _model: str | None = None,
    **_: Any,
) -> SectionReviseOutput:
    """Revise a paper section based on review feedback using LLM."""
    from .writing_checks import revision_damage, structural_revision_directives

    frozen_plans = _bound_eag_plans(db, topic_id, paper_plan)

    if not isinstance(full_manuscript, bool):
        raise ValueError("full_manuscript must be a boolean")
    if full_manuscript:
        for name, value, limit in (
            ("content", content, 250000),
            ("review_feedback", review_feedback, 100000),
            ("evidence_text", evidence_text, 100000),
        ):
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(
                    f"full manuscript {name} must be text of at most {limit} characters"
                )
        if not content.strip():
            raise ValueError("full manuscript content must not be empty")

    plan_for_domain = paper_plan or (
        _active_paper_plan(db, topic_id) if topic_id is not None else {}
    )
    domain_key = resolve_domain_key(plan_for_domain)
    if isinstance(paper_context, dict):
        rendered_context = render_paper_context(
            PaperContext.from_dict(paper_context), section
        )
    else:
        rendered_context = paper_context or ""
    revision_tier = _PRIMITIVE_TIERS.get("section_revise")
    checkpoint_context = None
    replay = None
    prepared_client = False
    client = None
    if budget_authorization is None:
        client = _get_client(_model, tier=revision_tier)
    else:
        checkpoint_context = getattr(_accounted_provider_local, "value", None)
        if not isinstance(checkpoint_context, dict):
            raise AccountedAttemptNotStarted(
                "accounted revision requires an RH durable provider checkpoint"
            )
        replay = checkpoint_context.get("replay")
        client = checkpoint_context.get("client")
        prepared_client = client is not None
        if replay is None and client is None:
            client = _get_client(_model, tier=revision_tier, accounted=True)
            prepared_client = True
    revision_prompt = prompts.section_revise_prompt(
        section,
        content,
        review_feedback,
        target_words,
        domain_key=domain_key,
        paper_context=rendered_context,
        evidence_text=evidence_text,
        # Restate the EAG target contract so review-driven revisions stay
        # within the exemplar structure instead of drifting generic.
        section_guidance=eag_revision_guidance(db, topic_id, section, frozen_plans),
        # Located structural defects, so the reviser fixes arrangement
        # problems it would otherwise have to be told about in prose.
        structural_directives=structural_revision_directives(content, section),
        full_manuscript=full_manuscript,
    )
    usage_receipt = None
    if budget_authorization is None:
        raw = _client_chat(client, revision_prompt)
    else:
        authorization = (
            budget_authorization
            if isinstance(budget_authorization, BudgetAuthorization)
            else BudgetAuthorization(**budget_authorization)
        )
        completed = checkpoint_context.get("completed")
        if replay is None:
            if not callable(completed):
                raise AccountedAttemptNotStarted(
                    "accounted revision requires an RH durable provider checkpoint"
                )
            raw, usage_receipt = client.chat_accounted(
                revision_prompt,
                authorization=authorization,
                **({} if prepared_client else {"tier": revision_tier}),
            )
        else:
            if not isinstance(replay, dict):
                raise ValueError("accounted provider replay is invalid")
            raw = replay.get("text")
            receipt_value = replay.get("receipt")
            if not isinstance(raw, str) or not isinstance(receipt_value, dict):
                raise ValueError("accounted provider replay is invalid")
            usage_receipt = ProviderUsageReceipt(**receipt_value)
        if (
            usage_receipt.attempt_id != authorization.attempt_id
            or usage_receipt.request_sha256 != authorization.request_sha256
            or usage_receipt.output_sha256 != hashlib.sha256(raw.encode()).hexdigest()
        ):
            raise ValueError("accounted provider replay differs from its authorization")
        if replay is None:
            completed(raw, usage_receipt)
        if not usage_receipt.completion_known:
            raise RuntimeError("accounted provider completion is unknown")
        if usage_receipt.cost_usd is None:
            raise RuntimeError("accounted provider cost is unknown")
        if usage_receipt.cost_usd > authorization.max_cost_usd:
            raise RuntimeError("accounted provider actual cost exceeds authorization")

    def accounted(output: SectionReviseOutput):
        return (
            AccountedPrimitiveOutput(output, (usage_receipt,))
            if usage_receipt is not None
            else output
        )

    if full_manuscript:
        parsed = _strict_manuscript_json(raw, limit=24000)
        revised = _full_manuscript_edits(content, parsed)
    else:
        parsed = _parse_json(raw, primitive="section_revise", context=section)
        if usage_receipt is not None and (
            not isinstance(parsed, dict)
            or not isinstance(parsed.get("revised_content"), str)
            or not parsed["revised_content"].strip()
        ):
            raise ValueError("accounted section revision returned invalid JSON")
        revised = str(parsed.get("revised_content") or raw[: len(content) * 2]).strip()
    changes = [str(c) for c in (parsed.get("changes_made") or []) if c]
    if not changes and not full_manuscript:
        changes = ["LLM revision applied"]

    # The model proposes; this decides. A revision that drops a label, a
    # citation, a measured number or a formal environment is rejected outright
    # rather than returned with a warning: downstream callers write the
    # returned text back to disk, so a warning nobody reads is not a control.
    damage = revision_damage(content, revised)
    if full_manuscript:
        damage = [*damage, *_full_manuscript_damage(content, revised)]
    if damage:
        reason = "; ".join(damage[:4])
        logger.warning(
            "section_revise reverted for %s — revision damaged protected material: %s",
            section,
            reason,
        )
        return accounted(
            SectionReviseOutput(
                section=section,
                revised_content=content,
                changes_made=[
                    f"reverted: revision damaged protected material ({reason})"
                ],
                word_count=len(content.split()),
                model_used=usage_receipt.model if usage_receipt else client.model,
                reverted=True,
                revert_reason=reason,
            )
        )

    word_count = _coerce_int(parsed.get("word_count"), len(revised.split()))

    return accounted(
        SectionReviseOutput(
            section=section,
            revised_content=revised,
            changes_made=changes,
            word_count=word_count,
            model_used=usage_receipt.model if usage_receipt else client.model,
            manuscript_edits=parsed["edits"] if full_manuscript else [],
            repair_deferred=parsed.get("repair_deferred", [])
            if full_manuscript
            else [],
        )
    )


def consistency_check(
    *,
    db: Database,
    topic_id: int,
    sections: list[str] | None = None,
    refresh_context: bool = False,
    paper_plan: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> ConsistencyCheckOutput:
    if refresh_context:
        from .compiled_summary import invalidate_topic_summary

        invalidate_topic_summary(db, topic_id)

    requested_sections = sections or []
    # Fail fast on an empty manuscript (BUG-008): running with no sections used
    # to return zero issues, which the gate read as "consistency passed". An
    # absent manuscript is not a clean check — surface it as a blocking issue so
    # execution-success is not mistaken for content-pass.
    if not any(str(s).strip() for s in requested_sections):
        return ConsistencyCheckOutput(
            issues=[
                ConsistencyIssue(
                    issue_type="missing_manuscript",
                    severity="high",
                    location="manuscript",
                    description=(
                        "consistency_check received no manuscript sections; there "
                        "is nothing to check. Do not treat this as a passing "
                        "consistency result."
                    ),
                    suggestion="Supply the drafted section texts via `sections`.",
                    source="manuscript",
                )
            ],
            sections_checked=[],
        )

    summary, _ = _get_topic_literature_summary(
        db, topic_id, task_type="consistency_check"
    )
    sections_label = (
        "\n\n".join(requested_sections)
        if requested_sections
        else f"(no manuscript sections supplied; topic {topic_id})"
    )

    # Promise-fulfillment context: the plan's committed claims, promises, and
    # terminology become explicit verification tasks in the prompt.
    plan_context = ""
    try:
        plan = paper_plan or _active_paper_plan(db, topic_id)
        ctx = build_paper_context(db, topic_id, paper_plan=plan)
        plan_context = render_paper_context_full(ctx)
    except Exception:
        logger.debug("consistency_check plan context build failed", exc_info=True)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("consistency_check"))
    raw = _client_chat(
        client,
        prompts.consistency_check_prompt(
            sections_label,
            literature_context=summary,
            paper_plan_context=plan_context,
        ),
    )
    parsed = _parse_json(raw, primitive="consistency_check")

    issues: list[ConsistencyIssue] = []
    for item in parsed.get("issues", []):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        source = str(item.get("source", "")).strip().lower()
        if source not in {"manuscript", "literature_context"}:
            source = "manuscript"
        issues.append(
            ConsistencyIssue(
                issue_type=str(item.get("issue_type", "unknown")).strip() or "unknown",
                severity=str(item.get("severity", "medium")).strip() or "medium",
                location=str(item.get("location", "")).strip(),
                description=description,
                suggestion=str(item.get("suggestion", "")).strip(),
                source=source,
            )
        )

    return ConsistencyCheckOutput(
        issues=issues,
        sections_checked=requested_sections,
    )


def _affiliations_from_deep_read_pass1(
    payload: dict[str, Any],
) -> tuple[list[str], str]:
    """Collect affiliation names and evidence summary from deep_read pass1 JSON."""
    names: list[str] = []
    evidence_lines: list[str] = []
    for item in payload.get("author_affiliations") or []:
        if isinstance(item, dict):
            institution = str(item.get("institution") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            source = str(item.get("source") or "").strip()
            if institution:
                names.append(institution)
            if institution and evidence:
                prefix = f"[{source}] " if source else ""
                evidence_lines.append(f"{prefix}{institution}: {evidence}")
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    for item in payload.get("affiliation_summary") or []:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names, "\n".join(evidence_lines)


def deep_read(
    *,
    db: Database,
    paper_id: int,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> DeepReadingOutput:
    """Two-pass deep reading: extraction (medium) then critical analysis (heavy)."""
    title, text = _get_paper_text(db, paper_id)
    if not text:
        # Deliberate short-circuit: no full text available. Record a named
        # local marker rather than the ambiguous literal "none" so the
        # route-audit assertion can distinguish "not yet run" from
        # "deliberately skipped because the paper has only an abstract".
        return DeepReadingOutput(
            paper_id=paper_id,
            note=DeepReadingNote(),
            model_used="local:abstract_only",
            confidence=0.0,
        )

    from research_harness.primitives.deepread_impls import (
        enrich_affiliations as _enrich_affiliations,
        persist_paper_affiliations,
    )

    _enrich_affiliations(db=db, paper_id=paper_id)

    # --- Pass 1: deep extraction (medium tier) ---
    client1 = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("deep_read_pass1"),
        task_name="deep_read_pass1",
    )
    raw1 = _client_chat(client1, prompts.deep_read_pass1_prompt(title, text, focus))
    p1 = _parse_json(raw1, primitive="deep_read", context="pass1")
    pass1_model = _describe_client(client1)
    llm_affiliations, affiliation_evidence = _affiliations_from_deep_read_pass1(p1)
    author_affiliations = persist_paper_affiliations(db, paper_id, llm_affiliations)

    # --- Pass 2: critical analysis (heavy tier) ---
    topic_summary, _ = _get_topic_literature_summary(
        db, topic_id, task_type="deep_read"
    )
    pass1_json = json.dumps(p1, ensure_ascii=False)

    client2 = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("deep_read_pass2"),
        task_name="deep_read_pass2",
    )
    raw2 = _client_chat(
        client2,
        prompts.deep_read_pass2_prompt(title, pass1_json, text, topic_summary, focus),
    )
    p2 = _parse_json(raw2, primitive="deep_read", context="pass2")
    pass2_model = _describe_client(client2)

    # Parse industrial feasibility
    feas_raw = p2.get("industrial_feasibility", {})
    if not isinstance(feas_raw, dict):
        feas_raw = {}
    feasibility = IndustrialFeasibility(
        viability=str(feas_raw.get("viability", "")).strip(),
        latency_constraints=str(feas_raw.get("latency_constraints", "")).strip(),
        data_requirements=str(feas_raw.get("data_requirements", "")).strip(),
        engineering_challenges=[
            str(c) for c in (feas_raw.get("engineering_challenges") or []) if c
        ],
        deployment_prerequisites=[
            str(p) for p in (feas_raw.get("deployment_prerequisites") or []) if p
        ],
    )

    # Parse cross-paper links
    links: list[CrossPaperLink] = []
    for item in p2.get("cross_paper_links", []):
        if not isinstance(item, dict):
            continue
        links.append(
            CrossPaperLink(
                target_paper_id=_coerce_int(item.get("target_paper_id"), 0),
                relation_type=str(item.get("relation_type", "")).strip(),
                evidence=str(item.get("evidence", "")).strip(),
            )
        )

    note = DeepReadingNote(
        algorithm_walkthrough=str(p1.get("algorithm_walkthrough", "")).strip(),
        limitation_analysis=str(p1.get("limitation_analysis", "")).strip(),
        reproducibility_assessment=str(
            p1.get("reproducibility_assessment", "")
        ).strip(),
        critical_assessment=str(p2.get("critical_assessment", "")).strip(),
        industrial_feasibility=feasibility,
        research_implications=[
            str(r) for r in (p2.get("research_implications") or []) if r
        ],
        cross_paper_links=links,
        author_affiliations=author_affiliations,
        affiliation_evidence=affiliation_evidence,
    )

    # --- Side effect: store in paper_annotations ---
    from dataclasses import asdict

    from research_harness.storage.models import PaperAnnotation

    conn = db.connect()
    try:
        from research_harness.core.paper_pool import PaperPool

        pool = PaperPool(conn)
        pool.upsert_annotation(
            PaperAnnotation(
                paper_id=paper_id,
                section="deep_reading",
                content=json.dumps(asdict(note), ensure_ascii=False),
                source=f"{pass1_model}+{pass2_model}",
                confidence=0.85,
                extractor_version="v1",
            )
        )
        conn.execute("UPDATE papers SET deep_read = 1 WHERE id = ?", (paper_id,))
        conn.commit()
    finally:
        conn.close()

    return DeepReadingOutput(
        paper_id=paper_id,
        note=note,
        model_used=f"{pass1_model}+{pass2_model}",
        pass1_model=pass1_model,
        pass2_model=pass2_model,
        confidence=0.85,
    )


def code_generate(
    *,
    db: Database,
    topic_id: int,
    study_spec: str,
    iteration: int = 0,
    previous_code: str = "",
    previous_metrics: dict[str, Any] | None = None,
    feedback: str = "",
    _model: str | None = None,
    **_: Any,
) -> CodeGenerationOutput:
    """Generate experiment code from study spec and topic context."""
    summary, _ = _get_topic_literature_summary(db, topic_id, task_type="section_draft")
    metrics_str = json.dumps(previous_metrics or {})

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.code_generate_prompt(
            study_spec=study_spec,
            topic_summary=summary,
            iteration=iteration,
            previous_code=previous_code,
            previous_metrics=metrics_str,
            feedback=feedback,
        ),
    )
    parsed = _parse_json(raw, primitive="code_generate", context=f"iter{iteration}")

    files = parsed.get("files", {})
    if not isinstance(files, dict):
        files = {}
    # Fallback: if LLM returned code directly without JSON wrapper
    if not files and raw.strip():
        files = {"main.py": raw.strip()}

    return CodeGenerationOutput(
        files=files,
        entry_point=str(parsed.get("entry_point", "main.py")),
        description=str(parsed.get("description", "")),
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Phase 2: Cross-paper analysis LLM primitives
# ---------------------------------------------------------------------------


def method_taxonomy(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    **_: Any,
) -> "MethodTaxonomyOutput":
    """Build method taxonomy from compiled summaries via LLM."""
    from research_harness.primitives.types import MethodTaxonomyOutput, TaxonomyNode
    from .compiled_summary import ensure_compiled_summary, format_compiled_for_context

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY COALESCE(p.citation_count, 0) DESC
            LIMIT 50
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return MethodTaxonomyOutput()

    # Build context from compiled summaries
    entries: list[str] = []
    for row in rows:
        pid = int(row["id"])
        compiled = ensure_compiled_summary(db, pid)
        ctx = format_compiled_for_context(compiled)
        header = f"[{pid}] {row['title'] or f'Paper #{pid}'}"
        if row["year"]:
            header += f" ({row['year']})"
        entries.append(f"{header}: {ctx}" if ctx else header)

    papers_text = "\n".join(entries)
    client = _get_client(tier="medium", task_name="method_taxonomy")
    prompt = prompts.method_taxonomy_prompt(papers_text, focus)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="method_taxonomy")
    nodes_raw = parsed.get("nodes", [])

    # Store to DB
    conn = db.connect()
    try:
        result_nodes: list[TaxonomyNode] = []
        node_name_to_id: dict[str, int] = {}

        # First pass: create all nodes
        for n in nodes_raw:
            name = n.get("name", "")
            if not name:
                continue
            aliases = n.get("aliases", [])
            desc = n.get("description", "")

            import json as _json

            conn.execute(
                """
                INSERT OR REPLACE INTO taxonomy_nodes (topic_id, name, description, aliases)
                VALUES (?, ?, ?, ?)
                """,
                (topic_id, name, desc, _json.dumps(aliases, ensure_ascii=False)),
            )
            nid_row = conn.execute(
                "SELECT id FROM taxonomy_nodes WHERE topic_id = ? AND name = ?",
                (topic_id, name),
            ).fetchone()
            nid = nid_row["id"] if nid_row else 0
            node_name_to_id[name] = nid

        # Second pass: set parent_id
        for n in nodes_raw:
            name = n.get("name", "")
            parent = n.get("parent")
            if parent and parent in node_name_to_id and name in node_name_to_id:
                conn.execute(
                    "UPDATE taxonomy_nodes SET parent_id = ? WHERE id = ?",
                    (node_name_to_id[parent], node_name_to_id[name]),
                )

        # Third pass: create assignments
        assignments = 0
        for n in nodes_raw:
            name = n.get("name", "")
            if name not in node_name_to_id:
                continue
            nid = node_name_to_id[name]
            for pid in n.get("paper_ids", []):
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO taxonomy_assignments (paper_id, node_id, confidence) VALUES (?, ?, 0.7)",
                        (int(pid), nid),
                    )
                    assignments += 1
                except Exception as exc:
                    logger.debug(
                        "Taxonomy assignment failed for paper %s → node %s: %s",
                        pid,
                        nid,
                        exc,
                    )

        conn.commit()

        # Build output
        for n in nodes_raw:
            name = n.get("name", "")
            if name not in node_name_to_id:
                continue
            parent_name = n.get("parent")
            result_nodes.append(
                TaxonomyNode(
                    node_id=node_name_to_id[name],
                    name=name,
                    parent_id=node_name_to_id.get(parent_name) if parent_name else None,
                    description=n.get("description", ""),
                    aliases=n.get("aliases", []),
                    paper_count=len(n.get("paper_ids", [])),
                )
            )
    finally:
        conn.close()

    return MethodTaxonomyOutput(
        nodes=result_nodes,
        assignments_count=assignments,
        papers_processed=len(rows),
    )


def evidence_matrix(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    paper_ids: list[int] | None = None,
    limit: int = 50,
    **_: Any,
) -> "EvidenceMatrixOutput":
    """Build evidence matrix: query existing claims, normalize via LLM, store."""
    from research_harness.primitives.types import EvidenceMatrixOutput, NormalizedClaim

    conn = db.connect()
    try:
        # Step 1: Gather claims from compiled summaries
        scoped_ids: list[int] = []
        for raw_pid in paper_ids or []:
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                continue
            if pid > 0:
                scoped_ids.append(pid)
        if scoped_ids:
            placeholders = ",".join("?" for _ in scoped_ids)
            rows = conn.execute(
                f"""
                SELECT p.id, p.title, p.compiled_summary FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                  AND p.id IN ({placeholders})
                  AND p.compiled_summary IS NOT NULL AND p.compiled_summary != ''
                ORDER BY COALESCE(p.citation_count, 0) DESC, p.id
                """,
                (topic_id, *scoped_ids),
            ).fetchall()
        else:
            safe_limit = max(1, min(int(limit or 50), 200))
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.compiled_summary FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                  AND p.compiled_summary IS NOT NULL AND p.compiled_summary != ''
                ORDER BY COALESCE(p.citation_count, 0) DESC, p.id
                LIMIT ?
                """,
                (topic_id, safe_limit),
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        return EvidenceMatrixOutput()

    import json as _json

    # Build claims context from compiled summaries
    claim_entries: list[str] = []
    for row in rows:
        pid = int(row["id"])
        try:
            compiled = _json.loads(row["compiled_summary"])
        except (TypeError, _json.JSONDecodeError):
            continue
        claims = compiled.get("claims", [])
        metrics = compiled.get("metrics", [])

        paper_claims: list[str] = []
        for c in claims:
            if isinstance(c, dict):
                paper_claims.append(c.get("claim", str(c)))
            elif isinstance(c, str):
                paper_claims.append(c)
        for m in metrics:
            if isinstance(m, dict):
                paper_claims.append(
                    f"{m.get('metric', '?')} on {m.get('dataset', '?')}: {m.get('value', '?')}"
                )

        if paper_claims:
            claim_entries.append(
                f"[Paper {pid}] {row['title'] or f'Paper #{pid}'}\n"
                + "\n".join(f"  - {c}" for c in paper_claims[:10])
            )

    if not claim_entries:
        return EvidenceMatrixOutput(papers_processed=len(rows))

    claims_text = "\n\n".join(claim_entries)
    client = _get_client(tier="medium", task_name="evidence_matrix")
    prompt = prompts.evidence_matrix_prompt(claims_text, focus)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="evidence_matrix")
    norm_claims_raw = parsed.get("normalized_claims", [])

    # Step 2: Store in DB
    conn = db.connect()
    result_claims: list[NormalizedClaim] = []
    methods_set: set[str] = set()
    datasets_set: set[str] = set()

    try:
        for nc in norm_claims_raw:
            paper_id = nc.get("paper_id", 0)
            claim_text = nc.get("claim_text", "")
            method = nc.get("method", "")
            dataset = nc.get("dataset", "")
            metric = nc.get("metric", "")
            task = nc.get("task", "")
            value = str(nc.get("value", ""))
            direction = nc.get("direction", "qualitative")
            confidence = float(nc.get("confidence", 0.5))

            if method:
                methods_set.add(method)
            if dataset:
                datasets_set.add(dataset)

            conn.execute(
                """
                INSERT INTO normalized_claims
                (topic_id, paper_id, claim_text, method, dataset, metric, task, value, direction, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    paper_id,
                    claim_text,
                    method,
                    dataset,
                    metric,
                    task,
                    value,
                    direction,
                    confidence,
                ),
            )
            cid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            cid = cid_row["id"] if cid_row else 0

            result_claims.append(
                NormalizedClaim(
                    claim_id=cid,
                    paper_id=paper_id,
                    claim_text=claim_text,
                    method=method,
                    dataset=dataset,
                    metric=metric,
                    task=task,
                    value=value,
                    direction=direction,
                    confidence=confidence,
                )
            )

        conn.commit()
    finally:
        conn.close()

    return EvidenceMatrixOutput(
        claims=result_claims,
        methods=sorted(methods_set),
        datasets=sorted(datasets_set),
        papers_processed=len(rows),
    )


def contradiction_detect(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> "ContradictionDetectOutput":
    """Detect contradictions between normalized claims."""
    from research_harness.primitives.types import (
        ContradictionCandidate,
        ContradictionDetectOutput,
        NormalizedClaim,
    )

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, paper_id, claim_text, method, dataset, metric, task, value, direction, confidence
            FROM normalized_claims WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return ContradictionDetectOutput(claims_analyzed=len(rows))

    # Build claims context
    claims_map: dict[int, NormalizedClaim] = {}
    lines: list[str] = []
    for r in rows:
        nc = NormalizedClaim(
            claim_id=int(r["id"]),
            paper_id=int(r["paper_id"]),
            claim_text=r["claim_text"],
            method=r["method"],
            dataset=r["dataset"],
            metric=r["metric"],
            task=r["task"],
            value=r["value"],
            direction=r["direction"],
            confidence=float(r["confidence"]),
        )
        claims_map[nc.claim_id] = nc
        lines.append(
            f"[{nc.claim_id}] paper={nc.paper_id} method={nc.method} "
            f"dataset={nc.dataset} metric={nc.metric} task={nc.task} "
            f"value={nc.value} direction={nc.direction}"
        )

    claims_text = "\n".join(lines)
    client = _get_client(tier="medium", task_name="contradiction_detect")
    prompt = prompts.contradiction_detect_prompt(claims_text)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="contradiction_detect")
    contras_raw = parsed.get("contradictions", [])

    # Store in DB
    conn = db.connect()
    results: list[ContradictionCandidate] = []
    try:
        for c in contras_raw:
            a_id = c.get("claim_a_id", 0)
            b_id = c.get("claim_b_id", 0)
            if a_id not in claims_map or b_id not in claims_map:
                continue

            conn.execute(
                """
                INSERT INTO contradictions
                (topic_id, claim_a_id, claim_b_id, same_task, same_dataset, same_metric, confidence, conflict_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    a_id,
                    b_id,
                    int(c.get("same_task", False)),
                    int(c.get("same_dataset", False)),
                    int(c.get("same_metric", False)),
                    float(c.get("confidence", 0.5)),
                    c.get("conflict_reason", ""),
                ),
            )
            cid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()

            results.append(
                ContradictionCandidate(
                    contradiction_id=cid_row["id"] if cid_row else 0,
                    claim_a=claims_map.get(a_id),
                    claim_b=claims_map.get(b_id),
                    same_task=bool(c.get("same_task", False)),
                    same_dataset=bool(c.get("same_dataset", False)),
                    same_metric=bool(c.get("same_metric", False)),
                    confidence=float(c.get("confidence", 0.5)),
                    conflict_reason=c.get("conflict_reason", ""),
                )
            )

        conn.commit()
    finally:
        conn.close()

    return ContradictionDetectOutput(
        contradictions=results,
        claims_analyzed=len(rows),
    )


# ---------------------------------------------------------------------------
# Phase 3: Quantitative extraction LLM primitives
# ---------------------------------------------------------------------------


def table_extract(
    *,
    db: Database,
    paper_id: int,
    **_: Any,
) -> "TableExtractOutput":
    """Extract structured tables from a paper via LLM."""
    from research_harness.primitives.types import ExtractedTable, TableExtractOutput

    title, text = _get_paper_text(db, paper_id)
    if not text:
        return TableExtractOutput(paper_id=paper_id)

    client = _get_client(tier="medium", task_name="table_extract")
    prompt = prompts.table_extract_prompt(title, text)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="table_extract", context=title)
    tables_raw = parsed.get("tables", [])

    import json as _json

    conn = db.connect()
    result_tables: list[ExtractedTable] = []
    try:
        for t in tables_raw:
            headers = t.get("headers", [])
            rows = t.get("rows", [])
            table_num = t.get("table_number", 0)
            caption = t.get("caption", "")
            source_page = t.get("source_page")

            conn.execute(
                """
                INSERT INTO extracted_tables
                (paper_id, table_number, caption, headers, rows, source_page, confidence)
                VALUES (?, ?, ?, ?, ?, ?, 0.7)
                """,
                (
                    paper_id,
                    table_num,
                    caption,
                    _json.dumps(headers, ensure_ascii=False),
                    _json.dumps(rows, ensure_ascii=False),
                    source_page,
                ),
            )
            tid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            tid = tid_row["id"] if tid_row else 0

            result_tables.append(
                ExtractedTable(
                    table_id=tid,
                    paper_id=paper_id,
                    table_number=table_num,
                    caption=caption,
                    headers=headers,
                    rows=rows,
                    source_page=source_page,
                    confidence=0.7,
                )
            )
        conn.commit()
    finally:
        conn.close()

    return TableExtractOutput(tables=result_tables, paper_id=paper_id)


def figure_interpret(
    *,
    db: Database,
    paper_id: int,
    **_: Any,
) -> "FigureInterpretOutput":
    """Interpret figures from a paper via LLM."""
    from research_harness.primitives.types import ExtractedFigure, FigureInterpretOutput

    title, text = _get_paper_text(db, paper_id)
    if not text:
        return FigureInterpretOutput(paper_id=paper_id)

    client = _get_client(tier="medium", task_name="figure_interpret")
    prompt = prompts.figure_interpret_prompt(title, text)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="figure_interpret", context=title)
    figures_raw = parsed.get("figures", [])

    import json as _json

    conn = db.connect()
    result_figures: list[ExtractedFigure] = []
    try:
        for f in figures_raw:
            fig_num = f.get("figure_number", 0)
            caption = f.get("caption", "")
            interp = f.get("interpretation", "")
            key_pts = f.get("key_data_points", [])
            fig_type = f.get("figure_type", "")
            source_page = f.get("source_page")

            conn.execute(
                """
                INSERT INTO extracted_figures
                (paper_id, figure_number, caption, interpretation, key_data_points, figure_type, source_page)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    fig_num,
                    caption,
                    interp,
                    _json.dumps(key_pts, ensure_ascii=False),
                    fig_type,
                    source_page,
                ),
            )
            fid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            fid = fid_row["id"] if fid_row else 0

            result_figures.append(
                ExtractedFigure(
                    figure_id=fid,
                    paper_id=paper_id,
                    figure_number=fig_num,
                    caption=caption,
                    interpretation=interp,
                    key_data_points=key_pts,
                    figure_type=fig_type,
                    source_page=source_page,
                )
            )
        conn.commit()
    finally:
        conn.close()

    return FigureInterpretOutput(figures=result_figures, paper_id=paper_id)


# ---------------------------------------------------------------------------
# Phase 4: Workflow primitives
# ---------------------------------------------------------------------------


def rebuttal_format(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> "RebuttalFormatOutput":
    """Format a rebuttal letter from review issues and author responses."""
    from research_harness.primitives.types import RebuttalFormatOutput

    conn = db.connect()
    try:
        # Gather review issues
        issues = conn.execute(
            """
            SELECT ri.severity, ri.category, ri.summary, ri.details, ri.recommended_action
            FROM review_issues ri
            WHERE ri.topic_id = ? AND ri.status != 'resolved'
            ORDER BY
                CASE ri.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                ri.created_at
            """,
            (topic_id,),
        ).fetchall()

        # Gather responses
        responses = conn.execute(
            """
            SELECT rr.response_type, rr.response_text, ri.summary as issue_summary
            FROM review_responses rr
            JOIN review_issues ri ON ri.id = rr.issue_id
            WHERE rr.topic_id = ?
            ORDER BY rr.created_at
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    if not issues:
        return RebuttalFormatOutput(
            rebuttal_text="No review issues found for this topic.",
            issues_addressed=0,
            topic_id=topic_id,
        )

    # Build issue text
    issue_lines: list[str] = []
    for i in issues:
        line = f"[{i['severity'].upper()}] {i['category']}: {i['summary']}"
        if i["details"]:
            line += f"\n  Details: {i['details']}"
        if i["recommended_action"]:
            line += f"\n  Recommended: {i['recommended_action']}"
        issue_lines.append(line)

    # Build response text
    resp_lines: list[str] = []
    for r in responses:
        resp_lines.append(
            f"Re: {r['issue_summary']}\n  [{r['response_type']}] {r['response_text']}"
        )

    issues_text = "\n\n".join(issue_lines)
    responses_text = (
        "\n\n".join(resp_lines) if resp_lines else "(no responses recorded)"
    )

    client = _get_client(tier="medium", task_name="rebuttal_format")
    prompt = prompts.rebuttal_draft_prompt(issues_text, responses_text)
    rebuttal = _client_chat(client, prompt)

    return RebuttalFormatOutput(
        rebuttal_text=rebuttal.strip(),
        issues_addressed=len(issues),
        topic_id=topic_id,
    )


# ---------------------------------------------------------------------------
# Evolution primitives (LLM-powered)
# ---------------------------------------------------------------------------


def lesson_extract(
    *,
    db: Database,
    stage: str,
    stage_summary: str,
    issues_encountered: list[str] | None = None,
    session_id: str = "",
    **_: Any,
) -> "LessonExtractOutput":
    """Extract structured lessons from a stage execution using LLM.

    Analyses trajectory data (if available) plus the stage summary and
    issues to produce structured lessons that feed into strategy distillation.
    """
    from research_harness.primitives.types import LessonExtractOutput, LessonItem

    issues = issues_encountered or []

    # Build trajectory context if session_id provided
    trajectory_text = ""
    if session_id:
        try:
            from research_harness.evolution.topic.trajectory import TrajectoryRecorder

            events = TrajectoryRecorder.get_stage_trajectories(
                db,
                stage,
                limit=30,
            )
            trajectory_text = TrajectoryRecorder.format_trajectory_text(events)
        except Exception:
            trajectory_text = "(trajectory data unavailable)"

    # Build the extraction prompt
    prompt_parts = [
        "You are a research workflow analyst. Extract structured lessons "
        "from the following stage execution data.\n",
        f"## Stage: {stage}\n",
        f"## Summary\n{stage_summary}\n",
    ]
    if issues:
        prompt_parts.append(
            "## Issues Encountered\n" + "\n".join(f"- {i}" for i in issues) + "\n"
        )
    if trajectory_text:
        prompt_parts.append(f"## Tool Execution Trajectory\n{trajectory_text}\n")

    prompt_parts.append(
        "\n## Task\n"
        "Extract 3-8 lessons from this execution. For each lesson, provide:\n"
        '- "stage": the workflow stage\n'
        '- "content": concise lesson text (1-2 sentences)\n'
        '- "lesson_type": one of "observation", "success", "failure", "tip"\n'
        '- "tags": 1-3 relevant tags\n\n'
        "Focus on:\n"
        "1. What strategies worked well (success)\n"
        "2. What failed and why (failure)\n"
        "3. Useful patterns worth repeating (tip)\n"
        "4. Non-obvious observations (observation)\n\n"
        'Return JSON: {"lessons": [...]}'
    )

    prompt = "\n".join(prompt_parts)
    client = _get_client(
        tier=_PRIMITIVE_TIERS.get("lesson_extract"), task_name="lesson_extract"
    )
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="lesson_extract", context=stage)

    lessons: list[LessonItem] = []
    for item in parsed.get("lessons", []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        lessons.append(
            LessonItem(
                stage=stage,
                content=content,
                lesson_type=str(item.get("lesson_type", "observation")).strip()
                or "observation",
                tags=[str(t) for t in (item.get("tags") or []) if t],
            )
        )

    # Fallback: if LLM returned nothing useful, use the old stub logic
    if not lessons:
        for issue in issues:
            lessons.append(
                LessonItem(
                    stage=stage, content=issue, lesson_type="failure", tags=[stage]
                )
            )
        if stage_summary:
            lessons.append(
                LessonItem(
                    stage=stage,
                    content=stage_summary,
                    lesson_type="observation",
                    tags=[stage],
                )
            )

    return LessonExtractOutput(
        lessons=lessons,
        stage=stage,
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Iterative retrieval loop
#
# Multi-round paper_search → overlap check → paper_ingest loop. Stops when
# the paper pool has converged (mean overlap ≥ threshold AND new papers added
# < floor) for `window` consecutive rounds, or when the optional
# cost-per-new-paper budget is exceeded.
# ---------------------------------------------------------------------------


def _paper_identity_key(ref: Any) -> str | None:
    """Pick a stable identifier for de-duplication: arxiv_id > doi > s2_id.

    Falls back to ``None`` when no strong identifier is present — those rows
    are discarded from the overlap calculation because title-based matching
    is known to be unreliable (see PASA bug fix history).
    """
    arxiv = str(getattr(ref, "arxiv_id", "") or "").strip().lower()
    if arxiv:
        return f"arxiv:{arxiv}"
    doi = str(getattr(ref, "doi", "") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    s2 = str(getattr(ref, "s2_id", "") or "").strip().lower()
    if s2:
        return f"s2:{s2}"
    return None


def _paper_in_pool(
    db: Database, *, arxiv_id: str = "", doi: str = "", s2_id: str = ""
) -> bool:
    """Check whether a paper already exists in the local pool."""
    arxiv_id = (arxiv_id or "").strip()
    doi = (doi or "").strip()
    s2_id = (s2_id or "").strip()
    if not (arxiv_id or doi or s2_id):
        return False
    conn = db.connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if arxiv_id:
            clauses.append("LOWER(COALESCE(arxiv_id,'')) = ?")
            params.append(arxiv_id.lower())
        if doi:
            clauses.append("LOWER(COALESCE(doi,'')) = ?")
            params.append(doi.lower())
        if s2_id:
            clauses.append("LOWER(COALESCE(s2_id,'')) = ?")
            params.append(s2_id.lower())
        where = " OR ".join(clauses)
        row = conn.execute(
            f"SELECT id FROM papers WHERE {where} LIMIT 1", params
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _ingest_source_from_ref(ref: Any) -> str | None:
    """Best identifier to hand to paper_ingest. Prefers arxiv over doi over url."""
    arxiv = str(getattr(ref, "arxiv_id", "") or "").strip()
    if arxiv:
        return arxiv
    doi = str(getattr(ref, "doi", "") or "").strip()
    if doi:
        return doi
    s2 = str(getattr(ref, "s2_id", "") or "").strip()
    if s2:
        return s2
    url = str(getattr(ref, "url", "") or "").strip()
    if url:
        return url
    return None


def _record_retrieval_round_to_db(
    db: Database,
    *,
    topic_id: int,
    query: str,
    round_index: int,
    record: RetrievalRoundRecord,
    cost_usd: float,
) -> None:
    """Upsert the round metrics into search_query_registry."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM search_query_registry WHERE topic_id = ? AND query = ?",
            (topic_id, query),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO search_query_registry
                    (topic_id, query, source, last_searched_at,
                     round_index, total_hits, dedup_hits, existing_hits,
                     new_papers_added, overlap_ratio, seed_gap, last_round_cost_usd)
                VALUES (?, ?, 'iterative_loop', datetime('now'),
                        ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    query,
                    round_index,
                    record.total_hits,
                    record.dedup_hits,
                    record.existing_hits,
                    record.new_papers_added,
                    record.overlap_ratio,
                    record.seed_gap,
                    cost_usd,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE search_query_registry
                SET last_searched_at = datetime('now'),
                    round_index = ?,
                    total_hits = ?,
                    dedup_hits = ?,
                    existing_hits = ?,
                    new_papers_added = ?,
                    overlap_ratio = ?,
                    seed_gap = ?,
                    last_round_cost_usd = ?
                WHERE id = ?
                """,
                (
                    round_index,
                    record.total_hits,
                    record.dedup_hits,
                    record.existing_hits,
                    record.new_papers_added,
                    record.overlap_ratio,
                    record.seed_gap,
                    cost_usd,
                    int(row["id"]),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def iterative_retrieval_loop(
    *,
    db: Database,
    topic_id: int,
    max_rounds: int = 5,
    convergence_threshold: float = 0.8,
    window: int = 2,
    new_paper_floor: int = 5,
    queries_per_round: int = 4,
    max_results_per_query: int = 30,
    budget_per_new_paper_usd: float | None = None,
    ingest_relevance: str = "medium",
    **_: Any,
) -> IterativeRetrievalLoopOutput:
    """Run multi-round retrieval until the paper pool converges.

    Each round:
      1. Calls query_refine for fresh candidate queries.
      2. Filters out queries already executed by this loop (or registered).
      3. Runs paper_search for each fresh query (auto_ingest=False), dedupes
         hits on (arxiv_id, doi, s2_id), computes overlap with the existing
         pool, and ingests only the new papers.
      4. Records per-query round metrics in search_query_registry and an
         in-memory RetrievalRoundRecord.

    Stop when either:
      • Mean overlap ≥ convergence_threshold AND round new_papers < new_paper_floor
        for `window` consecutive rounds.
      • Optional: cost_per_new_paper exceeds budget_per_new_paper_usd.
      • No fresh queries can be generated (query exhaustion).
      • max_rounds reached (hard cap).
    """
    # Lazy imports to avoid cycle — paper_search / paper_ingest live in the
    # local primitives module and do not require an LLM backend.
    from research_harness.primitives.impls import paper_ingest as _paper_ingest_impl
    from research_harness.primitives.impls import paper_search as _paper_search_impl

    rounds: list[RetrievalRoundRecord] = []
    per_round_mean_overlap: list[float] = []
    per_round_new_papers: list[int] = []

    # Load previously-registered queries so we don't replay them inside the loop.
    conn = db.connect()
    try:
        known = {
            str(row["query"]).strip().casefold()
            for row in conn.execute(
                "SELECT query FROM search_query_registry WHERE topic_id = ?",
                (topic_id,),
            ).fetchall()
            if row["query"]
        }
    finally:
        conn.close()

    total_new_papers = 0
    total_fresh_queries = 0
    converged_run = 0
    stop_reason = "max_rounds_reached"
    convergence_reached = False
    model_used = ""

    for round_idx in range(1, max_rounds + 1):
        refine = query_refine(
            db=db, topic_id=topic_id, max_candidates=queries_per_round * 3
        )
        model_used = refine.model_used or model_used

        fresh_candidates: list[QueryCandidate] = []
        for cand in refine.candidates:
            q_key = cand.query.strip().casefold()
            if not q_key or q_key in known:
                continue
            known.add(q_key)
            fresh_candidates.append(cand)
            if len(fresh_candidates) >= queries_per_round:
                break

        if not fresh_candidates:
            stop_reason = "query_refine_exhausted"
            break

        round_records: list[RetrievalRoundRecord] = []
        round_new_papers = 0
        round_effective_queries = 0  # queries that returned at least 1 hit

        for cand in fresh_candidates:
            total_fresh_queries += 1
            try:
                search_out = _paper_search_impl(
                    db=db,
                    query=cand.query,
                    topic_id=topic_id,
                    max_results=max_results_per_query,
                    auto_ingest=False,
                )
            except SPCAcquisitionError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("paper_search failed for %r: %s", cand.query, exc)
                continue

            # Dedup on strong identifier; drop rows without one.
            seen_keys: set[str] = set()
            deduped: list[Any] = []
            for paper_ref in search_out.papers:
                key = _paper_identity_key(paper_ref)
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(paper_ref)

            total_hits = len(search_out.papers)
            dedup_hits = len(deduped)

            # Count how many are already in the pool, ingest the rest.
            existing_hits = 0
            new_added = 0
            ingest_errors: list[str] = []
            for paper_ref in deduped:
                if _paper_in_pool(
                    db,
                    arxiv_id=getattr(paper_ref, "arxiv_id", ""),
                    doi=getattr(paper_ref, "doi", ""),
                    s2_id=getattr(paper_ref, "s2_id", ""),
                ):
                    existing_hits += 1
                    continue
                source = _ingest_source_from_ref(paper_ref)
                if not source:
                    continue
                try:
                    _paper_ingest_impl(
                        db=db,
                        source=source,
                        topic_id=topic_id,
                        relevance=ingest_relevance,
                    )
                    new_added += 1
                except SPCAcquisitionError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive
                    ingest_errors.append(f"{source}: {exc}")

            # Exclude empty-result queries from overlap computation to avoid
            # LLM-hallucinated terms trivially showing 0% overlap.
            if dedup_hits == 0:
                overlap_ratio = 0.0
            else:
                overlap_ratio = existing_hits / dedup_hits
                round_effective_queries += 1

            record = RetrievalRoundRecord(
                round_index=round_idx,
                query=cand.query,
                total_hits=total_hits,
                dedup_hits=dedup_hits,
                existing_hits=existing_hits,
                new_papers_added=new_added,
                overlap_ratio=overlap_ratio,
                seed_gap=cand.coverage_direction or cand.rationale,
                ingest_errors=ingest_errors,
                providers_queried=list(search_out.providers_queried),
            )
            round_records.append(record)

            # Persist the round for clients / gating.
            try:
                _record_retrieval_round_to_db(
                    db,
                    topic_id=topic_id,
                    query=cand.query,
                    round_index=round_idx,
                    record=record,
                    cost_usd=0.0,  # per-round cost is charged at loop level
                )
            except Exception as exc:  # pragma: no cover - logging only
                logger.warning(
                    "Failed to persist retrieval round record for %r: %s",
                    cand.query,
                    exc,
                )

            round_new_papers += new_added

        rounds.extend(round_records)
        if round_effective_queries == 0:
            mean_overlap = 0.0
        else:
            mean_overlap = (
                sum(r.overlap_ratio for r in round_records if r.dedup_hits > 0)
                / round_effective_queries
            )

        per_round_mean_overlap.append(mean_overlap)
        per_round_new_papers.append(round_new_papers)
        total_new_papers += round_new_papers

        # Cost-aware stop (requires observed token → cost estimation). The
        # accumulator is read by the backend after this impl returns; here we
        # read the current snapshot to decide mid-loop.
        if budget_per_new_paper_usd is not None and round_new_papers > 0:
            prompt_so_far, completion_so_far = _accumulated_tokens()
            if prompt_so_far is not None or completion_so_far is not None:
                # Crude cost estimate: $0.005 per primitive call already baked
                # into estimate_cost. Use accumulated token count as proxy:
                # assume $0.5 per million tokens in + $1.5 per million out
                # (matches gpt-4o rough pricing tier).
                est_cost = ((prompt_so_far or 0) / 1_000_000) * 0.5 + (
                    (completion_so_far or 0) / 1_000_000
                ) * 1.5
                if total_new_papers > 0:
                    cost_per_paper = est_cost / max(total_new_papers, 1)
                    if cost_per_paper > budget_per_new_paper_usd:
                        stop_reason = "cost_budget_exceeded"
                        break

        # Dual-condition convergence check
        if mean_overlap >= convergence_threshold and round_new_papers < new_paper_floor:
            converged_run += 1
            if converged_run >= window:
                convergence_reached = True
                stop_reason = "converged"
                break
        else:
            converged_run = 0

    final_mean_overlap = per_round_mean_overlap[-1] if per_round_mean_overlap else 0.0

    prompt_tokens_total, completion_tokens_total = _accumulated_tokens()
    # Crude cost reflection (ties into per-primitive estimate_cost baseline)
    total_cost_usd = 0.0
    if prompt_tokens_total is not None or completion_tokens_total is not None:
        total_cost_usd = ((prompt_tokens_total or 0) / 1_000_000) * 0.5 + (
            (completion_tokens_total or 0) / 1_000_000
        ) * 1.5
    cost_per_new_paper: float | None = None
    if total_new_papers > 0 and total_cost_usd > 0:
        cost_per_new_paper = total_cost_usd / total_new_papers

    return IterativeRetrievalLoopOutput(
        topic_id=topic_id,
        rounds_run=len(per_round_mean_overlap),
        total_new_papers=total_new_papers,
        total_fresh_queries=total_fresh_queries,
        final_mean_overlap=final_mean_overlap,
        convergence_reached=convergence_reached,
        stop_reason=stop_reason,
        rounds=rounds,
        per_round_mean_overlap=per_round_mean_overlap,
        per_round_new_papers=per_round_new_papers,
        total_prompt_tokens=prompt_tokens_total,
        total_completion_tokens=completion_tokens_total,
        total_cost_usd=total_cost_usd,
        cost_per_new_paper=cost_per_new_paper,
        model_used=model_used,
    )


# ---------------------------------------------------------------------------
# Topic framing (init stage)
# ---------------------------------------------------------------------------


def topic_framing(
    *,
    db: Database,
    context: str = "",
    _model: str | None = None,
    **_: Any,
) -> TopicFramingOutput:
    """Analyze project context and generate a structured topic definition."""
    if not context.strip():
        return TopicFramingOutput()

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("topic_framing"))
    raw = _client_chat(client, prompts.topic_framing_prompt(context))
    parsed = _parse_json(raw, primitive="topic_framing")

    return TopicFramingOutput(
        topic_name=str(parsed.get("topic_name", "")).strip(),
        description=str(parsed.get("description", "")).strip(),
        search_queries=[str(q) for q in (parsed.get("search_queries") or []) if q],
        scope_keywords=[str(k) for k in (parsed.get("scope_keywords") or []) if k],
        target_venue=str(parsed.get("target_venue", "")).strip(),
        year_from=_coerce_int(parsed.get("year_from"), 0),
        exclusions=[str(e) for e in (parsed.get("exclusions") or []) if e],
        seed_papers=[str(s) for s in (parsed.get("seed_papers") or []) if s],
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Research direction ranking (analyze stage)
# ---------------------------------------------------------------------------


def direction_ranking(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    area_red_ocean: float | None = None,
    task_red_ocean: float | None = None,
    method_red_ocean: float | None = None,
    opportunity_angle: str | None = None,
    _model: str | None = None,
    **_: Any,
) -> DirectionRankingOutput:
    """Rank candidate research directions by novelty × feasibility × impact.

    When red-ocean scores + opportunity_angle are supplied (typically by
    recommendations_generate), the prompt grows an extra section
    instructing the LLM to weight saturation signals into its ranking.
    """
    summary, related_paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="direction_ranking"
    )

    # Gather existing gaps
    conn = db.connect()
    try:
        gap_rows = conn.execute(
            """SELECT description, gap_type, severity FROM gaps
               WHERE topic_id = ? ORDER BY rowid""",
            (topic_id,),
        ).fetchall()
        gaps_text = (
            "\n".join(f"- [{r['severity']}] {r['description']}" for r in gap_rows)
            or "No gaps detected yet."
        )

        claim_rows = conn.execute(
            """SELECT claim_text, method, dataset, metric FROM normalized_claims
               WHERE topic_id = ? ORDER BY rowid LIMIT 30""",
            (topic_id,),
        ).fetchall()
        claims_text = (
            "\n".join(
                f"- {r['claim_text']}" + (f" [{r['method']}]" if r["method"] else "")
                for r in claim_rows
            )
            or "No claims extracted yet."
        )
    finally:
        conn.close()

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("direction_ranking"))
    raw = _client_chat(
        client,
        prompts.direction_ranking_prompt(
            gaps_text,
            claims_text,
            summary,
            area_red_ocean=area_red_ocean,
            task_red_ocean=task_red_ocean,
            method_red_ocean=method_red_ocean,
            opportunity_angle=opportunity_angle,
        ),
    )
    parsed = _parse_json(raw, primitive="direction_ranking")

    directions: list[RankedDirection] = []
    for item in parsed.get("directions", []):
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction", "")).strip()
        if not direction:
            continue
        directions.append(
            RankedDirection(
                direction=direction,
                description=str(item.get("description", "")).strip(),
                novelty=_coerce_float(item.get("novelty"), 0.0),
                feasibility=_coerce_float(item.get("feasibility"), 0.0),
                impact=_coerce_float(item.get("impact"), 0.0),
                composite_score=_coerce_float(item.get("composite_score"), 0.0),
                supporting_gaps=[
                    str(g) for g in (item.get("supporting_gaps") or []) if g
                ],
                risks=[str(r) for r in (item.get("risks") or []) if r],
            )
        )

    # Sort by composite score descending
    directions.sort(key=lambda d: d.composite_score, reverse=True)

    return DirectionRankingOutput(
        directions=directions,
        recommendation=str(parsed.get("recommendation", "")).strip(),
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Method layer expansion (propose stage)
# ---------------------------------------------------------------------------


def method_layer_expansion(
    *,
    db: Database,
    topic_id: int,
    proposal: str,
    _model: str | None = None,
    **_: Any,
) -> MethodLayerExpansionOutput:
    """Extract method keywords from a proposal and generate cross-domain search queries."""
    summary, _ = _get_topic_literature_summary(
        db, topic_id, task_type="method_layer_expansion"
    )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("method_layer_expansion"))
    raw = _client_chat(
        client,
        prompts.method_layer_expansion_prompt(proposal, summary),
    )
    parsed = _parse_json(raw, primitive="method_layer_expansion")

    queries: list[MethodQuery] = []
    for item in parsed.get("queries", []):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if query:
            queries.append(
                MethodQuery(
                    query=query,
                    category=str(item.get("category", "")).strip(),
                    rationale=str(item.get("rationale", "")).strip(),
                )
            )

    return MethodLayerExpansionOutput(
        method_keywords=[str(k) for k in (parsed.get("method_keywords") or []) if k],
        queries=queries,
        cross_domain_venues=[
            str(v) for v in (parsed.get("cross_domain_venues") or []) if v
        ],
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Writing architecture (write stage)
# ---------------------------------------------------------------------------


_MANUSCRIPT_LOGIC_CONTEXT_LIMIT = 100000


def _manuscript_logic_context_json(context: dict[str, Any]) -> str:
    if not isinstance(context, dict):
        raise ValueError("manuscript logic context must be an object")
    sections, evidence = context.get("sections"), context.get("allowed_evidence")
    if (
        not isinstance(sections, list)
        or not sections
        or any(
            not isinstance(section, str)
            or not section.strip()
            or section != section.strip()
            for section in sections
        )
        or len(set(sections)) != len(sections)
    ):
        raise ValueError("manuscript logic sections must be unique nonempty strings")
    if (
        not isinstance(evidence, list)
        or not evidence
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"].strip()
            or item["id"] != item["id"].strip()
            for item in evidence
        )
    ):
        raise ValueError("manuscript logic allowed_evidence must contain evidence IDs")
    if len({item["id"] for item in evidence}) != len(evidence):
        raise ValueError("manuscript logic evidence IDs must be unique")
    try:
        rendered = json.dumps(context, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("manuscript logic context must be finite JSON") from exc
    if len(rendered) > _MANUSCRIPT_LOGIC_CONTEXT_LIMIT:
        # A caller over the bound has to know which key to trim: the size alone sent A0114's
        # WRITE looking through a frozen revision for a cause the message already knew.
        largest = max(
            context,
            key=lambda key: len(
                json.dumps(context[key], ensure_ascii=False, default=str)
            ),
        )
        raise ValueError(
            f"manuscript logic context renders {len(rendered)} characters, above the limit of {_MANUSCRIPT_LOGIC_CONTEXT_LIMIT};"
            f" its largest key is {largest} at "
            f"{len(json.dumps(context[largest], ensure_ascii=False, default=str))} characters"
        )
    return rendered


_LOGIC_OBJECT_FIELDS = frozenset(
    {
        "core_claim_contract",
        "argument_tree",
        "fine_logic_audit",
        "intro_logic_map",
    }
)
_LOGIC_RECORD_FIELDS = frozenset(
    {
        "problems",
        "term_registry",
        "promise_realization_matrix",
        "paragraph_intent_tree",
        "argument_link_map",
        "assumption_warrant_table",
        "claim_certainty_audit",
        "paragraph_flow_audit",
        "figure_table_message_audit",
        "writing_defect_log",
    }
)
_LOGIC_TEXT_LIST_FIELDS = frozenset(
    {
        "allowed_focus",
        "forbidden_focus",
        "evidence_ids",
        "backing_evidence_ids",
        "section_ids",
        "allowed_aliases",
        "forbidden_aliases",
        "realized_by",
        "allowed_terms",
        "paragraph_ids",
        "chain",
        "supports_claim_ids",
    }
)
_LOGIC_BOOLEAN_FIELDS = frozenset({"serves_claim", "signal_word_valid"})
# What each field should have been, so a refusal can say it. "wrong type: made_in"
# named neither the value nor the shape expected of it, and the reader could not tell
# a list from a null from a number without the reply the refusal had already lost.
_LOGIC_FIELD_SHAPES = {
    **{key: "an object" for key in _LOGIC_OBJECT_FIELDS},
    **{key: "a list of objects" for key in _LOGIC_RECORD_FIELDS},
    **{key: "a list of nonempty strings" for key in _LOGIC_TEXT_LIST_FIELDS},
    **{key: "a boolean" for key in _LOGIC_BOOLEAN_FIELDS},
}


def _validate_logic_field_types(value: Any, allowed_evidence: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_logic_field_types(item, allowed_evidence)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in _LOGIC_OBJECT_FIELDS:
                valid = isinstance(item, dict)
            elif key in _LOGIC_RECORD_FIELDS:
                valid = isinstance(item, list) and all(
                    isinstance(row, dict) for row in item
                )
            elif key in _LOGIC_TEXT_LIST_FIELDS:
                valid = isinstance(item, list) and all(
                    isinstance(text, str) and text.strip() for text in item
                )
            elif key in _LOGIC_BOOLEAN_FIELDS:
                valid = isinstance(item, bool)
            else:
                valid = isinstance(item, str)
            if not valid:
                raise ValueError(
                    f"manuscript logic bundle field has wrong type: {key} is "
                    f"{type(item).__name__} "
                    f"{json.dumps(item, ensure_ascii=False, default=str)[:160]}, "
                    f"expected {_LOGIC_FIELD_SHAPES.get(key, 'a string')}"
                )
            if key in {"allowed_certainty", "actual_certainty"} and item not in {
                "unsupported",
                "tentative",
                "bounded",
                "strong",
                "universal",
            }:
                raise ValueError(
                    f"manuscript logic bundle has unknown certainty: {key}"
                )
            if (
                key in {"evidence_ids", "backing_evidence_ids"}
                and set(item) - allowed_evidence
            ):
                raise ValueError(
                    f"manuscript logic bundle references unknown evidence in {key}"
                )
            _validate_logic_field_types(item, allowed_evidence)


def _validate_logic_references(bundle: dict[str, Any], sections: list[str]) -> None:
    fine = bundle["fine_logic_audit"]
    paragraphs = [row.get("paragraph_id") for row in bundle["paragraph_intent_tree"]]
    claims = [row.get("claim_id") for row in fine["argument_link_map"]]
    for name, identities in (("paragraph", paragraphs), ("claim", claims)):
        if any(
            not isinstance(item, str) or not item.strip() for item in identities
        ) or len(set(identities)) != len(identities):
            raise ValueError(f"manuscript logic {name} IDs must be nonempty and unique")
    checks = [
        (
            bundle["argument_tree"].get("problems", []),
            "section_ids",
            set(sections),
            True,
        ),
        (bundle["paragraph_intent_tree"], "section", set(sections), False),
        (fine["argument_link_map"], "paragraph_ids", set(paragraphs), True),
        (fine["paragraph_flow_audit"], "paragraph_id", set(paragraphs), False),
        (fine["figure_table_message_audit"], "supports_claim_ids", set(claims), True),
        (fine["claim_certainty_audit"], "claim_id", set(claims), False),
    ]
    for rows, field, allowed, plural in checks:
        for row in rows:
            referenced = set(row.get(field, [])) if plural else {row.get(field)}
            if referenced - allowed:
                raise ValueError(
                    f"manuscript logic bundle has unresolved reference: {field}"
                )


def validate_manuscript_logic_bundle(
    bundle: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Validate raw planning inputs and recompute both canonical writing gates."""
    from research_harness._selfdev.manuscript_logic_gate import (
        evaluate_fine_logic_audit,
        evaluate_manuscript_logic_bundle,
    )

    _manuscript_logic_context_json(context)
    if (
        not isinstance(bundle, dict)
        or bundle.get("schema_version") != "rh.manuscript.logic_bundle.v1"
    ):
        raise ValueError(
            "manuscript logic bundle must use rh.manuscript.logic_bundle.v1"
        )
    required = {
        "schema_version",
        "core_claim_contract",
        "argument_tree",
        "term_registry",
        "promise_realization_matrix",
        "paragraph_intent_tree",
        "fine_logic_audit",
    }
    fine_fields = {
        "schema_version",
        "argument_link_map",
        "assumption_warrant_table",
        "claim_certainty_audit",
        "paragraph_flow_audit",
        "intro_logic_map",
        "figure_table_message_audit",
        "writing_defect_log",
    }
    fine = bundle.get("fine_logic_audit")
    if (
        set(bundle) != required
        or not isinstance(fine, dict)
        or set(fine) != fine_fields
    ):
        raise ValueError(
            "manuscript logic bundle requires complete raw coarse and fine fields"
        )
    if fine["schema_version"] != "rh.manuscript.fine_logic_audit.v1":
        raise ValueError("manuscript logic bundle fine audit schema is invalid")
    _validate_logic_field_types(
        bundle, {item["id"] for item in context["allowed_evidence"]}
    )
    covered = {item.get("section") for item in bundle["paragraph_intent_tree"]}
    if set(context["sections"]) - covered:
        raise ValueError("manuscript logic bundle lacks required section coverage")
    _validate_logic_references(bundle, context["sections"])
    coarse_report = evaluate_manuscript_logic_bundle(bundle)
    fine_report = evaluate_fine_logic_audit(fine)
    if coarse_report.status != "pass" or fine_report.status != "pass":
        blockers = [*coarse_report.blockers, *fine_report.blockers]
        raise ValueError(
            "manuscript logic bundle blocked: " + "; ".join(dict.fromkeys(blockers))
        )
    return {
        "manuscript_logic_gate_report": coarse_report.to_dict(),
        "fine_logic_audit_report": fine_report.to_dict(),
    }


def writing_architecture(
    *,
    db: Database,
    topic_id: int,
    contributions: str = "",
    writing_patterns: str = "",
    outline: str = "",
    manuscript_logic_context: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> WritingArchitectureOutput:
    """Design optimal paper structure based on contributions and venue patterns.

    ``contributions`` is optional: if omitted, auto-loaded from
    ``topics.contributions`` for this topic.
    """
    logic_context = (
        _manuscript_logic_context_json(manuscript_logic_context)
        if manuscript_logic_context is not None
        else ""
    )
    if not contributions.strip():
        contributions = _get_topic_latest_project_contributions(db, topic_id)
    if not contributions.strip():
        raise ValueError(
            "writing_architecture requires contributions either passed "
            "explicitly or set on the topic via topic_set_contributions."
        )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("writing_architecture"))
    raw = _client_chat(
        client,
        prompts.writing_architecture_prompt(
            contributions,
            writing_patterns,
            outline,
            manuscript_logic_context=logic_context,
        ),
    )
    parsed = (
        # The reply restates the logic bundle and adds the section plans, so it cannot fit in
        # the bound its own input sits under: A0114's context rendered 78248 and its architecture
        # came back at 104175, four percent over a ceiling copied from the context limit.
        _strict_manuscript_json(raw, limit=2 * _MANUSCRIPT_LOGIC_CONTEXT_LIMIT)
        if logic_context
        else _parse_json(raw, primitive="writing_architecture")
    )
    logic_bundle = parsed.get("manuscript_logic_bundle", {}) if logic_context else {}
    if manuscript_logic_context is not None:
        validate_manuscript_logic_bundle(logic_bundle, manuscript_logic_context)

    sections: list[SectionPlan] = []
    for item in parsed.get("sections", []):
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section", "")).strip()
        if section_id:
            sections.append(
                SectionPlan(
                    section=section_id,
                    title=str(item.get("title", section_id)).strip(),
                    target_words=_coerce_int(item.get("target_words"), 500),
                    argument_strategy=str(item.get("argument_strategy", "")).strip(),
                    key_evidence=[
                        str(e) for e in (item.get("key_evidence") or []) if e
                    ],
                )
            )

    if manuscript_logic_context is not None:
        section_ids = [item.section for item in sections]
        if len(section_ids) != len(set(section_ids)) or set(
            manuscript_logic_context["sections"]
        ) - set(section_ids):
            raise ValueError(
                "manuscript logic architecture lacks unique required sections"
            )

    return WritingArchitectureOutput(
        paper_title=str(parsed.get("paper_title", "")).strip(),
        narrative_strategy=str(parsed.get("narrative_strategy", "")).strip(),
        sections=sections,
        total_words=_coerce_int(
            parsed.get("total_words"), sum(s.target_words for s in sections)
        ),
        strengths=[str(s) for s in (parsed.get("strengths") or []) if s],
        model_used=client.model,
        manuscript_logic_bundle=logic_bundle,
    )


# ---------------------------------------------------------------------------
# Figure planning
# ---------------------------------------------------------------------------


def figure_plan(
    *,
    db: Database,
    topic_id: int,
    contributions: str = "",
    outline: str = "",
    target_venue: str = "",
    _model: str | None = None,
    **_: Any,
) -> "FigurePlanOutput":
    """Plan figures and tables for a paper.

    ``contributions`` is optional: if omitted, auto-loaded from
    ``topics.contributions`` for this topic.
    """
    from research_harness.primitives.types import FigurePlanItem, FigurePlanOutput

    if not contributions.strip():
        contributions = _get_topic_latest_project_contributions(db, topic_id)
    if not contributions.strip():
        raise ValueError(
            "figure_plan requires contributions either passed explicitly "
            "or set on the topic via topic_set_contributions."
        )

    evidence_text, _ = _build_numbered_evidence(
        db, topic_id, max_papers=15, task_type="figure_plan"
    )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("writing_architecture"))
    raw = _client_chat(
        client,
        prompts.figure_plan_prompt(contributions, outline, evidence_text, target_venue),
    )
    parsed = _parse_json(raw, primitive="figure_plan")

    items: list[FigurePlanItem] = []
    for entry in parsed.get("items", []):
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "figure")).strip().lower()
        if kind not in ("figure", "table"):
            kind = "figure"
        items.append(
            FigurePlanItem(
                figure_id=str(entry.get("figure_id", "")).strip(),
                kind=kind,
                title=str(entry.get("title", "")).strip(),
                caption=str(entry.get("caption", "")).strip(),
                section=str(entry.get("section", "")).strip(),
                purpose=str(entry.get("purpose", "")).strip(),
                data_source=str(entry.get("data_source", "")).strip(),
                suggested_layout=str(entry.get("suggested_layout", "")).strip(),
                placement_hint=str(entry.get("placement_hint", "")).strip(),
            )
        )

    figs = sum(1 for it in items if it.kind == "figure")
    tabs = sum(1 for it in items if it.kind == "table")
    return FigurePlanOutput(
        items=items,
        total_items=len(items),
        figures_count=figs,
        tables_count=tabs,
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Figure generation (via fal.ai — external image API)
# ---------------------------------------------------------------------------


def _style_ref_provenance(style_ref: dict[str, Any]) -> dict[str, Any]:
    """Compact, secret-free reference_style_selection provenance for a figure."""
    if not style_ref.get("executed"):
        return {"executed": False, "reason": str(style_ref.get("reason", ""))}
    anchor = (
        style_ref.get("style_anchor")
        if isinstance(style_ref.get("style_anchor"), dict)
        else {}
    )
    return {
        "executed": True,
        "source": "rh_exemplar_architecture",
        "reference_paper_ids": list(style_ref.get("reference_ids", []))[:8],
        "candidates_seen": style_ref.get("candidates_seen"),
        "style_anchor": anchor,
        "rationale": str(style_ref.get("rationale", ""))[:300],
        # >0 means the actual reference figures were fed to the model
        # (multimodal image-conditioning); 0 means text-only style anchor.
        "reference_image_count": int(style_ref.get("reference_image_count", 0) or 0),
        "conditioning": (
            "image" if style_ref.get("reference_image_count") else "text_anchor"
        ),
        "model_used": str(style_ref.get("model_used", "")),
    }


def figure_generate(
    *,
    db: Database,
    topic_id: int,
    items: list[dict[str, Any]],
    output_dir: str,
    model: str | None = None,
    evidence_boundary: str = "conceptual",
    figure_contract: dict[str, Any] | None = None,
    illustration_fake: bool = False,
    _model: str | None = None,
    **_: Any,
) -> "FigureGenerateOutput":
    """Generate academic figure images from figure_plan items."""
    from research_harness.primitives.types import (
        FigureGenerateItem,
        FigureGenerateOutput,
    )
    from .fal_image_client import (
        build_image_prompt,
        choose_dimensions,
        classify_figure_style,
        figure_id_to_filename,
        generate_image,
    )

    requested_model = (
        model or os.environ.get(FIGURE_MODEL_ENV, "").strip() or DEFAULT_FIGURE_MODEL
    )

    figure_items = [
        it
        for it in items
        if isinstance(it, dict) and it.get("kind", "figure") == "figure"
    ]

    # reference_style_selection (RH-native): anchor the architecture figure's
    # VISUAL FORM on the topic's schematic-figure exemplars before generation.
    # Best-effort; disable with RESEARCH_HARNESS_FIGURE_STYLE_REF=0.
    style_ref: dict[str, Any] = {"executed": False, "reason": "not_attempted"}
    if (
        not illustration_fake
        and not (figure_contract or {}).get("generation")
        and os.environ.get("RESEARCH_HARNESS_FIGURE_STYLE_REF", "1").strip() != "0"
        and db is not None
        and topic_id is not None
        and figure_items
    ):
        try:
            from research_harness.primitives.exemplar_impls import (
                architecture_style_reference,
            )

            ref_target = "; ".join(
                str(it.get("purpose") or it.get("title") or "").strip()
                for it in figure_items
                if str(it.get("purpose") or it.get("title") or "").strip()
            )[:2000]
            style_ref = architecture_style_reference(
                db=db, topic_id=topic_id, target_content=ref_target, _model=_model
            )
        except Exception as exc:  # noqa: BLE001 - never block figure generation
            style_ref = {"executed": False, "reason": f"error:{type(exc).__name__}"}

    # Optional true image-conditioning: feed the reference architecture figures
    # (actual PNGs) into a multimodal provider call. Opt-in — default keeps the
    # text-only style anchor. Requires a vision backend to gate which figures.
    reference_images: tuple[bytes, ...] = ()
    if (
        style_ref.get("executed")
        and os.environ.get("RESEARCH_HARNESS_FIGURE_REF_IMAGES", "0").strip() == "1"
        and style_ref.get("reference_ids")
    ):
        try:
            from research_harness.visualization.result_figure_refs import (
                architecture_reference_images,
            )

            reference_images = tuple(
                architecture_reference_images(
                    db, style_ref["reference_ids"], model=_model
                )
            )
        except Exception:  # noqa: BLE001 - degrade to text-only anchor
            reference_images = ()
    style_ref["reference_image_count"] = len(reference_images)

    results: list[FigureGenerateItem] = []
    for item in figure_items:
        figure_id = str(item.get("figure_id", "")).strip()
        title = str(item.get("title", "")).strip()
        caption = str(item.get("caption", "")).strip()
        purpose = str(item.get("purpose", "")).strip()
        data_source = str(item.get("data_source", "")).strip()
        suggested_layout = str(item.get("suggested_layout", "")).strip()
        section = str(item.get("section", "")).strip()
        item_evidence_boundary = str(
            item.get("evidence_boundary", evidence_boundary)
        ).strip()
        item_figure_contract = {
            key: value
            for key, value in item.items()
            if key
            in {
                "figure_id",
                "title",
                "caption",
                "purpose",
                "data_source",
                "suggested_layout",
                "section",
                "evidence_boundary",
            }
        }
        request_figure_contract = (
            dict(figure_contract)
            if figure_contract is not None
            else item_figure_contract
        )
        if style_ref.get("executed") and isinstance(
            style_ref.get("style_anchor"), dict
        ):
            request_figure_contract["style_reference"] = style_ref["style_anchor"]
        request_model = "illustration-fake" if illustration_fake else requested_model

        prompt = build_image_prompt(
            title=title,
            purpose=purpose,
            caption=caption,
            data_source=data_source,
            suggested_layout=suggested_layout,
            section=section,
            figure_contract=request_figure_contract,
        )
        style = classify_figure_style(purpose, suggested_layout, title)
        dimensions = choose_dimensions(suggested_layout, purpose)
        filename = figure_id_to_filename(figure_id)

        try:
            gen_result = generate_image(
                prompt=prompt,
                model=request_model,
                style=style,
                dimensions=dimensions,
                output_dir=output_dir,
                filename=filename,
                figure_id=figure_id,
                figure_contract=request_figure_contract,
                evidence_boundary=item_evidence_boundary or "conceptual",
                reference_images=reference_images,
            )
        except Exception as exc:
            results.append(
                FigureGenerateItem(
                    figure_id=figure_id,
                    filename=filename,
                    success=False,
                    error=str(exc),
                    prompt_used=prompt,
                    model_used=requested_model,
                    provenance={
                        "reference_style_selection": _style_ref_provenance(style_ref)
                    },
                )
            )
            continue

        item_provenance = dict(gen_result.provenance or {})
        # Record that reference_style_selection actually ran on the RH side (with
        # the real reference figure ids), instead of the provider-declared
        # contract-metadata step whose executed count is always zero.
        item_provenance["reference_style_selection"] = _style_ref_provenance(style_ref)
        results.append(
            FigureGenerateItem(
                figure_id=figure_id,
                filename=filename,
                path=gen_result.local_path if gen_result.success else "",
                success=gen_result.success,
                error=gen_result.error,
                prompt_used=prompt,
                model_used=gen_result.model_id,
                width=gen_result.width,
                height=gen_result.height,
                provenance=item_provenance,
            )
        )

    generated = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    primary_model = results[0].model_used if results else requested_model

    return FigureGenerateOutput(
        items=results,
        total_requested=len(figure_items),
        total_generated=generated,
        total_failed=failed,
        output_dir=output_dir,
        model_used=primary_model,
    )


# ---------------------------------------------------------------------------
# Universal Writing Skill: pattern extraction
# ---------------------------------------------------------------------------


def writing_pattern_extract(
    *,
    db: Database,
    paper_id: int,
    _model: str | None = None,
    **_: Any,
) -> "WritingPatternExtractOutput":
    """Extract structural writing patterns from a deeply-read paper."""
    from research_harness.primitives.types import (
        ALL_WRITING_DIMENSIONS,
        WRITING_SKILL_DIMENSIONS,
        WritingObservation,
        WritingPatternExtractOutput,
    )

    title, text = _get_paper_text(db, paper_id)
    if not text:
        return WritingPatternExtractOutput(paper_id=paper_id)

    # Get paper metadata for venue/year
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT venue, year FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()
    venue = (row["venue"] or "") if row else ""
    year = (row["year"] or 0) if row else 0

    # Determine venue tier
    venue_tier = ""
    if venue:
        from research_harness.venue_facts import venue_tier_label

        if venue_tier_label(venue).startswith("CCF-A"):
            venue_tier = "A"

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("paper_summarize"))
    raw = _client_chat(
        client,
        prompts.writing_pattern_extract_prompt(title, text, venue),
    )
    parsed = _parse_json(raw, primitive="writing_pattern_extract", context=title)

    # Build dimension→section lookup
    dim_to_section: dict[str, str] = {}
    for sec, dims in WRITING_SKILL_DIMENSIONS.items():
        for d in dims:
            dim_to_section[d] = sec

    observations: list[WritingObservation] = []
    for item in parsed.get("observations", []):
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension", "")).strip()
        if dim not in ALL_WRITING_DIMENSIONS:
            continue
        obs = WritingObservation(
            paper_id=paper_id,
            dimension=dim,
            section=dim_to_section.get(dim, str(item.get("section", "")).strip()),
            observation=str(item.get("observation", "")).strip(),
            example_text=str(item.get("example_text", "")).strip()[:1000],
            paper_venue=venue,
            paper_venue_tier=venue_tier,
            paper_year=year,
        )
        observations.append(obs)

    # Persist to DB
    conn = db.connect()
    try:
        for obs in observations:
            conn.execute(
                """INSERT INTO writing_observations
                   (paper_id, dimension, section, observation, example_text,
                    paper_venue, paper_venue_tier, paper_year, extractor_model)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs.paper_id,
                    obs.dimension,
                    obs.section,
                    obs.observation,
                    obs.example_text,
                    obs.paper_venue,
                    obs.paper_venue_tier,
                    obs.paper_year,
                    client.model,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return WritingPatternExtractOutput(
        paper_id=paper_id,
        observations=observations,
        dimensions_extracted=len(observations),
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Algorithm design subsystem (propose stage)
# ---------------------------------------------------------------------------


def _load_design_gap_context(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
) -> str:
    try:
        gap_rows = conn.execute(
            "SELECT description, gap_type, severity FROM gaps WHERE topic_id = ? ORDER BY rowid",
            (topic_id,),
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load gaps context for %s from gaps: %s",
            task_type,
            exc,
        )
        return ""

    return "\n".join(f"- [{row['severity']}] {row['description']}" for row in gap_rows)


def _load_design_papers_summary(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
) -> str:
    try:
        paper_rows = conn.execute(
            """SELECT p.id, p.title, p.year, p.venue
               FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
               WHERE pt.topic_id = ? AND pt.relevance IN ('high', 'medium')
               ORDER BY p.year DESC LIMIT 20""",
            (topic_id,),
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load paper summary context for %s from papers/paper_topics: %s",
            task_type,
            exc,
        )
        return ""

    return "\n".join(
        f"- [Paper {row['id']}] {row['title']}"
        + (f" ({row['year']})" if row["year"] else "")
        for row in paper_rows
    )


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _compact_context_value(value: Any, *, max_chars: int = 700) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > max_chars:
        result = text[: max_chars - 3].rstrip() + "..."
        # P-6: record what this truncation dropped. Instrumentation only — the
        # returned value is unchanged, and recording is a no-op outside a scope.
        _record_context_drop(
            kind="compact_context_value",
            source_id="",
            offered=len(text),
            kept=len(result),
            reason="compact_context_value",
        )
        return result
    _record_context_drop(
        kind="compact_context_value",
        source_id="",
        offered=len(text),
        kept=len(text),
        reason="compact_context_value",
    )
    return text


def _load_taxonomy_method_lines(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
    limit: int,
) -> list[str]:
    try:
        rows = conn.execute(
            """SELECT tn.name, tn.description, tn.aliases, COUNT(ta.paper_id) AS paper_count
               FROM taxonomy_nodes tn
               LEFT JOIN taxonomy_assignments ta ON ta.node_id = tn.id
               WHERE tn.topic_id = ?
               GROUP BY tn.id
               ORDER BY paper_count DESC, LOWER(tn.name)
               LIMIT ?""",
            (topic_id, limit),
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load method context for %s from taxonomy_nodes/taxonomy_assignments: %s",
            task_type,
            exc,
        )
        return []

    lines: list[str] = []
    for row in rows:
        aliases = [str(alias) for alias in _json_list(row["aliases"]) if alias]
        alias_text = f"; aliases: {', '.join(aliases[:3])}" if aliases else ""
        description = str(row["description"] or "").strip()
        detail = f" — {description}" if description else ""
        lines.append(
            f"- {row['name']} (taxonomy, {row['paper_count'] or 0} papers{alias_text}){detail}"
        )
    return lines


def _load_method_atom_lines(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
    limit: int,
) -> list[str]:
    try:
        rows = conn.execute(
            """SELECT atom_type, name, description, reported_gain, reuse_risk, source_paper_id
               FROM method_atoms
               WHERE topic_id = ?
               ORDER BY atom_type, id
               LIMIT ?""",
            (topic_id, limit),
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load method context for %s from method_atoms: %s",
            task_type,
            exc,
        )
        return []

    lines: list[str] = []
    for row in rows:
        gain = f"; gain: {row['reported_gain']}" if row["reported_gain"] else ""
        risk = f"; reuse risk: {row['reuse_risk']}" if row["reuse_risk"] else ""
        lines.append(
            f"- {row['name']} ({row['atom_type']}, paper {row['source_paper_id']}{gain}{risk})"
            f" — {row['description']}"
        )
    return lines


def _load_semantic_atom_lines(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
    limit: int,
) -> list[str]:
    try:
        rows = conn.execute(
            """SELECT atom_type, label, description, source_type, paper_id,
                      snippet, confidence
               FROM semantic_atoms
               WHERE topic_id = ?
                 AND atom_type IN ('method', 'baseline', 'dataset', 'metric', 'gap_signal', 'result')
               ORDER BY confidence DESC, id
               LIMIT ?""",
            (topic_id, limit),
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load topic knowledge context for %s from semantic_atoms: %s",
            task_type,
            exc,
        )
        return []

    lines: list[str] = []
    for row in rows:
        label = row["label"] or row["description"] or row["snippet"]
        if not label:
            continue
        paper = f", paper {row['paper_id']}" if row["paper_id"] else ""
        source = f", source={row['source_type']}" if row["source_type"] else ""
        confidence = f", confidence={float(row['confidence'] or 0):.2f}"
        detail = row["description"] or row["snippet"] or ""
        suffix = f" — {_compact_context_value(detail, max_chars=240)}" if detail else ""
        lines.append(
            f"- {label} ({row['atom_type']}{paper}{source}{confidence}){suffix}"
        )
    return lines


def _load_topic_knowledge_snapshot_lines(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
) -> list[str]:
    try:
        row = conn.execute(
            """
            SELECT tks.coverage_json, pa.payload_json
            FROM topic_knowledge_snapshots tks
            JOIN project_artifacts pa ON pa.id = tks.artifact_id
            WHERE tks.topic_id = ?
              AND tks.status = 'active'
              AND pa.artifact_type = 'topic_knowledge_snapshot'
              AND pa.status = 'active'
              AND COALESCE(pa.stale, 0) = 0
            ORDER BY tks.created_at DESC, tks.id DESC
            LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    except Exception as exc:
        logger.warning(
            "Failed to load topic knowledge context for %s from topic_knowledge_snapshots: %s",
            task_type,
            exc,
        )
        return []

    if row is None:
        return []

    payload = _json_obj(row["payload_json"])
    coverage = _json_obj(row["coverage_json"]) or _json_obj(payload.get("coverage"))
    covered = payload.get("covered") if isinstance(payload.get("covered"), dict) else {}
    weak_spots = (
        payload.get("weak_spots") if isinstance(payload.get("weak_spots"), dict) else {}
    )
    research_state = (
        payload.get("research_state")
        if isinstance(payload.get("research_state"), dict)
        else {}
    )

    lines = ["## Topic Knowledge Snapshot"]
    if coverage:
        coverage_text = ", ".join(
            f"{key}={value}" for key, value in sorted(coverage.items())
        )
        lines.append(f"- Coverage: {coverage_text}")
    if covered:
        for key in ("methods", "datasets", "metrics", "baselines", "claims", "gaps"):
            values = covered.get(key)
            if values:
                lines.append(
                    f"- Covered {key}: {_compact_context_value(values, max_chars=500)}"
                )
    if weak_spots:
        lines.append(
            f"- Weak spots: {_compact_context_value(weak_spots, max_chars=800)}"
        )
    if research_state:
        lines.append(
            f"- Research state: {_compact_context_value(research_state, max_chars=1000)}"
        )
    next_actions = payload.get("next_actions")
    if next_actions:
        lines.append(
            f"- Next actions: {_compact_context_value(next_actions, max_chars=500)}"
        )
    return lines


def _load_algorithm_design_method_context(
    conn: Any,
    topic_id: int,
    *,
    task_type: str,
) -> str:
    """Build design-time method context from current RH schema read models."""

    sections: list[str] = []

    taxonomy_lines = _load_taxonomy_method_lines(
        conn, topic_id, task_type=task_type, limit=30
    )
    if taxonomy_lines:
        sections.append("## Taxonomy Nodes\n" + "\n".join(taxonomy_lines))

    method_atom_lines = _load_method_atom_lines(
        conn, topic_id, task_type=task_type, limit=40
    )
    if method_atom_lines:
        sections.append("## Method Atoms\n" + "\n".join(method_atom_lines))

    semantic_atom_lines = _load_semantic_atom_lines(
        conn, topic_id, task_type=task_type, limit=40
    )
    if semantic_atom_lines:
        sections.append("## Semantic Atoms\n" + "\n".join(semantic_atom_lines))

    snapshot_lines = _load_topic_knowledge_snapshot_lines(
        conn, topic_id, task_type=task_type
    )
    if snapshot_lines:
        sections.append("\n".join(snapshot_lines))

    return "\n\n".join(sections)


def _deep_read_content_to_text(section: str, content: Any) -> str:
    raw = str(content or "").strip()
    if not raw:
        return ""
    parsed: Any
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, dict):
        return _compact_context_value(parsed, max_chars=1200)

    parts: list[str] = []
    fields = (
        ("pass1_summary", "Pass 1 summary"),
        ("pass2_critical", "Pass 2 critical"),
        ("algorithm_walkthrough", "Algorithm walkthrough"),
        ("limitation_analysis", "Limitation analysis"),
        ("reproducibility_assessment", "Reproducibility"),
        ("critical_assessment", "Critical assessment"),
        ("research_implications", "Research implications"),
        ("summary", "Summary"),
        ("notes", "Notes"),
        ("core_idea", "Core idea"),
        ("method_summary", "Method summary"),
        ("key_results", "Key results"),
    )
    for key, label in fields:
        value = parsed.get(key)
        if value:
            parts.append(f"{label}: {_compact_context_value(value, max_chars=700)}")
    if parts:
        return "\n".join(parts)
    return f"{section}: {_compact_context_value(parsed, max_chars=1200)}"


def _load_algorithm_design_deep_read_notes(
    conn: Any,
    paper_ids: list[int],
    *,
    task_type: str,
) -> list[dict[str, Any]]:
    target_ids = [int(pid) for pid in paper_ids[:5]]
    if not target_ids:
        return []

    placeholders = ",".join("?" for _ in target_ids)
    try:
        rows = conn.execute(
            f"""SELECT pa.paper_id, p.title, pa.section, pa.content
                FROM paper_annotations pa
                LEFT JOIN papers p ON p.id = pa.paper_id
                WHERE pa.paper_id IN ({placeholders})
                  AND pa.section IN ('deep_reading', 'paper_card', 'summary',
                                     'methodology', 'limitations')
                  AND COALESCE(pa.content, '') != ''
                ORDER BY pa.paper_id,
                         CASE pa.section
                           WHEN 'deep_reading' THEN 0
                           WHEN 'paper_card' THEN 1
                           WHEN 'summary' THEN 2
                           WHEN 'methodology' THEN 3
                           WHEN 'limitations' THEN 4
                           ELSE 99
                         END,
                         pa.id""",
            target_ids,
        ).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load deep-read context for %s from paper_annotations.section/content: %s",
            task_type,
            exc,
        )
        return []

    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        paper_id = int(row["paper_id"])
        item = grouped.setdefault(
            paper_id,
            {
                "paper_id": paper_id,
                "title": row["title"] or f"Paper {paper_id}",
                "sections": [],
            },
        )
        text = _deep_read_content_to_text(str(row["section"] or ""), row["content"])
        if text:
            item["sections"].append(f"[{row['section']}]\n{text}")

    notes: list[dict[str, Any]] = []
    for paper_id in target_ids:
        item = grouped.get(paper_id)
        if item and item["sections"]:
            notes.append(
                {
                    "paper_id": item["paper_id"],
                    "title": item["title"],
                    "summary": "\n\n".join(item["sections"]),
                }
            )
    return notes


def design_brief_expand(
    *,
    db: Database,
    topic_id: int,
    direction: str,
    constraints: list[str] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "DesignBriefOutput":
    """Expand a research direction into a formal design brief with method slots."""
    from research_harness.primitives.types import DesignBriefOutput

    summary, _paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="design_brief_expand"
    )

    conn = db.connect()
    try:
        gap_context = _load_design_gap_context(
            conn, topic_id, task_type="design_brief_expand"
        )
        method_context = _load_algorithm_design_method_context(
            conn, topic_id, task_type="design_brief_expand"
        )
    finally:
        conn.close()

    constraints_text = "\n".join(f"- {c}" for c in (constraints or []))

    client = _get_client(_model, tier="medium")
    raw = _client_chat(
        client,
        prompts.design_brief_expand_prompt(
            direction=direction,
            gap_context=gap_context,
            method_context=method_context,
            constraints=constraints_text,
        ),
    )
    parsed = _parse_json(raw, primitive="design_brief_expand")

    return DesignBriefOutput(
        problem_definition=str(parsed.get("problem_definition", "")).strip(),
        constraints=[str(c) for c in (parsed.get("constraints") or [])],
        method_slots=[
            s for s in (parsed.get("method_slots") or []) if isinstance(s, dict)
        ],
        blocking_questions=[str(q) for q in (parsed.get("blocking_questions") or [])],
        model_used=client.model,
    )


def design_gap_probe(
    *,
    db: Database,
    topic_id: int,
    brief: dict[str, Any],
    method_inventory: list[dict[str, Any]] | None = None,
    source_profile: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "DesignGapProbeOutput":
    """Probe a design brief for knowledge gaps requiring targeted search/reading."""
    from research_harness.primitives.types import DesignGapProbeOutput

    conn = db.connect()
    try:
        inv_text = _load_algorithm_design_method_context(
            conn, topic_id, task_type="design_gap_probe"
        )
        papers_summary = _load_design_papers_summary(
            conn, topic_id, task_type="design_gap_probe"
        )
    finally:
        conn.close()

    if method_inventory:
        inv_text = "\n".join(
            f"- {m.get('method_name', m.get('name', '?'))} ({m.get('category', '?')})"
            for m in method_inventory
        )

    brief_text = json.dumps(brief, indent=2, default=str)

    client = _get_client(_model, tier="light")
    raw = _client_chat(
        client,
        prompts.design_gap_probe_prompt(
            brief=brief_text,
            method_inventory=inv_text,
            existing_papers_summary=papers_summary,
            source_profile=json.dumps(source_profile or {}, indent=2, default=str),
        ),
    )
    parsed = _parse_json(raw, primitive="design_gap_probe")

    return DesignGapProbeOutput(
        knowledge_gaps=[
            g for g in (parsed.get("knowledge_gaps") or []) if isinstance(g, dict)
        ],
        recommended_actions=[str(a) for a in (parsed.get("recommended_actions") or [])],
        deep_read_targets=[
            int(t)
            for t in (parsed.get("deep_read_targets") or [])
            if isinstance(t, (int, float))
        ],
        model_used=client.model,
        question_resolutions=[
            item
            for item in (parsed.get("question_resolutions") or [])
            if isinstance(item, dict)
        ],
        endpoints=[
            row for row in parsed.get("endpoints") or [] if isinstance(row, dict)
        ],
    )


def algorithm_candidate_generate(
    *,
    db: Database,
    topic_id: int,
    brief: dict[str, Any],
    gap_probe: dict[str, Any] | None = None,
    deep_read_notes: list[dict[str, Any]] | None = None,
    analysis_substrate: dict[str, Any] | None = None,
    taste_mode: str = "",
    _model: str | None = None,
    **_: Any,
) -> "AlgorithmCandidateGenerateOutput":
    """Generate 2-3 algorithm candidates with provenance-tagged components."""
    from research_harness.primitives.types import (
        AlgorithmCandidate,
        AlgorithmCandidateGenerateOutput,
    )

    conn = db.connect()
    try:
        method_inventory = _load_algorithm_design_method_context(
            conn, topic_id, task_type="algorithm_candidate_generate"
        )
    finally:
        conn.close()

    # Collect deep reading notes if available
    dr_text = ""
    if deep_read_notes:
        dr_text = "\n\n".join(
            f"### Paper {n.get('paper_id', '?')}: {n.get('title', '?')}\n{n.get('summary', n.get('notes', ''))}"
            for n in deep_read_notes
        )

    brief_text = json.dumps(brief, indent=2, default=str)
    gap_text = json.dumps(gap_probe, indent=2, default=str) if gap_probe else ""
    ablation_memory = ""
    try:
        from research_harness.evolution.topic.experience import ExperienceStore

        experience_store = ExperienceStore(db)
        experience_store.sync_ablation_memory(topic_id)
        ablation_memory = experience_store.build_ablation_memory_overlay(topic_id)
    except Exception as exc:
        logger.debug("Ablation symbolic memory unavailable: %s", exc)

    # Use medium tier (not heavy) — Opus frequently times out on large
    # prompts when routed through proxies with upstream caps.
    client = _get_client(_model, tier="medium")
    raw = _client_chat(
        client,
        prompts.algorithm_candidate_generate_prompt(
            brief=brief_text,
            method_inventory=method_inventory,
            gap_probe=gap_text,
            deep_read_notes=dr_text,
            ablation_memory=ablation_memory,
            analysis_substrate=(
                json.dumps(analysis_substrate, sort_keys=True, default=str)
                if analysis_substrate
                else ""
            ),
            taste_mode=taste_mode,
        ),
    )
    parsed = _parse_json(raw, primitive="algorithm_candidate_generate")

    candidates: list[AlgorithmCandidate] = []
    for item in parsed.get("candidates", []):
        if not isinstance(item, dict):
            continue
        components = [c for c in (item.get("components") or []) if isinstance(c, dict)]
        provenance_tags = [str(c.get("provenance_tag", "unknown")) for c in components]
        feasibility = (
            item.get("feasibility") if isinstance(item.get("feasibility"), dict) else {}
        )
        notes = str(item.get("feasibility_notes", "")).strip()
        if not notes:
            notes = "; ".join(
                f"{key}={feasibility[key]}"
                for key in ("compute", "data", "n")
                if feasibility.get(key) not in (None, "")
            )
        exhaustion = (
            item.get("exhaustion_test")
            if isinstance(item.get("exhaustion_test"), dict)
            else {}
        )
        irreducible = [
            str(part).strip()
            for part in (item.get("irreducible_components") or [])
            if str(part).strip()
        ]
        candidates.append(
            AlgorithmCandidate(
                name=str(item.get("name", "")).strip(),
                architecture_description=str(
                    item.get("architecture_description", "")
                ).strip(),
                components=components,
                novelty_statement=str(item.get("novelty_statement", "")).strip(),
                feasibility_notes=notes,
                provenance_tags=provenance_tags,
                feasibility=feasibility,
                exhaustion_test=exhaustion,
                irreducible_components=irreducible,
                headline_contrast=(
                    item.get("headline_contrast")
                    if isinstance(item.get("headline_contrast"), dict)
                    else {}
                ),
                strongest_prior=(
                    item.get("strongest_prior")
                    if isinstance(item.get("strongest_prior"), dict)
                    else {}
                ),
            )
        )

    return AlgorithmCandidateGenerateOutput(
        candidates=candidates,
        method_inventory_used=_coerce_int(parsed.get("method_inventory_used"), 0),
        taste_mode=prompts.normalize_taste_mode(taste_mode),
        model_used=client.model,
    )


_PAPER_REF_RE = re.compile(r"\bpapers?\s*(?:id\s*)?[#:=]?\s*(\d{3,7})\b", re.IGNORECASE)


def _text_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, str):
        yield value


def declared_sources(candidate: dict[str, Any]) -> set[int]:
    """Paper ids a candidate says it builds on: component sources and "paper NNNN" mentions."""
    ids = {
        int(row["source_paper_id"])
        for row in candidate.get("components") or []
        if isinstance(row, dict) and isinstance(row.get("source_paper_id"), int)
    }
    prior = candidate.get("strongest_prior")
    if isinstance(prior, dict) and isinstance(prior.get("paper_id"), int):
        ids.add(int(prior["paper_id"]))
    for text in _text_values(candidate):
        ids.update(int(match) for match in _PAPER_REF_RE.findall(text))
    return ids


def _words(text: Any, limit: int = 9) -> str:
    return " ".join(
        re.sub(r"[_/()\[\]{},;:.\"']+", " ", str(text or "")).split()[:limit]
    )


def increment_queries(candidate: dict[str, Any]) -> list[str]:
    """Short method-neighbour queries for the increment, built from its own words.

    No model writes them: the answering component's name and mechanism, the gap it
    closes, and the novelty statement -- the terms a paper that already did the
    increment would be indexed under.
    """
    test = (
        candidate.get("exhaustion_test")
        if isinstance(candidate.get("exhaustion_test"), dict)
        else {}
    )
    answer = re.sub(r"[^a-z0-9]", "", str(test.get("answered_by") or "").lower())
    component = next(
        (
            row
            for row in candidate.get("components") or []
            if isinstance(row, dict)
            and answer
            and re.sub(r"[^a-z0-9]", "", str(row.get("name") or "").lower()) == answer
        ),
        {},
    )
    queries = [
        _words(component.get("name"), 8),
        _words(component.get("details") or component.get("role")),
        _words(test.get("gap_it_leaves")),
        _words(candidate.get("novelty_statement")),
    ]
    return list(dict.fromkeys(query for query in queries if len(query.split()) >= 2))


def candidate_increment(candidate: dict[str, Any]) -> str:
    """The increment a candidate claims: the component that answers its gap, and that gap."""
    test = (
        candidate.get("exhaustion_test")
        if isinstance(candidate.get("exhaustion_test"), dict)
        else {}
    )
    answer = re.sub(r"[^a-z0-9]", "", str(test.get("answered_by") or "").lower())
    component = next(
        (
            row
            for row in candidate.get("components") or []
            if isinstance(row, dict)
            and answer
            and re.sub(r"[^a-z0-9]", "", str(row.get("name") or "").lower()) == answer
        ),
        None,
    )
    parts = []
    if component:
        parts.append(
            f"{component.get('name')}: {component.get('details') or component.get('role') or ''}".strip()
        )
    if test.get("gap_it_leaves"):
        parts.append(
            f"closes the gap left by {test.get('strongest_cheap_reimplementation') or 'the cheap imitator'}: "
            f"{test['gap_it_leaves']}"
        )
    if not parts and candidate.get("novelty_statement"):
        parts.append(str(candidate["novelty_statement"]))
    return "\n".join(parts)


def originality_boundary_check(
    *,
    db: Database,
    topic_id: int,
    candidate: dict[str, Any],
    _model: str | None = None,
    **_: Any,
) -> "OriginalityBoundaryCheckOutput":
    """Is the candidate's increment already published?

    Retrieves method neighbours for the increment (not the ticket title), keeps
    the candidate's declared sources out of the collision set, and asks the judge
    whether a paper outside them already does the increment. Coverage too thin to
    decide is ``unclear`` -- never a finding -- as in RH's novelty certification.
    """
    from research_harness.primitives.types import OriginalityBoundaryCheckOutput

    candidate_name = str(candidate.get("name", "")).strip()
    declared = declared_sources(candidate)
    increment = candidate_increment(candidate)

    captured = _capture_prior_art(
        db=db,
        topic_id=topic_id,
        client=None,
        gap=f"No published method does this: {increment}"[:1500],
        focus="",
        max_candidates=15,
        queries=increment_queries(candidate),
    )
    conn = db.connect()
    try:
        paper_rows = conn.execute(
            """SELECT p.id, p.title, p.year, p.venue, p.doi, p.arxiv_id, p.abstract, p.compiled_summary
               FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
               WHERE pt.topic_id = ? AND pt.relevance IN ('high', 'medium')
               ORDER BY p.year DESC LIMIT 30""",
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    def _key(title: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(title or "").lower())

    declared_rows = [row for row in paper_rows if row["id"] in declared]
    declared_titles = {_key(row["title"]) for row in declared_rows}
    declared_ids = {
        str(value).strip().lower()
        for row in declared_rows
        for value in (row["doi"], row["arxiv_id"])
        if value
    }
    declared_text = "\n".join(
        f"- [Paper {row['id']}] {row['title']} ({row['year'] or '?'})"
        for row in declared_rows
    )

    neighbours: list[str] = []
    seen: set[str] = set()
    for row in paper_rows:
        if row["id"] in declared or _key(row["title"]) in seen:
            continue
        seen.add(_key(row["title"]))
        body = (row["abstract"] or row["compiled_summary"] or "").strip()
        neighbours.append(
            f"### [Paper {row['id']}] {row['title']} ({row['year'] or '?'})\n{body[:600]}"
        )
    retrieved = []
    for paper in captured["candidates"]:
        ids = {
            str(value).strip().lower() for value in (paper.doi, paper.arxiv_id) if value
        }
        if (
            _key(paper.title) in declared_titles
            or ids & declared_ids
            or _key(paper.title) in seen
        ):
            continue
        seen.add(_key(paper.title))
        retrieved.append(
            {
                "title": paper.title,
                "year": paper.year,
                "venue": paper.venue or "",
                "doi": paper.doi or "",
                "arxiv_id": paper.arxiv_id or "",
            }
        )
        body = (paper.abstract or paper.snippet or "").strip()
        neighbours.append(
            f"### [Retrieved] {paper.title} ({paper.year or '?'}, {paper.venue or 'n/a'})\n{body[:600]}"
        )

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.originality_boundary_check_prompt(
            candidate=json.dumps(candidate, indent=2, default=str),
            near_papers_summaries="\n\n".join(neighbours),
            declared_sources=declared_text,
            increment=increment,
        ),
    )
    parsed = _parse_json(raw, primitive="originality_boundary_check")

    def _outside(rows: Any) -> list[dict[str, Any]]:
        return [
            row
            for row in rows or []
            if isinstance(row, dict)
            and row.get("paper_id") not in declared
            and _key(row.get("title")) not in declared_titles
        ]

    verdict = str(parsed.get("novelty_verdict", "")).strip().lower()
    score = _coerce_float(parsed.get("novelty_score"), 0.0)
    published = str(parsed.get("increment_published", "")).strip().lower()
    prior_art = _outside(parsed.get("prior_art"))
    notes = []
    external = set(captured["providers_seen"]) - {
        "local",
        "local_only",
        "multi",
        "papervault",
        "stale_cache",
    }
    failed = {
        str(error).partition(":")[0].strip() for error in captured["provider_errors"]
    }
    evidence = prior_art or _outside(parsed.get("near_matches"))
    if verdict in {"incremental", "too_similar"} and not evidence:
        verdict = "unclear"
        notes.append(
            "the only prior art named was a declared source or none; a source is not a collision"
        )
    if verdict == "novel" and published == "yes" and prior_art:
        verdict, score = "incremental", min(score, 0.59)
        notes.append(
            "the judge found the increment published; verdict follows the evidence"
        )
    if verdict == "novel" and (not neighbours or not external - failed):
        verdict = "unclear"
        notes.append(
            "no external method-neighbour retrieval succeeded; coverage cannot support novel"
        )
    coverage_note = " ".join(
        [str(parsed.get("coverage_note", "")).strip(), *notes]
    ).strip()

    return OriginalityBoundaryCheckOutput(
        candidate_name=str(parsed.get("candidate_name", candidate_name)).strip(),
        near_matches=_outside(parsed.get("near_matches")),
        novelty_verdict=verdict,
        novelty_score=score,
        recommended_modifications=[
            str(m) for m in (parsed.get("recommended_modifications") or [])
        ],
        model_used=client.model,
        increment=str(parsed.get("increment") or increment).strip(),
        increment_published=published,
        prior_art=prior_art,
        declared_sources=sorted(declared),
        retrieved=retrieved,
        queries_used=list(captured["queries"]),
        providers_queried=list(captured["providers_seen"]),
        provider_errors=list(captured["provider_errors"]),
        coverage_note=coverage_note,
        floor=parsed.get("floor") if isinstance(parsed.get("floor"), dict) else {},
    )


def algorithm_design_refine(
    *,
    db: Database,
    topic_id: int,
    candidate: dict[str, Any],
    originality_result: dict[str, Any] | None = None,
    feedback: str = "",
    constraints: list[str] | None = None,
    taste_mode: str = "",
    _model: str | None = None,
    **_: Any,
) -> "AlgorithmDesignRefineOutput":
    """Refine best candidate into a publication-ready research proposal."""
    from research_harness.primitives.types import AlgorithmDesignRefineOutput

    candidate_text = json.dumps(candidate, indent=2, default=str)
    originality_text = (
        json.dumps(originality_result, indent=2, default=str)
        if originality_result
        else ""
    )
    constraints_text = "\n".join(f"- {c}" for c in (constraints or []))

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.algorithm_design_refine_prompt(
            candidate=candidate_text,
            originality_result=originality_text,
            feedback=feedback,
            constraints=constraints_text,
            taste_mode=taste_mode,
            novelty_verdict=str((originality_result or {}).get("novelty_verdict", "")),
        ),
    )
    parsed = _parse_json(raw, primitive="algorithm_design_refine")

    components = [c for c in (parsed.get("components") or []) if isinstance(c, dict)]
    provenance_summary = [
        p for p in (parsed.get("provenance_summary") or []) if isinstance(p, dict)
    ]

    fusion_raw = parsed.get("fusion")
    fusion: dict[str, Any] = dict(fusion_raw) if isinstance(fusion_raw, dict) else {}

    return AlgorithmDesignRefineOutput(
        proposal_title=str(parsed.get("proposal_title", "")).strip(),
        paper_title=str(parsed.get("paper_title", "")).strip(),
        problem_formulation=str(parsed.get("problem_formulation", "")).strip(),
        algorithm_description=str(parsed.get("algorithm_description", "")).strip(),
        components=components,
        novelty_statement=str(parsed.get("novelty_statement", "")).strip(),
        experiment_hooks=[str(h) for h in (parsed.get("experiment_hooks") or [])],
        provenance_summary=provenance_summary,
        taste_mode=prompts.normalize_taste_mode(taste_mode),
        fusion=fusion,
        refinement_posture="calibrator_1_0_to_1_1",
        model_used=client.model,
        study_spec=parsed["study_spec"]
        if isinstance(parsed.get("study_spec"), dict)
        else {},
        finding_responses=[
            row
            for row in parsed.get("finding_responses") or []
            if isinstance(row, dict)
        ],
    )


def algorithm_design_loop(
    *,
    db: Database,
    topic_id: int,
    direction: str,
    max_rounds: int = 3,
    constraints: list[str] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "AlgorithmDesignLoopOutput":
    """Iterative design loop: brief -> gap -> candidates -> originality -> refine.

    Stops when:
      - Best candidate achieves novelty_verdict == "novel" and no critical gaps.
      - max_rounds reached.
    """
    from research_harness.primitives.types import AlgorithmDesignLoopOutput

    briefs: list[Any] = []
    gap_probes: list[Any] = []
    candidates_history: list[Any] = []
    originality_checks: list[Any] = []
    papers_read = 0
    convergence_reason = "max_rounds_reached"
    final_proposal = None

    for round_idx in range(1, max_rounds + 1):
        brief_out = design_brief_expand(
            db=db,
            topic_id=topic_id,
            direction=direction,
            constraints=constraints,
            _model=_model,
        )
        briefs.append(brief_out)
        brief_dict: dict[str, Any] = {
            "problem_definition": brief_out.problem_definition,
            "constraints": list(brief_out.constraints),
            "method_slots": list(brief_out.method_slots),
            "blocking_questions": list(brief_out.blocking_questions),
        }

        gap_out = design_gap_probe(
            db=db,
            topic_id=topic_id,
            brief=brief_dict,
            _model=_model,
        )
        gap_probes.append(gap_out)

        if gap_out.deep_read_targets:
            papers_read += len(gap_out.deep_read_targets)

        deep_read_notes: list[dict[str, Any]] = []
        if gap_out.deep_read_targets:
            conn = db.connect()
            try:
                deep_read_notes = _load_algorithm_design_deep_read_notes(
                    conn,
                    list(gap_out.deep_read_targets),
                    task_type="algorithm_design_loop",
                )
            finally:
                conn.close()

        gap_dict: dict[str, Any] = {
            "knowledge_gaps": list(gap_out.knowledge_gaps),
            "recommended_actions": list(gap_out.recommended_actions),
            "deep_read_targets": list(gap_out.deep_read_targets),
        }

        cand_out = algorithm_candidate_generate(
            db=db,
            topic_id=topic_id,
            brief=brief_dict,
            gap_probe=gap_dict,
            deep_read_notes=deep_read_notes,
            _model=_model,
        )
        candidates_history.append(cand_out)

        if not cand_out.candidates:
            convergence_reason = "no_candidates_generated"
            break

        best = cand_out.candidates[0]
        best_dict: dict[str, Any] = {
            "name": best.name,
            "architecture_description": best.architecture_description,
            "components": list(best.components),
            "novelty_statement": best.novelty_statement,
            "feasibility_notes": best.feasibility_notes,
            "provenance_tags": list(best.provenance_tags),
            "feasibility": dict(best.feasibility),
            "exhaustion_test": dict(best.exhaustion_test),
            "irreducible_components": list(best.irreducible_components),
        }

        orig_out = originality_boundary_check(
            db=db,
            topic_id=topic_id,
            candidate=best_dict,
            _model=_model,
        )
        originality_checks.append(orig_out)

        has_critical_gaps = any(
            isinstance(g, dict) and g.get("severity") in ("critical", "high")
            for g in gap_out.knowledge_gaps
        )
        is_novel = orig_out.novelty_verdict == "novel"

        if is_novel and not has_critical_gaps:
            orig_dict: dict[str, Any] = {
                "candidate_name": orig_out.candidate_name,
                "near_matches": list(orig_out.near_matches),
                "novelty_verdict": orig_out.novelty_verdict,
                "novelty_score": orig_out.novelty_score,
                "recommended_modifications": list(orig_out.recommended_modifications),
            }
            refine_out = algorithm_design_refine(
                db=db,
                topic_id=topic_id,
                candidate=best_dict,
                originality_result=orig_dict,
                constraints=constraints,
                _model=_model,
            )
            return AlgorithmDesignLoopOutput(
                final_proposal=refine_out,
                rounds_completed=round_idx,
                convergence_reason="novel_and_no_critical_gaps",
                briefs=briefs,
                gap_probes=gap_probes,
                candidates_history=candidates_history,
                originality_checks=originality_checks,
                papers_read_during_loop=papers_read,
                model_used=_model or "",
            )

        feedback_parts: list[str] = []
        if not is_novel:
            mods = orig_out.recommended_modifications
            feedback_parts.append(
                f"Novelty verdict: {orig_out.novelty_verdict} (score={orig_out.novelty_score:.2f}). "
                f"Modifications needed: {'; '.join(mods) if mods else 'unspecified'}"
            )
        if has_critical_gaps:
            critical = [
                g
                for g in gap_out.knowledge_gaps
                if isinstance(g, dict) and g.get("severity") in ("critical", "high")
            ]
            feedback_parts.append(
                f"Critical gaps remain: {'; '.join(str(g.get('slot', '?')) for g in critical)}"
            )

        orig_dict = {
            "candidate_name": orig_out.candidate_name,
            "novelty_verdict": orig_out.novelty_verdict,
            "novelty_score": orig_out.novelty_score,
            "recommended_modifications": list(orig_out.recommended_modifications),
        }
        refine_out = algorithm_design_refine(
            db=db,
            topic_id=topic_id,
            candidate=best_dict,
            originality_result=orig_dict,
            feedback="\n".join(feedback_parts),
            constraints=constraints,
            _model=_model,
        )
        final_proposal = refine_out

        direction = (
            f"{direction}\n\n[Round {round_idx} refinement] "
            f"{refine_out.novelty_statement}"
        )

    return AlgorithmDesignLoopOutput(
        final_proposal=final_proposal,
        rounds_completed=max_rounds
        if convergence_reason == "max_rounds_reached"
        else len(briefs),
        convergence_reason=convergence_reason,
        briefs=briefs,
        gap_probes=gap_probes,
        candidates_history=candidates_history,
        originality_checks=originality_checks,
        papers_read_during_loop=papers_read,
        model_used=_model or "",
    )
