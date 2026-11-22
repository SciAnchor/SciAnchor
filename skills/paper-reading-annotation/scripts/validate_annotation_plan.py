#!/usr/bin/env python3
"""Validate a PDF annotation plan against RH/Zotero marginalia rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

FORBIDDEN_PHRASES = (
    "RH原语",
    "Primary primitive",
    "我会",
    "学生",
    "给新读者",
    "新读者",
    "让读者",
    "给读者",
    "对读者",
    "作为读者",
)

REQUIRED_BY_PROFILE: dict[str, dict[str, Any]] = {
    "zotero-content-primitives-v2": {
        "exact_count": 19,
        "required_categories": [
            "problem",
            "motivation",
            "core-claim",
            "concept-boundary",
            "method-taxonomy",
            "theoretical-innovation",
            "algorithm-step",
            "hidden-assumption",
            "evidence",
            "baseline",
            "reproducibility",
            "critical-assessment",
            "limitation-risk",
            "cross-paper-link",
            "rh-mapping",
            "follow-up",
        ],
        "exact_category_counts": {
            "problem": 1,
            "motivation": 2,
            "core-claim": 1,
            "concept-boundary": 1,
            "method-taxonomy": 2,
            "theoretical-innovation": 1,
            "algorithm-step": 1,
            "hidden-assumption": 1,
            "evidence": 2,
            "baseline": 1,
            "reproducibility": 1,
            "critical-assessment": 1,
            "limitation-risk": 1,
            "cross-paper-link": 1,
            "rh-mapping": 1,
            "follow-up": 1,
        },
        "required_primitive_focus": [
            "paper_summarize",
            "claim_extract",
            "deep_read",
            "method_taxonomy",
            "baseline_identify",
            "evidence_matrix",
            "contradiction_detect",
            "consistency_check",
            "gap_detect",
            "section_draft",
        ],
        "forbidden_categories": [
            "writing-move",
            "reusable-framing",
            "surprise",
        ],
        "comment_label_required": True,
        "primitive_focus_required": True,
    },
    "zotero-marginalia-batch-v1": {
        "exact_count": 19,
        "required_categories": [
            "problem",
            "motivation",
            "core-claim",
            "method-taxonomy",
            "evidence",
            "baseline",
            "limitation-risk",
            "writing-move",
            "rh-mapping",
            "follow-up",
        ],
        "comment_label_required": True,
    },
    "phd-quick-grasp-v1": {
        "min_count": 15,
        "required_categories": [
            "problem",
            "core-claim",
            "method-taxonomy",
            "evidence",
            "limitation-risk",
            "rh-mapping",
        ],
        "comment_label_required": True,
    },
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("annotation plan must be a JSON object")
    annotations = payload.get("annotations")
    if not isinstance(annotations, list):
        raise ValueError("annotation plan field 'annotations' must be a list")
    return payload


def validate_plan(payload: dict[str, Any], *, profile_override: str | None = None) -> dict[str, Any]:
    profile = _normalize(profile_override or str(payload.get("profile") or "")) or "phd-quick-grasp-v1"
    rules = REQUIRED_BY_PROFILE.get(profile)
    if rules is None:
        raise ValueError(f"unsupported annotation profile: {profile}")

    annotations = payload.get("annotations") or []
    errors: list[str] = []
    warnings: list[str] = []
    forbidden_hits: list[dict[str, Any]] = []
    unlabeled_comments: list[int] = []
    missing_anchor: list[int] = []
    missing_comment: list[int] = []
    category_counts: dict[str, int] = {}
    primitive_counts: dict[str, int] = {}
    primitive_focus_union: set[str] = set()
    missing_primitive_focus: list[int] = []

    planned_count = len(annotations)
    exact_count = rules.get("exact_count")
    min_count = rules.get("min_count")
    max_count = rules.get("max_count")

    if exact_count is not None and planned_count != int(exact_count):
        errors.append(
            f"profile {profile} requires exactly {exact_count} annotations, got {planned_count}"
        )
    if min_count is not None and planned_count < int(min_count):
        errors.append(
            f"profile {profile} requires at least {min_count} annotations, got {planned_count}"
        )
    if max_count is not None and planned_count > int(max_count):
        errors.append(
            f"profile {profile} allows at most {max_count} annotations, got {planned_count}"
        )

    for index, item in enumerate(annotations, start=1):
        if not isinstance(item, dict):
            errors.append(f"annotation #{index} must be an object")
            continue
        anchor = _normalize(str(item.get("anchor") or ""))
        comment = _normalize(str(item.get("comment") or ""))
        category = _normalize(str(item.get("category") or ""))
        primitive_focus_raw = item.get("primitive_focus")
        primitive_focus = [
            _normalize(str(value))
            for value in (primitive_focus_raw or [])
            if _normalize(str(value))
        ]
        if not anchor:
            missing_anchor.append(index)
        if not comment:
            missing_comment.append(index)
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1
        if rules.get("primitive_focus_required"):
            if not isinstance(primitive_focus_raw, list) or not primitive_focus:
                missing_primitive_focus.append(index)
        for primitive in primitive_focus:
            primitive_focus_union.add(primitive)
            primitive_counts[primitive] = primitive_counts.get(primitive, 0) + 1
        if rules.get("comment_label_required") and comment and not re.match(r"^【[^】]+】", comment):
            unlabeled_comments.append(index)
        for phrase in FORBIDDEN_PHRASES:
            if phrase and phrase in comment:
                forbidden_hits.append(
                    {
                        "index": index,
                        "phrase": phrase,
                        "comment": comment,
                    }
                )

    if missing_anchor:
        errors.append(f"missing anchor in annotations: {missing_anchor}")
    if missing_comment:
        errors.append(f"missing comment in annotations: {missing_comment}")
    if unlabeled_comments:
        errors.append(f"comments missing Chinese label prefix: {unlabeled_comments}")
    if forbidden_hits:
        errors.append(f"forbidden expressions found: {len(forbidden_hits)}")

    required_categories = [str(item) for item in rules.get("required_categories") or []]
    missing_categories = [name for name in required_categories if category_counts.get(name, 0) == 0]
    if missing_categories:
        errors.append(f"missing required categories: {', '.join(missing_categories)}")

    exact_category_counts = rules.get("exact_category_counts") or {}
    if exact_category_counts:
        unexpected_categories = sorted(
            category for category in category_counts.keys() if category not in exact_category_counts
        )
        if unexpected_categories:
            errors.append(
                f"unexpected categories for profile {profile}: {', '.join(unexpected_categories)}"
            )
        for category, expected in exact_category_counts.items():
            actual = int(category_counts.get(category, 0))
            if actual != int(expected):
                errors.append(
                    f"profile {profile} requires category {category} count={expected}, got {actual}"
                )

    forbidden_categories = [_normalize(str(v)) for v in rules.get("forbidden_categories") or []]
    present_forbidden_categories = [
        category for category in forbidden_categories if category_counts.get(category, 0) > 0
    ]
    if present_forbidden_categories:
        errors.append(
            "forbidden categories present: " + ", ".join(sorted(present_forbidden_categories))
        )

    if missing_primitive_focus:
        errors.append(f"annotations missing primitive_focus: {missing_primitive_focus}")

    required_primitive_focus = [str(item) for item in rules.get("required_primitive_focus") or []]
    missing_required_primitives = [
        primitive
        for primitive in required_primitive_focus
        if primitive not in primitive_focus_union
    ]
    if missing_required_primitives:
        errors.append(
            "missing required primitive coverage: " + ", ".join(missing_required_primitives)
        )

    if planned_count <= 3:
        errors.append("3-note abstract-only plans are not acceptable for PDF re-annotation")

    if planned_count < 8:
        warnings.append("very sparse annotation plan; likely too weak for a real PDF reading pass")

    return {
        "ok": not errors,
        "profile": profile,
        "planned_count": planned_count,
        "required_categories": required_categories,
        "category_counts": category_counts,
        "primitive_counts": primitive_counts,
        "primitive_focus_union": sorted(primitive_focus_union),
        "missing_categories": missing_categories,
        "missing_required_primitives": missing_required_primitives,
        "forbidden_hits": forbidden_hits,
        "warnings": warnings,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="Annotation plan JSON path")
    parser.add_argument("--profile", default="", help="Override profile in the plan JSON")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args(argv)

    payload = _load(Path(args.spec).expanduser().resolve())
    result = validate_plan(payload, profile_override=args.profile or None)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "OK" if result["ok"] else "FAIL"
        print(f"[{status}] profile={result['profile']} annotations={result['planned_count']}")
        for message in result["errors"]:
            print(f"ERROR: {message}", file=sys.stderr)
        for message in result["warnings"]:
            print(f"WARNING: {message}", file=sys.stderr)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
