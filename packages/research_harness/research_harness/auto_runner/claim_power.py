"""Power of a declared contrast, and the smallest effect a sample can detect.

Normal approximation, two-sided: power = Phi(|effect| / SE - z_{1-alpha/2}).
A contrast states its effect with a standard error, with an SD and the total n of
two equal groups (SE = 2 SD / sqrt(n)), or as a
hazard ratio with the event count (Schoenfeld: SE(ln HR) = 1/sqrt(D p (1-p))).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

POWER_TARGET = 0.8
ALPHA = 0.05
_Z = NormalDist()


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _critical(alpha: float = ALPHA, target: float = POWER_TARGET) -> float:
    return _Z.inv_cdf(1 - alpha / 2) + _Z.inv_cdf(target)


def effect_and_se(contrast: dict) -> tuple[float, float] | None:
    """(|effect|, SE) on the scale the test runs on, or None when not stated."""
    ratio = _positive(contrast.get("hazard_ratio"))
    if ratio is not None:
        events = _positive(contrast.get("events"))
        share = _positive(contrast.get("allocation")) or 0.5
        if events is None or not 0 < share < 1 or ratio == 1:
            return None
        return abs(math.log(ratio)), 1 / math.sqrt(events * share * (1 - share))
    effect = contrast.get("effect")
    if (
        isinstance(effect, bool)
        or not isinstance(effect, (int, float))
        or not math.isfinite(effect)
        or effect == 0
    ):
        return None
    se = _positive(contrast.get("se"))
    if se is None:
        sd, n = _positive(contrast.get("sd")), _positive(contrast.get("n"))
        se = 2 * sd / math.sqrt(n) if sd is not None and n is not None else None
    return (abs(float(effect)), se) if se is not None else None


def assess(
    contrast: dict, *, alpha: float = ALPHA, target: float = POWER_TARGET
) -> dict | None:
    """Power of one contrast and the effect it would need, or None without inputs."""
    stated = effect_and_se(contrast)
    if stated is None:
        return None
    effect, se = stated
    power = _Z.cdf(effect / se - _Z.inv_cdf(1 - alpha / 2))
    needed = _critical(alpha, target) * se
    if _positive(contrast.get("hazard_ratio")) is not None:
        needed = math.exp(needed)
    return {
        "power": round(power, 3),
        "powerable": power >= target,
        "se": round(se, 4),
        "detectable_effect": round(needed, 3),
        "alpha": alpha,
        "power_target": target,
    }


def budget(inputs: dict | None) -> dict:
    """The claim budget a sample carries, before any candidate is written.

    ``inputs``: ``n`` (analysis cases), ``events`` (outcome events) and any
    already-declared ``contrasts``. Every number is reported with the target
    it was computed at; nothing here is a threshold a caller can move.
    """
    inputs = inputs or {}
    n, events = _positive(inputs.get("n")), _positive(inputs.get("events"))
    critical = _critical()
    detectable = {}
    if n is not None:
        detectable["standardized_difference_two_equal_groups"] = round(
            2 * critical / math.sqrt(n), 3
        )
    if events is not None:
        detectable["hazard_ratio_balanced_binary"] = round(
            math.exp(critical / math.sqrt(events / 4)), 3
        )
    contrasts = []
    for row in inputs.get("contrasts") or []:
        if isinstance(row, dict):
            contrasts.append({**row, "assessment": assess(row)})
    return {
        "power_target": POWER_TARGET,
        "alpha": ALPHA,
        "n": n,
        "events": events,
        "detectable": detectable,
        "contrasts": contrasts,
        "powerable": [
            row.get("id") or row.get("name")
            for row in contrasts
            if row["assessment"] and row["assessment"]["powerable"]
        ],
    }


if __name__ == "__main__":
    # a0113's own numbers: c13 at a 0.5-month target with SE 0.37 is "about 27%".
    assert abs(assess({"effect": 0.5, "se": 0.37})["power"] - 0.27) < 0.01
    assert assess({"hazard_ratio": 2.0, "events": 66})["power"] > 0.8
    assert (
        budget({"n": 100})["detectable"]["standardized_difference_two_equal_groups"]
        == 0.56
    )
