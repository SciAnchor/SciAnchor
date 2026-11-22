"""L1 schema for the Domain Panorama KB.

Hard constraints encoded here (plan §3):
- every fact can carry 4-tuple evidence anchors (keywords/summary/insight/quote);
- edges are bi-temporal (event time, observed time, validity end);
- conflicts are never overwritten: contradictory facts coexist, linked by
  `contradicts` edges;
- the territory map (problem × mechanism × evidence cells) is first-class and
  gap_ground_verify verdicts are persisted against it.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3

#: What a verdict is allowed to be about. `unscoped` exists only to describe
#: pre-v3 rows; nothing may write it deliberately. There is deliberately no
#: `field`, `domain`, or `research_area` scope: a verdict cannot be about one.
VERDICT_SCOPE_KINDS = ("candidate_version", "query_lane", "cell", "unscoped")

#: `active` verdicts may influence ranking and promotion. `diagnostic_only` and
#: `quarantined` are readable for audit and must not.
VERDICT_ELIGIBILITY = ("active", "diagnostic_only", "quarantined")

ENTITY_KINDS = (
    "paper",
    "system",
    "code_repo",
    "benchmark",
    "dataset",
    "mechanism",
    "claim",
    "result",
    "limitation",
    "industry_doc",
    "org",
    "venue",
    "event",
)

EDGE_RELS = (
    "claims",
    "evaluates_on",
    "implements",
    "improves_on",
    "contradicts",
    "supersedes",
    "reuses",
    "cites",
    "derived_from",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS panorama_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS directions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    rh_domain_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER NOT NULL REFERENCES directions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    attrs_json TEXT NOT NULL DEFAULT '{}',
    ext_ids_json TEXT NOT NULL DEFAULT '{}',
    pool_paper_id INTEGER,
    source TEXT NOT NULL DEFAULT '',
    extractor_model TEXT NOT NULL DEFAULT '',
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (direction_id, kind, name)
);
CREATE INDEX IF NOT EXISTS idx_entities_dir_kind ON entities(direction_id, kind);
CREATE INDEX IF NOT EXISTS idx_entities_pool_paper ON entities(pool_paper_id)
    WHERE pool_paper_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS entity_ext_ids (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (scheme, value)
);
CREATE INDEX IF NOT EXISTS idx_ext_ids_entity ON entity_ext_ids(entity_id);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER NOT NULL REFERENCES directions(id) ON DELETE CASCADE,
    src_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dst_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    rel TEXT NOT NULL,
    event_at TEXT,
    observed_at TEXT NOT NULL DEFAULT (datetime('now')),
    valid_until TEXT,
    invalidated_by INTEGER REFERENCES edges(id),
    attrs_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id, rel);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id, rel);

CREATE TABLE IF NOT EXISTS anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_kind TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    insight TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_anchors_target ON anchors(target_kind, target_id);

CREATE TABLE IF NOT EXISTS territory_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER NOT NULL REFERENCES directions(id) ON DELETE CASCADE,
    problem TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    evidence_facet TEXT NOT NULL DEFAULT '',
    evidence_strength TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'unknown',
    last_verified_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE (direction_id, problem, mechanism, evidence_facet)
);

CREATE TABLE IF NOT EXISTS cell_claims (
    cell_id INTEGER NOT NULL REFERENCES territory_cells(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'occupies',
    PRIMARY KEY (cell_id, entity_id)
);

CREATE TABLE IF NOT EXISTS verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER NOT NULL REFERENCES directions(id) ON DELETE CASCADE,
    cell_id INTEGER REFERENCES territory_cells(id) ON DELETE SET NULL,
    claim_text TEXT NOT NULL,
    verdict TEXT NOT NULL,
    tool TEXT NOT NULL DEFAULT 'gap_ground_verify',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    decided_at TEXT NOT NULL DEFAULT (datetime('now')),
    scope_kind TEXT NOT NULL DEFAULT 'unscoped',
    scope_ref TEXT NOT NULL DEFAULT '',
    scope_status TEXT NOT NULL DEFAULT 'legacy_unscoped',
    eligibility TEXT NOT NULL DEFAULT 'diagnostic_only',
    quarantine_reason TEXT NOT NULL DEFAULT '',
    evidence_snapshot_id TEXT NOT NULL DEFAULT '',
    valid_until TEXT,
    superseded_by INTEGER REFERENCES verdicts(id),
    revival_triggers_json TEXT NOT NULL DEFAULT '[]',
    source_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_verdicts_dir ON verdicts(direction_id);
-- The eligibility index is created by `migrate_verdict_scope`, not here. On an
-- existing pre-v3 database `CREATE TABLE IF NOT EXISTS verdicts` is a no-op, so
-- the column does not exist yet at this point and indexing it would fail.

CREATE TABLE IF NOT EXISTS harvest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER NOT NULL REFERENCES directions(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    round INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    result_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_harvest_runs_dir ON harvest_runs(direction_id, source);

CREATE TABLE IF NOT EXISTS harvest_hits (
    run_id INTEGER NOT NULL REFERENCES harvest_runs(id) ON DELETE CASCADE,
    identity TEXT NOT NULL,
    scheme TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    matched_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    relevance REAL,
    PRIMARY KEY (run_id, identity)
);
CREATE INDEX IF NOT EXISTS idx_harvest_hits_identity ON harvest_hits(identity);

CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name, summary,
    content='entities',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS entities_fts_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, summary)
    VALUES (new.id, new.name, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS entities_fts_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, summary)
    VALUES ('delete', old.id, old.name, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS entities_fts_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, summary)
    VALUES ('delete', old.id, old.name, old.summary);
    INSERT INTO entities_fts(rowid, name, summary)
    VALUES (new.id, new.name, new.summary);
END;
"""


#: Columns added to `verdicts` in schema v3. `CREATE TABLE IF NOT EXISTS` cannot
#: add columns to a table that already exists, so an existing panorama DB needs
#: an explicit idempotent `ALTER TABLE` pass.
#:
#: Every default is the conservative value on purpose. A row written before v3
#: has no recorded scope, so it backfills to `legacy_unscoped` /
#: `diagnostic_only` and stops counting as a live judgement. A writer that does
#: not opt in to scoping gets the same treatment: deny by default.
_VERDICT_V3_COLUMNS: tuple[tuple[str, str], ...] = (
    ("scope_kind", "TEXT NOT NULL DEFAULT 'unscoped'"),
    ("scope_ref", "TEXT NOT NULL DEFAULT ''"),
    ("scope_status", "TEXT NOT NULL DEFAULT 'legacy_unscoped'"),
    ("eligibility", "TEXT NOT NULL DEFAULT 'diagnostic_only'"),
    ("quarantine_reason", "TEXT NOT NULL DEFAULT ''"),
    ("evidence_snapshot_id", "TEXT NOT NULL DEFAULT ''"),
    ("valid_until", "TEXT"),
    ("superseded_by", "INTEGER REFERENCES verdicts(id)"),
    ("revival_triggers_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("source_hash", "TEXT NOT NULL DEFAULT ''"),
)


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: tuple[tuple[str, str], ...]
) -> list[str]:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    added: list[str] = []
    for name, ddl in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            added.append(name)
    return added


def migrate_verdict_scope(conn: sqlite3.Connection) -> list[str]:
    """Add v3 scope/TTL columns to `verdicts` and quarantine pre-v3 rows.

    Returns the column names actually added, so a caller can tell a fresh
    database from an upgraded one. Safe to run repeatedly.
    """
    added = _add_missing_columns(conn, "verdicts", _VERDICT_V3_COLUMNS)
    # Only safe once the columns exist, which is why it lives here rather than
    # in SCHEMA_SQL: on a pre-v3 database the CREATE TABLE above is a no-op.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_verdicts_eligibility "
        "ON verdicts(direction_id, eligibility)"
    )
    if "quarantine_reason" in added:
        # Rows that existed before this migration were decided under a contract
        # with no scope, no evidence snapshot, and no expiry. They stay readable
        # for audit but must never be treated as a live judgement again.
        conn.execute(
            "UPDATE verdicts SET quarantine_reason = ? "
            "WHERE quarantine_reason = '' AND scope_status = 'legacy_unscoped'",
            ("recorded before schema v3: no scope, evidence snapshot, or TTL",),
        )
    return added


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create or upgrade the panorama schema in place (idempotent)."""
    conn.executescript(SCHEMA_SQL)
    migrate_verdict_scope(conn)
    conn.execute(
        "INSERT INTO panorama_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
