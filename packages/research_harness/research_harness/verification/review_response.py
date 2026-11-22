"""Track whether a revision actually answered the last round of review.

The failure this exists for is specific and was expensive. A manuscript scored
7.3 with nine weaknesses. The revision fixed three of them, moved the material
answering a fourth into an appendix, and left the rest. The next review scored
it 6.3 and re-raised exactly the points that had not been answered — while the
three that were answered went unmentioned.

Nothing in the writing stack noticed any of that. The revision looked fine
section by section; what it could not see was the review it was supposed to be
responding to. This module supplies that view: given last round's review and the
current manuscript, it says for each raised point whether the draft now answers
it, answers it only in an appendix, or does not answer it at all.

It is deliberately keyword-and-location based rather than model-based. A model
asked "did we address this?" will usually say yes, and that is the failure mode
being guarded against, not a capability being added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ResponseStatus(str, Enum):
    ANSWERED_IN_BODY = "answered_in_body"
    ANSWERED_IN_APPENDIX = "answered_in_appendix"
    UNANSWERED = "unanswered"


@dataclass
class ReviewPoint:
    """One criticism or question from a prior review.

    ``keywords`` should describe what an *answer* looks like, not what the
    criticism said. Those are different vocabularies and conflating them is the
    main way this check goes wrong: a reviewer writes "inconsistency in
    token-budget reporting" and the response says "22,840 tokens per manuscript
    ... a 1.3% difference". Zero shared terms, a complete answer.

    Falling back to the criticism's own wording is a weak default, kept only so
    a caller with no expectations still gets a signal. Treat an UNANSWERED from
    the fallback path as "look at this", not as a finding.
    """

    text: str
    keywords: list[str] = field(default_factory=list)

    def terms(self) -> list[str]:
        return self.keywords or _salient_terms(self.text)

    @property
    def keywords_supplied(self) -> bool:
        return bool(self.keywords)


@dataclass
class PointStatus:
    point: ReviewPoint
    status: ResponseStatus
    evidence: str = ""

    @property
    def answered(self) -> bool:
        return self.status is not ResponseStatus.UNANSWERED


@dataclass
class ReviewResponseReport:
    statuses: list[PointStatus]

    @property
    def unanswered(self) -> list[PointStatus]:
        """Points with no response found AND expectations to judge against.

        A point whose keywords were inferred from the criticism's own wording is
        excluded: the vocabularies differ, so an absence there says nothing.
        Those surface through :attr:`needs_attention` instead.
        """
        return [
            s
            for s in self.statuses
            if s.status is ResponseStatus.UNANSWERED and s.point.keywords_supplied
        ]

    @property
    def needs_attention(self) -> list[PointStatus]:
        """Unanswered on inferred keywords — a prompt to look, not a finding."""
        return [
            s
            for s in self.statuses
            if s.status is ResponseStatus.UNANSWERED and not s.point.keywords_supplied
        ]

    @property
    def appendix_only(self) -> list[PointStatus]:
        return [
            s for s in self.statuses if s.status is ResponseStatus.ANSWERED_IN_APPENDIX
        ]

    def summary(self) -> str:
        n = len(self.statuses)
        body = sum(
            1 for s in self.statuses if s.status is ResponseStatus.ANSWERED_IN_BODY
        )
        parts = [
            f"{body}/{n} answered in body",
            f"{len(self.appendix_only)} appendix-only",
            f"{len(self.unanswered)} unanswered",
        ]
        if self.needs_attention:
            parts.append(
                f"{len(self.needs_attention)} unverifiable (no expectations given)"
            )
        return ", ".join(parts)


# Words too common in review prose to locate anything.
_STOPWORDS = frozenset(
    """the a an and or but of to in for on with is are was were be been being this that
    these those it its as at by from not no nor so than then there here how what which
    who whom whose when where why can could would should may might must will shall do
    does did done have has had having more most much many some any all each every other
    such only own same very just also both few own paper authors work section results
    approach method methods provide provides provided given using used use also however
    while whether about into over under between within without across please""".split()
)


def _salient_terms(text: str, limit: int = 6) -> list[str]:
    """Content words a genuine response would almost certainly reuse."""
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", text.lower())
    seen: dict[str, int] = {}
    for w in words:
        if w in _STOPWORDS:
            continue
        seen[w] = seen.get(w, 0) + 1
    # Longer words first: they are the technical ones. Frequency breaks ties.
    ranked = sorted(seen, key=lambda w: (-len(w), -seen[w]))
    return ranked[:limit]


def _split_body_appendix(manuscript: str) -> tuple[str, str]:
    """Split at ``\\appendix``, the only unambiguous marker in LaTeX.

    Pass the manuscript in compile order. A root file that ends with
    ``\\appendix`` followed by ``\\input`` lines will otherwise swallow anything
    concatenated after it, and every section then reads as appendix material.
    """
    m = re.search(r"\\appendix\b", manuscript)
    if not m:
        return manuscript, ""
    return manuscript[: m.start()], manuscript[m.start() :]


def _coverage(terms: list[str], text: str) -> float:
    if not terms:
        return 0.0
    low = text.lower()
    hit = sum(1 for t in terms if re.search(rf"\b{re.escape(t)}", low))
    return hit / len(terms)


def track_review_responses(
    manuscript: str,
    points: list[ReviewPoint],
    *,
    threshold: float = 0.6,
) -> ReviewResponseReport:
    """Classify each prior review point against the current manuscript.

    ``threshold`` is the fraction of a point's salient terms that must appear
    for the draft to count as engaging with it. It is a coverage test, not a
    comprehension test: the claim is only that the manuscript talks about the
    thing, which is the minimum a response must clear.
    """
    body, appendix = _split_body_appendix(manuscript)
    out: list[PointStatus] = []

    for point in points:
        terms = point.terms()
        body_cov = _coverage(terms, body)
        appx_cov = _coverage(terms, appendix)

        if body_cov >= threshold:
            status, evidence = (
                ResponseStatus.ANSWERED_IN_BODY,
                f"{body_cov:.0%} of terms present in body",
            )
        elif appx_cov >= threshold:
            status, evidence = (
                ResponseStatus.ANSWERED_IN_APPENDIX,
                # Worth flagging separately: a reviewer reads the body. Material
                # that answers a criticism from the appendix frequently reads as
                # no answer at all, which is how a fixed weakness gets re-raised.
                f"{appx_cov:.0%} of terms in appendix, {body_cov:.0%} in body — "
                "a reviewer reading the body will not see this",
            )
        else:
            status, evidence = (
                ResponseStatus.UNANSWERED,
                f"only {max(body_cov, appx_cov):.0%} of terms appear anywhere",
            )
        out.append(PointStatus(point=point, status=status, evidence=evidence))

    return ReviewResponseReport(statuses=out)


# -- Revision direction ------------------------------------------------------

_MORE_CUES = (
    "could better",
    "wants more",
    "limited",
    "brief",
    "lightly discussed",
    "deferred",
    "untested",
    "would strengthen",
    "should be expanded",
    "more systematic",
    "could be tightened",
    "guidance on",
    "feasibility study",
    "extend",
)
_LESS_CUES = ("verbose", "too long", "redundant", "repetitive", "shorten", "condense")


def revision_direction_warning(
    review_text: str, words_before: int, words_after: int
) -> str | None:
    """Warn when a revision cuts length against a review that asked for more.

    Derived from a measured loss, not from principle: a review whose weaknesses
    asked for more in eight of nine cases was answered with a 28% cut, and the
    score fell. The asymmetry matters — reviewers who ask for depth read a
    shorter paper as less responsive, regardless of how much cleaner it reads.
    """
    low = review_text.lower()
    more = sum(low.count(c) for c in _MORE_CUES)
    less = sum(low.count(c) for c in _LESS_CUES)
    if more <= less or words_before == 0:
        return None

    delta = (words_after - words_before) / words_before
    if delta >= -0.05:
        return None

    return (
        f"the review asks for more in {more} places and for less in {less}, but this "
        f"revision is {abs(delta):.0%} shorter ({words_before} -> {words_after} words). "
        "Length cuts read as non-responsiveness when depth was the request."
    )
