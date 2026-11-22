"""Project certification: separate novelty refutation from promotion.

This module used to collapse novelty, methodology, significance, and rigor into
a single binary GO/NO-GO whose documented meaning was "stop and switch
direction". That shape caused a specific, recorded failure: a *methodology*
problem, or a single retrieval verdict, would be written down as though the
research area itself had been exhausted, and the resulting field-level
conclusion then suppressed later candidates.

Two artifacts are produced instead, and they are never allowed to overwrite each
other:

``NoveltyVerdict``
    Answers only: is the core contribution refuted by the evidence actually
    retrieved? Three states, always scoped to a candidate version. Never
    influenced by methodology, significance, rigor, or resources.

``PromotionDecision``
    Answers only: should this candidate advance now? Four states. May consume a
    novelty verdict, never rewrites one. A candidate can be
    ``not_refuted_by_retrieved_evidence`` and still ``hold`` for resource or
    quality reasons, and a ``refuted`` candidate may still leave a residual for
    a new candidate version.

Three rules follow from the failure this replaces:

1. A ``gap_ground_verify`` verdict is a statement about *retrieval coverage*,
   not about project value. ``occupied`` alone can no longer refute a candidate;
   it needs a corroborating reviewer judgement on the novelty axis.
2. When coverage is insufficient the verdict is ``unclear``. Emitting
   ``not_refuted_by_retrieved_evidence`` on thin evidence would launder a
   retrieval failure into a positive finding.
3. No output may assert anything about a field, domain, or research area. That
   is enforced by :func:`find_field_level_claims`, not by prompt wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Reviewer axes the panel must cover (matches the 4-reviewer ICLR panel).
REVIEW_AXES = ("novelty", "methodology", "significance", "rigor")

#: The only axis that may inform a novelty verdict. The rest inform promotion.
NOVELTY_AXIS = "novelty"
PROMOTION_AXES = tuple(axis for axis in REVIEW_AXES if axis != NOVELTY_AXIS)

#: Candidate-level novelty states. Deliberately absent: anything that could name
#: a field, such as `red_ocean`, `ceiling`, or `exhausted_field`.
NOVELTY_VERDICTS = ("refuted", "not_refuted_by_retrieved_evidence", "unclear")

#: Promotion states. `incubate` and `hold` are the paths the old binary gate
#: lacked, and their absence is what turned every non-GO into "switch direction".
PROMOTION_DECISIONS = ("advance", "incubate", "hold", "stop")

#: A novelty verdict is only ever about one candidate version.
NOVELTY_SCOPE_KIND = "candidate_version"

# Venue bars: (per-reviewer floor, panel mean bar). The target is now read.
VENUE_BARS: dict[str, tuple[float, float]] = {
    "iclr-main": (5, 6.0),
    "neurips-main": (5, 6.0),
    "icml-main": (5, 6.0),
    "aaai-main": (5, 6.0),
    "workshop": (4, 5.0),
    # Journal tiers (found live, three-line program 2026-08-16: every journal
    # target fell to the strictest CS-conference bar).
    "journal-flagship": (5, 6.0),  # Nature/Science/npj DM-class selectivity
    "journal-selective": (4, 5.25),  # solid SSCI/SCI Q1-Q2 (e.g. HSSC)
    "journal-sound-science": (4, 5.0),  # soundness-based (e.g. Sci Reports)
}
_STRICTEST_BAR = (5, 6.0)

_BLOCKING_REVIEWER_VERDICTS = {"no-commit", "occupied", "reject"}

#: The verdicts `gap_ground_verify` is contracted to return.
KNOWN_AUTO_VERDICTS = frozenset(
    {"open", "occupied", "partially_occupied", "inconclusive"}
)

#: Verdicts that mean retrieval could not establish coverage either way. An
#: unrecognised string joins them: an upstream contract drift must not be read
#: as evidence that coverage was adequate.
_INCONCLUSIVE_AUTO_VERDICTS = {"", "inconclusive"}


def _coverage_established(auto: str) -> bool:
    return auto in KNOWN_AUTO_VERDICTS and auto not in _INCONCLUSIVE_AUTO_VERDICTS


# Detecting a field-level claim by looking for the word "field" fails on the
# sentence that actually caused the problem, because a research area is usually
# named rather than described: "the panorama campaign already found
# automated-research saturated". So the rule is inverted. An exhaustion term
# must carry an explicit candidate/lane/snapshot scope, and may never be applied
# to a field/domain/area at all.
_FIELD_SCOPE = r"(?:field|domain|area|research space|领域|全域|方向空间)"
_EXHAUSTION = (
    r"(?:ceiling|saturat\w*|exhaust\w*|red[- ]ocean|no room|"
    r"nothing left|all directions occupied|stop searching|"
    r"天花板|饱和|穷尽|红海|没有(?:创新)?空间)"
)
#: Scope qualifiers that make an exhaustion statement admissible.
_SCOPE_QUALIFIER = (
    r"(?:candidate|dossier|version|query famil\w+|query lane|lane|retrieval|"
    r"snapshot|as of|cutoff|budget|this cluster|"
    r"候选|查询族|检索|快照|截至|预算)"
)

_FIELD_SCOPED_EXHAUSTION = (
    re.compile(rf"{_FIELD_SCOPE}[^.。\n]{{0,60}}{_EXHAUSTION}", re.IGNORECASE),
    re.compile(rf"{_EXHAUSTION}[^.。\n]{{0,60}}{_FIELD_SCOPE}", re.IGNORECASE),
)
_EXHAUSTION_TERM = re.compile(_EXHAUSTION, re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"[.。;；\n]")
_QUALIFIED = re.compile(_SCOPE_QUALIFIER, re.IGNORECASE)


class FieldLevelClaimError(ValueError):
    """Raised when an artifact asserts that a whole field is exhausted."""


def find_field_level_claims(text: str) -> list[str]:
    """Return unqualified field-level exhaustion claims found in ``text``.

    This is the mechanism behind the plan's ``promoted_field_ceiling_violations``
    metric. Candidate refutations, retrieval-lane stops, and scoped
    competition-density statements are legitimate and must pass; only claims
    that a field/domain/area is saturated, exhausted, or at a ceiling are
    rejected. Rejecting all negative output would fake safety.
    """
    body = text or ""
    matches: list[str] = []
    for pattern in _FIELD_SCOPED_EXHAUSTION:
        matches.extend(match.group(0).strip() for match in pattern.finditer(body))
    # An exhaustion term with no candidate/lane/snapshot scope in its sentence
    # is a field-level claim regardless of how the subject is spelled.
    for sentence in _SENTENCE_SPLIT.split(body):
        if _EXHAUSTION_TERM.search(sentence) and not _QUALIFIED.search(sentence):
            matches.append(sentence.strip())
    return sorted(set(matches))


def assert_no_field_level_claim(text: str, *, where: str = "artifact") -> None:
    found = find_field_level_claims(text)
    if found:
        raise FieldLevelClaimError(
            f"{where} contains unqualified field-level exhaustion claim(s): {found}"
        )


@dataclass
class ReviewerScore:
    axis: str
    overall: float  # ICLR 1-10
    verdict: str = ""  # commit / no-commit / occupied / ...
    note: str = ""


@dataclass
class NoveltyVerdict:
    """Whether the core contribution is refuted by the evidence retrieved.

    ``scope_kind`` is fixed to ``candidate_version``: this artifact cannot
    express a judgement about a query lane, a domain, or a field.
    """

    verdict: str
    coverage_sufficient: bool
    auto_verdict: str = ""
    preemptors: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    coverage_warnings: list[str] = field(default_factory=list)
    scope_kind: str = NOVELTY_SCOPE_KIND

    def __post_init__(self) -> None:
        if self.verdict not in NOVELTY_VERDICTS:
            raise ValueError(
                f"novelty verdict must be one of {NOVELTY_VERDICTS}, got {self.verdict!r}"
            )
        if self.scope_kind != NOVELTY_SCOPE_KIND:
            raise ValueError(
                f"novelty verdict scope must be {NOVELTY_SCOPE_KIND!r}, "
                f"got {self.scope_kind!r}"
            )
        if self.verdict == "not_refuted_by_retrieved_evidence" and (
            not self.coverage_sufficient
        ):
            raise ValueError(
                "not_refuted_by_retrieved_evidence requires sufficient coverage; "
                "use 'unclear' instead"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "scope_kind": self.scope_kind,
            "coverage_sufficient": self.coverage_sufficient,
            "coverage_warnings": self.coverage_warnings,
            "auto_verdict": self.auto_verdict,
            "preemptors": self.preemptors,
            "basis": self.basis,
        }


@dataclass
class PromotionDecision:
    """Whether to invest in the candidate now. Never rewrites novelty."""

    decision: str
    novelty_verdict: str
    target: str
    reasons: list[str] = field(default_factory=list)
    blocking_axes: list[str] = field(default_factory=list)
    panel_mean: float | None = None

    def __post_init__(self) -> None:
        if self.decision not in PROMOTION_DECISIONS:
            raise ValueError(
                f"promotion decision must be one of {PROMOTION_DECISIONS}, "
                f"got {self.decision!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "novelty_verdict": self.novelty_verdict,
            "target": self.target,
            "reasons": self.reasons,
            "blocking_axes": self.blocking_axes,
            "panel_mean": self.panel_mean,
        }


@dataclass
class CertificationDecision:
    """Container for both artifacts plus a compatibility ``decision`` field."""

    novelty: NoveltyVerdict
    promotion: PromotionDecision
    target: str
    reasons: list[str] = field(default_factory=list)
    panel_mean: float | None = None
    auto_verdict: str = ""
    reviewers: list[dict[str, Any]] = field(default_factory=list)
    preemptors: list[str] = field(default_factory=list)

    @property
    def decision(self) -> str:
        """Legacy ``go``/``no-go``. Derived, never an input.

        Kept so existing callers keep working. New consumers should read
        ``promotion.decision``, which distinguishes ``stop`` from ``hold`` and
        ``incubate`` — a distinction the binary form cannot express.
        """
        return "go" if self.promotion.decision == "advance" else "no-go"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "novelty_verdict": self.novelty.to_dict(),
            "promotion_decision": self.promotion.to_dict(),
            "target": self.target,
            "reasons": self.reasons,
            "panel_mean": self.panel_mean,
            "auto_verdict": self.auto_verdict,
            "reviewers": self.reviewers,
            "preemptors": self.preemptors,
        }


def _venue_bar(target: str) -> tuple[tuple[float, float], list[str]]:
    key = (target or "").strip().lower()
    if key in VENUE_BARS:
        return VENUE_BARS[key], []
    # Natural phrasings ("ICLR main track", "NeurIPS 2027", "ICLR workshop")
    # must resolve to the named venue's bar — the fallback made "ICLR
    # workshop" STRICTER than the venue the user named (found live, F1 v1).
    if "workshop" in key:
        return VENUE_BARS["workshop"], []
    for family in ("iclr", "neurips", "icml", "aaai"):
        if family in key:
            return VENUE_BARS[f"{family}-main"], []
    # Journal targets by selectivity class (natural names accepted).
    if "scientific reports" in key or key in {"sr", "plos one"}:
        return VENUE_BARS["journal-sound-science"], []
    if (
        "humanities and social sciences communications" in key
        or key == "hssc"
        or "communications" in key  # Nature Communications-family journals
        and "nature" not in key
    ):
        return VENUE_BARS["journal-selective"], []
    if (
        key.startswith("npj")
        or "nature" in key
        or key in {"science", "science advances", "pnas"}
        or "lancet" in key
    ):
        return VENUE_BARS["journal-flagship"], []
    return _STRICTEST_BAR, [
        f"unknown venue target {target!r}; applying strictest bar "
        f"{_STRICTEST_BAR[0]}/{_STRICTEST_BAR[1]}"
    ]


def evaluate_novelty(
    *,
    auto_verdict: str,
    reviewers: list[ReviewerScore],
    preemptors: list[str] | None = None,
    per_reviewer_floor: float = _STRICTEST_BAR[0],
    coverage: dict[str, Any] | None = None,
) -> NoveltyVerdict:
    """Decide only whether the core contribution is refuted.

    A retrieval verdict on its own never refutes: ``occupied`` from
    ``gap_ground_verify`` is a statement about what a query family found, and
    needs a corroborating novelty-axis reviewer judgement before it can close a
    candidate. Likewise a pre-emptor that no reviewer corroborates leaves the
    candidate ``unclear``, not ``refuted``.

    ``coverage`` is the dict returned by ``coverage.coverage_verdict``. When
    the quantitative signal is computable and the stopping bar is NOT reached,
    coverage is insufficient regardless of what the categorical retrieval
    verdict says — a Chao2 estimate that says "much of the neighbourhood is
    still unseen" outranks one query family's optimism (TAR stopping-rule
    line: TOIS 2025, SIGIR 2025/2026). When it is not computable the
    categorical check stands alone, flagged as unquantified.
    """
    preemptors = [p for p in (preemptors or []) if p]
    auto = (auto_verdict or "").strip().lower()
    basis: list[str] = []
    warnings: list[str] = []

    novelty_reviews = [r for r in reviewers if r.axis == NOVELTY_AXIS]
    if not novelty_reviews:
        warnings.append("no novelty-axis reviewer in the panel")
    if auto in _INCONCLUSIVE_AUTO_VERDICTS:
        warnings.append(f"automated retrieval verdict is {auto or 'absent'!r}")
    elif auto not in KNOWN_AUTO_VERDICTS:
        warnings.append(
            f"unrecognised automated retrieval verdict {auto!r}; "
            "treating coverage as unestablished"
        )

    novelty_blocking = any(
        r.overall < per_reviewer_floor
        or (r.verdict or "").strip().lower() in _BLOCKING_REVIEWER_VERDICTS
        for r in novelty_reviews
    )
    coverage_sufficient = bool(novelty_reviews) and _coverage_established(auto)
    if coverage is not None:
        unseen = coverage.get("unseen_fraction")
        marginal = coverage.get("marginal_rate")
        detail = (
            f"unseen_fraction={unseen:.3f}" if isinstance(unseen, float) else ""
        ) + (f" marginal_rate={marginal:.3f}" if isinstance(marginal, float) else "")
        sources_failed = [
            str(s) for s in (coverage.get("sources_failed") or []) if str(s).strip()
        ]
        if sources_failed:
            # A source that failed every query is not an empty search. Force
            # unclear regardless of Chao2 / categorical optimism (E1).
            coverage_sufficient = False
            warnings.append(
                "source-level harvest failure(s): "
                + ", ".join(sources_failed)
                + "; treat coverage as unestablished"
            )
        elif not coverage.get("computable"):
            warnings.append(
                "coverage unquantified (no computable stopping signal); "
                "relying on the categorical retrieval verdict alone"
            )
        elif coverage.get("stop_reached"):
            basis.append(
                f"quantitative coverage stopping bar reached ({detail.strip()})"
            )
        else:
            coverage_sufficient = False
            warnings.append(
                "quantitative coverage estimate below the stopping bar "
                f"({detail.strip()}); the retrieval verdict cannot establish "
                "coverage on its own"
            )

    if not coverage_sufficient:
        return NoveltyVerdict(
            verdict="unclear",
            coverage_sufficient=False,
            auto_verdict=auto,
            preemptors=preemptors,
            basis=["coverage insufficient to judge the core contribution"],
            coverage_warnings=warnings,
        )

    if preemptors and novelty_blocking:
        basis.append(
            f"{len(preemptors)} direct pre-emptor(s) corroborated by a blocking "
            f"novelty-axis review: {preemptors[:3]}"
        )
        verdict = "refuted"
    elif auto == "occupied" and novelty_blocking:
        basis.append(
            "automated retrieval reported 'occupied' and the novelty-axis "
            "reviewer returned a blocking judgement"
        )
        verdict = "refuted"
    elif preemptors:
        basis.append(
            f"{len(preemptors)} pre-emptor(s) found but not corroborated by the "
            f"novelty-axis review: {preemptors[:3]}"
        )
        warnings.append("pre-emptor found without corroborating reviewer judgement")
        verdict = "unclear"
    elif auto == "occupied":
        basis.append(
            "automated retrieval reported 'occupied'; this describes query-family "
            "coverage, not the candidate's core contribution"
        )
        warnings.append("retrieval-level occupancy without reviewer corroboration")
        verdict = "unclear"
    elif novelty_blocking:
        basis.append(
            "novelty-axis reviewer returned a blocking judgement without a "
            "concrete pre-emptor"
        )
        warnings.append("blocking novelty review without an evidence anchor")
        verdict = "unclear"
    else:
        basis.append("no admissible evidence refutes the core contribution")
        verdict = "not_refuted_by_retrieved_evidence"

    return NoveltyVerdict(
        verdict=verdict,
        coverage_sufficient=True,
        auto_verdict=auto,
        preemptors=preemptors,
        basis=basis,
        coverage_warnings=warnings,
    )


def evaluate_promotion(
    *,
    novelty: NoveltyVerdict,
    reviewers: list[ReviewerScore],
    target: str = "iclr-main",
) -> PromotionDecision:
    """Decide whether to invest now, given a novelty verdict it cannot change."""
    (floor, mean_bar), reasons = _venue_bar(target)
    blocking_axes: list[str] = []

    covered = {r.axis for r in reviewers}
    missing = [a for a in REVIEW_AXES if a not in covered]
    if missing:
        reasons.append(f"reviewer panel incomplete; missing axes: {sorted(missing)}")

    for r in reviewers:
        if r.axis == NOVELTY_AXIS:
            continue
        verdict = (r.verdict or "").strip().lower()
        if r.overall < floor:
            blocking_axes.append(r.axis)
            reasons.append(f"{r.axis} reviewer overall {r.overall} < {floor}")
        elif verdict in _BLOCKING_REVIEWER_VERDICTS:
            blocking_axes.append(r.axis)
            reasons.append(f"{r.axis} reviewer returned blocking verdict {verdict!r}")

    panel_mean: float | None = None
    if reviewers:
        panel_mean = round(sum(r.overall for r in reviewers) / len(reviewers), 2)
        if panel_mean < mean_bar:
            reasons.append(f"panel mean {panel_mean} < {target} bar {mean_bar}")

    if novelty.verdict == "refuted":
        decision = "stop"
        reasons.insert(0, "core contribution is refuted by admissible evidence")
    elif missing or blocking_axes or (panel_mean is not None and panel_mean < mean_bar):
        # A quality, resource, or procedural problem holds the candidate. It
        # says nothing about novelty and must not be recorded as if it did.
        decision = "hold"
        reasons.insert(
            0,
            "held for non-novelty reasons; the novelty verdict is unchanged "
            f"({novelty.verdict})",
        )
    elif novelty.verdict == "unclear":
        decision = "incubate"
        reasons.insert(
            0, "novelty is unclear on current evidence; incubate and re-certify"
        )
    else:
        decision = "advance"
        reasons.insert(
            0,
            f"not refuted by retrieved evidence and clears the {target} bar on "
            "every non-novelty axis",
        )

    return PromotionDecision(
        decision=decision,
        novelty_verdict=novelty.verdict,
        target=target,
        reasons=reasons,
        blocking_axes=sorted(set(blocking_axes)),
        panel_mean=panel_mean,
    )


def evaluate_certification(
    *,
    auto_verdict: str,
    reviewers: list[ReviewerScore],
    target: str = "iclr-main",
    preemptors: list[str] | None = None,
    coverage: dict[str, Any] | None = None,
) -> CertificationDecision:
    """Run both gates and return them together.

    The legacy ``.decision`` property still yields ``go``/``no-go`` so existing
    callers keep working, but it is derived from the promotion decision. Read
    ``promotion.decision`` to tell ``stop`` from ``hold`` and ``incubate``.
    """
    (floor, _mean_bar), _ = _venue_bar(target)
    novelty = evaluate_novelty(
        auto_verdict=auto_verdict,
        reviewers=reviewers,
        preemptors=preemptors,
        per_reviewer_floor=floor,
        coverage=coverage,
    )
    promotion = evaluate_promotion(novelty=novelty, reviewers=reviewers, target=target)
    reasons = [*novelty.basis, *promotion.reasons]
    for reason in reasons:
        assert_no_field_level_claim(reason, where="certification reason")
    return CertificationDecision(
        novelty=novelty,
        promotion=promotion,
        target=target,
        reasons=reasons,
        panel_mean=promotion.panel_mean,
        auto_verdict=novelty.auto_verdict,
        reviewers=[
            {"axis": r.axis, "overall": r.overall, "verdict": r.verdict, "note": r.note}
            for r in reviewers
        ],
        preemptors=novelty.preemptors,
    )


def parse_panel(panel: dict[str, Any]) -> tuple[str, list[ReviewerScore], list[str]]:
    """Parse a panel JSON payload into (auto_verdict, reviewers, preemptors)."""
    auto_verdict = str(panel.get("auto_verdict") or "").strip()
    reviewers: list[ReviewerScore] = []
    for item in panel.get("reviewers") or []:
        if not isinstance(item, dict):
            continue
        try:
            overall = float(item.get("overall"))
        except (TypeError, ValueError):
            continue
        reviewers.append(
            ReviewerScore(
                axis=str(item.get("axis") or "").strip().lower(),
                overall=overall,
                verdict=str(item.get("verdict") or "").strip(),
                note=str(item.get("note") or "").strip(),
            )
        )
    preemptors = [str(p) for p in (panel.get("preemptors") or []) if p]
    return auto_verdict, reviewers, preemptors
