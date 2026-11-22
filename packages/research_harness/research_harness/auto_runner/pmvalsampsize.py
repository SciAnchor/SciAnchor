"""Riley et al. BMJ 2024;384:e074821 — external-validation N* (O/E closed form).

Wraps the published O/E formula only. Calibration slope, C-statistic, and
sNB need LP / threshold inputs this module does not invent; those criteria
fail closed. pmsampsize (development) is out of scope. No 30-event default.
"""

from __future__ import annotations

import math
from typing import Any


class PmvalSampleSizeError(ValueError):
    """Missing or invalid pmvalsampsize inputs."""


def _positive_finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(str(value).strip())
        except (TypeError, ValueError):
            raise PmvalSampleSizeError(f"missing {name}") from None
    if not math.isfinite(value) or value <= 0:
        raise PmvalSampleSizeError(f"missing {name}")
    return float(value)


# BMJ 2024;384:e074821 tutorial precision. A looser declared SE shrinks N*
# and would freeze SUONR-class 94 events (se=1.0 → N*≈9). Tightening still raises N*.
OE_SE_LN_MAX = 0.1


def oe_n_star(*, prevalence: Any, se_ln_oe: Any) -> float:
    """N* = (1-φ) / (φ · [SE(ln(O/E))]^2)."""
    phi = _positive_finite(prevalence, "prevalence")
    if not 0 < phi < 1:
        raise PmvalSampleSizeError("missing prevalence")
    se = min(_positive_finite(se_ln_oe, "se_ln_oe"), OE_SE_LN_MAX)
    return (1.0 - phi) / (phi * se * se)


def n_star(criteria: str, /, **inputs: Any) -> float:
    # Positional-only: the DEFINE prompt asks for sample_size {"criteria": "oe", ...}, and a
    # caller passing that dict as **inputs collided with this name (a0113, 2026-09-27: TypeError).
    key = str(criteria or "").strip().lower().replace("-", "_").replace("/", "")
    if key in {"oe", "o_e", "observed_expected", "observedexpected"}:
        return oe_n_star(
            prevalence=inputs.get("prevalence", inputs.get("phi")),
            se_ln_oe=inputs.get("se_ln_oe", inputs.get("se_ln_OE")),
        )
    raise PmvalSampleSizeError(
        f"unsupported criteria {criteria}: slope/C/sNB need LP or threshold "
        "inputs this wrap does not invent"
    )
