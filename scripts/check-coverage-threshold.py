#!/usr/bin/env python3
"""Check pytest-cov JSON against the release coverage threshold decision."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE_JSON = ROOT / ".tmp" / "coverage-baseline" / "coverage.json"
DEFAULT_DECISION_PATH = ROOT / "docs" / "contracts" / "release-coverage-threshold.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def coverage_percent(coverage: dict[str, Any]) -> float:
    totals = coverage.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("coverage JSON is missing totals")
    raw_percent = totals.get("percent_covered")
    if raw_percent is None:
        raw_percent = totals.get("percent_statements_covered")
    if raw_percent is None:
        raise ValueError("coverage JSON totals are missing percent_covered")
    return float(raw_percent)


def rounded_down_threshold(percent: float) -> int:
    return max(0, min(100, math.floor(percent)))


def decision_threshold(decision: dict[str, Any]) -> float:
    raw_threshold = decision.get("threshold_percent")
    if raw_threshold is None:
        raise ValueError("coverage decision is missing threshold_percent")
    return float(raw_threshold)


def validate_coverage_threshold(
    *,
    measured_percent: float,
    threshold_percent: float,
) -> list[str]:
    if measured_percent + 1e-9 < threshold_percent:
        return [
            (
                "coverage regression: "
                f"{measured_percent:.2f}% is below threshold {threshold_percent:.2f}%"
            )
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "coverage_json",
        nargs="?",
        default=str(DEFAULT_COVERAGE_JSON),
        help="Path to pytest-cov coverage JSON.",
    )
    parser.add_argument(
        "--decision",
        default=str(DEFAULT_DECISION_PATH),
        help="Path to the machine-readable coverage threshold decision.",
    )
    args = parser.parse_args()

    coverage_path = Path(args.coverage_json)
    decision_path = Path(args.decision)
    if not coverage_path.is_file():
        print(f"FAIL: coverage JSON not found: {coverage_path}", file=sys.stderr)
        return 1
    if not decision_path.is_file():
        print(
            f"FAIL: coverage threshold decision not found: {decision_path}",
            file=sys.stderr,
        )
        return 1

    try:
        measured = coverage_percent(load_json(coverage_path))
        decision = load_json(decision_path)
        threshold = decision_threshold(decision)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: invalid coverage threshold input: {exc}", file=sys.stderr)
        return 1

    errors = validate_coverage_threshold(
        measured_percent=measured,
        threshold_percent=threshold,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    target = float(decision.get("target_percent", 80.0))
    print(
        "Coverage threshold passed: "
        f"{measured:.2f}% >= {threshold:.2f}% "
        f"(target {target:.2f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
