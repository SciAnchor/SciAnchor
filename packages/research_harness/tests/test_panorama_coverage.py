"""Tests for the panorama coverage estimator (Chao2 + freshness + verdict)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_harness.panorama.coverage import (
    coverage_data,
    coverage_verdict,
    render_coverage_md,
)
from research_harness.panorama.store import PanoramaStore

SLUG = "coverage-direction"


def _new_store(tmp_path: Path) -> tuple[PanoramaStore, int]:
    store = PanoramaStore(tmp_path / "panorama")
    store.init()
    direction = store.get_or_create_direction(SLUG, "Coverage Direction")
    return store, direction


def _hit(identity: str, source: str) -> dict[str, str]:
    return {"identity": identity, "scheme": "arxiv", "title": identity}


def _record(
    store: PanoramaStore,
    direction: int,
    source: str,
    identities: list[str],
    *,
    round_no: int = 1,
) -> int:
    hits = [_hit(i, source) for i in identities]
    return store.record_harvest_run(
        direction, source, f"q:{source}", hits, round_no=round_no
    )


def _set_edge_observed_at(store: PanoramaStore, edge_id: int, when: str) -> None:
    conn = store.connect()
    try:
        conn.execute("UPDATE edges SET observed_at = ? WHERE id = ?", (when, edge_id))
        conn.commit()
    finally:
        conn.close()


def _set_run_finished_at(store: PanoramaStore, run_id: int, when: str) -> None:
    conn = store.connect()
    try:
        conn.execute(
            "UPDATE harvest_runs SET finished_at = ? WHERE id = ?", (when, run_id)
        )
        conn.commit()
    finally:
        conn.close()


# -- Chao2 point estimate: hand-verified --------------------------------------


def test_chao2_matches_hand_math(tmp_path: Path) -> None:
    """Sources A/B/C, S_obs=10, Q1=4, Q2=3 => S_est = 10 + (2/3)*16/6 ~ 11.78.

    Construct the capture matrix explicitly:
      * 4 identities seen by exactly one source  (Q1 = 4)
      * 3 identities seen by exactly two sources (Q2 = 3)
      * 3 identities seen by all three sources   (Q3 = 3)
    => S_obs = 10, m = 3.
    """
    store, direction = _new_store(tmp_path)

    # Q1 singletons (one per source, split across A/B/C).
    _record(store, direction, "A", ["s-a1", "s-a2"])
    _record(store, direction, "B", ["s-b1"])
    _record(store, direction, "C", ["s-c1"])

    # Q2 doubletons: each appears in exactly two sources.
    _record(store, direction, "A", ["d-ab", "d-ac"])
    _record(store, direction, "B", ["d-ab", "d-bc"])
    _record(store, direction, "C", ["d-ac", "d-bc"])

    # Q3 tripletons: appear in all three.
    for src in ("A", "B", "C"):
        _record(store, direction, src, ["t-1", "t-2", "t-3"])

    data = coverage_data(store, direction)
    assert data["s_obs"] == 10
    assert data["m"] == 3
    assert data["q1"] == 4
    assert data["q2"] == 3
    # 10 + (2/3) * 16 / 6 = 11.7777...
    assert abs(data["s_est"] - (10 + (2 / 3) * 16 / 6)) < 1e-9
    assert not data["used_bias_correction"]
    assert data["chao_computable"]

    # estimated_unseen and fraction consistent with S_est.
    assert abs(data["estimated_unseen"] - (data["s_est"] - 10)) < 1e-9
    assert (
        abs(data["unseen_fraction"] - (data["estimated_unseen"] / data["s_est"])) < 1e-9
    )

    # Log-transform CI keeps the lower bound at/above S_obs.
    assert data["ci_low"] >= data["s_obs"] - 1e-9
    assert data["ci_high"] > data["s_est"]


def test_chao2_bias_corrected_when_no_doubletons(tmp_path: Path) -> None:
    """Q2 == 0 triggers the bias-corrected fallback Q1*(Q1-1)/(2*(Q2+1))."""
    store, direction = _new_store(tmp_path)

    # 4 singletons, 2 tripletons => Q1 = 4, Q2 = 0, S_obs = 6, m = 3.
    _record(store, direction, "A", ["s1"])
    _record(store, direction, "B", ["s2"])
    _record(store, direction, "C", ["s3"])
    _record(store, direction, "A", ["s4"])
    for src in ("A", "B", "C"):
        _record(store, direction, src, ["t1", "t2"])

    data = coverage_data(store, direction)
    assert data["q1"] == 4
    assert data["q2"] == 0
    assert data["used_bias_correction"]
    # S_est = 6 + (2/3) * 4*3 / (2*1) = 6 + (2/3)*6 = 10.
    assert abs(data["s_est"] - 10.0) < 1e-9
    assert data["ci_low"] >= data["s_obs"] - 1e-9


def test_single_source_is_not_computable(tmp_path: Path) -> None:
    """With m < 2 Chao2 is undefined: S_est == S_obs, unseen fraction 0."""
    store, direction = _new_store(tmp_path)
    _record(store, direction, "A", ["p1", "p2", "p3"])

    data = coverage_data(store, direction)
    assert data["m"] == 1
    assert data["s_est"] == data["s_obs"] == 3
    assert data["unseen_fraction"] == 0.0
    assert not data["chao_computable"]

    verdict = coverage_verdict(data)
    caveat_text = " ".join(verdict["caveats"])
    assert "fewer than 3 sources" in caveat_text
    assert "S_obs=3" in caveat_text


def test_empty_direction_is_safe(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    data = coverage_data(store, direction)
    assert data["s_obs"] == 0
    assert data["s_est"] == 0.0
    assert data["unseen_fraction"] == 0.0
    verdict = coverage_verdict(data)
    assert verdict["stop_reached"] is False


# -- marginal discovery series ------------------------------------------------


def test_marginal_series_skips_zero_result_runs(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    # result=10 new=4 -> 0.4 ; result=10 new=2 -> 0.2 ; empty ; result=10 new=0.
    _record(store, direction, "A", [f"a{i}" for i in range(10)])  # 10 new
    # second run: overlap 8 of the previous, 2 fresh -> new=2/result=... build:
    _record(
        store, direction, "B", [f"a{i}" for i in range(8)] + ["b1", "b2"]
    )  # result=10, new=2
    # zero-result run (no hits) is recorded and must be skipped.
    store.record_harvest_run(direction, "C", "empty", [], round_no=2)
    # fully-overlapping run -> new=0.
    _record(store, direction, "A", ["a0", "a1", "a2"])  # result=3 new=0

    data = coverage_data(store, direction, k=5)
    rates = data["marginal"]["rates"]
    # zero-result run is not present in the series.
    assert rates[0] == 1.0  # first run: 10 new / 10 results
    assert abs(rates[1] - 0.2) < 1e-9
    assert rates[-1] == 0.0
    assert len(rates) == 3
    assert data["marginal"]["computable"]


def test_marginal_rolling_window(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    # Six discovering runs with declining novelty; k=2 window = last two.
    _record(store, direction, "A", [f"x{i}" for i in range(10)])  # 1.0
    _record(store, direction, "B", [f"x{i}" for i in range(9)] + ["y1"])  # 0.1
    _record(store, direction, "C", [f"x{i}" for i in range(10)])  # 0.0
    data = coverage_data(store, direction, k=2)
    window = data["marginal"]["window"]
    assert window == [0.1, 0.0]
    assert abs(data["marginal"]["rolling_rate"] - 0.05) < 1e-9


# -- verdict logic: both branches --------------------------------------------


def _saturated_data() -> dict[str, object]:
    return {
        "s_obs": 120,
        "m": 4,
        "q1": 2,
        "q2": 5,
        "s_est": 122.0,
        "unseen_fraction": 0.02,
        "chao_computable": True,
        "used_bias_correction": False,
        "per_source": {"A": 60, "B": 55, "C": 50, "D": 40},
        "marginal": {
            "rates": [0.3, 0.1, 0.05],
            "k": 5,
            "window": [0.3, 0.1, 0.05],
            "rolling_rate": 0.15,
            "computable": True,
        },
    }


def test_verdict_stops_on_unseen_fraction() -> None:
    data = _saturated_data()
    verdict = coverage_verdict(data, epsilon=0.10, marginal_threshold=0.02)
    assert verdict["stop_reached"] is True
    assert any("unseen fraction" in r for r in verdict["reasons"])
    assert verdict["sources_used"] == ["A", "B", "C", "D"]
    assert verdict["caveats"] == []


def test_verdict_stops_on_marginal_rate() -> None:
    data = _saturated_data()
    # High unseen fraction, but marginal rate has collapsed below threshold.
    data["unseen_fraction"] = 0.5
    data["marginal"]["rolling_rate"] = 0.01
    verdict = coverage_verdict(data, epsilon=0.10, marginal_threshold=0.02)
    assert verdict["stop_reached"] is True
    assert any("marginal discovery rate" in r for r in verdict["reasons"])


def test_verdict_keeps_going_when_neither_condition_met() -> None:
    data = _saturated_data()
    data["unseen_fraction"] = 0.4
    data["marginal"]["rolling_rate"] = 0.2
    verdict = coverage_verdict(data, epsilon=0.10, marginal_threshold=0.02)
    assert verdict["stop_reached"] is False
    assert verdict["reasons"] == []


def test_verdict_requires_computable_signal() -> None:
    """Low unseen fraction that is NOT computable must not trigger a stop."""
    data = _saturated_data()
    data["chao_computable"] = False
    data["marginal"]["computable"] = False
    data["marginal"]["rolling_rate"] = None
    verdict = coverage_verdict(data)
    assert verdict["stop_reached"] is False
    assert any("no computable stopping signal" in r for r in verdict["reasons"])


def test_failed_sources_suppress_stop_and_surface_in_verdict(tmp_path: Path) -> None:
    """E1: a source that only failed must not look like an empty successful search."""
    store, direction = _new_store(tmp_path)
    # Successful captures from A/B/C so Chao2 is computable and would stop.
    for src, ids in (
        ("A", ["a1", "ab", "ac", "abc"]),
        ("B", ["b1", "ab", "bc", "abc"]),
        ("C", ["c1", "ac", "bc", "abc"]),
    ):
        _record(store, direction, src, ids)
    # OpenAlex-style total failure: attrs.status=failed, zero hits.
    store.record_harvest_run(
        direction,
        "openalex",
        "q:openalex",
        [],
        attrs={"status": "failed", "error": "HTTP 429"},
    )
    data = coverage_data(store, direction)
    assert "openalex" in data["sources_failed"]
    assert "openalex" in data["sources_attempted"]
    assert "openalex" not in data["per_source"]
    verdict = coverage_verdict(data, epsilon=1.0, marginal_threshold=1.0)
    assert verdict["stop_reached"] is False
    assert verdict["sources_failed"] == ["openalex"]
    assert any("source failure" in r for r in verdict["reasons"])
    assert any("openalex" in c for c in verdict["caveats"])
    md = render_coverage_md(data, verdict)
    assert "Failed sources" in md
    assert "openalex" in md


# -- freshness with injected now ---------------------------------------------


def test_freshness_with_injected_now(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    a = store.upsert_entity(direction, "system", "SysA")
    b = store.upsert_entity(direction, "system", "SysB")
    c = store.upsert_entity(direction, "system", "SysC")
    d = store.upsert_entity(direction, "system", "SysD")

    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    def ts(days_ago: float) -> str:
        return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

    e1 = store.add_edge(direction, a, b, "cites")
    e2 = store.add_edge(direction, b, c, "cites")
    e3 = store.add_edge(direction, c, d, "cites")
    e4 = store.add_edge(direction, a, d, "cites")
    _set_edge_observed_at(store, e1, ts(1))
    _set_edge_observed_at(store, e2, ts(10))
    _set_edge_observed_at(store, e3, ts(30))
    _set_edge_observed_at(store, e4, ts(100))

    # Harvest runs finished at various times, two per source.
    r1 = _record(store, direction, "arxiv", ["p1"])
    r2 = _record(store, direction, "openalex", ["p2"])
    _set_run_finished_at(store, r1, ts(2))
    _set_run_finished_at(store, r2, ts(5))

    data = coverage_data(store, direction, now=now)
    fresh = data["freshness"]
    assert fresh["edge_count"] == 4
    assert fresh["dated_edges"] == 4
    assert abs(fresh["min_days"] - 1.0) < 1e-6
    assert abs(fresh["max_days"] - 100.0) < 1e-6
    # median of [1, 10, 30, 100] = (10 + 30) / 2 = 20.
    assert abs(fresh["median_days"] - 20.0) < 1e-6
    # p90 (linear interp) of sorted [1,10,30,100]: rank = 0.9*3 = 2.7.
    assert abs(fresh["p90_days"] - (30 + 0.7 * (100 - 30))) < 1e-6

    last = fresh["last_harvest_age_by_source"]
    assert abs(last["arxiv"] - 2.0) < 1e-6
    assert abs(last["openalex"] - 5.0) < 1e-6


def test_freshness_naive_now_is_coerced_to_utc(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    a = store.upsert_entity(direction, "system", "SysA")
    b = store.upsert_entity(direction, "system", "SysB")
    now_naive = datetime(2026, 8, 1, 12, 0, 0)
    edge = store.add_edge(direction, a, b, "cites")
    when = (now_naive - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    _set_edge_observed_at(store, edge, when)
    data = coverage_data(store, direction, now=now_naive)
    assert abs(data["freshness"]["max_days"] - 7.0) < 1e-6


# -- markdown render ----------------------------------------------------------


def test_render_contains_key_numbers(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    _record(store, direction, "A", ["s-a1", "s-a2"])
    _record(store, direction, "B", ["s-b1"])
    _record(store, direction, "C", ["s-c1"])
    _record(store, direction, "A", ["d-ab", "d-ac"])
    _record(store, direction, "B", ["d-ab", "d-bc"])
    _record(store, direction, "C", ["d-ac", "d-bc"])
    for src in ("A", "B", "C"):
        _record(store, direction, src, ["t-1", "t-2", "t-3"])

    data = coverage_data(store, direction)
    verdict = coverage_verdict(data)
    md = render_coverage_md(data, verdict)

    assert md.startswith("## Coverage")
    assert "GENERATED" not in md
    # S_obs and richness numbers surface.
    assert "S_obs" in md
    assert "10" in md  # S_obs
    assert "11.78" in md  # Chao2 point estimate
    # Marginal sparkline uses the arrow separator.
    assert "→" in md
    # Freshness and verdict headings present.
    assert "### Freshness" in md
    assert "### Verdict" in md
    # Sources appear in the capture table in deterministic order.
    assert md.index("| A |") < md.index("| B |") < md.index("| C |")


def test_render_flags_single_source_caveat(tmp_path: Path) -> None:
    store, direction = _new_store(tmp_path)
    _record(store, direction, "A", ["p1", "p2"])
    data = coverage_data(store, direction)
    verdict = coverage_verdict(data)
    md = render_coverage_md(data, verdict)
    assert "Caveats:" in md
    assert "fewer than 3 sources" in md
