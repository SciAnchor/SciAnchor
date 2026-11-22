"""Deterministic writing quality checks — no LLM required.

Checks: AI boilerplate phrases, weasel words, word count, section targets,
anti-hedging, anti-repetition, citation coverage, paragraph development.
Used by section_review primitive alongside LLM-based 13-dim scoring.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from research_harness.primitives.types import SECTION_REVIEW_DIMENSIONS

# Re-export SECTION_REVIEW_DIMENSIONS under the name `REVIEW_DIMENSIONS` —
# this module is the unified source of truth for the 13 scoring dimensions
# used by writing primitives and section_review (see TestUnifiedDimensions).
REVIEW_DIMENSIONS = SECTION_REVIEW_DIMENSIONS

# -- Word count targets per section (borrowed from ARC) -----------------------

SECTION_WORD_TARGETS: dict[str, tuple[int, int]] = {
    "title": (5, 14),
    "abstract": (180, 260),
    "introduction": (1200, 1800),
    "related_work": (1500, 2800),
    "related work": (1500, 2800),
    "method": (2000, 3500),
    "methodology": (2000, 3500),
    "experiments": (2500, 4500),
    "experiment": (2500, 4500),
    "results": (1000, 2000),
    "discussion": (600, 1200),
    "conclusion": (250, 500),
    "conclusions": (250, 500),
    "limitations": (200, 500),
    "appendix": (500, 5000),
}

# Minimum citation count per section type (top-venue norms)
SECTION_CITATION_QUOTA: dict[str, int] = {
    "introduction": 15,
    "related_work": 30,
    "related work": 30,
    "method": 5,
    "methodology": 5,
    "experiments": 8,
    "experiment": 8,
    "discussion": 3,
    "abstract": 0,
    "conclusion": 2,
    "conclusions": 2,
}

# -- AI-phrase governance (two layers) ----------------------------------------
#
# Layer 1 — TRUE_AI_CLICHES: phrases that essentially never appear in edited
# top-venue prose. Hard-banned: any occurrence fails the check.
#
# Layer 2 — STANDARD_REGISTER_CAPS: completely normal academic phrasing that
# LLMs merely overuse. The pre-2026-07 behaviour banned these outright, which
# pushed drafting models OUT of the standard scientific register and made them
# invent odd substitutes — the opposite of the intended effect. They are
# allowed with a per-section occurrence cap: AI flavour is a distribution
# property, not a vocabulary property.
#
# UNRESTRICTED (removed from governance entirely): "as shown in Table",
# "as illustrated in Figure", "as depicted in Figure", "as demonstrated in" —
# cross-references are the standard mechanics of a paper, not style tells.

TRUE_AI_CLICHES: frozenset[str] = frozenset(
    {
        "delve into",
        "delves into",
        "delving into",
        "shed light on",
        "sheds light on",
        "in the realm of",
        "in the landscape of",
        "leveraging the power of",
        "harnessing the power of",
        "tapping into the potential",
        "unlocking the potential",
        "paving the way",
        "pave the way",
        "a testament to",
        "groundbreaking",
        "cutting-edge",
        "paradigm shift",
        "it is worth noting that",
        "it should be noted that",
        "it is important to note",
        "it is noteworthy that",
        "it is interesting to note",
        "plays a crucial role",
        "plays a pivotal role",
        "is of paramount importance",
        "is of utmost importance",
        "a myriad of",
        "has garnered significant attention",
        "has gained significant attention",
        "has attracted considerable attention",
        "has received increasing attention",
        "has attracted growing interest",
        "ever-evolving",
        "rapidly evolving landscape",
        "in today's world",
    }
)

STANDARD_REGISTER_CAPS: dict[str, int] = {
    # Connectives: fine, but not as a metronome. Caps RELAXED in r3: the
    # 2026-08-17 contrastive run measured drafts at 0.3% connective-opened
    # sentences vs 6.4% in published papers (d=-1.89) — the caps had pushed
    # models to avoid connectives entirely, itself a detectable tell.
    "moreover": 3,
    "furthermore": 3,
    "additionally": 3,
    "notably": 3,
    "importantly": 3,
    "significantly": 4,
    # Self-reference to the method: THE standard phrasing; generous caps.
    "the proposed method": 5,
    "the proposed approach": 3,
    "the proposed framework": 3,
    "the proposed model": 3,
    "the proposed system": 3,
    "our proposed method": 2,
    # Novelty vocabulary (mirrors the rigor rule: at most 2 uses of "novel").
    "we propose a novel": 1,
    "a novel approach": 1,
    "a novel method": 1,
    "a novel framework": 1,
    # Results phrasing.
    "state-of-the-art results": 2,
    "state-of-the-art performance": 2,
    "achieves state-of-the-art": 2,
    "outperforms state-of-the-art": 2,
    "surpasses state-of-the-art": 1,
    "extensive experiments show": 1,
    "extensive experiments demonstrate": 1,
    "comprehensive experiments": 1,
    "rigorous evaluation": 1,
    "thorough evaluation": 1,
    # Framing / summary phrasing.
    "in this paper, we propose": 1,
    "in this work, we present": 1,
    "in summary": 1,
    "to summarize": 1,
    "to conclude": 1,
    "in conclusion": 1,
    "in the context of": 2,
    "from the perspective of": 2,
    "remains an open challenge": 1,
    "remains an open problem": 1,
    "poses significant challenges": 1,
    "aims to address": 1,
    "aims to bridge the gap": 1,
    "bridge the gap between": 1,
    "fill the gap": 1,
    "close the gap": 1,
    "to this end": 2,
    "to address this issue": 1,
    "to tackle this problem": 1,
    "to overcome this limitation": 1,
    "a comprehensive overview": 1,
    "a comprehensive survey": 1,
    "a comprehensive study": 1,
    "plays an important role": 1,
}

# Backward-compatible union for older callers/tests.
AI_BOILERPLATE_PHRASES: frozenset[str] = TRUE_AI_CLICHES | frozenset(
    STANDARD_REGISTER_CAPS
)

# -- Weasel words / hedging phrases ------------------------------------------
#
# Scientific hedging that is REQUIRED register in many fields is deliberately
# NOT listed here: approximately, roughly, likely, may, might, appear to,
# seems to, tends to, possibly, presumably, "may suggest", "in some cases",
# "under certain conditions". Flagging those forced non-standard substitutes.

WEASEL_WORDS: frozenset[str] = frozenset(
    {
        "somewhat",
        "arguably",
        "fairly",
        "quite",
        "rather",
        "basically",
        "essentially",
        "virtually",
        "practically",
        "seemingly",
        "conceivably",
        "could potentially",
        "it appears that",
        "it seems that",
        "to some extent",
        "to a certain degree",
    }
)

# -- Review dimensions (imported from authoritative source) -------------------


@dataclass
class CheckResult:
    """Result of a single deterministic check."""

    check_name: str
    passed: bool = True
    details: str = ""
    items_found: list[str] = field(default_factory=list)


def check_word_count(
    content: str,
    section: str,
    target_words: int = 0,
    venue: str = "",
) -> CheckResult:
    """Check if word count is within target range; an abstract also within the venue's cap."""
    words = len(content.split())
    section_lower = section.lower().strip()

    if target_words > 0:
        lo, hi = int(target_words * 0.8), int(target_words * 1.2)
    elif section_lower in SECTION_WORD_TARGETS:
        lo, hi = SECTION_WORD_TARGETS[section_lower]
    else:
        return CheckResult(
            check_name="word_count",
            passed=True,
            details=f"Word count: {words} (no target for '{section}')",
        )
    if section_lower == "abstract" and venue:
        from research_harness.primitives.venue_prescription import venue_abstract_max

        cap = venue_abstract_max(venue)
        if cap:  # the same band resolve_venue_prescription gives this venue
            lo, hi = min(lo, round(cap * 0.8)), min(hi, cap)

    passed = lo <= words <= hi
    return CheckResult(
        check_name="word_count",
        passed=passed,
        details=f"Word count: {words}, target: {lo}-{hi}",
    )


def check_ai_boilerplate(content: str) -> CheckResult:
    """Two-layer AI-phrase governance.

    True cliches are hard-banned (any occurrence fails); standard academic
    register is allowed up to a per-section occurrence cap. See the list
    definitions above for the rationale.
    """
    lower = content.lower()

    banned = sorted(p for p in TRUE_AI_CLICHES if p in lower)
    over_cap: list[str] = []
    for phrase, cap in STANDARD_REGISTER_CAPS.items():
        n = lower.count(phrase)
        if n > cap:
            over_cap.append(f"{phrase} x{n} (cap {cap})")

    passed = not banned and not over_cap
    parts: list[str] = []
    if banned:
        parts.append(f"{len(banned)} true AI cliche(s): {', '.join(banned[:5])}")
    if over_cap:
        parts.append(f"{len(over_cap)} over-cap phrase(s): {', '.join(over_cap[:5])}")
    return CheckResult(
        check_name="ai_boilerplate",
        passed=passed,
        details="; ".join(parts) or "No true cliches; standard register within caps",
        items_found=banned + sorted(over_cap),
    )


def check_weasel_words(content: str) -> CheckResult:
    """Detect hedging and weasel words."""
    lower = content.lower()
    found: list[str] = []

    for word in WEASEL_WORDS:
        # Match as whole word/phrase
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, lower):
            found.append(word)

    word_count = len(content.split())
    density = len(found) / max(word_count, 1) * 100

    return CheckResult(
        check_name="weasel_words",
        passed=density < 2.0,  # less than 2% weasel density
        details=f"Found {len(found)} weasel words ({density:.1f}% density)",
        items_found=sorted(found),
    )


def check_repetition(content: str, threshold: int = 3) -> CheckResult:
    """Detect sentence-level repetition (trigram overlap)."""
    sentences = re.split(r"[.!?]+", content)
    sentences = [s.strip().lower() for s in sentences if len(s.strip()) > 20]

    if len(sentences) < 2:
        return CheckResult(
            check_name="repetition", passed=True, details="Too few sentences to check"
        )

    # Extract trigrams from each sentence
    all_trigrams: dict[str, int] = {}
    for sent in sentences:
        words = sent.split()
        for i in range(len(words) - 2):
            trigram = " ".join(words[i : i + 3])
            all_trigrams[trigram] = all_trigrams.get(trigram, 0) + 1

    repeated = [t for t, c in all_trigrams.items() if c >= threshold]

    return CheckResult(
        check_name="repetition",
        passed=len(repeated) <= 2,
        details=f"Found {len(repeated)} repeated trigrams (threshold={threshold})",
        items_found=repeated[:10],
    )


def check_section_structure(content: str, section: str) -> CheckResult:
    """Check basic section structure requirements."""
    issues: list[str] = []

    # Check for empty content
    if not content.strip():
        return CheckResult(
            check_name="section_structure",
            passed=False,
            details="Section is empty",
        )

    # Check for citation presence in key sections
    section_lower = section.lower()
    needs_citations = section_lower in {
        "introduction",
        "related work",
        "related_work",
        "method",
        "methodology",
    }
    has_citations = bool(
        re.search(r"\\cite\{|\\citep\{|\\citet\{|\[[\d,\s]+\]", content)
    )

    if needs_citations and not has_citations:
        issues.append(f"Section '{section}' typically needs citations but none found")

    return CheckResult(
        check_name="section_structure",
        passed=len(issues) == 0,
        details="; ".join(issues) if issues else "Structure OK",
        items_found=issues,
    )


def check_citation_quota(content: str, section: str) -> CheckResult:
    """Check that the section cites at least the venue-norm number of papers."""
    section_lower = section.lower().strip()
    quota = SECTION_CITATION_QUOTA.get(section_lower, 0)
    if quota == 0:
        return CheckResult(
            check_name="citation_quota",
            passed=True,
            details=f"No citation quota for '{section}'",
        )

    # Count distinct citation markers: [N] or [N,M] or \cite{...}
    numeric_markers = set()
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", content):
        for n in m.group(1).split(","):
            numeric_markers.add(n.strip())

    latex_keys = set()
    for m in re.finditer(r"\\cite[pt]?\*?\{([^}]+)\}", content):
        for k in m.group(1).split(","):
            latex_keys.add(k.strip())

    distinct_citations = len(numeric_markers) + len(latex_keys)
    passed = distinct_citations >= quota

    return CheckResult(
        check_name="citation_quota",
        passed=passed,
        details=(
            f"Section '{section}' cites {distinct_citations} distinct papers "
            f"(quota {quota}, {'OK' if passed else 'BELOW QUOTA'})"
        ),
        items_found=[]
        if passed
        else [f"need {quota - distinct_citations} more unique citations"],
    )


def check_overclaiming(content: str) -> CheckResult:
    """Detect overclaiming patterns — unhedged 'first', excessive 'novel'."""
    lower = content.lower()
    issues: list[str] = []

    # "the first" without "to our knowledge" / "to the best of our knowledge"
    first_matches = list(re.finditer(r"\bthe first\b", lower))
    hedged_phrases = [
        "to our knowledge",
        "to the best of our knowledge",
        "among the first",
    ]
    for m in first_matches:
        # Check if hedged within 100 chars before
        context_before = lower[max(0, m.start() - 100) : m.start()]
        if not any(h in context_before for h in hedged_phrases):
            issues.append(f"Unhedged 'the first' at position {m.start()}")

    # Count "novel" usage
    novel_count = len(re.findall(r"\bnovel\b", lower))
    if novel_count > 2:
        issues.append(f"'novel' used {novel_count} times (recommend ≤2)")

    return CheckResult(
        check_name="overclaiming",
        passed=len(issues) == 0,
        details=f"Found {len(issues)} overclaiming issues"
        if issues
        else "No overclaiming detected",
        items_found=issues,
    )


def check_post_table_analysis(content: str, section: str) -> CheckResult:
    """Check that result tables in experiments sections are followed by analysis."""
    section_lower = section.lower()
    if section_lower not in {"experiments", "experiment", "results"}:
        return CheckResult(
            check_name="post_table_analysis",
            passed=True,
            details=f"Not an experiment section ('{section}')",
        )

    # Find table environments
    table_ends = [
        m.end() for m in re.finditer(r"\\end\{table\}|\\end\{tabular\}", content)
    ]
    if not table_ends:
        return CheckResult(
            check_name="post_table_analysis",
            passed=True,
            details="No tables found in section",
        )

    issues: list[str] = []
    for i, end_pos in enumerate(table_ends):
        # Check what follows the table
        after_table = content[end_pos : end_pos + 300].strip()
        # If the next significant content is another table or subsection heading, flag it
        if re.match(r"^\\(subsection|section|begin\{table)", after_table):
            issues.append(f"Table {i + 1}: no analysis text before next section/table")
        elif len(after_table.split()) < 30:
            issues.append(f"Table {i + 1}: fewer than 30 words of analysis after table")

    return CheckResult(
        check_name="post_table_analysis",
        passed=len(issues) == 0,
        details=f"{len(issues)} tables lack post-table analysis"
        if issues
        else "All tables have analysis",
        items_found=issues,
    )


# Paper types for which formal machinery is decoration rather than contribution.
# The gate is opt-in: an unrecognised or unstated type is left alone, because
# the cost of wrongly telling a theory paper to delete its theorems is far
# higher than the cost of missing decoration in an algorithm paper. RH's
# paper_type vocabulary is not centrally fixed (venue_prescription defaults to
# "empirical", callers pass "method", "system", "original-research", ...), so a
# deny-list that fires on everything unknown would fire almost always.
_THEORY_GATED_PAPER_TYPES = frozenset({"algorithm", "system", "systems", "engineering"})


def _normalize_paper_type(paper_type: str) -> str:
    return (paper_type or "").strip().lower().replace("_", "-")


def check_theory_overload(
    content: str, section: str, paper_type: str = ""
) -> CheckResult:
    """Flag formal math that a paper's own type does not warrant.

    The risk this guards against is real but conditional: for an algorithm or
    systems paper, multi-step formal proofs are usually decoration, and
    LLM-generated ones carry a high error rate. For a paper whose contribution
    *is* theoretical, the same environments are the contribution, and flagging
    them inverts the advice. ``paper_type`` decides which regime applies;
    theory-class papers skip the check rather than being told to delete their
    own results.
    """
    if _normalize_paper_type(paper_type) not in _THEORY_GATED_PAPER_TYPES:
        return CheckResult(
            check_name="theory_overload",
            passed=True,
            details=f"Not gated for paper_type={paper_type!r}",
        )
    proof_env_patterns = [
        r"\\begin\{proof\}",
        r"\\begin\{theorem\}",
        r"\\begin\{lemma\}",
        r"\\begin\{corollary\}",
        r"\\begin\{proposition\}",
    ]
    keyword_patterns = [
        r"\\textbf\{Theorem\s+\d",
        r"\\textbf\{Lemma\s+\d",
        r"\\textbf\{Proof\}",
        r"\\textit\{Proof\}",
        r"\bQ\.E\.D\b",
        r"\\qed\b",
        r"\\blacksquare",
        r"\\square",
    ]

    issues: list[str] = []
    proof_count = 0
    theorem_count = 0

    for pat in proof_env_patterns:
        matches = re.findall(pat, content)
        if "proof" in pat:
            proof_count += len(matches)
        else:
            theorem_count += len(matches)

    for pat in keyword_patterns:
        matches = re.findall(pat, content, re.IGNORECASE)
        if "proof" in pat.lower():
            proof_count += len(matches)
        else:
            theorem_count += len(matches)

    if proof_count > 0:
        issues.append(
            f"Found {proof_count} formal proof block(s) — LLM-generated proofs have high error risk. "
            "Replace with informal justification, remarks, or remove."
        )
    if theorem_count > 1:
        issues.append(
            f"Found {theorem_count} theorem/lemma/corollary environments — "
            "at most 1 simple proposition is acceptable for algorithm papers."
        )

    return CheckResult(
        check_name="theory_overload",
        passed=len(issues) == 0,
        details=(
            f"Theory overload: {proof_count} proofs, {theorem_count} theorems"
            if issues
            else "No theory overload detected"
        ),
        items_found=issues,
    )


_LATEX_BLOCK_PREFIXES = (
    "\\begin",
    "\\end",
    "\\item",
    "\\section",
    "\\subsection",
    "\\subsubsection",
    "\\caption",
    "\\label",
    "\\include",
    "%",
    "#",
)


def _body_paragraphs(content: str) -> list[str]:
    """Prose paragraphs only: LaTeX environments and headings are skipped."""
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", content or ""):
        text = block.strip()
        if not text:
            continue
        first_line = text.splitlines()[0].strip()
        if first_line.startswith(_LATEX_BLOCK_PREFIXES):
            continue
        # Mostly-markup blocks (tables pasted without a blank line, etc.)
        latex_lines = sum(1 for ln in text.splitlines() if ln.strip().startswith("\\"))
        if latex_lines > len(text.splitlines()) / 2:
            continue
        paragraphs.append(text)
    return paragraphs


def check_uncited_paragraphs(content: str, section: str) -> CheckResult:
    """Dense-citation sections: every substantial body paragraph cites evidence.

    Applies to introduction and related work, where nearly every factual
    sentence should carry a [N] or \\cite marker; a >40-word paragraph without
    a single citation is unsupported narrative.
    """
    section_lower = section.lower().strip().replace(" ", "_")
    if section_lower not in {"introduction", "intro", "related_work", "related"}:
        return CheckResult(
            check_name="uncited_paragraphs",
            passed=True,
            details=f"No dense-citation requirement for '{section}'",
        )

    offenders: list[str] = []
    for paragraph in _body_paragraphs(content):
        if len(paragraph.split()) <= 40:
            continue
        has_citation = bool(
            re.search(r"\[\d+(?:\s*,\s*\d+)*\]", paragraph)
            or re.search(r"\\cite[pt]?\*?\{", paragraph)
        )
        if not has_citation:
            offenders.append(paragraph[:80].replace("\n", " ") + "…")

    return CheckResult(
        check_name="uncited_paragraphs",
        passed=not offenders,
        details=(
            f"{len(offenders)} paragraph(s) over 40 words carry no citation"
            if offenders
            else "All substantial paragraphs cite evidence"
        ),
        items_found=offenders,
    )


_TABULAR_RE = re.compile(r"\\begin\{tabular\}.*?\\end\{tabular\}", re.S)
_MAGNITUDE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*([KMB])\b")
# Claims about how two quantities relate. When a table reports raw totals and
# the prose says they are matched to within a percent, one of the two is
# describing something the other is not.
_RELATION_CLAIM_RE = re.compile(
    r"\b(?:budget[- ]matched|matched (?:to )?within|differ by|equivalent budget|"
    r"same budget|comparable (?:budget|cost))\b",
    re.I,
)


def check_table_text_agreement(content: str, section: str) -> CheckResult:
    """Catch a table and its prose describing different quantities.

    The failure this exists for: a results table lists per-protocol totals while
    the surrounding text claims the protocols were matched to within a percent.
    Both statements are true of different denominators, so neither is a
    detectable error on its own — and a reviewer who notices discounts every
    other number in the paper. It is cheap to check and expensive to miss.

    Two signals, both deterministic:

    1. A relation claim ("budget-matched", "differ by 1.3%") sits near a table
       whose column header names a bare quantity rather than a rate. The fix is
       usually to relabel the column, not to change the number.
    2. A magnitude written in the prose (2.40M) has no counterpart in any table,
       or vice versa, suggesting one was updated and the other was not.
    """
    issues: list[str] = []
    body = re.sub(r"(?<!\\)%.*", "", content)
    tables = _TABULAR_RE.findall(body)
    if not tables:
        return CheckResult(
            check_name="table_text_agreement",
            passed=True,
            details="No tabular environment in this section",
        )

    prose = _TABULAR_RE.sub(" ", body)

    # A relation claim names a quantity ("budget", "tokens"). Check the column
    # carrying THAT quantity, not the table as a whole: a table can report a
    # rate in one column and a raw total in the next, and it is the column the
    # prose is talking about that has to agree with it.
    _PER_UNIT = (
        "/paper",
        "per paper",
        "/manuscript",
        "per manuscript",
        "/round",
        "rate",
    )
    for claim in _RELATION_CLAIM_RE.finditer(prose):
        window = prose[max(0, claim.start() - 240) : claim.end() + 240].lower()
        subject = next(
            (q for q in ("token", "cost", "budget", "call", "sample") if q in window),
            None,
        )
        if subject is None:
            continue
        for table in tables:
            header = table.split(r"\\")[0].lower()
            columns = [c.strip() for c in header.split("&")]
            named = [c for c in columns if subject in c]
            if named and not any(u in c for c in named for u in _PER_UNIT):
                issues.append(
                    f'prose says "{claim.group(0)}" of a per-unit {subject} budget, '
                    f'but the table column is labelled "{named[0]}" — a raw total. '
                    "Relabel the column or restate the claim against the totals."
                )
                break
        if issues:
            break

    table_magnitudes = {f"{v}{u}" for t in tables for v, u in _MAGNITUDE_RE.findall(t)}
    prose_magnitudes = {f"{v}{u}" for v, u in _MAGNITUDE_RE.findall(prose)}
    orphaned = sorted(table_magnitudes - prose_magnitudes)
    if orphaned and prose_magnitudes:
        issues.append(
            f"magnitude(s) in a table with no mention in the prose: "
            f"{', '.join(orphaned[:5])} — check the two were updated together"
        )

    return CheckResult(
        check_name="table_text_agreement",
        passed=not issues,
        details="; ".join(issues) or "Table and prose describe the same quantities",
        items_found=issues,
    )


def check_number_consistency(content: str) -> CheckResult:
    """Anti-repetition for results: each specific number appears at most twice.

    Restating the same percentage or decimal in new words is filler and an AI
    tell; a number belongs at its first report plus at most one summary
    mention. Only decimals and percentages are counted — bare integers (years,
    counts, section numbers) are too noisy to police.
    """
    counts: dict[str, int] = {}
    for m in re.finditer(r"\b\d+\.\d+\s*\\?%|\b\d+\.\d+\b|\b\d+\s*\\?%", content or ""):
        token = re.sub(r"\s+", "", m.group(0))
        counts[token] = counts.get(token, 0) + 1

    offenders = [
        f"{token} appears {count} times"
        for token, count in sorted(counts.items())
        if count > 2
    ]
    return CheckResult(
        check_name="number_consistency",
        passed=not offenders,
        details=(
            f"{len(offenders)} number(s) repeated more than twice"
            if offenders
            else "No over-repeated numbers"
        ),
        items_found=offenders,
    )


_FORMAL_ENV_RE = re.compile(
    r"\\begin\{(theorem|definition|lemma|proposition|corollary|assumption)\}"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def check_structural_verbosity(content: str, section: str) -> CheckResult:
    """Detect length that comes from structure rather than from padding.

    The other checks here look for bad phrases. A manuscript can pass all of
    them and still be a third longer than it needs to be, because the cost sits
    in how the material is arranged: one definition split across four
    environments, a sentence carrying five clauses joined by semicolons, the
    same point made once per section. Those cost pages, and unlike a stock
    phrase they are invisible to a substring scan.

    Reported as advice, not as a gate: fragmentation is sometimes the right
    call, and a long sentence in a methods section may be carrying real load.
    The check exists to make the cost visible to whoever is deciding.
    """
    issues: list[str] = []

    body = re.sub(r"(?<!\\)%.*", "", content)
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]

    # 1. Adjacent formal environments with no connecting prose. Four
    #    definitions in a row cost four headers and four vertical gaps to say
    #    what one definition can say; they also read as a wall.
    adjacent = 0
    for cur, nxt in zip(paras, paras[1:]):
        if _FORMAL_ENV_RE.search(cur) and _FORMAL_ENV_RE.search(nxt):
            adjacent += 1
    if adjacent >= 2:
        issues.append(
            f"{adjacent} adjacent formal environments with no prose between them — "
            "consider merging those that define one object"
        )

    # 2. Sentences long enough that the reader has to hold too much at once.
    #    The threshold is deliberately high: this is not a style preference,
    #    it flags the outliers that semicolon-chaining produces.
    prose = re.sub(r"\\begin\{.*?\}.*?\\end\{.*?\}", " ", body, flags=re.S)
    prose = re.sub(r"\$[^$]*\$", " M ", prose)
    prose = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", prose)
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(prose) if len(s.split()) > 3]
    overlong = [s for s in sentences if len(s.split()) > 60]
    if overlong:
        worst = max(len(s.split()) for s in overlong)
        issues.append(
            f"{len(overlong)} sentence(s) over 60 words (longest {worst}) — "
            "usually a list that wants to be a list"
        )

    # 3. Claims restated across sections. Distinct from check_repetition, which
    #    works on trigrams inside one section: this looks for a whole clause
    #    reappearing, which is what cross-section duplication actually looks
    #    like once the wording has been varied.
    seen: dict[str, int] = {}
    for s in sentences:
        words = [w.lower() for w in re.findall(r"[a-z]{4,}", s.lower())]
        if len(words) >= 8:
            key = " ".join(sorted(set(words))[:8])
            seen[key] = seen.get(key, 0) + 1
    echoed = [k for k, n in seen.items() if n > 1]
    if echoed:
        issues.append(
            f"{len(echoed)} claim(s) restated with different wording — "
            "keep the statement where it is argued, cite it elsewhere"
        )

    return CheckResult(
        check_name="structural_verbosity",
        passed=not issues,
        details="; ".join(issues) or "No structural verbosity detected",
        items_found=issues,
    )


def structural_revision_directives(content: str, section: str) -> list[str]:
    """Turn structural findings into instructions a reviser can act on.

    ``check_structural_verbosity`` reports that a section has a 111-word
    sentence. That tells a human where to look and tells a model nothing it can
    execute. This renders the same findings as located, bounded edits — quote
    the opening of the offending sentence, say what to do with it, say what not
    to touch — so the detection can drive the revision instead of a person
    having to paraphrase it into feedback prose.

    Returns an empty list when the section is clean, which is the signal for
    the caller to skip the revision entirely rather than ask a model to improve
    something that has no identified defect.
    """
    directives: list[str] = []

    body = re.sub(r"(?<!\\)%.*", "", content)
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]

    prose = re.sub(r"\\begin\{.*?\}.*?\\end\{.*?\}", " ", body, flags=re.S)
    prose = re.sub(r"\$[^$]*\$", " $MATH$ ", prose)
    prose = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", prose)

    for s in _SENTENCE_SPLIT_RE.split(prose):
        n = len(s.split())
        if n <= 60:
            continue
        opening = " ".join(s.split()[:12])
        # A semicolon-chained sentence is an unwritten list; say so explicitly,
        # because "shorten this" invites deletion and we want re-shaping.
        if s.count(";") >= 2:
            directives.append(
                f'Sentence of {n} words starting "{opening}..." chains '
                f"{s.count(';') + 1} items with semicolons. Convert it to an "
                "itemize list or to separate sentences, one item each. Keep "
                "every item; this is a formatting change, not a cut."
            )
        else:
            directives.append(
                f'Sentence of {n} words starting "{opening}..." is too long to '
                "hold in one reading. Split it into two or three sentences at "
                "its natural clause boundaries. Do not drop any clause."
            )

    adjacent = [
        (cur, nxt)
        for cur, nxt in zip(paras, paras[1:])
        if _FORMAL_ENV_RE.search(cur) and _FORMAL_ENV_RE.search(nxt)
    ]
    if len(adjacent) >= 2:
        names = []
        for cur, _ in adjacent:
            m = _FORMAL_ENV_RE.search(cur)
            if m:
                names.append(m.group(1))
        directives.append(
            f"{len(adjacent)} formal environments sit back to back "
            f"({', '.join(names[:4])}). Where consecutive environments define "
            "one object or state two halves of one result, merge them into a "
            "single environment and keep every symbol, every clause, and every "
            "\\label. Where they are genuinely separate results, leave them and "
            "add a sentence of connecting prose instead."
        )

    return directives


# Words that bound a claim rather than decorate it. Deleting one is a cheap way
# to shorten a sentence and an expensive way to change what it says. The list is
# deliberately short: only terms whose removal strictly widens the assertion.
_CLAIM_QUALIFIERS: frozenset[str] = frozenset(
    {
        "randomized",
        "conditional",
        "conditionally",
        "marginal",
        "asymptotically",
        "non-linearly",
        "nonlinearly",
        "monotonically",
        "exactly",
        "at most",
        "at least",
        "up to",
        "almost surely",
        "independently",
        "uniformly",
        "strictly",
        "skewed",
        "per-round",
        "per-accusation",
        "worst-case",
        "anytime-valid",
        "distinct",
    }
)

_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_CITE_RE = re.compile(r"\\cite[a-zA-Z]*\{([^}]+)\}")


_MATH_ENVIRONMENTS = frozenset(
    {
        "equation",
        "align",
        "alignat",
        "flalign",
        "gather",
        "multline",
        "displaymath",
        "math",
        "eqnarray",
        "aligned",
        "alignedat",
        "gathered",
        "split",
    }
)
_MATH_TOKEN = re.compile(
    r"\\(?P<environment>begin|end)\s*\{(?P<name>[A-Za-z]+\*?)\}"
    r"|\\[()[\]]|\$\$?|\\(?:[A-Za-z@]+|.)|%[^\n]*"
)


def _manuscript_math(text: str) -> list[str]:
    """Inventory explicit math regions in source order, without macro expansion."""
    regions, stack = [], []
    start = 0
    for token in _MATH_TOKEN.finditer(text):
        value = token.group()
        environment = token.group("environment")
        name = token.group("name")
        opening, closing = "", ""
        if environment and name.rstrip("*") in _MATH_ENVIRONMENTS:
            if environment == "begin":
                opening = f"environment:{name}"
            else:
                closing = f"environment:{name}"
        elif value in {r"\(", r"\["}:
            opening = {r"\(": r"\)", r"\[": r"\]"}[value]
        elif value in {r"\)", r"\]"}:
            closing = value
        elif value in {"$", "$$"}:
            if stack and stack[-1] == value:
                closing = value
            else:
                opening = value
        if opening:
            if not stack:
                start = token.start()
            stack.append(opening)
        elif closing:
            if not stack or stack.pop() != closing:
                raise ValueError("unbalanced mathematical delimiters")
            if not stack:
                regions.append(text[start : token.end()])
    if stack:
        raise ValueError("unclosed mathematical region")
    return regions


def check_manuscript_math(original: str, revised: str) -> list[str]:
    """Block prose repairs that alter explicit mathematical source or its order."""
    try:
        if _manuscript_math(original) != _manuscript_math(revised):
            return ["math contents or occurrence order changed"]
    except ValueError as exc:
        return [f"math source invalid: {exc}"]
    return []


def revision_damage(original: str, revised: str) -> list[str]:
    """Check a revision against the material it was not allowed to touch.

    A model asked to restructure prose can quietly drop a label, a citation or
    a measured number, and the result still reads well — which is exactly why
    prose-level review misses it. This is the non-model half of the control:
    the model proposes, this decides, and a revision that loses protected
    material is rejected rather than rated.

    Empty list means the revision is safe to accept.
    """
    damage: list[str] = []

    lost_labels = set(_LABEL_RE.findall(original)) - set(_LABEL_RE.findall(revised))
    if lost_labels:
        damage.append(f"dropped \\label: {', '.join(sorted(lost_labels))}")

    lost_cites: set[str] = set()
    for group in _CITE_RE.findall(original):
        lost_cites |= {k.strip() for k in group.split(",") if k.strip()}
    for group in _CITE_RE.findall(revised):
        lost_cites -= {k.strip() for k in group.split(",") if k.strip()}
    if lost_cites:
        damage.append(f"dropped citation: {', '.join(sorted(lost_cites))}")

    # Numbers are compared by occurrence count, not as a set. A set comparison
    # silently passes the substitution that matters most: change one of three
    # occurrences of 0.05 to 0.10 and the value still appears, so a set says
    # nothing was lost. Counting catches it, and counting up as well as down —
    # a number appearing more often than before is also a claim nobody made.
    before = Counter(_NUMBER_RE.findall(original))
    after = Counter(_NUMBER_RE.findall(revised))
    changed = [
        f"{value} x{before[value]} -> x{after.get(value, 0)}"
        for value in before
        if after.get(value, 0) != before[value]
    ]
    if changed:
        damage.append(f"number occurrences changed: {', '.join(sorted(changed)[:6])}")

    env_before = _env_inventory(original)
    env_after = _env_inventory(revised)
    for env, n in env_before.items():
        if env_after.get(env, 0) < n:
            damage.append(f"{env}: {n} -> {env_after.get(env, 0)}")

    # Qualifiers that narrow a claim. Dropping one shortens the sentence and
    # broadens what it asserts, which is the failure a length objective is most
    # likely to produce and a reader is least likely to notice: "increases
    # non-linearly" and "increases" differ by one word and by one claim.
    lost_qualifiers = [
        q
        for q in _CLAIM_QUALIFIERS
        if len(re.findall(rf"\b{re.escape(q)}\b", original, re.I))
        > len(re.findall(rf"\b{re.escape(q)}\b", revised, re.I))
    ]
    if lost_qualifiers:
        damage.append(f"dropped qualifier: {', '.join(sorted(lost_qualifiers)[:6])}")

    return damage


def _env_inventory(text: str) -> dict[str, int]:
    envs = re.findall(r"\\begin\{([a-zA-Z*]+)\}", text)
    counts: dict[str, int] = {}
    for e in envs:
        if e in (
            "theorem",
            "definition",
            "lemma",
            "proposition",
            "corollary",
            "assumption",
            "table",
            "tabular",
            "figure",
            "equation",
            "align",
        ):
            counts[e] = counts.get(e, 0) + 1
    return counts


def check_paragraph_development(content: str, section: str) -> CheckResult:
    """Flag thin (1-2 sentence) body paragraphs and uniform paragraph rhythm.

    Underdeveloped paragraphs are the main reason drafts read as shallow: a
    claim with no evidence or analysis attached. Near-uniform paragraph
    lengths across the section are an AI tell.
    """
    section_lower = section.lower().strip()
    if section_lower in {"abstract", "title"}:
        return CheckResult(
            check_name="paragraph_development",
            passed=True,
            details=f"No paragraph-development requirement for '{section}'",
        )

    paragraphs = _body_paragraphs(content)
    sentence_counts: list[int] = []
    thin: list[str] = []
    for paragraph in paragraphs:
        sentences = [
            s for s in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if s.strip()
        ]
        sentence_counts.append(len(sentences))
        if len(sentences) <= 2 and len(paragraph.split()) > 15:
            thin.append(paragraph[:80].replace("\n", " ") + "…")

    issues = list(thin)
    if len(sentence_counts) >= 4:
        mean = sum(sentence_counts) / len(sentence_counts)
        if mean > 0:
            variance = sum((c - mean) ** 2 for c in sentence_counts) / len(
                sentence_counts
            )
            if (variance**0.5) / mean < 0.15:
                issues.append(
                    f"Paragraph lengths are near-uniform (~{mean:.1f} sentences each) — vary the rhythm"
                )

    return CheckResult(
        check_name="paragraph_development",
        passed=not issues,
        details=(
            f"{len(thin)} thin paragraph(s); uniformity flagged: "
            f"{len(issues) > len(thin)}"
            if issues
            else "Paragraphs are developed and varied"
        ),
        items_found=issues,
    )


def run_all_checks(
    content: str,
    section: str,
    target_words: int = 0,
    paper_type: str = "",
    venue: str = "",
) -> list[CheckResult]:
    """Run all deterministic writing checks on a section.

    ``paper_type`` gates checks whose advice depends on what kind of paper this
    is; see :func:`check_theory_overload`. ``venue`` caps an abstract's band at
    the venue's abstract cap.
    """
    return [
        check_word_count(content, section, target_words, venue),
        check_ai_boilerplate(content),
        check_weasel_words(content),
        check_repetition(content),
        check_section_structure(content, section),
        check_overclaiming(content),
        check_post_table_analysis(content, section),
        check_citation_quota(content, section),
        check_theory_overload(content, section, paper_type),
        check_structural_verbosity(content, section),
        check_table_text_agreement(content, section),
        check_uncited_paragraphs(content, section),
        check_number_consistency(content),
        check_paragraph_development(content, section),
    ]


# -- Logic-tree coverage (EAG-Ladder batch 2; needs the tree, so it is NOT in
#    run_all_checks — callers with a logic_tree payload invoke it directly) ---

_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z-]{4,}")
_KEYWORD_STOP = frozenset(
    "their there these those which where while about should would could between"
    " through during against because therefore however section paper propose"
    " proposed establish establishes measure measures derive derives defend"
    " defends state states claim claims result results".split()
)


def _obligation_keywords(node: dict, max_terms: int = 6) -> list[str]:
    """Deterministic content terms for one obligation (claim + obligation)."""
    text = f"{node.get('claim') or ''} {node.get('obligation') or ''}".lower()
    seen: list[str] = []
    for term in _KEYWORD_RE.findall(text):
        if term in _KEYWORD_STOP or term in seen:
            continue
        seen.append(term)
        if len(seen) >= max_terms:
            break
    return seen


def check_logic_obligation_coverage(
    content: str,
    obligations: list[dict],
    *,
    min_keyword_hits: int = 2,
) -> CheckResult:
    """Which logic-tree obligations does this section fail to touch?

    Deterministic proxy: an obligation counts as covered when at least
    ``min_keyword_hits`` of its content keywords occur in the section text.
    A coarse lower bound on coverage — good for A/B deltas, not for absolute
    claims (documented in the E2 prereg).
    """
    lowered = str(content or "").lower()
    uncovered: list[str] = []
    for node in obligations or []:
        keywords = _obligation_keywords(node if isinstance(node, dict) else {})
        if not keywords:
            continue
        hits = sum(1 for term in keywords if term in lowered)
        if hits < min(min_keyword_hits, len(keywords)):
            uncovered.append(
                f"{node.get('node_id', '?')}: {str(node.get('claim') or '')[:80]}"
            )
    return CheckResult(
        check_name="logic_obligation_coverage",
        passed=not uncovered,
        details=(
            f"{len(uncovered)}/{len(obligations or [])} obligations look "
            "unrealized in this section"
            if uncovered
            else f"all {len(obligations or [])} obligations touched"
        ),
        items_found=uncovered,
    )
