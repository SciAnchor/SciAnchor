"""False-open-rate calibration for novelty verdicts (slice NOV02).

Reproduces HindSight's temporal-split protocol (arXiv 2603.15164 — no public
artifacts, method reimplemented per the sourcing-principles 裁决记录): judge a
candidate gap with retrieval restricted to pre-cutoff literature
(``gap_ground_verify(published_before=...)``), then score the verdict against
what is known to exist. Seed cases come from the 2026-08 automated-research
gap-mining record (docs/innovation-kb/evidence/), where a web-enabled panel
found direct pre-emptors the automated verdict missed in 8 of 9 candidates —
each case therefore carries a confirmed ground truth.

The harness is deterministic: the verifier is injected as
``callable(case, budget) -> result dict`` so tests use fakes and the real run
wraps the ``gap_ground_verify`` primitive. Two failure modes are separated per
case — the pre-emptor was never retrieved (recall failure) vs retrieved but
not recognised as occupying (judge failure) — because they call for different
fixes (index/recency lane vs judge prompt).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: Verdicts counted as "the candidate looks open" when the truth is occupied.
_OPTIMISTIC_VERDICTS = {"open", "partially_occupied"}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CalibrationCase:
    case_id: str
    gap: str
    truth: str  # "occupied" | "open"
    preemptors: list[dict[str, str]] = field(default_factory=list)
    judged_at: str = ""  # YYYY-MM-DD — honest replays cut retrieval here
    notes: str = ""

    def __post_init__(self) -> None:
        if self.truth not in {"occupied", "open"}:
            raise ValueError(f"truth must be occupied|open, got {self.truth!r}")
        if self.truth == "occupied" and not self.preemptors:
            raise ValueError(
                f"case {self.case_id}: occupied ground truth requires at "
                "least one confirmed pre-emptor"
            )


def _load_preemptor(raw: dict[str, Any]) -> dict[str, str]:
    item = {
        "title": str(raw.get("title", "")),
        "arxiv_id": str(raw.get("arxiv_id", "")),
    }
    published_ym = str(raw.get("published_ym") or "").strip()
    if published_ym:
        item["published_ym"] = published_ym
    return item


def load_cases(path: Path | str) -> list[CalibrationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        CalibrationCase(
            case_id=str(item["case_id"]),
            gap=str(item["gap"]),
            truth=str(item["truth"]),
            preemptors=[_load_preemptor(p) for p in item.get("preemptors", [])],
            judged_at=str(item.get("judged_at", "")),
            notes=str(item.get("notes", "")),
        )
        for item in payload["cases"]
    ]


def _norm_title(title: str) -> str:
    return _NON_ALNUM.sub(" ", (title or "").lower()).strip()


def _mentions(preemptor: dict[str, str], item: dict[str, Any]) -> bool:
    arxiv = str(preemptor.get("arxiv_id") or "")
    if arxiv and arxiv == str(item.get("arxiv_id") or ""):
        return True
    wanted = _norm_title(str(preemptor.get("title") or ""))
    seen = _norm_title(str(item.get("title") or ""))
    return bool(wanted) and (wanted in seen or seen in wanted) if seen else False


def _any_preemptor_in(
    preemptors: list[dict[str, str]], items: list[dict[str, Any]]
) -> bool:
    return any(_mentions(p, item) for p in preemptors for item in items)


def evaluate_case(case: CalibrationCase, result: dict[str, Any]) -> dict[str, Any]:
    """Score one verifier result against the case's ground truth.

    ``result`` needs ``verdict`` and ``occupying`` (list of {title, arxiv_id});
    ``candidates`` (all retrieved papers, same shape) is optional — without it
    the recall/judge split is reported as unknown rather than guessed.
    """
    verdict = str(result.get("verdict", "")).strip().lower()
    cited = [i for i in (result.get("occupying") or []) if isinstance(i, dict)]
    candidates = result.get("candidates")

    preemptor_cited = _any_preemptor_in(case.preemptors, cited)
    preemptor_retrieved: bool | None = None
    if candidates is not None:
        preemptor_retrieved = preemptor_cited or _any_preemptor_in(
            case.preemptors, [i for i in candidates if isinstance(i, dict)]
        )

    record: dict[str, Any] = {
        "case_id": case.case_id,
        "truth": case.truth,
        "verdict": verdict,
        "preemptor_cited": preemptor_cited,
        "preemptor_retrieved": preemptor_retrieved,
    }
    # NOV02 judge arm (judge_mode="panel"): keep per-perspective votes and
    # narrowness notes in the record for inspection; no metric consumes them.
    if result.get("judge_votes"):
        record["judge_votes"] = result["judge_votes"]
    if result.get("narrowness"):
        record["narrowness"] = result["narrowness"]
    if case.truth == "occupied":
        record["missed_occupation"] = verdict != "occupied"
        record["false_open"] = verdict in _OPTIMISTIC_VERDICTS
        if preemptor_retrieved is not None:
            record["failure_mode"] = (
                "none"
                if verdict == "occupied"
                else ("judge" if preemptor_retrieved else "recall")
            )
    else:
        record["false_occupied"] = verdict == "occupied"
    return record


def _rate(records: list[dict[str, Any]], key: str) -> float | None:
    hits = [r[key] for r in records if key in r]
    return (sum(bool(h) for h in hits) / len(hits)) if hits else None


def prior_success_index(
    prior: dict[str, Any] | None,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Map (budget, case_id) → evaluated record from a previous calibrate JSON."""
    index: dict[tuple[int, str], dict[str, Any]] = {}
    if not prior:
        return index
    for point in prior.get("curve") or []:
        try:
            budget = int(point["budget"])
        except (KeyError, TypeError, ValueError):
            continue
        for rec in point.get("records") or []:
            case_id = str(rec.get("case_id") or "")
            if case_id:
                index[(budget, case_id)] = rec
    return index


def run_calibration(
    cases: list[CalibrationCase],
    verify: Callable[[CalibrationCase, int], dict[str, Any]],
    budgets: list[int],
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay every case at every retrieval budget; return the curve.

    A verifier exception marks the case ``error`` for that budget and is
    excluded from rates — a crashed replay must not read as a correct verdict.

    ``prior`` is an optional previous calibrate report: successful records are
    reused and not re-verified; prior ``errors`` are retried. Enables resume
    after gateway faults without replaying the whole matrix.
    """
    reused = prior_success_index(prior)
    resumed_cells = 0
    curve: list[dict[str, Any]] = []
    for budget in budgets:
        records: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for case in cases:
            key = (budget, case.case_id)
            if key in reused:
                records.append(reused[key])
                resumed_cells += 1
                continue
            try:
                result = verify(case, budget)
            except Exception as exc:  # noqa: BLE001 — record, keep replaying
                errors.append({"case_id": case.case_id, "error": str(exc)})
                continue
            records.append(evaluate_case(case, result))
        occupied = [r for r in records if r["truth"] == "occupied"]
        with_recall = [r for r in occupied if r["preemptor_retrieved"] is not None]
        judged = [r for r in with_recall if r["preemptor_retrieved"]]
        curve.append(
            {
                "budget": budget,
                "n_cases": len(records),
                "false_open_rate": _rate(occupied, "false_open"),
                "missed_occupation_rate": _rate(occupied, "missed_occupation"),
                "preemptor_retrieval_recall": _rate(with_recall, "preemptor_retrieved"),
                "judge_miss_rate_given_retrieved": _rate(judged, "missed_occupation"),
                "records": records,
                "errors": errors,
            }
        )
    return {
        "budgets": budgets,
        "curve": curve,
        "resumed_cells": resumed_cells,
    }
