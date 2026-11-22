"""Finish-form contract (rulebook-backed) for EAG appendix/figure planning.

P0: typed appendix modules + case-trace genre seats in the form layer.
P1: exhibit content blueprints, claim→payoff scan, light ablation isomorphism.

FORM + drafting scaffolds only — does not invent metrics or fabricate results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Iterable

# Controlled appendix_plan / appendix_components tokens (underscore form).
# Legacy hyphenated synonyms normalize into these.
APPENDIX_COMPONENT_VOCAB: tuple[str, ...] = (
    "extended_methods",
    "extended_tables",
    "extra_figures",
    "case_study_trace",
    "failure_gallery",
    "prompt_or_protocol_export",
    "instrument_codebook",
    "reporting_checklist",
    "proofs",
    "robustness_checks",
    "implementation_details",
    "hyperparams",
)

_APPENDIX_ALIASES: dict[str, str] = {
    "extended-tables": "extended_tables",
    "extended-table": "extended_tables",
    "extra-figures": "extra_figures",
    "extra-figure": "extra_figures",
    "implementation-details": "implementation_details",
    "robustness-checks": "robustness_checks",
    "robustness": "robustness_checks",
    "case-study": "case_study_trace",
    "case-study-trace": "case_study_trace",
    "case_study": "case_study_trace",
    "walkthrough": "case_study_trace",
    "mechanism_walkthrough": "case_study_trace",
    "repair_trace": "case_study_trace",
    "vignette": "case_study_trace",
    "qual_case": "case_study_trace",
    "failure-gallery": "failure_gallery",
    "failure_cases": "failure_gallery",
    "prompt-export": "prompt_or_protocol_export",
    "prompt_export": "prompt_or_protocol_export",
    "protocol_export": "prompt_or_protocol_export",
    "prompts": "prompt_or_protocol_export",
    "codebook": "instrument_codebook",
    "instrument": "instrument_codebook",
    "questionnaire": "instrument_codebook",
    "checklist": "reporting_checklist",
    "tripod": "reporting_checklist",
    "consort": "reporting_checklist",
    "strobe": "reporting_checklist",
    "stard": "reporting_checklist",
    "proof": "proofs",
    "hyperparameters": "hyperparams",
    "hyper-params": "hyperparams",
}

APPENDIX_VOCAB_PROMPT = "|".join(APPENDIX_COMPONENT_VOCAB)

# Figure-suite roles added for rulebook case-exhibit layer (generative).
FINISH_FIGURE_ROLES_EXTRA: tuple[str, ...] = (
    "case_exhibit",
    "failure_gallery",
)

_MECHANISM_HINT = re.compile(
    r"\b(method|architecture|pipeline|mechanism|model|algorithm|agent|system|"
    r"framework|network|module|ablation|diagnostic|prognostic|segmentation|"
    r"classifier|predictor)\b",
    re.I,
)
# Loose genre words alone are not enough (empty "Case Study" headings).
_CASE_LOOSE = re.compile(
    r"\b(case[_\s-]?study|walkthrough|vignette|worked example|"
    r"representative case|failure case|error analysis|qualitative example|"
    r"theme.?excerpt|repair trace|case_exhibit|failure_gallery)\b",
    re.I,
)
# Evidence seat must look like a real walkthrough, not a distant overview fig.
_CASE_ANCHOR = re.compile(
    r"("
    # Fig. N only counts with panel/walkthrough cue nearby in the same window
    r"\b(?:fig(?:ure)?s?|figs\.?)\s*\.?\s*[sS]?\d+[a-zA-Z]?"
    r".{0,40}(?:\([a-dA-D]\)|panel|input|intermediate|output|heatmap|walkthrough|case)"
    r"|\b(?:appendix|supplementary(?:\s+(?:note|fig|table|information))?|extended data)\b"
    r".{0,60}(?:case|walkthrough|trace|vignette|exhibit|item|note)"
    r"|\([a-dA-D]\)\s*(?:input|output|intermediate|heatmap|mask|excerpt)"
    r"|\b(?:panel|panels)\s+[a-dA-D]\b"
    r"|\b(?:input|intermediate|output)\b.{0,40}\b(?:panel|map|field|prediction|excerpt)\b"
    r"|\b(?:heatmap|overlay)\b.{0,30}\b(?:case|panel|prediction|ground\s*truth)\b"
    r"|\b(?:excerpt|quote)\b.{0,40}\b(?:theme|construct|profile|respondent)\b"
    r")",
    re.I | re.S,
)
_APPENDIX_HEAD = re.compile(
    r"\b(appendix|supplementar(?:y|ies)|extended data|supporting information)\b",
    re.I,
)


def normalize_appendix_token(raw: str) -> str | None:
    """Map free text / legacy token to controlled vocab, or None if unknown."""
    s = re.sub(r"\s+", " ", str(raw or "").strip().lower())
    if not s:
        return None
    s = s.replace(" ", "_").replace("-", "_")
    # direct
    if s in APPENDIX_COMPONENT_VOCAB:
        return s
    # alias with hyphens restored roughly
    compact = str(raw or "").strip().lower().replace(" ", "-")
    if compact in _APPENDIX_ALIASES:
        return _APPENDIX_ALIASES[compact]
    unders = compact.replace("-", "_")
    if unders in _APPENDIX_ALIASES:
        return _APPENDIX_ALIASES[unders]
    if unders in APPENDIX_COMPONENT_VOCAB:
        return unders
    # substring soft match for planner noise like "case study traces (app B)"
    for key, canon in _APPENDIX_ALIASES.items():
        if key.replace("-", "_") in unders or key in str(raw or "").lower():
            return canon
    for canon in APPENDIX_COMPONENT_VOCAB:
        if canon in unders:
            return canon
    return None


def normalize_appendix_plan(items: Iterable[Any]) -> list[str]:
    """Normalize a plan list; drop unknowns; de-dupe preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for it in items or []:
        tok = normalize_appendix_token(str(it))
        if not tok or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def ensure_case_trace_in_appendix_plan(
    plan: list[str],
    *,
    mechanism_paper: bool,
) -> list[str]:
    """Rulebook P0: mechanism papers must seat case_study_trace in appendix_plan."""
    norm = normalize_appendix_plan(plan)
    if mechanism_paper and "case_study_trace" not in norm:
        # Prefer near front after methods-ish modules
        insert_at = 0
        for i, t in enumerate(norm):
            if t in {"extended_methods", "implementation_details"}:
                insert_at = i + 1
        norm.insert(insert_at, "case_study_trace")
    return norm


def looks_like_mechanism_paper(text: str) -> bool:
    if not text:
        return False
    return len(_MECHANISM_HINT.findall(text)) >= 3


def manuscript_has_case_trace_signal(text: str) -> bool:
    """True only when case-genre language co-occurs with an evidence anchor.

    A bare subsection title \"Case Study\" without Fig./Appendix/panel cues
    does **not** count (finish_rulebook M4: keywords ≠ modules).
    """
    if not text:
        return False
    if not _CASE_LOOSE.search(text):
        return False
    # Prefer local windows around each match so a distant Fig.1 overview
    # cannot launder an empty case heading.
    for m in _CASE_LOOSE.finditer(text):
        # Look slightly before (for "Figure 4 case study") and shortly after.
        lo = max(0, m.start() - 50)
        hi = min(len(text), m.end() + 100)
        window = text[lo:hi]
        if _CASE_ANCHOR.search(window):
            return True
    return False


def manuscript_has_appendix_signal(text: str) -> bool:
    if not text:
        return False
    return bool(_APPENDIX_HEAD.search(text))


_CONTRIB_LINE = re.compile(
    r"(?im)^(?:\s*[-*•]|\s*\d+[.)]\s+|\s*\\item\s+)\s*(.{12,200})$"
)
_CONTRIB_HEADER = re.compile(
    r"(?im)^(?:#{1,3}\s*)?(?:contributions?|our contributions?|main contributions?)\s*$"
)
_FIG_REF = re.compile(r"\b(?:fig(?:ure)?s?|figs\.?)\s*\.?\s*([sS]?\d+[a-zA-Z]?)", re.I)
_TAB_REF = re.compile(r"\b(?:tables?|tabs\.?)\s*\.?\s*([sS]?\d+[a-zA-Z]?)", re.I)
_APP_REF = re.compile(
    r"\b(?:appendix|supplementary(?:\s+note|\s+fig|\s+table)?|extended data)\s*"
    r"([A-Z]|\d+)?",
    re.I,
)
_COMPONENT_CLAIM = re.compile(
    r"(?i)\b(?:module|component|branch|encoder|decoder|gate|head|block|layer)\s+"
    r"[A-Za-z][\w\-]{1,24}"
)
_ABLATION_HIT = re.compile(r"(?i)\bablation\b")


def finish_form_findings(manuscript_text: str) -> list[dict[str, str]]:
    """Deterministic polish-oriented findings (rulebook P0+P1 heuristics).

    Returns dicts compatible with ReviewFinding fields (angle/severity/location/issue/fix).
    """
    text = manuscript_text or ""
    findings: list[dict[str, str]] = []
    mech = looks_like_mechanism_paper(text)
    has_case = manuscript_has_case_trace_signal(text)
    has_app = manuscript_has_appendix_signal(text)

    if mech and not has_case:
        findings.append(
            {
                "angle": "finish_form",
                "severity": "high",
                "location": "appendix_or_results",
                "issue": (
                    "Mechanism/model paper lacks an auditable case-trace signal "
                    "(case study / walkthrough / vignette / theme-excerpt / failure gallery)."
                ),
                "fix": (
                    "Add a typed case_study_trace module (main teaser optional) per "
                    "finish_rulebook_v0.1 U-CASE-01 / CS-01 / MED-02 / HSS-03. "
                    "Use build_exhibit_blueprint() for a section skeleton."
                ),
            }
        )
    if mech and not has_app:
        findings.append(
            {
                "angle": "finish_form",
                "severity": "medium",
                "location": "appendix",
                "issue": "No appendix/supplementary second-stage signal on a mechanism-length manuscript.",
                "fix": (
                    "Add a typed AppendixPlan (extended_methods, case_study_trace, "
                    "protocol/instrument as applicable) with named main→SI pointers."
                ),
            }
        )

    payoff = scan_claim_payoff(text)
    if payoff.orphan_contributions:
        n = len(payoff.orphan_contributions)
        sample = "; ".join(payoff.orphan_contributions[:2])
        findings.append(
            {
                "angle": "finish_form",
                "severity": "high" if n >= 2 or mech else "medium",
                "location": "contributions",
                "issue": (
                    f"{n} contribution bullet(s) lack a fig/table/appendix payoff pointer "
                    f"(e.g. “{sample}”)."
                ),
                "fix": (
                    "Each contribution must name its evidence locator (Fig./Table/Appendix). "
                    "Rulebook U-NAR-01."
                ),
            }
        )

    iso = scan_ablation_isomorphism(text)
    if iso.claimed_components and iso.missing_in_ablation:
        findings.append(
            {
                "angle": "finish_form",
                "severity": "medium",
                "location": "ablation",
                "issue": (
                    "Claimed components not clearly reflected in ablation language: "
                    + ", ".join(iso.missing_in_ablation[:6])
                ),
                "fix": (
                    "Align ablation rows with named modules (rulebook U-TAB-03 / CS-04). "
                    "If a component is design-only, label it non-causal explicitly."
                ),
            }
        )
    return findings


def ablation_contract_findings(
    payload: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    """Map experiment coverage_gate ablation contract into finish_form findings.

    Prefer this over pure lexical scan when a structured ablation payload exists
    (canonical_components + ablation_components).
    """
    if not isinstance(payload, Mapping) or not payload:
        return []
    try:
        from research_harness.experiment.coverage_gate import evaluate_ablation_payload
    except Exception:
        return []
    result = evaluate_ablation_payload(dict(payload))
    if not result:
        return []
    verdict = str(result.get("verdict") or "")
    blockers = [str(b) for b in (result.get("blockers") or []) if b]
    if verdict in {"pass", "ok", ""} and not blockers:
        return []
    detail = (
        ", ".join(blockers[:8]) if blockers else verdict or "ablation_contract_failed"
    )
    return [
        {
            "angle": "finish_form",
            "severity": "high"
            if verdict == "blocked" or "mismatch" in detail
            else "medium",
            "location": "ablation_contract",
            "issue": f"Structured ablation contract failed: {detail}",
            "fix": (
                "Make ablation_components match canonical_components (order and set). "
                "Rulebook U-TAB-03; see experiment.coverage_gate."
            ),
        }
    ]


def appendix_plan_prompt_clause() -> str:
    return (
        "appendix_plan MUST be an ordered list of tokens from this controlled vocabulary "
        f"only: [{APPENDIX_VOCAB_PROMPT}]. "
        "For mechanism/method/system/model/clinical-AI/process papers ALWAYS include "
        "case_study_trace (auditable walkthrough/vignette/qual exhibit/repair trace — "
        "not hyperparams). Prefer also failure_gallery when superiority is claimed. "
        "Systems/agent papers should include prompt_or_protocol_export; survey/HSS "
        "instrumented papers should include instrument_codebook; clinical diagnostic/"
        "prognostic papers should include reporting_checklist when applicable. "
        "Do NOT emit free-text appendix blurbs — tokens only."
    )


# --- P1: claim → payoff -----------------------------------------------------


@dataclass(frozen=True)
class ClaimPayoffReport:
    contributions: tuple[str, ...]
    orphan_contributions: tuple[str, ...]
    with_payoff: tuple[str, ...]


def extract_contribution_bullets(text: str) -> list[str]:
    """Best-effort harvest of contribution-like bullets near a contributions header."""
    if not text:
        return []
    lines = text.splitlines()
    bullets: list[str] = []
    in_block = False
    empty_streak = 0
    for line in lines:
        if _CONTRIB_HEADER.search(line.strip()):
            in_block = True
            empty_streak = 0
            continue
        if not in_block:
            # also accept early "We contribute" style lists without header
            continue
        if not line.strip():
            empty_streak += 1
            if empty_streak >= 2 and bullets:
                break
            continue
        empty_streak = 0
        m = _CONTRIB_LINE.match(line)
        if m:
            bullets.append(re.sub(r"\s+", " ", m.group(1)).strip())
        elif bullets and (
            line.strip().startswith("#")
            or re.match(r"^(?:Related|Method|Experiment|Result)", line.strip(), re.I)
        ):
            break
    if bullets:
        return bullets[:12]
    # fallback: any "We propose/introduce" sentences are NOT treated as bullets
    return []


def _has_payoff_pointer(sentence: str) -> bool:
    return bool(
        _FIG_REF.search(sentence)
        or _TAB_REF.search(sentence)
        or _APP_REF.search(sentence)
    )


def scan_claim_payoff(text: str) -> ClaimPayoffReport:
    """Only score *explicit* contribution bullets (header + list).

    Free-prose "we propose…" sentences are too common in methods text to treat
    as orphan claims — that path false-fired on mechanism papers that already
    had a full case walkthrough.
    """
    contribs = extract_contribution_bullets(text)
    orphans: list[str] = []
    ok: list[str] = []
    # Pointer must be in the bullet itself (rulebook: visible in one skim).
    for c in contribs:
        if _has_payoff_pointer(c):
            ok.append(c)
        else:
            orphans.append(c)
    return ClaimPayoffReport(
        contributions=tuple(contribs),
        orphan_contributions=tuple(orphans),
        with_payoff=tuple(ok),
    )


# --- P1: ablation isomorphism (lexical) ------------------------------------


@dataclass(frozen=True)
class AblationIsoReport:
    claimed_components: tuple[str, ...]
    missing_in_ablation: tuple[str, ...]
    has_ablation_section: bool


def scan_ablation_isomorphism(text: str) -> AblationIsoReport:
    text = text or ""
    claimed = []
    seen: set[str] = set()
    for m in _COMPONENT_CLAIM.finditer(text):
        tok = re.sub(r"\s+", " ", m.group(0)).strip().lower()
        # drop generic "module that"
        if len(tok) < 8:
            continue
        if tok not in seen:
            seen.add(tok)
            claimed.append(tok)
        if len(claimed) >= 12:
            break
    has_ab = bool(_ABLATION_HIT.search(text))
    missing: list[str] = []
    if has_ab and claimed:
        # find ablation windows
        parts = re.split(r"(?i)\bablation\b", text)
        ab_blob = " ".join(parts[1:2]) if len(parts) > 1 else text
        ab_l = ab_blob.lower()
        for c in claimed:
            # last token of "module Foo"
            key = c.split()[-1]
            if key not in ab_l and c not in ab_l:
                missing.append(c)
    return AblationIsoReport(
        claimed_components=tuple(claimed),
        missing_in_ablation=tuple(missing),
        has_ablation_section=has_ab,
    )


# --- P1: exhibit content blueprints (draft scaffolds) ----------------------


@dataclass(frozen=True)
class ExhibitBlueprint:
    """Scaffold for drafting a case-trace exhibit (prose + figure intent)."""

    domain_family: str  # cs | medicine | hss
    genre: str
    appendix_token: str
    figure_role: str
    section_title: str
    outline_steps: tuple[str, ...]
    figure_caption_skeleton: str
    drafting_prompt: str
    required_locators: tuple[str, ...]


def infer_domain_family(text: str) -> str:
    t = (text or "").lower()
    if re.search(
        r"\b(patient|cohort|clinical|biopsy|mri|patholog|prognos|diagnos|trial|tripod|consort)\b",
        t,
    ):
        return "medicine"
    if re.search(
        r"\b(survey|interview|questionnaire|likert|construct|respondent|qualitative theme|"
        r"codebook|framework figure|structural equation)\b",
        t,
    ):
        return "hss"
    return "cs"


def build_exhibit_blueprint(
    *,
    domain_family: str | None = None,
    manuscript_hint: str = "",
    genre: str | None = None,
) -> ExhibitBlueprint:
    """Return a domain-appropriate case-trace drafting scaffold (no invented results)."""
    family = (domain_family or infer_domain_family(manuscript_hint) or "cs").lower()
    if family not in {"cs", "medicine", "hss"}:
        family = "cs"

    if family == "medicine":
        g = genre or "patient_vignette"
        steps = (
            "State the clinical unit (de-identified): modality, indication, reference label.",
            "Show model input panel and output panel (heatmap/prob/mask) side by side.",
            "State agreement or error mode vs reference; if error, name the mode.",
            "Point from main text: “Fig. X Case A–D”; put extended plates in SI if needed.",
            "Do not invent pixel values — bind to recorded predictions/assets only.",
        )
        caption = (
            "Representative cases. (a) input; (b) model output; (c) reference; "
            "(d) brief clinical readout. Failures called out when present."
        )
        prompt = (
            "Draft a RESULTS or APPENDIX case-exhibit section for a clinical AI paper. "
            "Use ONLY provided case records/assets. Structure as multipanel vignettes "
            "with input/output/reference. No new metrics. Genre=patient_vignette or "
            "failure_gallery per finish_rulebook MED-02/MED-03."
        )
        return ExhibitBlueprint(
            domain_family="medicine",
            genre=g,
            appendix_token="case_study_trace",
            figure_role="case_exhibit",
            section_title="Representative cases and error modes",
            outline_steps=steps,
            figure_caption_skeleton=caption,
            drafting_prompt=prompt,
            required_locators=("Fig. case plate", "Appendix/SI case note"),
        )

    if family == "hss":
        g = genre or "qual_case_embedded"
        steps = (
            "Restate the construct or profile the exhibit is meant to illustrate.",
            "Provide theme×excerpt table or embedded case with source tags.",
            "Link each excerpt back to the framework figure or hypothesis path.",
            "If measures are claimed, ensure instrument_codebook appendix is listed.",
            "Do not invent interview quotes — use only deposited excerpts.",
        )
        caption = (
            "Qualitative exhibit. Themes with representative excerpts; "
            "each row tags construct/profile."
        )
        prompt = (
            "Draft a qualitative exhibit or case appendix for an empirical social-science "
            "paper. Prefer theme×excerpt tables tied to constructs. Use only provided "
            "excerpts/codebook. finish_rulebook HSS-03/HSS-04."
        )
        return ExhibitBlueprint(
            domain_family="hss",
            genre=g,
            appendix_token="case_study_trace",
            figure_role="case_exhibit",
            section_title="Qualitative exhibits",
            outline_steps=steps,
            figure_caption_skeleton=caption,
            drafting_prompt=prompt,
            required_locators=("Table theme×excerpt", "Appendix instrument_codebook"),
        )

    # cs default
    g = genre or "mechanism_walkthrough"
    steps = (
        "Pick one concrete input (example id from records).",
        "Walk ordered modules: input → intermediate representation → output.",
        "Show where the method diverges from a baseline on that same input if available.",
        "Optional failure case with named mode.",
        "Main may teaser one panel; appendix holds full trace. No invented tensors.",
    )
    caption = (
        "Case walkthrough. (a) input; (b–c) intermediate fields/maps; "
        "(d) final prediction; (e) optional failure mode."
    )
    prompt = (
        "Draft a mechanism walkthrough or repair-trace section for a CS method/system paper. "
        "One concrete input through modules with intermediate artifacts. Use only provided "
        "records/assets. finish_rulebook CS-01/CS-03. Prefer role=case_exhibit figure."
    )
    return ExhibitBlueprint(
        domain_family="cs",
        genre=g,
        appendix_token="case_study_trace",
        figure_role="case_exhibit",
        section_title="Case study / mechanism walkthrough",
        outline_steps=steps,
        figure_caption_skeleton=caption,
        drafting_prompt=prompt,
        required_locators=("Fig. case_exhibit", "Appendix case_study_trace"),
    )


def exhibit_blueprint_as_prompt_block(bp: ExhibitBlueprint) -> str:
    """Inject into WRITE/section_draft prompts."""
    steps = "\n".join(f"  {i}. {s}" for i, s in enumerate(bp.outline_steps, 1))
    return "\n".join(
        [
            f"EXHIBIT CONTENT CONTRACT ({bp.domain_family} / {bp.genre}) — binding scaffold:",
            f"- Section title suggestion: {bp.section_title}",
            f"- appendix_plan token required: {bp.appendix_token}",
            f"- figure_suite role required: {bp.figure_role}",
            f"- Caption skeleton: {bp.figure_caption_skeleton}",
            "- Drafting steps:",
            steps,
            f"- Locators that must appear in prose: {', '.join(bp.required_locators)}",
            f"- Drafter brief: {bp.drafting_prompt}",
            "- Never invent measurements, quotes, or pixel-level outputs not in records.",
        ]
    )


def domain_appendix_extras(domain_family: str, text: str = "") -> list[str]:
    """Extra appendix tokens commonly required by domain profiles."""
    d = (domain_family or "").lower()
    t = text or ""
    if d == "medicine":
        out = ["extended_methods"]
        if re.search(r"(?i)\b(diagnos|prognos|clinical|patient|cohort|trial)\b", t):
            out.insert(0, "reporting_checklist")
        return out
    if d == "hss":
        out = []
        if re.search(r"(?i)\b(survey|scale|questionnaire|instrument|likert|item)\b", t):
            out.append("instrument_codebook")
        return out
    if d == "cs":
        if re.search(r"(?i)\b(agent|prompt|llm|protocol|tool[-\s]?use)\b", t):
            return ["prompt_or_protocol_export"]
        return []
    return []


def enrich_appendix_plan_for_domain(
    plan: list[str], domain_family: str, *, mechanism: bool, text: str = ""
) -> list[str]:
    """Normalize, seat case_trace if mechanism, add light domain extras."""
    norm = ensure_case_trace_in_appendix_plan(plan, mechanism_paper=mechanism)
    for tok in domain_appendix_extras(domain_family, text):
        if tok not in norm:
            norm.append(tok)
    return normalize_appendix_plan(norm)
