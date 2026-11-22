"""E1 A/B writing-quality evaluation harness (EAG-Ladder batch 1).

Private self-development runner. Compares section generations under the
EAG contract conditions on a FIXED topic corpus, with preregistered
deterministic metrics. The generation step is injectable: tests use fakes;
the real run drives ``run_section_loop`` inside a sandbox DB with the
condition's env switches applied (see experiments/writing-ab/E1_RUNBOOK.md).

Conditions (cumulative, matching the plan's C0→C2):

- ``C0`` baseline: no style card, no section arcs (current default).
- ``C1`` +style card (RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN=1).
- ``C2`` +L1 section arcs on top (RESEARCH_HARNESS_EAG_SECTION_ARCS=1).

Deterministic metrics v0 (LLM-judge metrics are added at real-run time and
must be preregistered in the run manifest before execution):

- writing_checks violation density (violations per 1000 words, per check
  and total) — lower is better;
- word count;
- paragraph-structure distance to the section's arc plan when one exists
  (|paragraphs - planned moves|) — a coarse form-adherence proxy.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

# Cumulative condition ladder; each maps to the env switches that define it.
_SWITCHES = (
    "RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN",
    "RESEARCH_HARNESS_EAG_SECTION_ARCS",
    "RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES",
    "RESEARCH_HARNESS_EAG_LOGIC_TREE",
)


def _ladder(*on: str) -> dict[str, str]:
    """Every switch pinned explicitly: cumulative ladder, no ambient leakage."""
    return {switch: ("1" if switch in on else "0") for switch in _SWITCHES}


CONDITIONS: dict[str, dict[str, str]] = {
    "C0": _ladder(),
    "C1": _ladder(_SWITCHES[0]),
    "C2": _ladder(*_SWITCHES[:2]),
    # Batch-2 ladder extensions (E2): + L2 paragraph craft, + logic tree.
    "C3": _ladder(*_SWITCHES[:3]),
    "C4": _ladder(*_SWITCHES),
}

# (topic_id, section) generation callback: returns the drafted text.
GenerateFn = Callable[[int, str], str]


@dataclass
class GenerationRecord:
    topic_id: int
    section: str
    condition: str
    seed: int
    text: str
    metrics: dict[str, Any] = field(default_factory=dict)


@contextmanager
def condition_env(condition: str) -> Iterator[None]:
    """Apply a condition's env switches, restoring previous values after."""
    overrides = CONDITIONS[condition]
    saved = {key: os.environ.get(key) for key in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def evaluate_section_text(
    text: str, section: str, *, planned_moves: int | None = None
) -> dict[str, Any]:
    """Deterministic metrics for one drafted section."""
    from research_harness._workflow.execution.writing_checks import run_all_checks

    words = len(str(text or "").split())
    checks = run_all_checks(str(text or ""), section)
    violations: dict[str, int] = {}
    for result in checks:
        if not result.passed:
            violations[result.check_name] = max(1, len(result.items_found))
    total_violations = sum(violations.values())
    paragraphs = len([p for p in _PARA_SPLIT_RE.split(str(text or "")) if p.strip()])
    metrics: dict[str, Any] = {
        "words": words,
        "paragraphs": paragraphs,
        "violations": violations,
        "total_violations": total_violations,
        "violation_density_per_1k": (
            round(total_violations * 1000.0 / words, 3) if words else None
        ),
    }
    if planned_moves is not None:
        metrics["planned_moves"] = planned_moves
        metrics["structure_distance"] = abs(paragraphs - planned_moves)
    return metrics


def run_condition(
    *,
    topics: list[int],
    sections: list[str],
    condition: str,
    generate: GenerateFn,
    seeds: int = 1,
    planned_moves_by_section: dict[str, int] | None = None,
) -> list[GenerationRecord]:
    """Generate + evaluate every (topic, section, seed) under one condition."""
    records: list[GenerationRecord] = []
    planned = planned_moves_by_section or {}
    with condition_env(condition):
        for topic_id in topics:
            for section in sections:
                for seed in range(seeds):
                    text = generate(topic_id, section)
                    record = GenerationRecord(
                        topic_id=topic_id,
                        section=section,
                        condition=condition,
                        seed=seed,
                        text=text,
                    )
                    record.metrics = evaluate_section_text(
                        text, section, planned_moves=planned.get(section)
                    )
                    records.append(record)
    return records


def paired_summary(records: list[GenerationRecord]) -> dict[str, Any]:
    """Aggregate per condition + paired deltas vs C0 on shared keys.

    Pairing key is (topic_id, section, seed); deltas are computed on
    violation density (negative delta = condition beats baseline).
    """
    by_condition: dict[str, list[GenerationRecord]] = {}
    for record in records:
        by_condition.setdefault(record.condition, []).append(record)

    def _mean(values: list[float]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 3) if clean else None

    summary: dict[str, Any] = {"conditions": {}, "paired_vs_C0": {}}
    for condition, group in sorted(by_condition.items()):
        summary["conditions"][condition] = {
            "n": len(group),
            "mean_violation_density_per_1k": _mean(
                [r.metrics.get("violation_density_per_1k") for r in group]
            ),
            "mean_words": _mean([float(r.metrics.get("words") or 0) for r in group]),
            "mean_structure_distance": _mean(
                [
                    float(r.metrics["structure_distance"])
                    for r in group
                    if "structure_distance" in r.metrics
                ]
            ),
        }

    baseline = {(r.topic_id, r.section, r.seed): r for r in by_condition.get("C0", [])}
    for condition, group in sorted(by_condition.items()):
        if condition == "C0" or not baseline:
            continue
        deltas: list[float] = []
        wins = losses = ties = 0
        for record in group:
            base = baseline.get((record.topic_id, record.section, record.seed))
            if base is None:
                continue
            density = record.metrics.get("violation_density_per_1k")
            base_density = base.metrics.get("violation_density_per_1k")
            if density is None or base_density is None:
                continue
            delta = density - base_density
            deltas.append(delta)
            if delta < 0:
                wins += 1
            elif delta > 0:
                losses += 1
            else:
                ties += 1
        summary["paired_vs_C0"][condition] = {
            "n_pairs": len(deltas),
            "mean_delta_violation_density": _mean(deltas),
            "wins": wins,
            "losses": losses,
            "ties": ties,
        }
    return summary


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_report(
    *,
    records: list[GenerationRecord],
    topics: list[int],
    sections: list[str],
    seeds: int,
) -> dict[str, Any]:
    return {
        "schema": "rh.selfdev.writing_ab_eval.v1",
        "git_sha": _git_sha(),
        "topics": topics,
        "sections": sections,
        "seeds": seeds,
        "conditions": {name: dict(env) for name, env in CONDITIONS.items()},
        "summary": paired_summary(records),
        "records": [
            {
                "topic_id": r.topic_id,
                "section": r.section,
                "condition": r.condition,
                "seed": r.seed,
                "metrics": r.metrics,
                "chars": len(r.text),
            }
            for r in records
        ],
    }


def write_report(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
