"""Table archetypes and per-archetype record contracts.

Single source of truth for which record fields each table type consumes, and
how records map onto the (row, column-group, column-metric) axes. Mirrors the
figure renderer's ``CHART_FIELD_REQUIREMENTS`` so the planning layer can reason
about figures and tables with one vocabulary.
"""

from __future__ import annotations

from typing import Any

# lower-is-better metric name fragments, used only as a fallback when a record
# does not carry an explicit ``higher_is_better`` flag.
LOWER_IS_BETTER_HINTS = (
    "error",
    "err",
    "loss",
    "rmse",
    "mae",
    "mse",
    "mape",
    "nll",
    "ppl",
    "perplex",
    "fid",
    "kid",
    "latency",
    "time",
    "cost",
    "flops",
    "params",
    "ece",
    "wer",
    "cer",
    "eer",
    "rank",
)


TABLE_FIELD_REQUIREMENTS: dict[str, dict[str, Any]] = {
    # Classic ML leaderboard: rows = methods, columns = (dataset x metric),
    # best per column bolded, mean +- std over seeds.
    "main_results": {
        "required": ["method", "metric", "value"],
        "optional": ["dataset", "std", "lo", "hi", "n", "higher_is_better"],
        "row": "method",
        "group": "dataset",
        "metric": "metric",
        "granularity": "per-run (n>=3 to aggregate mean +- std)",
    },
    # Ablation: rows = variants (component on/off), columns = metric(s).
    "ablation": {
        "required": ["variant", "metric", "value"],
        "optional": ["dataset", "std", "n", "higher_is_better"],
        "row": "variant",
        "group": "dataset",
        "metric": "metric",
        "granularity": "per-variant",
    },
    # Table 1 style baseline characteristics: rows = characteristics,
    # columns = cohort groups; cells are pre-formatted summaries (mean+-sd / n(%)).
    "baseline_characteristics": {
        "required": ["characteristic", "group", "value"],
        "optional": ["p_value", "n"],
        "row": "characteristic",
        "group": None,
        "metric": "group",
        "granularity": "per-characteristic",
        "no_best": True,  # descriptive table: never bold a "winner"
        "preformatted": True,  # value is already a display string
    },
}

_ALIASES = {
    "leaderboard": "main_results",
    "benchmark": "main_results",
    "main": "main_results",
    "results": "main_results",
    "comparison": "main_results",
    "ablation_table": "ablation",
    "component_ablation": "ablation",
    "table1": "baseline_characteristics",
    "cohort": "baseline_characteristics",
    "demographics": "baseline_characteristics",
}


def canonical_table_kind(kind: str | None) -> str | None:
    key = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in TABLE_FIELD_REQUIREMENTS:
        return key
    return _ALIASES.get(key)


def table_field_requirements(kind: str | None) -> dict[str, Any]:
    canon = canonical_table_kind(kind)
    return dict(TABLE_FIELD_REQUIREMENTS.get(canon or "", {}))


def metric_higher_is_better(metric: str | None, explicit: bool | None) -> bool:
    """Resolve direction: explicit flag wins; else name heuristic; else up."""
    if explicit is not None:
        return bool(explicit)
    name = str(metric or "").strip().lower()
    for frag in LOWER_IS_BETTER_HINTS:
        if frag in name:
            return False
    return True
