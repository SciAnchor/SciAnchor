"""Two-phase figure-contract planning helpers (deterministic, no LLM).

The design layer of the full-paper figure contract runs at experiment-design
time (before real results exist); the execution layer runs at write time. This
module bridges them with three pure/deterministic pieces:

- ``synthesize_planned_inventory`` — build a record inventory the plan step can
  ground on, from whatever the topic already has: explicit records/matrix JSON,
  then ``experiment_result`` artifacts (real results), then ``goal_pool`` +
  ``baseline_matrix`` +
  ``PAPER_PLAN``. Carries ``mode: planned|observed`` so the plan prompt knows
  whether the numbers are final. Never invents metrics it cannot source.
- ``derive_logging_requirements`` — from a suite spec, list what each panel's
  chart needs recorded during experiments (fields + granularity), so the run
  phase logs the right things instead of discovering gaps at write time.
- ``reconcile`` — diff a design-phase spec against the actual records: which
  panels are feedable, which must be pruned, which experiments feed no panel.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .experiment_figures import (
    canonical_chart_kind,
    chart_field_requirements,
    summarize_records_for_plan,
)


# --------------------------------------------------------------------------- #
# Planned inventory synthesis (fallback chain)                                #
# --------------------------------------------------------------------------- #


def synthesize_planned_records(
    *,
    db: Any = None,
    topic_id: int | None = None,
    records: Sequence[Mapping[str, Any]] | None = None,
    matrix_json: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Return (records, source, mode) from the best available grounding.

    Resolution order (first non-empty wins):

    1. explicit ``records`` (observed).
    2. explicit ``matrix_json`` (planned).
    3. ``experiment_result`` artifacts (observed).
    4. ``goal_pool`` + ``baseline_matrix`` (planned).

    Raises ``ValueError`` when nothing is available, so the caller can demand
    explicit input rather than plan against a fabricated matrix.
    """
    if records:
        return (
            [dict(r) for r in records if isinstance(r, Mapping)],
            "explicit_records",
            "observed",
        )

    art_records: list[dict[str, Any]] = []
    art_mode = "planned"
    if db is not None and topic_id is not None:
        art_records, art_mode = _records_from_experiment_artifacts(db, int(topic_id))
    # Observed evidence outranks any planned inventory, including a matrix the caller
    # passed explicitly. A matrix states what an experiment was going to produce; once
    # it has produced something, the intent is not the thing to plot — and the planner
    # is shown this inventory as "the only data available to plot". csmopen12's figure
    # plan is built inside WRITE, long after EVIDENCE, and was handed a matrix anyway:
    # it filtered four result figures on task/model/target/split while its 884 real
    # records carried method/metric/split/cutoff/figure_type, and no panel could be fed.
    if art_records and art_mode == "observed":
        return art_records, "experiment_result_artifact", art_mode

    if isinstance(matrix_json, Mapping):
        synth = _matrix_json_to_records(matrix_json)
        if synth:
            return synth, "explicit_matrix", "planned"

    if art_records:
        return art_records, "experiment_result_artifact", art_mode

    if db is not None and topic_id is not None:
        goal_records = _records_from_goal_pool_and_baselines(db, int(topic_id))
        if goal_records:
            return goal_records, "goal_pool_baselines", "planned"

    raise ValueError(
        "no experiment inventory available: pass explicit records/matrix, or "
        "build goal_pool / experiment_result artifacts for the topic first "
        "(refusing to plan figures against a fabricated matrix)."
    )


def synthesize_planned_inventory(
    *,
    db: Any = None,
    topic_id: int | None = None,
    records: Sequence[Mapping[str, Any]] | None = None,
    matrix_json: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Best-available record inventory (compact summary) for the plan step,
    tagged with ``source`` and ``mode`` (planned|observed)."""
    synth, source, mode = synthesize_planned_records(
        db=db, topic_id=topic_id, records=records, matrix_json=matrix_json
    )
    inv = summarize_records_for_plan(synth)
    inv.update(source=source, mode=mode)
    return inv


def _matrix_json_to_records(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand a compact planned matrix into benchmark-shaped records.

    Accepts {"datasets":[...], "methods":[...], "metric":"F1"} or a
    {"cells":[{dataset,method,metric,value?}]} list.
    """
    cells = matrix.get("cells")
    if isinstance(cells, list):
        out = []
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            out.append(
                {
                    "figure_type": str(cell.get("figure_type", "benchmark")),
                    "dataset": str(cell.get("dataset", "")),
                    "method": str(cell.get("method", "")),
                    "metric": str(cell.get("metric", matrix.get("metric", "score"))),
                    **({"value": cell["value"]} if "value" in cell else {}),
                }
            )
        return [c for c in out if c["dataset"] and c["method"]]
    datasets = [str(d) for d in matrix.get("datasets", []) if str(d)]
    methods = [str(m) for m in matrix.get("methods", []) if str(m)]
    metrics = matrix.get("metrics") or (
        [matrix["metric"]] if matrix.get("metric") else []
    )
    metrics = [str(m) for m in metrics if str(m)] or ["score"]
    if not datasets or not methods:
        return []
    return [
        {"figure_type": "benchmark", "dataset": d, "method": m, "metric": metric}
        for d in datasets
        for m in methods
        for metric in metrics
    ]


def _records_from_experiment_artifacts(
    db: Any, topic_id: int
) -> tuple[list[dict[str, Any]], str]:
    """Pull records from experiment_result artifacts (observed).

    Returns ([], "planned") when none.
    """
    payloads = _active_artifact_payloads(db, topic_id, "experiment_result")
    records: list[dict[str, Any]] = []
    for payload in payloads:
        records.extend(_coerce_result_rows(payload))
    if records:
        return records, "observed"
    return [], "planned"


def _coerce_result_rows(block: Any) -> list[dict[str, Any]]:
    """Coerce a variety of result payload shapes into flat benchmark rows."""
    rows: list[dict[str, Any]] = []
    items = (
        block
        if isinstance(block, list)
        else block.get("rows")
        if isinstance(block, Mapping)
        else None
    )
    if not isinstance(items, list):
        # {dataset: {method: value}} nested form
        if isinstance(block, Mapping):
            for dataset, inner in block.items():
                if isinstance(inner, Mapping):
                    for method, value in inner.items():
                        rows.append(
                            {
                                "figure_type": "benchmark",
                                "dataset": str(dataset),
                                "method": str(method),
                                "metric": "score",
                                "value": value,
                            }
                        )
        return rows
    for item in items:
        if not isinstance(item, Mapping):
            continue
        row = {"figure_type": str(item.get("figure_type", "benchmark"))}
        for key in ("dataset", "method", "metric", "variant", "value", "std"):
            if key in item:
                row[key] = item[key]
        if row.get("dataset") or row.get("method") or row.get("value") is not None:
            rows.append(row)
    return rows


def _records_from_goal_pool_and_baselines(
    db: Any, topic_id: int
) -> list[dict[str, Any]]:
    """Synthesize a planned benchmark inventory from goal_pool rows (dataset ×
    metric × baseline) plus baseline_matrix methods. Values stay absent — this
    is a *planned* matrix, not results."""
    goals = _goal_pool_rows(db, topic_id)
    if not goals:
        return []
    methods = _baseline_methods(db, topic_id) or ["Baseline"]
    methods = list(dict.fromkeys([*methods, "Ours"]))
    records: list[dict[str, Any]] = []
    for goal in goals:
        dataset = str(goal.get("dataset") or "").strip()
        metric = str(goal.get("metric_name") or "score").strip()
        if not dataset:
            continue
        for method in methods:
            records.append(
                {
                    "figure_type": "benchmark",
                    "dataset": dataset,
                    "method": method,
                    "metric": metric,
                }
            )
    return records


# --------------------------------------------------------------------------- #
# Defensive DB helpers                                                         #
# --------------------------------------------------------------------------- #


def _active_artifact_payloads(
    db: Any, topic_id: int, artifact_type: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        conn = db.connect()
    except Exception:
        return out
    try:
        rows = conn.execute(
            """SELECT payload_json FROM project_artifacts
               WHERE topic_id = ? AND artifact_type = ? AND status = 'active'
               ORDER BY version DESC, id DESC""",
            (topic_id, artifact_type),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError, KeyError):
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _goal_pool_rows(db: Any, topic_id: int) -> list[dict[str, Any]]:
    try:
        conn = db.connect()
    except Exception:
        return []
    try:
        rows = conn.execute(
            """SELECT dataset, metric_name, baseline_metric, target_metric_delta, target_venue
               FROM goal_pool WHERE topic_id = ? AND status = 'active'
               ORDER BY priority_rank""",
            (topic_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _baseline_methods(db: Any, topic_id: int) -> list[str]:
    methods: list[str] = []
    for payload in _active_artifact_payloads(db, topic_id, "baseline_matrix"):
        raw = payload.get("baselines")
        if not isinstance(raw, list):
            raw = payload.get("baseline_records")
        for item in raw or []:
            if isinstance(item, Mapping):
                name = str(
                    item.get("method") or item.get("name") or item.get("baseline") or ""
                ).strip()
                if name:
                    methods.append(name)
    return list(dict.fromkeys(methods))


# --------------------------------------------------------------------------- #
# Logging requirements                                                         #
# --------------------------------------------------------------------------- #


def _iter_spec_panels(spec: Mapping[str, Any]):
    """Yield (figure_id, panel_id, panel_dict) over a suite spec (plan wrapper ok)."""
    inner = spec
    for wrapper in ("plan", "suite", "figure_suite"):
        nested = inner.get(wrapper) if isinstance(inner, Mapping) else None
        if isinstance(nested, Mapping) and "figures" in nested:
            inner = nested
            break
    for f_index, figure in enumerate(
        inner.get("figures", []) if isinstance(inner, Mapping) else []
    ):
        if not isinstance(figure, Mapping):
            continue
        fid = str(figure.get("figure_id", "") or f"figure_{f_index + 1}")
        for p_index, panel in enumerate(figure.get("panels", []) or []):
            if isinstance(panel, Mapping):
                pid = str(panel.get("panel_id", "") or chr(ord("a") + p_index))
                yield fid, pid, panel


def derive_logging_requirements(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What each deterministic panel needs recorded during experiments.

    Skips generative/latex/external panels (image, qualitative_grid, and any
    panel whose ``pipeline`` is not deterministic) — those don't consume logged
    records. Deduplicated by (chart, required-fields).
    """
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[dict[str, Any]] = []
    for fid, pid, panel in _iter_spec_panels(spec):
        pipeline = str(panel.get("pipeline", "deterministic") or "deterministic")
        if pipeline not in ("deterministic", ""):
            continue
        kind = canonical_chart_kind(str(panel.get("chart", "")))
        if kind is None:
            continue
        req = chart_field_requirements(kind)
        required = list(req.get("required", []))
        if not required:  # image/qualitative — asset-backed, nothing to log
            continue
        key = (kind, tuple(required))
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "panel": f"{fid}/{pid}",
            "chart": kind,
            "required_fields": required,
            "granularity": req.get("granularity", ""),
        }
        optional = list(req.get("optional", []))
        if optional:
            entry["optional_fields"] = optional
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Reconcile design spec against actual records                                #
# --------------------------------------------------------------------------- #


def reconcile(
    spec: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Diff a design-phase (v1) suite spec against actual records.

    Deterministic: uses the same record-selection logic as the renderer to
    decide, per panel, whether real records can feed it. Reports:

    - ``satisfied`` / ``unsatisfied`` panels (with reason);
    - ``prune`` — figures whose every panel is unsatisfiable (drop at write time);
    - ``unfed_figure_types`` — record figure_types no panel consumes (candidate
      analysis figures the design missed).
    """
    from .experiment_figures import _clean_record, _filter_miss, _select_panel_records
    import pandas as pd

    cleaned = [_clean_record(r) for r in records if isinstance(r, Mapping)]
    df = pd.DataFrame(cleaned) if cleaned else pd.DataFrame()

    satisfied: list[str] = []
    unsatisfied: list[dict[str, str]] = []
    prune: list[str] = []
    consumed_types: set[str] = set()

    for fid, pid, panel in _iter_spec_panels(spec):
        ref = f"{fid}/{pid}"
        pipeline = str(panel.get("pipeline", "deterministic") or "deterministic")
        if pipeline not in ("deterministic", ""):
            satisfied.append(ref)  # non-deterministic panels aren't record-fed
            continue
        kind = canonical_chart_kind(str(panel.get("chart", "")))
        if kind is None:
            unsatisfied.append(
                {"panel": ref, "reason": f"unsupported_chart:{panel.get('chart')}"}
            )
            continue
        if kind in ("image", "qualitative_grid"):
            if panel.get("asset_path") or panel.get("assets"):
                satisfied.append(ref)
            else:
                unsatisfied.append({"panel": ref, "reason": "missing_asset"})
            continue
        if df.empty:
            unsatisfied.append({"panel": ref, "reason": "no_records"})
            continue
        selected = _select_panel_records(df, panel, kind)
        if selected.empty:
            unsatisfied.append(
                {
                    "panel": ref,
                    "reason": f"no_matching_records{_filter_miss(df, panel)}",
                }
            )
        else:
            satisfied.append(ref)
            if "figure_type" in selected.columns:
                consumed_types |= {
                    str(t) for t in selected["figure_type"].unique() if str(t)
                }

    # figures with zero satisfied panels → prune candidates
    per_figure: dict[str, list[bool]] = {}
    for fid, pid, panel in _iter_spec_panels(spec):
        ref = f"{fid}/{pid}"
        per_figure.setdefault(fid, []).append(ref in satisfied)
    for fid, flags in per_figure.items():
        if flags and not any(flags):
            prune.append(fid)

    available_types = (
        {str(t) for t in df["figure_type"].unique() if str(t)}
        if not df.empty and "figure_type" in df.columns
        else set()
    )
    unfed_types = sorted(available_types - consumed_types)

    verdict = "complete" if not unsatisfied and not unfed_types else "gaps_found"
    return {
        "verdict": verdict,
        "satisfied": satisfied,
        "unsatisfied": unsatisfied,
        "prune": prune,
        "unfed_figure_types": unfed_types,
    }
