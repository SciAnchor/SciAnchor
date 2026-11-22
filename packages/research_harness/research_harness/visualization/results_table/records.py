"""Record normalization for the results-table renderer.

Records use the SAME plain-dict schema as the RH experiment-figure renderer so
the two can share one evidence stream (observed logs, reported baselines, or
planned matrices). The renderer never invents numbers: every value plotted or
tabulated comes from a caller record.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

NUMERIC_KEYS = ("value", "std", "lo", "hi", "n", "se", "ci")

# Row/column axis keys recognised across table archetypes. Mirrors the field
# vocabulary of the figure renderer (method/dataset/metric/value/std/...).
AXIS_KEYS = (
    "method",
    "variant",
    "dataset",
    "metric",
    "group",
    "characteristic",
    "split",
)

# Keys carried through onto cells/rows beyond the numeric/axis vocabulary.


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN guard
        return None
    return out


def clean_record(record: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = {str(key): value for key, value in record.items()}
    kind = str(cleaned.get("table_type") or cleaned.get("kind") or "").strip().lower()
    cleaned["table_type"] = kind
    # Preformatted (Table-1 / characteristic) records carry display strings; a
    # bare "1" must stay "1", not become 1.0. Detect via the characteristic row
    # key or the baseline_characteristics family.
    preformatted = ("characteristic" in cleaned) or kind in (
        "baseline_characteristics",
        "table1",
        "cohort",
        "demographics",
    )
    for key in NUMERIC_KEYS:
        if key not in cleaned:
            continue
        if key == "value" and preformatted:
            cleaned[key] = str(cleaned[key])  # keep display string verbatim
            continue
        coerced = _coerce_float(cleaned[key])
        if key == "value" and coerced is None:
            # keep pre-formatted display strings (e.g. "45.3 ± 8.2", "28 (56%)")
            # intact; only numeric values become floats for aggregation.
            continue
        cleaned[key] = coerced
    # higher_is_better may be absent; leave as None so the aggregator can fall
    # back to a metric-name heuristic rather than silently assuming "up".
    hib = cleaned.get("higher_is_better")
    if hib is not None:
        cleaned["higher_is_better"] = bool(hib)
    # comparability class: reference rows / hindsight upper bounds are shown but
    # never eligible to be the bolded "best" (a real need seen across papers).
    if cleaned.get("exclude_from_best") is not None:
        cleaned["exclude_from_best"] = bool(cleaned.get("exclude_from_best"))
    for key in AXIS_KEYS + ("row_group",):
        if key in cleaned and cleaned[key] is not None:
            cleaned[key] = str(cleaned[key]).strip()
    return cleaned


def clean_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [clean_record(r) for r in records if isinstance(r, Mapping)]
