"""Regression for the 7.3 -> 6.3 loss.

A revision fixed three of nine weaknesses, moved a fourth into an appendix,
cut 28% of the words against a review that asked for more in eleven places,
and scored a point lower. Nothing in the writing stack could see any of it,
because nothing in the writing stack could see the review.
"""

from research_harness.verification.review_response import (
    ReviewPoint,
    ResponseStatus,
    revision_direction_warning,
    track_review_responses,
)

BODY = r"""
The comparison is budget-matched by construction: 22,840 tokens/paper for our
audit against 23,143 for the rubric reviewer, a 1.3\% difference.
Out-of-universe accusations are reported separately; 15.2\% of rounds produced
only such findings.
\appendix
\section{Extensions}
Citation--claim pairs satisfy all three requirements, so cross-generator
substrates built with AI-Scientist outputs are the natural next corpus.
"""


class TestResponseTracking:
    def test_answered_in_body_is_recognised(self):
        p = ReviewPoint("token budget", keywords=["tokens/paper", "22,840", "1.3"])
        s = track_review_responses(BODY, [p]).statuses[0]
        assert s.status is ResponseStatus.ANSWERED_IN_BODY

    def test_appendix_only_is_distinguished_from_answered(self):
        """The distinction that cost a point: a reviewer reads the body."""
        p = ReviewPoint("cross-generator", keywords=["cross-generator", "substrates"])
        report = track_review_responses(BODY, [p])
        s = report.statuses[0]
        assert s.status is ResponseStatus.ANSWERED_IN_APPENDIX
        assert report.appendix_only == [s]
        assert "will not see this" in s.evidence

    def test_unanswered_point_is_reported(self):
        p = ReviewPoint("K range", keywords=["K=4", "adaptive replicate"])
        report = track_review_responses(BODY, [p])
        assert report.statuses[0].status is ResponseStatus.UNANSWERED
        assert len(report.unanswered) == 1

    def test_inferred_keywords_do_not_produce_findings(self):
        """A criticism and its answer use different words; absence proves nothing."""
        p = ReviewPoint("inconsistency in token-budget reporting across the table")
        report = track_review_responses(BODY, [p])
        assert report.unanswered == []
        assert len(report.needs_attention) == 1

    def test_appendix_split_needs_compile_order(self):
        """Concatenating a section after the root file hides it in the appendix."""
        p = ReviewPoint("token budget", keywords=["tokens/paper", "22,840", "1.3"])
        wrong_order = "\\appendix\n" + BODY
        s = track_review_responses(wrong_order, [p]).statuses[0]
        assert s.status is ResponseStatus.ANSWERED_IN_APPENDIX


class TestRevisionDirection:
    REVIEW_ASKING_FOR_MORE = (
        "the paper's discussion of extension paths is limited; guidance on scaling N "
        "is brief; cross-generator generalization is untested; out-of-universe "
        "accusations are lightly discussed and deferred; a compact recipe would help; "
        "the related work could be tightened; broader ranges would strengthen the case"
    )

    def test_warns_when_a_more_review_is_answered_with_cuts(self):
        w = revision_direction_warning(self.REVIEW_ASKING_FOR_MORE, 5385, 3852)
        assert w and "28% shorter" in w

    def test_silent_when_length_holds(self):
        assert (
            revision_direction_warning(self.REVIEW_ASKING_FOR_MORE, 5385, 5385) is None
        )

    def test_silent_when_the_review_asked_for_brevity(self):
        terse = "the manuscript is verbose and repetitive; please shorten and condense"
        assert revision_direction_warning(terse, 5385, 3852) is None
