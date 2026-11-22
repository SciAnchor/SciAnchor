"""Adversarial optimization: proposer/auditor/resolver protocol.

This module formalizes the structured challenge-and-resolution cycle
for high-risk research decisions (direction selection, study design).

Loop contract v2 (from a 30-round non-convergence post-mortem):

- every objection carries a content-stable ``objection_id`` so proposer
  responses reference ids, not free-text target equality;
- a round after the first is rejected outright when the previous round left
  unresolved objections and the new round carries no proposer responses —
  without that channel every round is an independent sample and the loop
  cannot converge;
- termination adds two reachable exits beyond ``approved``/max-rounds:
  two consecutive sub-3.0 mean scores force ``reject_and_return`` (a 1.5/5
  manuscript must leave the polish loop), and two consecutive rounds that
  introduce no new objection key stop the repeat cycle.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from research_harness.storage.db import Database
from .artifacts import ArtifactManager

# Resolutions below this mean score in two consecutive rounds abort the loop:
# revision noise cannot lift a manuscript this far, it needs a rethink.
STAGNATION_MEAN_THRESHOLD = 3.0
#: A score must not have improved beyond noise for the round to count as
#: stalled; scores are on a 1-5 scale.
_STAGNATION_SCORE_EPSILON = 0.05
#: ...and the objection load must not have dropped by at least this fraction.
_STAGNATION_MIN_OBJECTION_DROP = 0.10


def compute_objection_id(category: str, severity: str, target: str) -> str:
    """Content-stable id: the same complaint keeps its id across rounds."""
    basis = "|".join(
        (
            category.strip().lower(),
            severity.strip().lower(),
            re.sub(r"\s+", " ", target.strip().lower()),
        )
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def compute_objection_key(category: str, target: str) -> str:
    """Recurrence key for the no-new-objections termination check.

    Severity is excluded (the same complaint re-graded is not new) and the
    target is normalized. Free-text targets mean a reworded complaint gets a
    new key, so this check can only delay termination, never end it early —
    max-rounds and the stagnation rule are the hard backstops.
    """
    axis = category.split(":")[-1].strip().lower()
    norm = re.sub(r"\W+", " ", target.lower()).strip()[:80]
    return f"{axis}|{norm}"


@dataclass
class Objection:
    """A single objection raised by the auditor."""

    category: str
    severity: str  # critical, major, minor
    target: str
    reasoning: str
    suggested_fix: str = ""
    objection_id: str = ""

    def __post_init__(self) -> None:
        if not self.objection_id:
            self.objection_id = compute_objection_id(
                self.category, self.severity, self.target
            )


@dataclass
class AdversarialRound:
    """One round of proposal, audit, and response."""

    round_number: int
    target_artifact_id: int
    target_stage: str
    proposal_snapshot: dict[str, Any] = field(default_factory=dict)
    objections: list[Objection] = field(default_factory=list)
    proposer_responses: list[dict[str, Any]] = field(default_factory=list)
    unresolved_objections: list[Objection] = field(default_factory=list)
    resolver_notes: str = ""
    # Review focus/profile. Empty for classic
    # direction/study-design reviews; lets gates distinguish review kinds.
    focus: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "target_artifact_id": self.target_artifact_id,
            "target_stage": self.target_stage,
            "focus": self.focus,
            "proposal_snapshot": self.proposal_snapshot,
            "objections": [
                {
                    "objection_id": o.objection_id,
                    "category": o.category,
                    "severity": o.severity,
                    "target": o.target,
                    "reasoning": o.reasoning,
                    "suggested_fix": o.suggested_fix,
                }
                for o in self.objections
            ],
            "proposer_responses": self.proposer_responses,
            "unresolved_objections": [
                {
                    "objection_id": o.objection_id,
                    "category": o.category,
                    "severity": o.severity,
                    "target": o.target,
                    "reasoning": o.reasoning,
                }
                for o in self.unresolved_objections
            ],
            "resolver_notes": self.resolver_notes,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AdversarialRound":
        objections = [
            Objection(
                category=o.get("category", ""),
                severity=o.get("severity", "minor"),
                target=o.get("target", ""),
                reasoning=o.get("reasoning", ""),
                suggested_fix=o.get("suggested_fix", ""),
                objection_id=o.get("objection_id", ""),
            )
            for o in payload.get("objections", [])
        ]
        unresolved = [
            Objection(
                category=o.get("category", ""),
                severity=o.get("severity", "minor"),
                target=o.get("target", ""),
                reasoning=o.get("reasoning", ""),
                objection_id=o.get("objection_id", ""),
            )
            for o in payload.get("unresolved_objections", [])
        ]
        return cls(
            round_number=payload.get("round_number", 0),
            target_artifact_id=payload.get("target_artifact_id", 0),
            target_stage=payload.get("target_stage", ""),
            proposal_snapshot=payload.get("proposal_snapshot", {}),
            objections=objections,
            proposer_responses=payload.get("proposer_responses", []),
            unresolved_objections=unresolved,
            resolver_notes=payload.get("resolver_notes", ""),
            focus=payload.get("focus", ""),
        )


@dataclass
class AdversarialResolution:
    """Outcome of an adversarial round."""

    outcome: (
        str  # approved, approved_with_conditions, revise_and_repeat, reject_and_return
    )
    scores: dict[str, float] = field(default_factory=dict)
    mean_score: float = 0.0
    critical_unresolved: int = 0
    major_unresolved: int = 0
    round_number: int = 0
    notes: str = ""
    # Copied from the round so gates can match resolutions to a review kind
    # and to the exact artifact version that was reviewed.
    focus: str = ""
    target_artifact_id: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "scores": self.scores,
            "mean_score": self.mean_score,
            "critical_unresolved": self.critical_unresolved,
            "major_unresolved": self.major_unresolved,
            "round_number": self.round_number,
            "notes": self.notes,
            "focus": self.focus,
            "target_artifact_id": self.target_artifact_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AdversarialResolution":
        return cls(
            outcome=payload.get("outcome", "revise_and_repeat"),
            scores=payload.get("scores", {}),
            mean_score=payload.get("mean_score", 0.0),
            critical_unresolved=payload.get("critical_unresolved", 0),
            major_unresolved=payload.get("major_unresolved", 0),
            round_number=payload.get("round_number", 0),
            notes=payload.get("notes", ""),
            focus=payload.get("focus", ""),
            target_artifact_id=payload.get("target_artifact_id", 0),
        )


class AdversarialLoop:
    """Manages adversarial rounds for a project."""

    MAX_ROUNDS: dict[str, int] = {
        "explore": 2,
        "standard": 3,
        "strict": 5,
        "demo": 2,
    }

    SCORE_DIMENSIONS: tuple[str, ...] = (
        "novelty",
        "evidence_coverage",
        "method_validity",
        "baseline_completeness",
        "scope_discipline",
        "falsifiability",
        "clarity",
    )

    def __init__(self, db: Database):
        self._db = db
        self._artifact_manager = ArtifactManager(db)

    def get_max_rounds(self, mode: str) -> int:
        return self.MAX_ROUNDS.get(mode, 3)

    def run_round(
        self,
        topic_id: int,
        target_artifact_id: int,
        target_stage: str,
        round_number: int,
        proposal_snapshot: dict[str, Any],
        objections: list[Objection],
        proposer_responses: list[dict[str, Any]] | None = None,
        resolver_notes: str = "",
        focus: str = "",
    ) -> dict[str, Any]:
        """Record an adversarial round artifact.

        Raises ``ValueError`` when the previous round left unresolved
        objections and this round carries no proposer responses: without the
        response channel every round is an independent sample and the loop
        cannot converge (topic-78: 30 rounds, 0 responses recorded).
        """
        prev = self._artifact_manager.get_latest(
            topic_id, target_stage, "adversarial_round"
        )
        if prev is not None and not proposer_responses:
            prev_unresolved = prev.payload.get("unresolved_objections") or []
            if prev_unresolved:
                sample = ", ".join(
                    f"{o.get('objection_id', '?')} ({o.get('target', '')[:40]})"
                    for o in prev_unresolved[:3]
                )
                raise ValueError(
                    "adversarial round rejected: the previous round left "
                    f"{len(prev_unresolved)} unresolved objection(s) and this "
                    "round carries no proposer_responses. Submit responses "
                    "keyed by objection_id (resolved: true/false + what "
                    f"changed) first; e.g. {sample}"
                )

        unresolved = self._compute_unresolved(objections, proposer_responses or [])

        round_obj = AdversarialRound(
            round_number=round_number,
            target_artifact_id=target_artifact_id,
            target_stage=target_stage,
            proposal_snapshot=proposal_snapshot,
            objections=objections,
            proposer_responses=proposer_responses or [],
            unresolved_objections=unresolved,
            resolver_notes=resolver_notes,
            focus=focus,
        )

        targets_addressed = sorted(
            {
                str(r.get("objection_id") or r.get("target") or "")
                for r in (proposer_responses or [])
                if r.get("objection_id") or r.get("target")
            }
        )
        payload = round_obj.to_payload()
        payload["targets_addressed"] = targets_addressed

        artifact = self._artifact_manager.record(
            topic_id=topic_id,
            stage=target_stage,
            artifact_type="adversarial_round",
            title=f"Adversarial Round {round_number}",
            payload=payload,
            metadata={
                "round_number": round_number,
                "target_artifact_id": target_artifact_id,
                "focus": focus,
                "targets_addressed": targets_addressed,
            },
        )

        return {
            "artifact_id": artifact.id,
            "round": payload,
        }

    def resolve_round(
        self,
        topic_id: int,
        target_stage: str,
        round_number: int,
        round_artifact_id: int,
        scores: dict[str, float] | None = None,
        notes: str = "",
        parent_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        """Record an adversarial resolution artifact."""
        # Fetch the round to compute unresolved counts
        round_artifact = self._artifact_manager.get(round_artifact_id)
        if round_artifact is None:
            raise ValueError(f"Round artifact {round_artifact_id} not found")

        round_payload = round_artifact.payload
        round_obj = AdversarialRound.from_payload(round_payload)

        critical = sum(
            1 for o in round_obj.unresolved_objections if o.severity == "critical"
        )
        major = sum(1 for o in round_obj.unresolved_objections if o.severity == "major")

        computed_scores = scores or {}
        mean_score = (
            sum(computed_scores.values()) / len(computed_scores)
            if computed_scores
            else 0.0
        )

        prior = self._artifact_manager.get_latest(
            topic_id, target_stage, "adversarial_resolution"
        )
        prior_mean = (
            float(prior.payload.get("mean_score", 0.0)) if prior is not None else None
        )
        prior_unresolved = None
        if prior is not None:
            prior_unresolved = int(
                prior.payload.get("critical_unresolved", 0) or 0
            ) + int(prior.payload.get("major_unresolved", 0) or 0)

        outcome = self._determine_outcome(
            critical=critical,
            major=major,
            mean_score=mean_score,
            prior_mean_score=prior_mean,
            unresolved=critical + major,
            prior_unresolved=prior_unresolved,
        )

        resolution = AdversarialResolution(
            outcome=outcome,
            scores=computed_scores,
            mean_score=mean_score,
            critical_unresolved=critical,
            major_unresolved=major,
            round_number=round_number,
            notes=notes,
            focus=round_obj.focus,
            target_artifact_id=round_obj.target_artifact_id,
        )

        artifact = self._artifact_manager.record(
            topic_id=topic_id,
            stage=target_stage,
            artifact_type="adversarial_resolution",
            title=f"Resolution Round {round_number}",
            payload=resolution.to_payload(),
            metadata={
                "round_number": round_number,
                "outcome": outcome,
                "mean_score": mean_score,
                "focus": round_obj.focus,
            },
            parent_artifact_id=parent_artifact_id or round_artifact_id,
        )

        return {
            "artifact_id": artifact.id,
            "resolution": resolution.to_payload(),
        }

    def should_repeat(
        self,
        topic_id: int,
        target_stage: str,
        mode: str,
    ) -> tuple[bool, str]:
        """Determine if another adversarial round is needed.

        Returns (should_repeat, reason).
        """
        # Fetch latest resolution
        resolution_artifact = self._artifact_manager.get_latest(
            topic_id, target_stage, "adversarial_resolution"
        )
        if resolution_artifact is None:
            return True, "No resolution recorded yet"

        resolution = AdversarialResolution.from_payload(resolution_artifact.payload)

        if resolution.outcome in ("approved", "approved_with_conditions"):
            return False, f"Resolution outcome: {resolution.outcome}"

        if resolution.outcome == "reject_and_return":
            return False, "Proposal rejected"

        # Check max rounds
        max_rounds = self.get_max_rounds(mode)
        round_count = self._count_rounds(topic_id, target_stage)
        if round_count >= max_rounds:
            return False, f"Max rounds ({max_rounds}) reached"

        # No-new-objections termination: two consecutive rounds that raised
        # nothing outside the objection-key library mean the panel is
        # re-sampling known complaints, not finding new ones. (A reworded
        # complaint gets a new key, so this only ever delays termination;
        # max-rounds and the stagnation rule are the hard backstops.)
        history = self._round_objection_key_history(topic_id, target_stage)
        if len(history) >= 3:
            new_last = history[-1] - set().union(*history[:-1])
            new_prev = history[-2] - set().union(*history[:-2])
            if not new_last and not new_prev:
                return (
                    False,
                    "No new objection keys in 2 consecutive rounds: the "
                    "objection library is saturated; resolve the recorded "
                    "objections instead of running another panel",
                )

        return (
            True,
            f"Round {round_count}/{max_rounds}: outcome was {resolution.outcome}",
        )

    def check_convergence(
        self,
        scores: dict[str, float],
        critical_unresolved: int,
        mode: str = "standard",
    ) -> tuple[bool, str]:
        """Check if adversarial process has converged.

        Returns (converged, reason).
        """
        if critical_unresolved > 0:
            return False, f"{critical_unresolved} critical objections unresolved"

        if not scores:
            return False, "No scores provided"

        mean = sum(scores.values()) / len(scores)
        threshold = 4.0 if mode == "standard" else 4.5

        # Check key dimensions
        key_dims = ("novelty", "evidence_coverage", "method_validity")
        for dim in key_dims:
            if dim in scores and scores[dim] < 4:
                return False, f"{dim} score {scores[dim]} below 4"

        if mean < threshold:
            return False, f"Mean score {mean:.1f} below threshold {threshold}"

        return True, f"Converged: mean={mean:.1f}, no critical objections"

    def _compute_unresolved(
        self,
        objections: list[Objection],
        responses: list[dict[str, Any]],
    ) -> list[Objection]:
        """Compute which objections remain unresolved after responses.

        Matching is by ``objection_id`` (content-stable, so a response to
        last round's objection also resolves this round's identical
        recurrence). The target-string fallback only serves legacy payloads.
        """
        if not responses:
            return list(objections)

        resolved_ids = {
            str(r.get("objection_id", "")) for r in responses if r.get("resolved")
        }
        resolved_targets = {
            r.get("target", "")
            for r in responses
            if r.get("resolved") and not r.get("objection_id")
        }
        return [
            o
            for o in objections
            if o.objection_id not in resolved_ids and o.target not in resolved_targets
        ]

    def _determine_outcome(
        self,
        critical: int,
        major: int,
        mean_score: float,
        prior_mean_score: float | None = None,
        unresolved: int | None = None,
        prior_unresolved: int | None = None,
    ) -> str:
        """Determine resolution outcome from metrics.

        The stagnation rule outranks the critical rule: on topic 78 a
        manuscript scoring ~1.5/5 was held in ``revise_and_repeat`` for 30
        rounds solely because ``critical > 0`` — a score that low for two
        consecutive rounds means revision noise, and the manuscript must be
        returned, not polished again.

        Stagnation means *no progress*, not merely *a low score*. A round that
        materially reduced the objection load is progress even while the score
        is still low, and rejecting it discards real revision work (topic 37:
        objections 96 -> 73 with a bit-identical mean, rejected at round 2).
        """
        stalled_score = (
            0.0 < mean_score < STAGNATION_MEAN_THRESHOLD
            and prior_mean_score is not None
            and 0.0 < prior_mean_score < STAGNATION_MEAN_THRESHOLD
            and mean_score <= prior_mean_score + _STAGNATION_SCORE_EPSILON
        )
        stalled_objections = True
        if unresolved is not None and prior_unresolved is not None:
            stalled_objections = unresolved > prior_unresolved * (
                1.0 - _STAGNATION_MIN_OBJECTION_DROP
            )
        if stalled_score and stalled_objections:
            return "reject_and_return"
        if critical > 0:
            return "revise_and_repeat"
        if mean_score >= 4.0 and major == 0:
            return "approved"
        if mean_score >= 4.0 and major > 0:
            return "approved_with_conditions"
        if mean_score < 3.0:
            return "reject_and_return"
        return "revise_and_repeat"

    def _round_objection_key_history(
        self, topic_id: int, target_stage: str
    ) -> list[set[str]]:
        """Per-round objection-key sets, in round order (all statuses)."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND stage = ? AND artifact_type = 'adversarial_round'
                ORDER BY id
                """,
                (topic_id, target_stage),
            ).fetchall()
        finally:
            conn.close()
        history: list[set[str]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            history.append(
                {
                    compute_objection_key(o.get("category", ""), o.get("target", ""))
                    for o in payload.get("objections", [])
                }
            )
        return history

    def _count_rounds(self, topic_id: int, target_stage: str) -> int:
        """Count how many adversarial rounds have been recorded.

        Counts superseded rounds too: recording a round supersedes the previous
        one, so an ``status = 'active'`` filter would always return 1 and the
        max-rounds guard in :meth:`should_repeat` could never fire.
        """
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM project_artifacts
                WHERE topic_id = ? AND stage = ? AND artifact_type = 'adversarial_round'
                """,
                (topic_id, target_stage),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
