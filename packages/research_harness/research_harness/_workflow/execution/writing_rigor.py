"""Always-on writing-rigor rules, per-section methodology, and domain overlays.

Single source of truth for the static writing-quality floor injected into
every section draft/revise prompt. Encodes the methodology from
``skills/paper-writing/SKILL.md`` (six-move introduction, 3-gap related work,
five-sentence abstract) and the claim boundaries from
``skills/domain-writing-*/SKILL.md`` so executable prompts and interactive
skill guidance cannot drift apart.

Dynamic guidance (WritingSkillAggregator strategies, per-topic writing
lessons) is layered on top by callers; these constants guarantee a section is
never drafted with zero methodology.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PAPER_RIGOR_RULES = """## SCIENTIFIC RIGOR RULES (apply to every section)

Evidence and claims:
- EVIDENCE-BOUNDING: every quantitative or comparative claim must be backed by
  a number that appears in the evidence list or in this paper's own stated
  results. If the number is not yet known, write an explicit placeholder such
  as X.X\\% — NEVER invent a plausible-looking value.
- CITATION DENSITY: in the introduction and related work, nearly every
  sentence stating a fact about the field carries a [N] citation; the only
  uncited sentences are the ones describing OUR approach. Cite the ORIGINAL
  paper that introduced a method or result, not a survey that mentions it.
- FAILURE-AWARE REPORTING: report settings or regimes where the method loses
  as well as wins, and state the suspected reason. A results narrative with no
  losses reads as cherry-picking.
- TERMINOLOGY: one term per concept for the whole paper. When a TERM REGISTRY
  is provided in the paper context, use those terms verbatim; never introduce
  a synonym for a registered term. Do NOT rotate near-synonyms
  (method/approach/technique, use/employ/leverage, show/demonstrate/reveal)
  to avoid repetition — published papers repeat their terms; rotation is a
  measurable AI tell.

Paragraph discipline — every body paragraph follows this shape:
1. Topic sentence stating the paragraph's single claim
2. Evidence: data, citations, or a worked argument supporting it
3. Analysis: what the evidence means and why it matters here
4. Transition that advances the argument to the next paragraph
- No body paragraph under 3 sentences; develop the point or merge it.
- No bullet lists in body prose. The contributions itemize in the introduction
  and explicitly requested tables/algorithms are the only exceptions.

Repetition and hedging:
- Each specific number appears at most twice in a section (first report, plus
  optionally one summary mention); never restate the same finding in new words
  to fill space.
- State results plainly. Consolidate caveats into the Limitations discussion
  once instead of hedging every sentence. Published papers average ~4 hedge
  words (may/likely/suggests/typically) per 1000 words; drafts overshoot —
  hedge only where the uncertainty is real.
- Prefer verbs over nominalizations: "we evaluate X" not "the evaluation of
  X is performed". Draft prose carries ~35% more -tion/-ment/-ity nouns than
  published prose; heavy nominalization reads as machine register.

PROHIBITED — true AI cliches (never use, zero tolerance):
- "delve into", "it is important to note", "it is worth noting"
- "in the realm of", "a myriad of", "shed light on"
- "pave the way", "a testament to", "plays a crucial role"
- "has attracted growing interest", "has become increasingly important"
- "leveraging/harnessing the power of", "unlocking the potential"

ALLOWED but capped — standard academic register (use naturally, never as a
metronome; at most ~3 uses per section of any one connective):
- "furthermore", "moreover", "additionally", "notably", "significantly"
- "the proposed method", "in conclusion", "in the context of"
- "extensive experiments show", "state-of-the-art"
- Sentence-initial connectives (However/Moreover/Thus/In contrast) are NORMAL
  logical signposts: published papers open roughly 1 sentence in 16 with one.
  USE them at that rate to mark real logical joints — a section with no
  connectives at all reads as disconnected and is itself a machine tell.
  Just never chain them sentence after sentence.
- Cross-references ("as shown in Table 2", "as illustrated in Figure 1") and
  quantitative hedges ("approximately", "likely", "may") are NORMAL scientific
  register — use them wherever natural; never invent substitutes for them.

Other prohibitions:
- Overuse of em dashes (maximum 2 per page)
- Starting consecutive paragraphs with the same word or structure
- Using "the first" without "to our knowledge" or "among the first"
- Using "novel" more than 2 times total

REQUIRED style:
- Vary paragraph length (3-8 sentences per paragraph, not uniform)
- Vary sentence structure: mix short declarative with longer compound
  sentences — but never contort syntax just to avoid repeating a sentence
  opening; natural prose repeats "We ..."/"The ..." openers freely
- Prefer active voice; use passive only when the actor is unknown or irrelevant
- Use precise, discipline-specific vocabulary rather than generic academic filler
- Every factual claim must reference evidence via [N] markers
- Transitions between paragraphs should advance the argument, not just summarize
- Hedge novelty claims with "to our knowledge" or "among the first"
"""


PER_SECTION_TIPS: dict[str, str] = {
    "abstract": """## ABSTRACT METHODOLOGY (five-sentence formula)

Write the abstract as exactly five moves, one or two sentences each:
1. What we did — "We introduce / prove / demonstrate ..." (the contribution,
   not the field)
2. Why the problem is hard and important — one concrete reason, not a platitude
3. How we did it — the key mechanism, phrased with searchable technical keywords
4. What evidence we have — the datasets, benchmarks, or analyses used
5. The most memorable number — the single strongest quantitative result

Deletion test: if the first sentence could open any paper in this area
("Large language models have achieved remarkable success..."), delete it and
start directly at move 1.
""",
    "introduction": """## INTRODUCTION METHODOLOGY

- Move-1 packing rule: the opening 2-3 sentences must simultaneously convey
  (a) application urgency with a concrete number, (b) academic momentum
  (e.g., recent top-venue activity), and (c) named industrial or lab efforts
  — data, not adjectives.
- Gap statements must be STRUCTURAL ("cannot express X because Y"), never
  merely quantitative ("accuracy is still low").
- Contribution template — apply to every itemized contribution: state the
  concept being transformed, the before-to-after reframing, the technical
  means, and the concrete benefit, and name the section or table that will
  prove it. Pattern: "We transform <concept> from <old paradigm> to
  <new paradigm> via <technique>, yielding <benefit> (Section N / Table N)."
""",
    "related_work": """## RELATED WORK METHODOLOGY (3-gap / 3-contribution symmetry)

- Synthesize AT MOST 3 open problems across all families, and make each map
  one-to-one onto one of our contributions.
- For each family: PROGRESS FIRST (what the family achieved, citing its
  strongest members), THEN the shared STRUCTURAL barrier ("assumes
  stationarity", "requires labeled pairs") — never a purely quantitative
  complaint.
- Close the section with a positioning sentence of the form: "Our work
  addresses (1) through <contribution 1>, (2) through <contribution 2>, and
  (3) through <contribution 3>."
- Synthesis over enumeration: group papers by shared idea; never one paper per
  sentence in sequence.
""",
    "method": """## METHOD METHODOLOGY

- Every major design choice needs a 1-2 sentence WHY: the rationale versus the
  obvious simpler alternative, citing prior work where the alternative was
  tried.
- State clearly on which axis the method is "first", if any, and hedge it
  ("to our knowledge").
- Every displayed equation is followed by an intuition sentence in prose — no
  orphan math.
- Complexity or cost analysis appears once, near the end of the section.
""",
    "experiments": """## EXPERIMENTS METHODOLOGY

- Claim-first narrative: open each experiment subsection with the claim it
  tests ("This experiment evaluates whether ..."), then the setup, then the
  result table or figure as evidence.
- Per-regime reporting: when a result spans datasets or regimes, report per
  regime; aggregate-only numbers cannot support robustness or generality
  claims.
- Win/loss diagnosis after every table: where we win, where we lose, and why.
- End each experiment group with a one-paragraph Takeaway.
""",
    "discussion": """## DISCUSSION METHODOLOGY

- Interpret, don't repeat: connect results back to the paper's core claim and
  to the gaps named in related work.
- Include an honest failure and boundary analysis: where the method is
  expected to break and why.
- Future work items must be specific consequences of THIS paper's findings,
  not a generic wish list.
""",
    "conclusion": """## CONCLUSION METHODOLOGY

- Mirror the introduction's claims with the delivered numbers — every promise
  made in the introduction is either confirmed with its result here or
  explicitly scoped down.
- No new claims, no new citations, no new concepts in the conclusion.
- One honest limitation sentence; end on the concrete contribution, not a
  grand vision.
""",
    "limitations": """## LIMITATIONS METHODOLOGY

- Each limitation names the affected claim, the boundary condition, and the
  consequence for the reader — not vague modesty.
- Order limitations by severity, and include at least one that a skeptical
  reviewer would raise unprompted.
""",
}


DOMAIN_OVERLAYS: dict[str, str] = {
    "stem": """## DOMAIN OVERLAY: STEM / ENGINEERING

- Performance, novelty, and generalization claims stay inside the tested
  task/dataset/system boundary; make no claims about untested regimes.
- Always disclose: datasets, metrics, baselines, ablations, implementation and
  reproducibility details (or state where they will appear).
- Baselines must represent current practice; if a strong recent baseline is
  excluded, say so explicitly and give the reason.
""",
    "biomedical": """## DOMAIN OVERLAY: BIOMEDICAL

- Match claim strength to study design: observational or retrospective work
  must not use causal or treatment-recommendation language.
- Report effect sizes with uncertainty (95% CI or mean +/- sd), cohort or
  sample characteristics, and ethics/consent statements where applicable.
- Mechanism claims need mechanistic evidence; correlation alone is not enough.
""",
    "social_science": """## DOMAIN OVERLAY: SOCIAL SCIENCE

- Cross-sectional designs forbid causal, temporal, or mechanism-proof
  language; use association wording.
- Disclose constructs, instruments and measures, sample and sampling frame,
  and the identification strategy behind any causal claim.
- Distinguish statistical significance from practical significance.
""",
    "humanities": """## DOMAIN OVERLAY: HUMANITIES

- Do NOT import benchmark/baseline/ablation/metric rhetoric; the argument is
  interpretive and source-grounded.
- Every interpretive claim ties to primary sources: name the corpus, archive,
  edition, or translation used.
- Situate claims in historical and critical context; acknowledge competing
  interpretations explicitly.
""",
    "law_policy": """## DOMAIN OVERLAY: LAW / POLICY

- Separate four claim types explicitly: legal authority (statute or precedent,
  with jurisdiction), empirical policy evidence, normative argument, and
  implementation feasibility — never blend them in one sentence.
- Name the jurisdiction and authority for every doctrinal statement.
- Policy recommendations must state stakeholders, tradeoffs, and enforcement
  feasibility.
""",
}


_SECTION_ALIASES: dict[str, str] = {
    "intro": "introduction",
    "related work": "related_work",
    "related-work": "related_work",
    "related": "related_work",
    "methods": "method",
    "methodology": "method",
    "approach": "method",
    "proposed_method": "method",
    "experiment": "experiments",
    "results": "experiments",
    "evaluation": "experiments",
    "conclusions": "conclusion",
}

_DISCIPLINE_TO_DOMAIN: dict[str, str] = {
    # STEM
    "ai": "stem",
    "ml": "stem",
    "cs": "stem",
    "computer_science": "stem",
    "data": "stem",
    "engineering": "stem",
    "physical_science": "stem",
    "stem": "stem",
    "systems": "stem",
    # Biomedical
    "biomedical": "biomedical",
    "clinical": "biomedical",
    "life_science": "biomedical",
    "medical": "biomedical",
    "medicine": "biomedical",
    "public_health": "biomedical",
    # Social science
    "communication": "social_science",
    "economics": "social_science",
    "edu": "social_science",
    "education": "social_science",
    "political_science": "social_science",
    "psy": "social_science",
    "psychology": "social_science",
    "social_science": "social_science",
    "sociology": "social_science",
    # Humanities
    "archive": "humanities",
    "art_history": "humanities",
    "cultural_studies": "humanities",
    "history": "humanities",
    "humanities": "humanities",
    "literary_studies": "humanities",
    "philosophy": "humanities",
    # Law / policy
    "governance": "law_policy",
    "law": "law_policy",
    "law_policy": "law_policy",
    "policy": "law_policy",
    "regulation": "law_policy",
}


def normalize_section_key(section: str) -> str:
    key = (section or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _SECTION_ALIASES.get(
        key, _SECTION_ALIASES.get((section or "").strip().lower(), key)
    )


def resolve_domain_key(paper_plan: Mapping[str, Any] | None) -> str:
    """Map a PAPER_PLAN payload to one of the five domain overlay keys."""
    if not isinstance(paper_plan, Mapping):
        return "stem"

    profile = paper_plan.get("domain_writing_profile")
    if isinstance(profile, Mapping):
        skill = str(profile.get("domain_skill") or "").strip().lower()
        if skill.startswith("domain-writing-"):
            skill = skill[len("domain-writing-") :]
        key = skill.replace("-", "_")
        if key in DOMAIN_OVERLAYS:
            return key

    paper_profile = paper_plan.get("paper_profile")
    if isinstance(paper_profile, Mapping):
        discipline = (
            str(paper_profile.get("discipline") or "").strip().lower().replace("-", "_")
        )
        if discipline in _DISCIPLINE_TO_DOMAIN:
            return _DISCIPLINE_TO_DOMAIN[discipline]

    return "stem"


def build_rigor_block(section: str, domain_key: str = "stem") -> str:
    """Compose the static guidance block for one section draft/revise prompt.

    One base ruleset + one per-section methodology tip + one domain overlay;
    the composition is what keeps 8 sections x 5 domains from exploding into
    40 bespoke prompts.
    """
    parts = [PAPER_RIGOR_RULES]
    tip = PER_SECTION_TIPS.get(normalize_section_key(section))
    if tip:
        parts.append(tip)
    overlay = DOMAIN_OVERLAYS.get((domain_key or "").strip().lower())
    if overlay:
        parts.append(overlay)
    return "\n\n".join(part.strip() for part in parts)
