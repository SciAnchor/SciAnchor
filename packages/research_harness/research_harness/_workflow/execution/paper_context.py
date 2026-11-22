"""Shared paper context threaded through every section draft.

Sections used to be drafted in isolation: the drafter never saw the core
claim, the contributions, the gaps named in related work, the term registry,
or what earlier sections already said. This module builds one PaperContext
per write run from the validated PAPER_PLAN artifact (already enforced by the
manuscript logic gate), the topic contributions, and the writing-architecture
artifact, then renders a per-section prompt block stating exactly which
promises the section must realize and what the other sections cover.

``build_paper_context`` never raises — drafting must not gain a new hard
dependency; a partially filled context is always acceptable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from research_harness.storage.db import Database

from .writing_rigor import normalize_section_key

logger = logging.getLogger(__name__)

_CONTEXT_HEADER = (
    "## PAPER CONTEXT (single source of truth — the paper YOU are writing)"
)


@dataclass
class PaperContext:
    """Cross-section state for one paper write run."""

    title: str = ""
    one_sentence_claim: str = ""
    central_problem: str = ""
    allowed_focus: list[str] = field(default_factory=list)
    contributions: str = ""
    gaps: list[dict[str, Any]] = field(default_factory=list)
    term_registry: list[dict[str, Any]] = field(default_factory=list)
    promises: list[dict[str, Any]] = field(default_factory=list)
    outline_sections: dict[str, list[str]] = field(default_factory=dict)
    drafted: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "PaperContext":
        if not isinstance(data, Mapping):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        kwargs: dict[str, Any] = {}
        for key in known:
            if key in data and data[key] is not None:
                kwargs[key] = data[key]
        try:
            return cls(**kwargs)
        except (TypeError, ValueError):
            logger.debug("PaperContext.from_dict got malformed payload", exc_info=True)
            return cls()

    def is_empty(self) -> bool:
        return not (
            self.title
            or self.one_sentence_claim
            or self.central_problem
            or self.contributions
            or self.gaps
            or self.term_registry
            or self.promises
            or self.outline_sections
            or self.drafted
        )


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _topic_contributions(db: Database, topic_id: int) -> str:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    return (row["contributions"] or "").strip()


def _writing_architecture_payload(db: Database, topic_id: int) -> Mapping[str, Any]:
    import json as _json

    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'writing_architecture'
              AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    try:
        payload = _json.loads(row["payload_json"] or "{}")
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def build_paper_context(
    db: Database | None,
    topic_id: int | None,
    paper_plan: Mapping[str, Any] | None = None,
    outline: str = "",
) -> PaperContext:
    """Assemble the paper context; partial results are fine, never raises."""
    ctx = PaperContext()
    if db is None or not topic_id:
        return ctx

    try:
        plan = paper_plan
        if not isinstance(plan, Mapping) or not plan:
            from research_harness._selfdev.writing_logic_gate_runtime import (
                _active_paper_plan,
            )

            plan = _active_paper_plan(db, topic_id)

        if isinstance(plan, Mapping):
            core = plan.get("core_claim_contract")
            if isinstance(core, Mapping):
                ctx.one_sentence_claim = _text(core.get("one_sentence_claim"))
                ctx.central_problem = _text(core.get("central_problem"))
                ctx.allowed_focus = _text_list(core.get("allowed_focus"))
                ctx.title = _text(core.get("title") or core.get("working_title"))
            tree = plan.get("argument_tree")
            if isinstance(tree, Mapping):
                ctx.gaps = _mapping_list(tree.get("problems"))
                if not ctx.one_sentence_claim:
                    ctx.one_sentence_claim = _text(tree.get("root_claim"))
            ctx.term_registry = _mapping_list(plan.get("term_registry"))
            ctx.promises = _mapping_list(plan.get("promise_realization_matrix"))
    except Exception:
        logger.debug("paper context: PAPER_PLAN load failed", exc_info=True)

    try:
        ctx.contributions = _topic_contributions(db, int(topic_id))
    except Exception:
        logger.debug("paper context: contributions load failed", exc_info=True)

    try:
        arch = _writing_architecture_payload(db, int(topic_id))
        if not ctx.title:
            ctx.title = _text(arch.get("paper_title"))
        for entry in _mapping_list(arch.get("sections")):
            name = normalize_section_key(_text(entry.get("section")))
            if not name:
                continue
            points = _text_list(entry.get("key_points"))
            strategy = _text(entry.get("argument_strategy"))
            if strategy:
                points = [strategy, *points]
            points.extend(
                f"key evidence: {item}"
                for item in _text_list(entry.get("key_evidence"))[:3]
            )
            if points:
                ctx.outline_sections[name] = points
    except Exception:
        logger.debug("paper context: writing_architecture load failed", exc_info=True)

    if not ctx.title and outline:
        match = re.search(
            r"(?:working\s+)?title\s*[:：]\s*(.+)", outline, re.IGNORECASE
        )
        if match:
            ctx.title = match.group(1).strip()[:200]

    return ctx


def digest_section(content: str, max_chars: int = 600) -> str:
    """Compact digest of a drafted section for later sections to see."""
    text = (content or "").strip()
    if not text:
        return ""
    prose = re.sub(r"\s+", " ", text)
    sentences = re.split(r"(?<=[.!?])\s+", prose)
    parts = [" ".join(sentences[:2])[:320]]
    items = [
        line.strip() for line in text.splitlines() if line.strip().startswith("\\item")
    ]
    if items:
        parts.append(
            "Contributions listed: " + " | ".join(item[:120] for item in items[:4])
        )
    parts.append(f"({len(text.split())} words)")
    return "\n".join(parts)[:max_chars]


def _promise_sections(promise: Mapping[str, Any]) -> tuple[str, set[str]]:
    made_in = normalize_section_key(_text(promise.get("made_in")))
    realized = {
        normalize_section_key(item) for item in _text_list(promise.get("realized_by"))
    }
    return made_in, realized


def render_paper_context_full(ctx: PaperContext, max_chars: int = 6000) -> str:
    """Section-agnostic render for whole-manuscript checks.

    Unlike ``render_paper_context`` this lists EVERY promise with its
    made_in/realized_by mapping, so a consistency pass can verify each one was
    actually delivered somewhere in the manuscript.
    """
    if ctx is None or ctx.is_empty():
        return ""
    lines: list[str] = []
    if ctx.title:
        lines.append(f"Title: {ctx.title}")
    if ctx.one_sentence_claim:
        lines.append(f"Core claim: {ctx.one_sentence_claim}")
    if ctx.central_problem:
        lines.append(f"Central problem: {ctx.central_problem}")
    if ctx.contributions:
        lines.append("Contributions:")
        lines.append(ctx.contributions[:1500])
    if ctx.gaps:
        lines.append("Committed open problems:")
        for gap in ctx.gaps[:3]:
            statement = _text(gap.get("statement"))
            if statement:
                contribution = _text(gap.get("contribution_id"))
                lines.append(
                    f"- [{_text(gap.get('problem_id')) or '?'}] {statement}"
                    + (f" -> contribution {contribution}" if contribution else "")
                )
    if ctx.promises:
        lines.append("Promise realization matrix (verify each is delivered):")
        for promise in ctx.promises:
            label = _text(promise.get("promise"))
            if not label:
                continue
            made_in, realized = _promise_sections(promise)
            realized_note = ", ".join(sorted(realized)) or "?"
            lines.append(
                f'- "{label}" (made in: {made_in or "?"}; must be realized by: {realized_note})'
            )
    if ctx.term_registry:
        lines.append("Term registry (verbatim usage required):")
        for entry in ctx.term_registry[:12]:
            term = _text(entry.get("term"))
            if term:
                lines.append(f"- {term}: {_text(entry.get('definition'))[:160]}")
    return "\n".join(lines).strip()[:max_chars]


def render_paper_context(
    ctx: PaperContext, section: str, max_chars: int = 24000
) -> str:
    """Render the prompt block for one section; returns "" when empty."""
    if ctx is None or ctx.is_empty():
        return ""
    sec = normalize_section_key(section)
    lines: list[str] = [_CONTEXT_HEADER, ""]

    if ctx.title:
        lines.append(f"Title: {ctx.title}")
    if ctx.one_sentence_claim:
        lines.append(f"Core claim: {ctx.one_sentence_claim}")
    if ctx.central_problem:
        lines.append(f"Central problem: {ctx.central_problem}")
    if ctx.allowed_focus:
        lines.append(
            "Allowed focus (do not drift outside): " + "; ".join(ctx.allowed_focus)
        )

    if ctx.contributions:
        lines.append("")
        lines.append("Contributions:")
        lines.append(ctx.contributions[:1500])

    if ctx.gaps:
        lines.append("")
        lines.append("Open problems (each maps to one contribution):")
        for gap in ctx.gaps[:3]:
            statement = _text(gap.get("statement"))
            if not statement:
                continue
            problem_id = _text(gap.get("problem_id")) or "?"
            contribution = _text(gap.get("contribution_id"))
            sections = _text_list(gap.get("section_ids"))
            suffix = f" -> contribution {contribution}" if contribution else ""
            if sections:
                suffix += f"; proven in: {', '.join(sections)}"
            lines.append(f"- [{problem_id}] {statement}{suffix}")

    if ctx.term_registry:
        lines.append("")
        lines.append("Term registry (use these terms verbatim, no synonyms):")
        for entry in ctx.term_registry[:12]:
            term = _text(entry.get("term"))
            definition = _text(entry.get("definition"))
            if term:
                lines.append(f"- {term}: {definition[:160]}")

    made_here = []
    realized_here = []
    for promise in ctx.promises:
        made_in, realized = _promise_sections(promise)
        label = _text(promise.get("promise"))
        if not label:
            continue
        evidence = _text_list(promise.get("evidence_ids"))
        evidence_note = f" (evidence: {', '.join(evidence[:3])})" if evidence else ""
        if sec and sec in realized:
            realized_here.append(f"- {label}{evidence_note}")
        elif sec and made_in == sec:
            made_here.append(f"- {label}")
    if realized_here:
        lines.append("")
        lines.append("Promises this section MUST realize (deliver each with evidence):")
        lines.extend(realized_here)
    if made_here:
        lines.append("")
        lines.append("Promises this section makes (later sections must realize them):")
        lines.extend(made_here)

    if ctx.outline_sections:
        own = ctx.outline_sections.get(sec) or []
        if own:
            lines.append("")
            lines.append("This section's outline key points:")
            lines.extend(f"- {point[:200]}" for point in own[:6])
        others = [
            (name, points)
            for name, points in ctx.outline_sections.items()
            if name != sec and points
        ]
        if others:
            lines.append("")
            lines.append("Scope of other sections (do NOT duplicate their content):")
            for name, points in others:
                lines.append(f"- {name}: {points[0][:150]}")

    # Drafted-sections block. ctx.drafted now holds FULL section texts (older
    # callers may still store short digests — the tail logic degrades cleanly).
    # The immediately preceding section's ENDING is shown verbatim so the next
    # section can open with a real transition; earlier sections are digested.
    # This block is rendered with a reserved budget so a rich plan can never
    # truncate it away (it used to be the first casualty of [:max_chars]).
    drafted_block = ""
    if ctx.drafted:
        drafted = [
            (name, text) for name, text in ctx.drafted.items() if name != sec and text
        ]
        if drafted:
            dlines: list[str] = [
                "",
                "",
                "Already drafted sections (stay consistent with them):",
            ]
            last_name = drafted[-1][0]
            for name, text in drafted:
                dlines.append(f"### {name}")
                if name == last_name:
                    stripped = text.strip()
                    if len(stripped) > 2400:
                        dlines.append("[... section opening omitted ...]")
                    dlines.append(stripped[-2400:])
                    dlines.append(
                        "(this is the immediately preceding section's ending — "
                        "open the new section with a transition that follows from it)"
                    )
                else:
                    dlines.append(digest_section(text, max_chars=900))
            drafted_block = "\n".join(dlines)

    rendered_head = "\n".join(lines).strip()
    if rendered_head == _CONTEXT_HEADER:
        rendered_head = ""
    head_budget = max(0, max_chars - len(drafted_block))
    rendered = (rendered_head[:head_budget] + drafted_block).strip()
    if not rendered or rendered == _CONTEXT_HEADER:
        return ""
    return rendered[:max_chars]
