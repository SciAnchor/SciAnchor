"""Tests for the upgraded section loop: structured revision briefs,
adversarial convergence gating, and revision inputs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_harness.execution import llm_primitives
from research_harness.execution.loops import build_revision_brief, run_section_loop


def _draft(content="First draft. It argues the claim. It cites [1]."):
    return SimpleNamespace(draft=SimpleNamespace(content=content))


def _review(
    score=0.9,
    needs_revision=False,
    suggestions=("tighten the hook",),
    checks=(),
    dimensions=(),
):
    return SimpleNamespace(
        overall_score=score,
        needs_revision=needs_revision,
        suggestions=list(suggestions),
        deterministic_checks=list(checks),
        dimensions=list(dimensions),
    )


def _check(name="citation_quota", passed=False, details="below quota", items=("[3]",)):
    return SimpleNamespace(
        check_name=name, passed=passed, details=details, items_found=list(items)
    )


def _dim(name="claim_evidence_grounding", score=0.4, comment="claim X uncited"):
    return SimpleNamespace(dimension=name, score=score, comment=comment)


def _revise(content="Revised draft.", changes=("added citation",)):
    return SimpleNamespace(revised_content=content, changes_made=list(changes))


@pytest.fixture
def fake_db():
    return object()


class TestBuildRevisionBrief:
    def test_groups_checks_dimensions_suggestions_and_adversarial(self):
        review = _review(
            score=0.5,
            suggestions=["fix hook", "add takeaway"],
            checks=[_check()],
            dimensions=[_dim(), _dim("clarity", 0.9, "fine")],
        )
        adversarial = {
            "weaknesses": [
                {
                    "severity": "critical",
                    "category": "baseline_fairness",
                    "description": "missing 2025 baselines",
                    "evidence": "table 2 only lists 2022 methods",
                }
            ],
            "critical_count": 1,
        }
        brief = build_revision_brief(review, adversarial)
        assert "Failed deterministic checks" in brief
        assert "citation_quota" in brief and "[3]" in brief
        assert "Weakest review dimensions" in brief
        assert "claim_evidence_grounding (score 0.40)" in brief
        # 0.9-scoring dimension is not listed among the weakest
        assert "clarity" not in brief
        assert "Reviewer suggestions" in brief and "fix hook" in brief
        assert "Adversarial weaknesses" in brief
        assert "[critical] baseline_fairness" in brief
        assert "table 2 only lists 2022 methods" in brief
        assert "Address every item above explicitly" in brief

    def test_mapping_review_matches_tracked_dataclass_shape(self):
        review = _review(
            score=0.5,
            suggestions=["fix hook"],
            checks=[_check()],
            dimensions=[_dim()],
        )
        mapping = {
            "overall_score": review.overall_score,
            "needs_revision": review.needs_revision,
            "suggestions": review.suggestions,
            "deterministic_checks": [
                vars(item) for item in review.deterministic_checks
            ],
            "dimensions": [vars(item) for item in review.dimensions],
        }
        assert build_revision_brief(mapping) == build_revision_brief(review)

    def test_empty_review_yields_empty_brief(self):
        assert build_revision_brief(_review(suggestions=())) == ""


class TestSectionLoopAdversarialGate:
    def _patch(self, monkeypatch, *, reviews, adversarials, revises=None):
        calls = {"draft": [], "review": [], "adv": [], "revise": []}

        def fake_draft(**kwargs):
            calls["draft"].append(kwargs)
            return _draft()

        review_iter = iter(reviews)

        def fake_review(**kwargs):
            calls["review"].append(kwargs)
            return next(review_iter)

        adv_iter = iter(adversarials)

        def fake_adv(**kwargs):
            calls["adv"].append(kwargs)
            return next(adv_iter)

        revise_iter = iter(revises or [])

        def fake_revise(**kwargs):
            calls["revise"].append(kwargs)
            return next(revise_iter)

        monkeypatch.setattr(llm_primitives, "section_draft", fake_draft)
        monkeypatch.setattr(llm_primitives, "section_review", fake_review)
        monkeypatch.setattr(llm_primitives, "adversarial_section_review", fake_adv)
        monkeypatch.setattr(llm_primitives, "section_revise", fake_revise)
        monkeypatch.setattr(
            llm_primitives,
            "_build_numbered_evidence",
            lambda *a, **k: ("[1] Some paper", [1]),
        )
        return calls

    def test_critical_weakness_blocks_convergence(self, fake_db, monkeypatch):
        calls = self._patch(
            monkeypatch,
            reviews=[_review(score=0.9), _review(score=0.9)],
            adversarials=[
                {
                    "weaknesses": [
                        {
                            "severity": "critical",
                            "category": "novelty_claim",
                            "description": "prior work does this",
                            "evidence": "quote",
                        }
                    ],
                    "critical_count": 1,
                },
                {"weaknesses": [], "critical_count": 0},
            ],
            revises=[_revise()],
        )
        result = run_section_loop(
            db=fake_db,
            section="introduction",
            topic_id=1,
            max_rounds=3,
            adversarial=True,
        )
        # Round 1 passed cooperatively but had a critical weakness -> revise.
        # Round 2 passed both -> converged in 2 rounds.
        assert result.converged is True
        assert result.total_rounds == 2
        assert len(calls["adv"]) == 2
        assert len(calls["revise"]) == 1
        # The revision brief carried the adversarial weakness forward.
        brief = calls["revise"][0]["review_feedback"]
        assert "prior work does this" in brief

    def test_adversarial_skipped_when_cooperative_fails_midway(
        self, fake_db, monkeypatch
    ):
        calls = self._patch(
            monkeypatch,
            reviews=[
                _review(score=0.4, needs_revision=True),
                _review(score=0.9),
            ],
            adversarials=[{"weaknesses": [], "critical_count": 0}],
            revises=[_revise()],
        )
        result = run_section_loop(
            db=fake_db,
            section="method",
            topic_id=1,
            max_rounds=3,
            adversarial=True,
        )
        assert result.converged is True
        # Adversarial ran only on round 2 (the qualifying round), not round 1.
        assert len(calls["adv"]) == 1

    def test_adversarial_disabled_keeps_legacy_behavior(self, fake_db, monkeypatch):
        calls = self._patch(
            monkeypatch,
            reviews=[_review(score=0.9)],
            adversarials=[],
        )
        result = run_section_loop(
            db=fake_db, section="method", topic_id=1, adversarial=False
        )
        assert result.converged is True
        assert calls["adv"] == []

    def test_adversarial_failure_does_not_break_loop(self, fake_db, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("adversarial model down")

        calls = self._patch(
            monkeypatch,
            reviews=[_review(score=0.9)],
            adversarials=[],
        )
        monkeypatch.setattr(llm_primitives, "adversarial_section_review", boom)
        result = run_section_loop(
            db=fake_db, section="method", topic_id=1, adversarial=True
        )
        assert result.converged is True
        assert calls["revise"] == []

    def test_revise_receives_evidence_and_context(self, fake_db, monkeypatch):
        calls = self._patch(
            monkeypatch,
            reviews=[
                _review(score=0.4, needs_revision=True, checks=[_check()]),
                _review(score=0.9),
            ],
            adversarials=[{"weaknesses": [], "critical_count": 0}],
            revises=[_revise(changes=["expanded paragraph 2"])],
        )
        ctx = {"one_sentence_claim": "We transform X.", "drafted": {}}
        result = run_section_loop(
            db=fake_db,
            section="experiments",
            topic_id=1,
            max_rounds=2,
            adversarial=True,
            paper_context=ctx,
        )
        revise_kwargs = calls["revise"][0]
        assert revise_kwargs["evidence_text"] == "[1] Some paper"
        assert revise_kwargs["paper_context"] == ctx
        assert "Failed deterministic checks" in revise_kwargs["review_feedback"]
        # Draft and review also saw the shared context.
        assert calls["draft"][0]["paper_context"] == ctx
        assert calls["review"][0]["paper_context"] == ctx
        # Bug fix regression: changes are recorded on the round they occurred.
        assert result.iterations[0].changes == []
        assert result.iterations[1].changes == ["expanded paragraph 2"]
