"""Triage papers that need manual download: filter by venue tier + LLM necessity."""

from __future__ import annotations

import logging
from typing import Any

from ..venue_facts import venue_tier_label, venue_tier_score

logger = logging.getLogger(__name__)

# CCF-B (70) / CAS-Q2 (65) and above count as "worth human effort".
_TOP_VENUE_MIN_SCORE = 65


def triage_manual_papers(
    manual_list: list[dict[str, Any]],
    necessity_map: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Filter manual_list to papers worth human effort (venue OR necessity).

    Args:
        manual_list: papers from AcquisitionReport.manual_list
        necessity_map: {paper_id: "high"|"medium"|"low"} from paper_coverage_check

    Returns:
        Filtered list with added 'triage_reason' field.
    """
    necessity_map = necessity_map or {}
    result: list[dict[str, Any]] = []

    for item in manual_list:
        paper_id = item["paper_id"]
        venue = item.get("venue", "")
        tier = venue_tier_label(venue) or None
        necessity = necessity_map.get(paper_id, "medium")

        is_top_venue = venue_tier_score(venue) >= _TOP_VENUE_MIN_SCORE
        is_high_necessity = necessity == "high"

        if is_top_venue or is_high_necessity:
            reasons = []
            if is_top_venue:
                reasons.append(f"venue_tier={tier}")
            if is_high_necessity:
                reasons.append("llm_necessity=high")
            item_out = {
                **item,
                "triage_reason": " + ".join(reasons),
                "venue_tier": tier,
            }
            result.append(item_out)
        else:
            logger.debug(
                "Skipping paper %d (%s) — venue=%s, necessity=%s",
                paper_id,
                item.get("title", ""),
                venue,
                necessity,
            )

    return result
