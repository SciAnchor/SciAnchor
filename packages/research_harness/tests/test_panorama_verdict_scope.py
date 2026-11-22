"""Verdict scope, TTL, supersession, and legacy quarantine.

The behaviour under test exists because of a recorded failure: verdicts were
stored as free text with no scope and no expiry, every historical row was
rendered into the direction brief with no freshness filter, and a run of stale
candidate NO-GOs was then read as evidence about a whole research area.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_harness.panorama.schema import (
    SCHEMA_VERSION,
    apply_schema,
    migrate_verdict_scope,
)
from research_harness.panorama.store import PanoramaStore
from research_harness.panorama.views import (
    generate_views,
    sorted_ineligible_verdicts,
    sorted_verdicts,
)


@pytest.fixture()
def store(tmp_path: Path) -> PanoramaStore:
    s = PanoramaStore(tmp_path / "panorama")
    s.init()
    return s


@pytest.fixture()
def direction_id(store: PanoramaStore) -> int:
    return int(store.get_or_create_direction("d", "Direction", rh_domain_id=1))


# --------------------------------------------------------------------------
# Migration from a pre-v3 database
# --------------------------------------------------------------------------


def _create_v2_verdicts_table(conn: sqlite3.Connection) -> None:
    """The exact pre-v3 `verdicts` shape."""
    conn.executescript(
        """
        CREATE TABLE verdicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction_id INTEGER NOT NULL,
            cell_id INTEGER,
            claim_text TEXT NOT NULL,
            verdict TEXT NOT NULL,
            tool TEXT NOT NULL DEFAULT 'gap_ground_verify',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            decided_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def test_migration_adds_columns_and_quarantines_pre_v3_rows(tmp_path: Path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _create_v2_verdicts_table(conn)
    conn.execute(
        "INSERT INTO verdicts (direction_id, claim_text, verdict) VALUES (1,?,?)",
        ("automated research is a red ocean", "project-no-go"),
    )
    conn.commit()

    added = migrate_verdict_scope(conn)
    conn.commit()

    assert "scope_status" in added
    assert "eligibility" in added
    row = conn.execute("SELECT * FROM verdicts").fetchone()
    assert row["scope_status"] == "legacy_unscoped"
    assert row["eligibility"] == "diagnostic_only"
    assert "before schema v3" in row["quarantine_reason"]
    # The original judgement is preserved verbatim for audit.
    assert row["claim_text"] == "automated research is a red ocean"
    assert row["verdict"] == "project-no-go"
    conn.close()


def test_migration_is_idempotent(tmp_path: Path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _create_v2_verdicts_table(conn)
    conn.commit()

    first = migrate_verdict_scope(conn)
    second = migrate_verdict_scope(conn)
    third = migrate_verdict_scope(conn)

    assert first  # columns were added the first time
    assert second == []
    assert third == []
    conn.close()


def test_migration_does_not_re_quarantine_a_scoped_row(tmp_path: Path):
    """Running the migration again must not clobber a live verdict."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _create_v2_verdicts_table(conn)
    migrate_verdict_scope(conn)
    conn.execute(
        "INSERT INTO verdicts (direction_id, claim_text, verdict, scope_kind, "
        "scope_ref, scope_status, eligibility) "
        "VALUES (1,'c','v','candidate_version','cand:1','scoped','active')"
    )
    conn.commit()

    migrate_verdict_scope(conn)
    conn.commit()

    row = conn.execute("SELECT * FROM verdicts WHERE scope_ref='cand:1'").fetchone()
    assert row["eligibility"] == "active"
    assert row["quarantine_reason"] == ""
    conn.close()


def test_apply_schema_upgrades_a_real_pre_v3_database(tmp_path: Path):
    """The whole upgrade path, not just the migration helper.

    Regression: an earlier version created the eligibility index inside
    SCHEMA_SQL. On a pre-v3 database `CREATE TABLE IF NOT EXISTS verdicts` is a
    no-op, so `executescript` reached the index before the ALTER pass had added
    the column and `apply_schema` raised `no such column: eligibility`. Calling
    `migrate_verdict_scope` directly did not catch it — only opening an actual
    pre-v3 store does.
    """
    db = tmp_path / "panorama" / "L1" / "panorama.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    _create_v2_verdicts_table(conn)
    conn.execute(
        "INSERT INTO verdicts (direction_id, claim_text, verdict) VALUES (1,?,?)",
        ("a claim decided under the old contract", "occupied"),
    )
    conn.commit()
    conn.close()

    store = PanoramaStore(tmp_path / "panorama")
    store.init()  # must not raise

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM verdicts").fetchone()
    assert row["eligibility"] == "diagnostic_only"
    assert row["claim_text"] == "a claim decided under the old contract"
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(verdicts)")}
    assert "idx_verdicts_eligibility" in indexes
    conn.close()

    # Re-opening an already-upgraded store is also a no-op.
    store.init()


def test_apply_schema_records_version_3(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "fresh.db")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)

    version = conn.execute(
        "SELECT value FROM panorama_meta WHERE key='schema_version'"
    ).fetchone()
    assert int(version["value"]) == SCHEMA_VERSION == 3
    conn.close()


# --------------------------------------------------------------------------
# Deny by default
# --------------------------------------------------------------------------


def test_unscoped_write_is_diagnostic_only(store: PanoramaStore, direction_id: int):
    store.record_verdict(direction_id, "some claim", "occupied")

    verdict = store.verdicts(direction_id)[0]
    assert verdict["scope_status"] == "legacy_unscoped"
    assert verdict["eligibility"] == "diagnostic_only"
    assert store.active_verdicts(direction_id) == []


def test_scoped_write_is_active(store: PanoramaStore, direction_id: int):
    store.record_verdict(
        direction_id,
        "candidate v3 core claim",
        "project-advance",
        scope_kind="candidate_version",
        scope_ref="cand:v3",
        evidence_snapshot_id="snap-2026-08-04",
    )

    active = store.active_verdicts(direction_id)
    assert len(active) == 1
    assert active[0]["scope_kind"] == "candidate_version"
    assert active[0]["scope_ref"] == "cand:v3"
    assert active[0]["evidence_snapshot_id"] == "snap-2026-08-04"


def test_scope_kind_requires_a_scope_ref(store: PanoramaStore, direction_id: int):
    with pytest.raises(ValueError, match="requires a non-empty scope_ref"):
        store.record_verdict(
            direction_id, "c", "v", scope_kind="candidate_version", scope_ref="  "
        )


def test_schema_has_no_field_or_domain_scope(store: PanoramaStore, direction_id: int):
    """A verdict cannot be about a research area, by construction."""
    for bad in ("field", "domain", "research_area"):
        with pytest.raises(ValueError, match="scope_kind must be one of"):
            store.record_verdict(direction_id, "c", "v", scope_kind=bad, scope_ref="x")


# --------------------------------------------------------------------------
# Expiry and supersession
# --------------------------------------------------------------------------


def test_expired_verdict_stops_being_active(store: PanoramaStore, direction_id: int):
    store.record_verdict(
        direction_id,
        "candidate v1",
        "project-stop",
        scope_kind="candidate_version",
        scope_ref="cand:v1",
        ttl_days=-1,  # already expired
    )

    stored = store.verdicts(direction_id)[0]
    # The column still says active; effective eligibility is computed at read
    # time so an expired verdict cannot keep counting just because no writer ran.
    assert stored["eligibility"] == "active"
    assert store.effective_eligibility(stored) == "diagnostic_only"
    assert store.active_verdicts(direction_id) == []


def test_unexpired_verdict_stays_active(store: PanoramaStore, direction_id: int):
    store.record_verdict(
        direction_id,
        "candidate v2",
        "project-hold",
        scope_kind="candidate_version",
        scope_ref="cand:v2",
        ttl_days=90,
    )

    assert len(store.active_verdicts(direction_id)) == 1


def test_superseded_verdict_stops_being_active(store: PanoramaStore, direction_id: int):
    old = store.record_verdict(
        direction_id,
        "candidate v1",
        "project-stop",
        scope_kind="candidate_version",
        scope_ref="cand:v1",
        ttl_days=90,
    )
    new = store.record_verdict(
        direction_id,
        "candidate v2 after residual analysis",
        "project-incubate",
        scope_kind="candidate_version",
        scope_ref="cand:v2",
        ttl_days=90,
    )
    store.supersede_verdict(old, new)

    active = store.active_verdicts(direction_id)
    assert [v["id"] for v in active] == [new]
    # The superseded row is preserved, not deleted.
    assert len(store.verdicts(direction_id)) == 2


def test_a_verdict_cannot_supersede_itself(store: PanoramaStore, direction_id: int):
    vid = store.record_verdict(
        direction_id, "c", "v", scope_kind="cell", scope_ref="cell:1"
    )
    with pytest.raises(ValueError, match="cannot supersede itself"):
        store.supersede_verdict(vid, vid)


def test_quarantine_removes_a_verdict_from_the_live_set(
    store: PanoramaStore, direction_id: int
):
    vid = store.record_verdict(
        direction_id,
        "candidate v1",
        "project-stop",
        scope_kind="candidate_version",
        scope_ref="cand:v1",
        ttl_days=90,
    )
    store.quarantine_verdict(vid, "evidence snapshot was contaminated")

    assert store.active_verdicts(direction_id) == []
    assert store.verdicts(direction_id)[0]["quarantine_reason"] == (
        "evidence snapshot was contaminated"
    )


def test_revival_triggers_round_trip(store: PanoramaStore, direction_id: int):
    store.record_verdict(
        direction_id,
        "candidate v1",
        "project-stop",
        scope_kind="candidate_version",
        scope_ref="cand:v1",
        revival_triggers=["a stronger base model ships"],
    )

    stored = store.verdicts(direction_id)[0]
    assert "a stronger base model ships" in stored["revival_triggers_json"]


# --------------------------------------------------------------------------
# The renderer, which is where a stale verdict actually reaches a reader
# --------------------------------------------------------------------------


def test_renderer_separates_live_from_diagnostic_verdicts(
    store: PanoramaStore, direction_id: int
):
    store.record_verdict(direction_id, "legacy unscoped claim", "occupied")
    store.record_verdict(
        direction_id,
        "live candidate claim",
        "project-advance",
        scope_kind="candidate_version",
        scope_ref="cand:v3",
        ttl_days=90,
    )

    live = sorted_verdicts(store, direction_id)
    ineligible = sorted_ineligible_verdicts(store, direction_id)

    assert [v["claim_text"] for v in live] == ["live candidate claim"]
    assert [v["claim_text"] for v in ineligible] == ["legacy unscoped claim"]


def test_frontier_brief_marks_diagnostic_verdicts_as_non_influential(
    store: PanoramaStore, direction_id: int
):
    store.record_verdict(
        direction_id, "automated research is saturated", "project-no-go"
    )
    generate_views(store, "d")
    frontier = (store.vault_dir / "frontier.md").read_text(encoding="utf-8")

    assert "Verdict ledger (live)" in frontier
    assert "_No live verdicts._" in frontier
    assert "must not influence ranking" in frontier
    # The historical claim is still visible for audit, in the quarantined table,
    # and the brief says in plain words why it is not live.
    assert "automated research is saturated" in frontier
    assert "written without a scope; not eligible for ranking" in frontier
