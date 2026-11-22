"""Coverage estimation for the Domain Panorama KB (plan §5).

We model multi-source harvesting as a *capture-recapture* problem: each source
is a sampling occasion, and every identity (canonical paper/system id) is a
"captured individual". The recapture structure — how many identities were seen
by exactly one source, exactly two, etc. — lets us estimate the total richness
(seen + unseen) with the **Chao2** incidence-based estimator, and hence the
fraction of the domain still missing.

Two runtime dashboards fall out (plan §5.3):

* **coverage estimate** — how much of the domain is still unseen (Chao2), plus
  the marginal discovery rate (are new runs still finding new things?);
* **freshness lag** — the age distribution of live edges (bi-temporal facts) and
  the last successful harvest per source.

Estimators (all pure stdlib, ``math`` only):

* Chao2 richness (Chao 1987; Colwell & Coddington 1994):
  ``S_est = S_obs + ((m-1)/m) * Q1^2 / (2*Q2)`` when ``Q2 > 0``.
* Bias-corrected Chao2 (used when ``Q2 == 0``; Chao 1987 eq. for the
  small-sample / no-doubletons case):
  ``S_est = S_obs + ((m-1)/m) * Q1*(Q1-1) / (2*(Q2+1))``.
* 95% CI via the log-transform of Chao (1987), which keeps the lower bound at
  or above ``S_obs``: with ``f0 = S_est - S_obs`` and variance ``var`` of
  ``f0``, ``C = exp(1.96 * sqrt(log(1 + var/f0^2)))`` gives
  ``[S_obs + f0/C, S_obs + f0*C]``. The variance uses the standard Chao2
  incidence formula (Colwell 2013, EstimateS; ``R = (m-1)/m``):
  ``var = R*(Q1^2)/(2*Q2)`` ... (full four-term form below).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import median
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .store import PanoramaStore

_Z = 1.96  # two-sided 95% normal quantile
_SQL_TS = "%Y-%m-%d %H:%M:%S"


# -- timestamp parsing --------------------------------------------------------


def _parse_sql_ts(value: str | None) -> datetime | None:
    """Parse a SQLite ``YYYY-MM-DD HH:MM:SS`` string as a UTC datetime.

    ``datetime('now')`` writes second-resolution UTC without a zone suffix, so
    we attach UTC explicitly. Fractional seconds and a trailing ``Z`` are
    tolerated. Unparseable / empty values yield ``None``.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        text = text.split(".", 1)[0]
    try:
        parsed = datetime.strptime(text, _SQL_TS)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _age_days(ts: datetime, now: datetime) -> float:
    return (now - ts).total_seconds() / 86400.0


# -- Chao2 richness -----------------------------------------------------------


def _chao2(s_obs: int, m: int, q1: int, q2: int) -> dict[str, Any]:
    """Chao2 point estimate + log-transform 95% CI.

    Guards every division: with ``m < 2`` the ``(m-1)/m`` correction and the
    whole estimator are undefined, so we return ``S_est == S_obs`` and no CI.
    """
    out: dict[str, Any] = {
        "s_est": float(s_obs),
        "ci_low": float(s_obs),
        "ci_high": float(s_obs),
        "used_bias_correction": False,
        "computable": False,
    }
    if s_obs == 0 or m < 2:
        return out

    ratio = (m - 1) / m
    if q2 > 0:
        f0 = ratio * (q1 * q1) / (2 * q2)
    else:
        # Bias-corrected form (no doubletons): Q1*(Q1-1) / (2*(Q2+1)).
        f0 = ratio * (q1 * (q1 - 1)) / (2 * (q2 + 1))
        out["used_bias_correction"] = True

    f0 = max(f0, 0.0)
    s_est = s_obs + f0
    out["s_est"] = s_est
    out["computable"] = True

    # Variance of f0 (Colwell 2013 / EstimateS Chao2 incidence formula).
    if q2 > 0:
        r = ratio
        term1 = r * (q1 * q1) / (2 * q2)  # == f0
        var = (
            r * (q1 * (2 * q1 - 1) ** 2) / (4 * q2)
            + r * r * (q1 * q1) * (2 * q1 - 1) / (2 * q2 * q2)
            + r * r * (q1**4) / (4 * q2**3)
        )
        # Guard against a degenerate collapse to zero (keeps CI a proper band).
        var = max(var, term1)
    else:
        # No-doubleton variance (Chao & Chiu; uses Q1 only).
        r = ratio
        var = (
            r * q1 * (q1 - 1) / 2
            + r * r * q1 * (2 * q1 - 1) ** 2 / 4
            - r * r * (q1**4) / (4 * s_est)
        )
        var = max(var, 0.0)

    if f0 > 0 and var > 0:
        ln_arg = 1.0 + var / (f0 * f0)
        c = math.exp(_Z * math.sqrt(math.log(ln_arg)))
        out["ci_low"] = s_obs + f0 / c
        out["ci_high"] = s_obs + f0 * c
    else:
        out["ci_low"] = s_est
        out["ci_high"] = s_est
    return out


# -- capture matrix / incidence ----------------------------------------------


def _incidence(matrix: dict[str, set[str]]) -> dict[str, Any]:
    """Distil the capture matrix into per-source counts and Q1/Q2."""
    per_source: dict[str, int] = {}
    sources: set[str] = set()
    q1 = q2 = 0
    for _identity, srcs in matrix.items():
        for src in srcs:
            per_source[src] = per_source.get(src, 0) + 1
            sources.add(src)
        k = len(srcs)
        if k == 1:
            q1 += 1
        elif k == 2:
            q2 += 1
    return {
        "per_source": dict(sorted(per_source.items())),
        "s_obs": len(matrix),
        "m": len(sources),
        "q1": q1,
        "q2": q2,
    }


def _source_health(
    runs: list[dict[str, Any]],
    per_source: dict[str, int],
) -> dict[str, Any]:
    """Distinguish sources that returned hits from sources that only failed.

    A source that 429'd on every query never appears in the capture matrix, so
    incidence alone cannot tell "searched and empty" from "never successfully
    searched". Failed harvest runs carry ``attrs.status == "failed"``.
    """
    attempted: set[str] = set(per_source)
    error_counts: dict[str, int] = {}
    for run in runs:
        source = str(run.get("source") or "")
        if not source:
            continue
        attempted.add(source)
        attrs = run.get("attrs") if isinstance(run.get("attrs"), dict) else {}
        if attrs.get("status") == "failed":
            error_counts[source] = error_counts.get(source, 0) + 1
    # Failed = had at least one error and contributed zero identities.
    failed = sorted(
        src for src, n in error_counts.items() if n > 0 and per_source.get(src, 0) == 0
    )
    return {
        "sources_attempted": sorted(attempted),
        "sources_failed": failed,
        "source_error_counts": dict(sorted(error_counts.items())),
    }


# -- marginal discovery -------------------------------------------------------


def _marginal_series(runs: list[dict[str, Any]], k: int) -> dict[str, Any]:
    """Chronological per-run discovery rate ``new_count / result_count``.

    Runs are already id-ordered by the store; we skip zero-result runs (an
    empty query carries no discovery signal). The rolling mean over the last
    ``k`` non-empty runs is the headline marginal rate.
    """
    rates: list[float] = []
    for run in runs:
        result_count = run.get("result_count") or 0
        if result_count <= 0:
            continue
        new_count = run.get("new_count") or 0
        rates.append(new_count / result_count)

    window = rates[-k:] if k > 0 else rates
    rolling = sum(window) / len(window) if window else None
    return {
        "rates": rates,
        "k": k,
        "window": window,
        "rolling_rate": rolling,
        "computable": rolling is not None,
    }


# -- freshness ----------------------------------------------------------------


def _freshness(
    edges: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Age distribution of live edges + last harvest time per source."""
    ages: list[float] = []
    undated = 0
    for edge in edges:
        ts = _parse_sql_ts(edge.get("observed_at"))
        if ts is None:
            undated += 1
            continue
        ages.append(_age_days(ts, now))

    ages.sort()
    stats: dict[str, Any] = {
        "edge_count": len(edges),
        "dated_edges": len(ages),
        "undated_edges": undated,
        "min_days": ages[0] if ages else None,
        "median_days": median(ages) if ages else None,
        "p90_days": _percentile(ages, 90) if ages else None,
        "max_days": ages[-1] if ages else None,
    }

    last_by_source: dict[str, float | None] = {}
    for run in runs:
        source = run.get("source") or ""
        ts = _parse_sql_ts(run.get("finished_at"))
        age = _age_days(ts, now) if ts is not None else None
        prev = last_by_source.get(source, math.inf)
        # Keep the freshest (smallest age); None means never-finished.
        if age is None:
            last_by_source.setdefault(source, None)
        elif prev is None or prev is math.inf or age < prev:
            last_by_source[source] = age
    stats["last_harvest_age_by_source"] = {
        s: last_by_source[s] for s in sorted(last_by_source)
    }
    return stats


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list."""
    if not sorted_values:
        raise ValueError("empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


# -- public API ---------------------------------------------------------------


def coverage_data(
    store: PanoramaStore,
    direction_id: int,
    *,
    k: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute coverage/freshness inputs for one direction from the store.

    ``now`` is injectable for deterministic freshness tests; it defaults to the
    current UTC time.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    matrix = store.capture_matrix(direction_id)
    runs = store.harvest_runs(direction_id)
    edges = store.edges(direction_id, live_only=True)

    incidence = _incidence(matrix)
    chao = _chao2(incidence["s_obs"], incidence["m"], incidence["q1"], incidence["q2"])
    marginal = _marginal_series(runs, k)
    freshness = _freshness(edges, runs, now)
    source_health = _source_health(runs, incidence["per_source"])

    s_est = chao["s_est"]
    s_obs = incidence["s_obs"]
    estimated_unseen = max(s_est - s_obs, 0.0)
    unseen_fraction = estimated_unseen / s_est if s_est > 0 else 0.0

    return {
        "direction_id": direction_id,
        "per_source": incidence["per_source"],
        "s_obs": s_obs,
        "m": incidence["m"],
        "q1": incidence["q1"],
        "q2": incidence["q2"],
        "s_est": s_est,
        "ci_low": chao["ci_low"],
        "ci_high": chao["ci_high"],
        "chao_computable": chao["computable"],
        "used_bias_correction": chao["used_bias_correction"],
        "estimated_unseen": estimated_unseen,
        "unseen_fraction": unseen_fraction,
        "marginal": marginal,
        "freshness": freshness,
        "sources_attempted": source_health["sources_attempted"],
        "sources_failed": source_health["sources_failed"],
        "source_error_counts": source_health["source_error_counts"],
        "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def coverage_verdict(
    data: dict[str, Any],
    *,
    epsilon: float = 0.10,
    marginal_threshold: float = 0.02,
    k: int = 5,
) -> dict[str, Any]:
    """Decide whether harvesting can stop (plan §5.2).

    Stop iff BOTH the coverage signal is computable AND at least one stopping
    condition holds: the estimated unseen fraction is at or below ``epsilon``,
    or the marginal discovery rate is at or below ``marginal_threshold``.
    """
    unseen_fraction = data["unseen_fraction"]
    marginal = data["marginal"]
    marginal_rate = marginal.get("rolling_rate")

    coverage_computable = bool(data["chao_computable"])
    marginal_computable = bool(marginal.get("computable"))

    reasons: list[str] = []
    unseen_ok = coverage_computable and unseen_fraction <= epsilon
    marginal_ok = (
        marginal_computable
        and marginal_rate is not None
        and (marginal_rate <= marginal_threshold)
    )
    if unseen_ok:
        reasons.append(
            f"estimated unseen fraction {unseen_fraction:.3f} <= epsilon {epsilon:.3f}"
        )
    if marginal_ok:
        reasons.append(
            f"marginal discovery rate {marginal_rate:.3f} <= threshold "
            f"{marginal_threshold:.3f}"
        )

    if not (coverage_computable or marginal_computable):
        reasons.append("no computable stopping signal yet (need harvest runs)")

    stop_reached = (coverage_computable or marginal_computable) and (
        unseen_ok or marginal_ok
    )

    caveats: list[str] = []
    if data["m"] < 3:
        caveats.append(
            f"only {data['m']} distinct source(s): Chao2 is unstable with "
            "fewer than 3 sources"
        )
    if data["s_obs"] < 50:
        caveats.append(
            f"small observed richness (S_obs={data['s_obs']} < 50): estimate "
            "has wide error"
        )
    if data["used_bias_correction"]:
        caveats.append(
            "Q2 == 0: bias-corrected Chao2 fallback (no doubletons observed)"
        )

    sources_failed = list(data.get("sources_failed") or [])
    source_error_counts = dict(data.get("source_error_counts") or {})
    if sources_failed:
        detail = ", ".join(
            f"{src}({source_error_counts.get(src, 0)})" for src in sources_failed
        )
        caveats.append(
            f"source-level harvest failures (zero identities): {detail}; "
            "failed sources must not be read as empty searches"
        )
        # A silent source failure makes stop signals untrustworthy.
        stop_reached = False
        reasons.append(
            "source failure(s) present — coverage stop suppressed until "
            "failed sources succeed or are explicitly dropped"
        )

    return {
        "stop_reached": stop_reached,
        "computable": coverage_computable or marginal_computable,
        "reasons": reasons,
        "unseen_fraction": unseen_fraction,
        "marginal_rate": marginal_rate,
        "sources_used": sorted(data["per_source"].keys()),
        "sources_attempted": list(
            data.get("sources_attempted") or sorted(data["per_source"].keys())
        ),
        "sources_failed": sources_failed,
        "source_error_counts": source_error_counts,
        "caveats": caveats,
    }


# -- markdown dashboard -------------------------------------------------------


def _fmt_num(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_days(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}d"


def _sparkline(rates: list[float]) -> str:
    if not rates:
        return "(no non-empty runs)"
    return " → ".join(f"{r:.2f}" for r in rates)


def render_coverage_md(data: dict[str, Any], verdict: dict[str, Any]) -> str:
    """Render the coverage dashboard as a markdown section (deterministic).

    Returned as a string for the orchestrator to embed into the vault; this
    function never writes files and emits no GENERATED header.
    """
    lines: list[str] = ["## Coverage", ""]

    # -- capture table -------------------------------------------------------
    lines.append("### Capture by source")
    lines.append("")
    lines.append("| Source | Distinct identities |")
    lines.append("| --- | ---: |")
    for source, count in data["per_source"].items():
        lines.append(f"| {source} | {count} |")
    lines.append(f"| **total (S_obs)** | **{data['s_obs']}** |")
    lines.append("")
    failed = data.get("sources_failed") or []
    if failed:
        err_counts = data.get("source_error_counts") or {}
        lines.append("### Failed sources")
        lines.append("")
        lines.append("| Source | Error runs |")
        lines.append("| --- | ---: |")
        for source in failed:
            lines.append(f"| {source} | {err_counts.get(source, 0)} |")
        lines.append("")

    # -- overlap / richness --------------------------------------------------
    lines.append("### Richness estimate")
    lines.append("")
    lines.append(f"- Distinct sources (m): {data['m']}")
    lines.append(f"- Observed identities (S_obs): {data['s_obs']}")
    lines.append(
        f"- Overlap incidence: Q1 (seen once)={data['q1']}, "
        f"Q2 (seen twice)={data['q2']}"
    )
    est_label = "Chao2 (bias-corrected)" if data["used_bias_correction"] else "Chao2"
    lines.append(
        f"- {est_label} S_est: {_fmt_num(data['s_est'])} "
        f"(95% CI {_fmt_num(data['ci_low'])} - {_fmt_num(data['ci_high'])})"
    )
    lines.append(
        f"- Estimated unseen: {_fmt_num(data['estimated_unseen'])} "
        f"(unseen fraction {_fmt_num(data['unseen_fraction'], digits=3)})"
    )
    lines.append("")

    # -- marginal discovery --------------------------------------------------
    marginal = data["marginal"]
    lines.append("### Marginal discovery")
    lines.append("")
    lines.append(f"- Per-run new/result rate: {_sparkline(marginal['rates'])}")
    lines.append(
        f"- Rolling mean (last {marginal['k']}): "
        f"{_fmt_num(marginal['rolling_rate'], digits=3)}"
    )
    lines.append("")

    # -- freshness -----------------------------------------------------------
    fresh = data["freshness"]
    lines.append("### Freshness")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| Live edges | {fresh['edge_count']} |")
    lines.append(f"| Min age | {_fmt_days(fresh['min_days'])} |")
    lines.append(f"| Median age | {_fmt_days(fresh['median_days'])} |")
    lines.append(f"| P90 age | {_fmt_days(fresh['p90_days'])} |")
    lines.append(f"| Max age | {_fmt_days(fresh['max_days'])} |")
    if fresh["undated_edges"]:
        lines.append(f"| Undated edges | {fresh['undated_edges']} |")
    lines.append("")
    last_by_source = fresh["last_harvest_age_by_source"]
    if last_by_source:
        lines.append("Last harvest age by source:")
        lines.append("")
        for source, age in last_by_source.items():
            lines.append(f"- {source}: {_fmt_days(age)}")
        lines.append("")

    # -- verdict -------------------------------------------------------------
    lines.append("### Verdict")
    lines.append("")
    lines.append(f"- Stop reached: {'yes' if verdict['stop_reached'] else 'no'}")
    lines.append(f"- Unseen fraction: {_fmt_num(verdict['unseen_fraction'], digits=3)}")
    lines.append(f"- Marginal rate: {_fmt_num(verdict['marginal_rate'], digits=3)}")
    if verdict["reasons"]:
        lines.append("- Reasons:")
        for reason in verdict["reasons"]:
            lines.append(f"  - {reason}")
    if verdict["caveats"]:
        lines.append("- Caveats:")
        for caveat in verdict["caveats"]:
            lines.append(f"  - {caveat}")
    lines.append("")

    return "\n".join(lines)
