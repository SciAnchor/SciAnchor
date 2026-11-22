"""Style fingerprint + zero-hallucination destyle layer — no LLM.

AI flavour is mostly a DISTRIBUTION property (sentence-length collapse,
connective cadence, template paragraphs), not a vocabulary property; the
vocabulary layer already lives in writing_checks (TRUE_AI_CLICHES /
STANDARD_REGISTER_CAPS). This module adds the distribution axes plus the
two zero-hallucination repair mechanisms:

- ``style_fingerprint(text)`` — per-axis metrics + flagged sentences (the
  surgery list a later LLM destyle pass edits; nothing here calls an LLM);
- ``content_invariant(before, after)`` — the per-edit gate: citations,
  numbers, and protected tokens (negations/hedges/quantifiers/modals) must
  be multiset-preserved, no content word may enter from outside the edited
  window, and the text may not grow. Deletion-side drift is a first-class
  failure: dropping "not" or a hedge flips claim strength and is rejected.
- ``destyle_deterministic(text)`` — a closed, curated substitution/deletion
  table applied in pure Python; citations and numbers are re-verified.

Bands are EXEMPLAR-MEASURED (r3): p10/p90 of 60 published pool papers from
the 2026-08-17 contrastive fingerprint run (experiments/destyle-loop). They
stay deliberately loose (p90 side) so false positives stay rare.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from research_harness.primitives.types import ReviewFinding

from .writing_checks import _body_paragraphs

# -- Sentence splitting (abbreviation-safe) -----------------------------------

_ABBREVS = (
    "e.g.",
    "i.e.",
    "et al.",
    "cf.",
    "vs.",
    "Fig.",
    "Figs.",
    "Eq.",
    "Eqs.",
    "Sec.",
    "resp.",
    "approx.",
    "w.r.t.",
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def split_sentences(text: str) -> list[str]:
    masked = str(text or "")
    for abbrev in _ABBREVS:
        masked = masked.replace(abbrev, abbrev.replace(".", "\x00"))
    out = []
    for s in _SENT_SPLIT_RE.split(masked):
        s = s.strip().replace("\x00", ".")
        if s:
            out.append(s)
    return out


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


# -- Fingerprint axes ---------------------------------------------------------

_CONNECTIVE_OPENERS = (
    "moreover",
    "furthermore",
    "additionally",
    "however",
    "notably",
    "importantly",
    "specifically",
    "consequently",
    "therefore",
    "thus",
    "overall",
    "finally",
    "in addition",
    "in particular",
    "in contrast",
    "as a result",
    "on the other hand",
)
_SUBORDINATORS = frozenset(
    "that which while although though because whereas since unless if".split()
)
_CLOSER_OPENERS = (
    "in summary",
    "overall",
    "taken together",
    "in conclusion",
    "collectively",
)
_NEG_PARALLEL_RE = re.compile(
    r"\bnot\s+(?:just|only|merely|simply)\b.{0,80}?\b(?:but|rather)\b",
    re.IGNORECASE | re.DOTALL,
)
_RULE_OF_THREE_RE = re.compile(r"\b\w[\w-]*, \w[\w-]*, (?:and|or) \w[\w-]*\b")
_NOMINAL_RE = re.compile(r"\b\w+(?:tion|sion|ment|ness|ity)s?\b", re.IGNORECASE)

# Curated near-synonym sets LLM drafts rotate through to fake lexical variety
# (contrastive r3: MATTR is the #1 draft-vs-published separator, d=+1.94 —
# published papers REPEAT their terms). Closed list; only members that are
# safe to unify when they name the same referent. Deliberately excluded:
# significant/substantial (statistical meaning), outcome/result (clinical
# term), assess/evaluate kept because the surgery prompt requires
# same-referent before replacing.
ROTATION_SETS: tuple[tuple[str, ...], ...] = (
    ("method", "approach", "technique", "framework", "strategy"),
    ("use", "employ", "leverage", "adopt"),
    ("show", "demonstrate", "reveal", "indicate"),
    ("improve", "enhance", "boost"),
    ("important", "crucial", "critical", "vital", "essential"),
    ("evaluate", "assess"),
)

# ponytail: single global band set measured on the 60-paper pool corpus
# (contrastive run 2026-08-17, p10/p90); per-(venue, domain) bands when the
# EAG corpus pass lands. Two r2 self-harm caps were relaxed on the same
# evidence: published papers open 6% of sentences with a connective and
# repeat paragraph openers freely — over-suppressing both is itself a tell.
EXEMPLAR_BANDS: dict[str, float] = {
    "sentence_len_cv_min": 0.55,  # pub p10 (r2's 0.35 was far too loose)
    "midband_share_max": 0.60,  # non-separating axis (d=-0.08); left loose
    "initial_connective_ratio_max": 0.11,  # pub p90
    "consecutive_connective_openers_max": 1,  # was 0: over-suppression tell
    "negative_parallelism_max": 1,
    "opener_repetition_max": 3,  # was 2: forced opener rotation is a tell
    "clause_stacking_max": 2,
    "closer_habit_ratio_max": 0.25,
    "em_dash_per_1k_max": 1.5,  # pub p90 (was 5.0)
    "lexical_rotation_mattr_max": 0.75,  # pub p90 MATTR-100
    "rule_of_three_per_1k_max": 2.9,  # pub p90 (v1 "report-only" overturned)
    "nominalization_per_1k_max": 87.0,  # pub p90 — generation-side signal
    "hedge_per_1k_max": 8.3,  # pub p90 — generation-side signal
    "subord_per_sent_max": 0.35,  # pub p90
}
# per-1k / diversity axes are noise on short texts; below this they auto-pass
_MIN_WORDS_FOR_RATES = 500


@dataclass
class StyleFlag:
    """One sentence/paragraph needing surgery, tagged with its tell."""

    axis: str
    location: str  # "sent:<i>" or "para:<i>"
    snippet: str
    detail: str = ""
    full: str = ""  # exact substring of the source text — the surgery window
    # per-flag gate extensions (lexical_rotation): the canonical term the
    # rewrite may introduce, and the rotated synonym it may thereby delete
    extra_allowed: tuple[str, ...] = ()
    extra_deletable: tuple[str, ...] = ()


@dataclass
class AxisResult:
    axis: str
    value: float
    passed: bool
    detail: str = ""


@dataclass
class StyleFingerprint:
    axes: list[AxisResult] = field(default_factory=list)
    flags: list[StyleFlag] = field(default_factory=list)
    n_sentences: int = 0
    n_words: int = 0

    @property
    def failed_axes(self) -> list[AxisResult]:
        return [a for a in self.axes if not a.passed]


def _starts_with_connective(sentence: str) -> str:
    low = sentence.lower()
    for c in _CONNECTIVE_OPENERS:
        if low.startswith(c) and low[len(c) : len(c) + 1] in (",", " ", ""):
            return c
    return ""


def _cv(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if not mean:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return (var**0.5) / mean


def _mattr(tokens: list[str], window: int = 100) -> float:
    """Moving-average type-token ratio (lexical diversity)."""
    if len(tokens) < window:
        return len(set(tokens)) / max(len(tokens), 1)
    vals = []
    for i in range(0, len(tokens) - window, window // 2):
        seg = tokens[i : i + window]
        vals.append(len(set(seg)) / window)
    return sum(vals) / len(vals)


def _rotation_groups(tokens: list[str]) -> list[tuple[str, dict[str, int]]]:
    """Detect curated synonym sets a document alternates through.

    A set counts as rotating only when the runner-up member is itself common
    (>=3 uses and >=half the dominant member) — a paper that says "method"
    30x and "approach" twice is repeating its term, not rotating it.
    """
    stem_counts = Counter(_stem(t) for t in tokens)
    out = []
    for group in ROTATION_SETS:
        present = {m: stem_counts[_stem(m)] for m in group if stem_counts[_stem(m)]}
        if len(present) < 2:
            continue
        ranked = sorted(present.values(), reverse=True)
        if ranked[1] >= 3 and ranked[1] * 2 >= ranked[0]:
            dom = max(present, key=lambda m: present[m])
            out.append((dom, present))
    return out


def style_fingerprint(text: str) -> StyleFingerprint:
    """Whole-text distribution fingerprint. Deterministic, no LLM."""
    b = EXEMPLAR_BANDS
    paragraphs = _body_paragraphs(str(text or ""))
    sents_by_para = [split_sentences(p) for p in paragraphs]
    sentences = [s for para in sents_by_para for s in para]
    n_words = sum(len(_words(s)) for s in sentences)
    fp = StyleFingerprint(n_sentences=len(sentences), n_words=n_words)
    if not sentences:
        return fp
    per_1k = 1000.0 / max(n_words, 1)

    # sentence-length collapse: global CV + 18-28-word midband share
    lens = [len(_words(s)) for s in sentences]
    cv = _cv(lens)
    midband = sum(1 for n in lens if 18 <= n <= 28) / len(lens)
    fp.axes.append(
        AxisResult(
            "sentence_len_cv",
            round(cv, 3),
            passed=len(lens) < 8 or cv >= b["sentence_len_cv_min"],
            detail=f"CV of sentence word counts (min {b['sentence_len_cv_min']})",
        )
    )
    fp.axes.append(
        AxisResult(
            "midband_share",
            round(midband, 3),
            passed=len(lens) < 8 or midband <= b["midband_share_max"],
            detail=f"share of 18-28-word sentences (max {b['midband_share_max']})",
        )
    )
    for i, para_sents in enumerate(sents_by_para):
        local = [len(_words(s)) for s in para_sents]
        if len(local) >= 4 and _cv(local) < 0.20:
            fp.flags.append(
                StyleFlag(
                    "sentence_len_cv",
                    f"para:{i}",
                    para_sents[0][:80],
                    f"local CV {_cv(local):.2f} — metronomic rhythm",
                    full=paragraphs[i],
                )
            )

    # connective cadence: opener ratio + back-to-back connective openers
    openers = [_starts_with_connective(s) for s in sentences]
    ratio = sum(1 for o in openers if o) / len(sentences)
    consecutive = 0
    for i in range(1, len(sentences)):
        if openers[i] and openers[i - 1]:
            consecutive += 1
            fp.flags.append(
                StyleFlag(
                    "connective_cadence",
                    f"sent:{i}",
                    sentences[i][:80],
                    f"'{openers[i]}' opener directly after '{openers[i - 1]}'",
                    full=sentences[i],
                )
            )
    fp.axes.append(
        AxisResult(
            "initial_connective_ratio",
            round(ratio, 3),
            passed=ratio <= b["initial_connective_ratio_max"],
            detail=f"sentences opening with a connective (max {b['initial_connective_ratio_max']})",
        )
    )
    fp.axes.append(
        AxisResult(
            "consecutive_connective_openers",
            consecutive,
            passed=consecutive <= b["consecutive_connective_openers_max"],
            detail="back-to-back connective-opened sentences",
        )
    )

    # negative parallelism ("not just X, but Y")
    neg = 0
    for i, s in enumerate(sentences):
        if _NEG_PARALLEL_RE.search(s):
            neg += 1
            fp.flags.append(
                StyleFlag("negative_parallelism", f"sent:{i}", s[:80], full=s)
            )
    fp.axes.append(
        AxisResult(
            "negative_parallelism",
            neg,
            passed=neg <= b["negative_parallelism_max"],
            detail="'not just X but Y' constructions",
        )
    )

    # rule-of-three: GATED since r3 — the v1 "legit lists are everywhere"
    # assumption was overturned by the contrastive run (d=+1.02: drafts
    # drumbeat triads at 2x the published rate)
    rates_ok = n_words < _MIN_WORDS_FOR_RATES  # short text: rate axes auto-pass
    triads = sum(len(_RULE_OF_THREE_RE.findall(s)) for s in sentences)
    triad_rate = round(triads * per_1k, 2)
    triads_passed = rates_ok or triad_rate <= b["rule_of_three_per_1k_max"]
    fp.axes.append(
        AxisResult(
            "rule_of_three",
            triad_rate,
            passed=triads_passed,
            detail=f"'A, B, and C' per 1k words (max {b['rule_of_three_per_1k_max']})",
        )
    )
    if not triads_passed:
        for i, s in enumerate(sentences):
            if _RULE_OF_THREE_RE.search(s):
                fp.flags.append(StyleFlag("rule_of_three", f"sent:{i}", s[:80], full=s))

    # lexical rotation: published papers repeat their terms; drafts rotate
    # synonyms (the #1 contrastive separator). MATTR alone decides pass/fail
    # (calibration: the synonym-set detector fires on 72% of PUBLISHED
    # papers, so it may only LOCATE surgery windows, never fail the axis);
    # flags carry the canonical term so the gate can admit it.
    tokens = [w.lower() for s in sentences for w in _words(s)]
    mattr = round(_mattr(tokens), 3)
    groups = _rotation_groups(tokens)
    rotation_passed = rates_ok or mattr <= b["lexical_rotation_mattr_max"]
    fp.axes.append(
        AxisResult(
            "lexical_rotation",
            mattr,
            passed=rotation_passed,
            detail=(
                f"MATTR-100 (max {b['lexical_rotation_mattr_max']})"
                + (
                    "; rotating sets: "
                    + ", ".join(f"{dict(p)} -> '{d}'" for d, p in groups[:3])
                    if groups
                    else ""
                )
            ),
        )
    )
    if not rotation_passed:
        for dom, present in groups:
            flagged = 0
            for i, s in enumerate(sentences):
                stems = {_stem(w.lower()) for w in _words(s)}
                minority = [m for m in present if m != dom and _stem(m) in stems]
                if not minority:
                    continue
                fp.flags.append(
                    StyleFlag(
                        "lexical_rotation",
                        f"sent:{i}",
                        s[:80],
                        f"rotates {minority} where the document's term is '{dom}'",
                        full=s,
                        extra_allowed=(dom,),
                        extra_deletable=tuple(minority),
                    )
                )
                flagged += 1
                if flagged >= 3:
                    break

    # nominalization + hedge density: generation-side signals (hedges are
    # protected tokens and nominalizations need derivational rewrites, so
    # neither is surgically editable — no flags, no _DESTYLE_STRATEGY entry)
    nominal_rate = round(len(_NOMINAL_RE.findall(" ".join(sentences))) * per_1k, 2)
    fp.axes.append(
        AxisResult(
            "nominalization_per_1k",
            nominal_rate,
            passed=rates_ok or nominal_rate <= b["nominalization_per_1k_max"],
            detail=f"-tion/-ment/-ity tokens per 1k words (max {b['nominalization_per_1k_max']}); fix at generation, not surgery",
        )
    )
    hedge_rate = round(sum(1 for t in tokens if t in _HEDGES) * per_1k, 2)
    fp.axes.append(
        AxisResult(
            "hedge_per_1k",
            hedge_rate,
            passed=rates_ok or hedge_rate <= b["hedge_per_1k_max"],
            detail=f"hedge tokens per 1k words (max {b['hedge_per_1k_max']}); consolidate caveats at generation — surgery may not touch hedges",
        )
    )

    # subordinator density: no own flags; failure licenses clause_stacking
    # windows via _AXIS_TO_FLAG in polish_impls
    subord_rate = round(
        sum(1 for t in tokens if t in _SUBORDINATORS) / len(sentences), 3
    )
    fp.axes.append(
        AxisResult(
            "subord_per_sent",
            subord_rate,
            passed=rates_ok or subord_rate <= b["subord_per_sent_max"],
            detail=f"subordinators per sentence (max {b['subord_per_sent_max']})",
        )
    )

    # paragraph opener repetition (template paragraphs)
    opener_bigrams = Counter(
        " ".join(w.lower() for w in _words(p)[:2])
        for p in paragraphs
        if len(_words(p)) >= 2
    )
    top = opener_bigrams.most_common(1)
    top_count = top[0][1] if top else 0
    fp.axes.append(
        AxisResult(
            "opener_repetition",
            top_count,
            passed=len(paragraphs) < 4 or top_count <= b["opener_repetition_max"],
            detail=(
                f"paragraphs sharing opener '{top[0][0]}'" if top else "no paragraphs"
            ),
        )
    )
    if len(paragraphs) >= 4 and top_count > b["opener_repetition_max"]:
        for i, p in enumerate(paragraphs):
            if " ".join(w.lower() for w in _words(p)[:2]) == top[0][0]:
                fp.flags.append(
                    StyleFlag("opener_repetition", f"para:{i}", p[:80], full=p)
                )

    # clause stacking (>30 words with >=3 subordinators)
    stacked = 0
    for i, s in enumerate(sentences):
        ws = [w.lower() for w in _words(s)]
        subs = sum(1 for w in ws if w in _SUBORDINATORS)
        if len(ws) > 30 and subs >= 3:
            stacked += 1
            fp.flags.append(
                StyleFlag(
                    "clause_stacking",
                    f"sent:{i}",
                    s[:80],
                    f"{len(ws)} words, {subs} subordinators",
                    full=s,
                )
            )
    fp.axes.append(
        AxisResult(
            "clause_stacking",
            stacked,
            passed=stacked <= b["clause_stacking_max"],
            detail="overlong clause-stacked sentences",
        )
    )

    # closer habit ("In summary, ..." paragraph endings)
    multi = [p for p in sents_by_para if len(p) >= 2]
    closers = 0
    for i, para_sents in enumerate(sents_by_para):
        if len(para_sents) < 2:
            continue
        low = para_sents[-1].lower()
        if any(low.startswith(c) for c in _CLOSER_OPENERS):
            closers += 1
            fp.flags.append(
                StyleFlag(
                    "closer_habit", f"para:{i}", para_sents[-1][:80], full=paragraphs[i]
                )
            )
    closer_ratio = closers / len(multi) if multi else 0.0
    fp.axes.append(
        AxisResult(
            "closer_habit",
            round(closer_ratio, 3),
            passed=len(multi) < 3 or closer_ratio <= b["closer_habit_ratio_max"],
            detail="paragraphs ending on a summary-formula sentence",
        )
    )

    # em-dash density
    dashes = sum(s.count("—") + s.count("---") for s in sentences)
    fp.axes.append(
        AxisResult(
            "em_dash_per_1k",
            round(dashes * per_1k, 2),
            passed=dashes * per_1k <= b["em_dash_per_1k_max"],
            detail="em-dashes per 1k words",
        )
    )
    for i, s in enumerate(sentences):
        if s.count("—") + s.count("---") >= 2:
            fp.flags.append(StyleFlag("em_dash_per_1k", f"sent:{i}", s[:80], full=s))

    return fp


def style_fingerprint_findings(text: str) -> list[ReviewFinding]:
    """Failed fingerprint axes as manuscript_polish findings (severity=low)."""
    fp = style_fingerprint(text)
    out: list[ReviewFinding] = []
    for axis in fp.failed_axes:
        examples = [f.snippet for f in fp.flags if f.axis == axis.axis][:2]
        issue = f"{axis.axis}={axis.value} ({axis.detail})"
        if examples:
            issue += "; e.g. " + " | ".join(examples)
        out.append(
            ReviewFinding(
                angle="style_fingerprint",
                severity="low",
                location=axis.axis,
                issue=issue[:500],
                fix="apply a gated destyle edit to the flagged sentences",
            )
        )
    return out


# -- Content-invariant gate (the zero-hallucination contract) -----------------

# Self-contained copies of the citation/identifier patterns (polish_impls has
# equivalents, but importing them would invert the dependency direction once
# polish_impls imports this module).
_CITE_RE = re.compile(
    r"\\cite[tp]?\*?(?:\[[^\]]*\])?\{([^}]*)\}|\[(\d+(?:\s*[,–-]\s*\d+)*)\]"
)
_ID_RE = re.compile(
    r"PMID\s*(\d+)|PMCID\s*(\d+)|(?:^|[^A-Za-z])RH\s+(\d+)|arXiv:\s*(\S+)",
    re.IGNORECASE,
)
_ALLNUM_RE = re.compile(r"\d+(?:\.\d+)?%?")

# Deleting any of these flips or reweights a claim — a style edit may never
# touch them. (Deliberately overlaps WEASEL_WORDS: removing "somewhat" is a
# claim-strength decision for the logic gate / author, not a style edit.)
_NEGATIONS = frozenset("not no nor neither never none cannot without".split())
_HEDGES = frozenset(
    "may might could can appear appears seem seems suggest suggests suggested"
    " approximately roughly likely unlikely possibly potentially presumably"
    " somewhat partially tend tends generally typically usually often rarely"
    " sometimes".split()
)
_QUANTIFIERS = frozenset(
    "all every each only most many few some several both any always".split()
)
_MODALS = frozenset("must should would will shall".split())
_PROTECTED = _NEGATIONS | _HEDGES | _QUANTIFIERS | _MODALS

# content stems a destyle edit MAY delete outright (register filler); anything
# else must remain present in the rewritten window (true redundancy) — r1 rule
# after r0 judges caught "to favor the intervention" silently compressed away.
_FILLER_DELETABLE = frozenset(
    "note noting worth important importantly notable notably interesting"
    " interestingly emphasize emphasized clear clearly obvious obviously"
    " summary conclusion overall collectively essentially basically".split()
)
_DELETABLE_STEMS: frozenset | None = None


def _deletable_stems() -> frozenset:
    """Stems a destyle edit may delete: filler + the curated cliche tables."""
    global _DELETABLE_STEMS
    if _DELETABLE_STEMS is None:
        words = set(_FILLER_DELETABLE)
        for phrase in list(DESTYLE_SUBSTITUTIONS) + list(DESTYLE_DELETIONS):
            words.update(phrase.split())
        _DELETABLE_STEMS = frozenset(_stem(w) for w in words)
    return _DELETABLE_STEMS


# a NEW sentence boundary must consume one of these separators — splitting at
# an unmarked clause boundary rebinds subordinate/purpose clauses (r0 alerts).
_SPLIT_CONSUMABLE = (":", ";", ", and ", ", but ", ", so ", "---", "—")

_FUNCTION_WORDS = (
    frozenset(
        "a an the this that these those it its we our they their is are was were"
        " be been being has have had do does did to of in on for with by from as"
        " at and or but so yet if then than while when where which who whom whose"
        " what into onto over under between among through during within across"
        " per via such same other another more less very also just even still"
        " further first second third finally moreover however therefore thus"
        " hence furthermore additionally specifically respectively here there"
        " how why one two three".split()
    )
    | _PROTECTED
)


def _stem(w: str) -> str:
    """Crude suffix stripper — just enough to accept inflection changes."""
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("ss"):
        pass
    elif w.endswith("s") and len(w) > 3:
        w = w[:-1]
    if w.endswith("ing") and len(w) >= 6:
        w = w[:-3]
    elif w.endswith("ed") and len(w) >= 5:
        w = w[:-2]
    if w.endswith("ly") and len(w) >= 5:
        w = w[:-2]
    return w


def _protected_anchors(text: str) -> Counter:
    """(protected token, next content stem within 3 tokens) pairs — moving a
    hedge/quantifier/negation away from what it modifies changes scope even
    when the word multiset is intact (r1 'often' alerts)."""
    toks = [w.lower() for w in _words(text)]
    pairs: Counter = Counter()
    for i, tok in enumerate(toks):
        if tok not in _PROTECTED:
            continue
        anchor = ""
        for nxt in toks[i + 1 : i + 4]:
            if nxt not in _FUNCTION_WORDS:
                anchor = _stem(nxt)
                break
        pairs[(tok, anchor)] += 1
    return pairs


def _protected_counter(text: str) -> Counter:
    c: Counter = Counter()
    for tok in re.findall(r"[a-z']+", text.lower()):
        if tok.endswith("n't"):
            c["not"] += 1
            tok = tok[:-3]
        if tok in _PROTECTED:
            c[tok] += 1
    return c


def _multiset(regex: re.Pattern, text: str) -> Counter:
    c: Counter = Counter()
    for m in regex.finditer(text):
        key = next((g for g in m.groups() if g), None) if m.groups() else None
        key = (key if key is not None else m.group(0)).replace(" ", "")
        if key:
            c[key] += 1
    return c


def _word_allowed(word: str, source_stems: set[str]) -> bool:
    s = _stem(word)
    if s in source_stems:
        return True
    # prefix fallback for e-drop/doubling ("utilize"/"utilized"); >=4 chars so
    # short function-ish words never cross-match
    return any(
        len(s) >= 4 and len(t) >= 4 and (s.startswith(t) or t.startswith(s))
        for t in source_stems
    )


def content_invariant(
    before: str,
    after: str,
    *,
    extra_allowed: tuple[str, ...] = (),
    extra_deletable: tuple[str, ...] = (),
) -> dict:
    """Gate one destyle edit. Returns {"passed": bool, "issues": [...]}.

    ``extra_allowed`` is for words the curated substitution table introduces;
    ``extra_deletable`` is for a rotated synonym a lexical_rotation flag
    licenses the edit to replace with the document's canonical term.
    """
    issues: list[str] = []
    if _multiset(_CITE_RE, before) != _multiset(_CITE_RE, after):
        issues.append("citation markers changed")
    if _multiset(_ID_RE, before) != _multiset(_ID_RE, after):
        issues.append("evidence identifiers changed")
    b_nums, a_nums = (
        Counter(_ALLNUM_RE.findall(before)),
        Counter(_ALLNUM_RE.findall(after)),
    )
    if b_nums != a_nums:
        delta = (a_nums - b_nums) + (b_nums - a_nums)
        issues.append(f"numbers changed: {sorted(delta)[:5]}")
    b_prot, a_prot = _protected_counter(before), _protected_counter(after)
    if b_prot != a_prot:
        delta = (b_prot - a_prot) + (a_prot - b_prot)
        issues.append(
            f"protected tokens changed (negation/hedge/quantifier/modal): {sorted(delta)[:5]}"
        )
    elif _protected_anchors(before) != _protected_anchors(after):
        moved = _protected_anchors(before) - _protected_anchors(after)
        issues.append(
            f"protected token moved off its target (scope shift): {sorted(moved)[:3]}"
        )
    source_stems = {_stem(w.lower()) for w in _words(before)}
    source_stems |= {
        _stem(w.lower()) for phrase in extra_allowed for w in _words(phrase)
    }
    foreign = sorted(
        {
            w
            for w in _words(after)
            if w.lower() not in _FUNCTION_WORDS
            and not _word_allowed(w.lower(), source_stems)
        }
    )
    if foreign:
        issues.append(f"content words from outside the edit window: {foreign[:5]}")
    if len(after) > max(1.10 * len(before), len(before) + 20):
        issues.append(
            f"grew {len(after) / max(len(before), 1):.2f}x — style edits only shrink"
        )
    n_b, n_a = len(split_sentences(before)), len(split_sentences(after))
    if n_a > n_b + 1:
        issues.append("added more than one sentence boundary")
    if n_a > n_b:
        consumed = sum(before.count(m) - after.count(m) for m in _SPLIT_CONSUMABLE)
        if consumed < n_a - n_b:
            issues.append(
                "split at an unmarked clause boundary (only : ; coordination "
                "or an em-dash may become a sentence break)"
            )
    lost_stems = (
        {_stem(w.lower()) for w in _words(before) if w.lower() not in _FUNCTION_WORDS}
        - {_stem(w.lower()) for w in _words(after)}
        - _deletable_stems()
        - {_stem(w.lower()) for w in extra_deletable}
    )
    if lost_stems:
        issues.append(
            f"content deleted (not filler/redundant): {sorted(lost_stems)[:5]}"
        )
    return {"passed": not issues, "issues": issues}


# -- Deterministic destyle (closed curated table, pure Python) ----------------

# 1:1 meaning-preserving replacements; curated, so exempt from the
# protected-token rule ("a myriad of" -> "many" IS the quantifier).
DESTYLE_SUBSTITUTIONS: dict[str, str] = {
    "delve into": "examine",
    "delves into": "examines",
    "delving into": "examining",
    "shed light on": "clarify",
    "sheds light on": "clarifies",
    "a myriad of": "many",
    "plays a crucial role in": "is central to",
    "plays a pivotal role in": "is central to",
    "in order to": "to",
    "leveraging the power of": "using",
    "harnessing the power of": "using",
    "utilize": "use",
    "utilizes": "uses",
    "utilized": "used",
    "utilizing": "using",
}
# Pure filler: removal changes nothing but register.
DESTYLE_DELETIONS: tuple[str, ...] = (
    "it is worth noting that",
    "it should be noted that",
    "it is important to note that",
    "it is noteworthy that",
    "it is interesting to note that",
)
DESTYLE_RHS_WORDS: tuple[str, ...] = tuple(
    sorted({w for rhs in DESTYLE_SUBSTITUTIONS.values() for w in rhs.split()})
)


@dataclass
class DestyleResult:
    text: str
    changes: list[str] = field(default_factory=list)
    gate: dict = field(default_factory=dict)


def _delete_filler(text: str, phrase: str, changes: list[str]) -> str:
    # sentence-start occurrences: drop phrase, recapitalize a lowercase next
    # word (mixed-case tokens like mRNA are left untouched)
    start_pat = re.compile(
        r"(^|(?<=[.!?])\s+)" + re.escape(phrase) + r",?\s+(\w[\w-]*)",
        re.IGNORECASE,
    )

    def start_repl(m: re.Match) -> str:
        word = m.group(2)
        if word.islower():
            word = word[0].upper() + word[1:]
        return m.group(1) + word

    new = start_pat.sub(start_repl, text)
    # mid-sentence occurrences: plain removal
    new = re.sub(r"\b" + re.escape(phrase) + r",?\s+", "", new, flags=re.IGNORECASE)
    if new != text:
        changes.append(f"deleted '{phrase}'")
    return new


def destyle_deterministic(text: str) -> DestyleResult:
    """Apply the closed table; verify citations/numbers; idempotent."""
    original = str(text or "")
    out = original
    changes: list[str] = []
    for phrase in DESTYLE_DELETIONS:
        out = _delete_filler(out, phrase, changes)
    for phrase, rhs in DESTYLE_SUBSTITUTIONS.items():
        pat = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)

        def repl(m: re.Match, rhs: str = rhs) -> str:
            return rhs[0].upper() + rhs[1:] if m.group(0)[0].isupper() else rhs

        new = pat.sub(repl, out)
        if new != out:
            changes.append(f"'{phrase}' -> '{rhs}'")
            out = new
    gate_issues: list[str] = []
    if _multiset(_CITE_RE, original) != _multiset(_CITE_RE, out):
        gate_issues.append("citation markers changed")
    if Counter(_ALLNUM_RE.findall(original)) != Counter(_ALLNUM_RE.findall(out)):
        gate_issues.append("numbers changed")
    if gate_issues:  # table bug — refuse the whole pass
        return DestyleResult(
            text=original, changes=[], gate={"passed": False, "issues": gate_issues}
        )
    return DestyleResult(text=out, changes=changes, gate={"passed": True, "issues": []})
