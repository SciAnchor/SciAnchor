from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "packages" / "research_harness" / "migrations"
MIGRATION_077 = MIGRATIONS_DIR / "077_competition_density_navigation.sql"
EXPECTED_INDEX_SQL = " ".join(
    """
    CREATE INDEX idx_rc_scope_sort ON research_candidates(
        scope,
        llm_score DESC,
        (CASE confidence_level
            WHEN 'high' THEN 0
            WHEN 'normal' THEN 1
            WHEN 'low' THEN 2
            ELSE 3
        END),
        id ASC
    )
    """.split()
)
EXPECTED_COLUMNS = (
    "id",
    "scope",
    "primary_domain_id",
    "research_area_ids",
    "title",
    "pitch",
    "llm_score",
    "llm_score_breakdown",
    "area_red_ocean",
    "task_red_ocean",
    "method_red_ocean",
    "opportunity_angle",
    "confidence_level",
    "evidence_gap_ids",
    "evidence_contradiction_ids",
    "evidence_claim_ids",
    "seed_paper_ids",
    "why",
    "risks",
    "lineage_key",
    "evidence_signature",
    "status",
    "narration_model",
    "generated_at",
    "updated_at",
)


def _load_database_class():
    prefix = "pgl03b_database"
    for name in (prefix, f"{prefix}._core", f"{prefix}._core.storage"):
        package = ModuleType(name)
        package.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = package
    config = ModuleType(f"{prefix}._core.config")
    config.GLOBAL_DB_PATH = Path("unused-pgl03b.db")
    sys.modules[config.__name__] = config

    module_name = f"{prefix}._core.storage.db"
    source = (
        REPO_ROOT
        / "packages"
        / "research_harness"
        / "research_harness"
        / "_core"
        / "storage"
        / "db.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.Database


DATABASE_CLASS = _load_database_class()


def _normalize_sql(value: str) -> str:
    return " ".join(value.split())


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _migration_077_sql() -> str:
    assert MIGRATION_077.is_file(), "migration 077 must exist before implementation"
    return MIGRATION_077.read_text()


def _apply_migrations(path: Path, *, through: int | None = None) -> None:
    connection = _connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        applied = {
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(sql_file.name.split("_")[0])
            if through is not None and version > through:
                continue
            if version in applied:
                continue
            try:
                connection.executescript(sql_file.read_text())
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, sql_file.stem),
            )
            connection.commit()
    finally:
        connection.close()


def _index_sql(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND name = 'idx_rc_scope_sort'"
    ).fetchone()
    assert row is not None
    return _normalize_sql(str(row[0]))


def _row_fingerprint(connection: sqlite3.Connection) -> str:
    rows = [
        tuple(row)
        for row in connection.execute(
            "SELECT * FROM research_candidates ORDER BY id"
        ).fetchall()
    ]
    payload = json.dumps(rows, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _insert_ranking_fixture(connection: sqlite3.Connection) -> None:
    rows = (
        ("dense-high-9", 9.0, 0.9, 0.9, 0.1, "high", "candidate"),
        ("open-low-10", 10.0, 0.1, 0.1, 0.1, "low", "active"),
        ("tie-low", 8.0, 0.1, 0.1, 0.1, "low", "candidate"),
        ("tie-high", 8.0, 0.9, 0.9, 0.9, "high", "active"),
        ("tie-normal", 8.0, 0.5, 0.5, 0.5, "normal", "candidate"),
        ("same-dense", 7.0, 0.9, 0.9, 0.9, "normal", "candidate"),
        ("same-open", 7.0, 0.1, 0.1, 0.1, "normal", "active"),
    )
    for position, row in enumerate(rows, start=1):
        title, score, area, task, method, confidence, status = row
        connection.execute(
            """
            INSERT INTO research_candidates(
                scope, title, llm_score, area_red_ocean, task_red_ocean,
                method_red_ocean, confidence_level, status, lineage_key,
                evidence_signature
            ) VALUES ('topic:1', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                score,
                area,
                task,
                method,
                confidence,
                status,
                f"lineage-{position}",
                f"evidence-{position}",
            ),
        )
    connection.commit()


def test_fresh_database_applies_077_with_exact_score_first_index(
    tmp_path: Path,
) -> None:
    _migration_077_sql()
    database_path = tmp_path / "fresh.db"

    DATABASE_CLASS(database_path).migrate()

    connection = _connect(database_path)
    try:
        columns = connection.execute(
            "PRAGMA table_info(research_candidates)"
        ).fetchall()
        marker_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 77"
        ).fetchone()[0]
        assert tuple(str(row["name"]) for row in columns) == EXPECTED_COLUMNS
        assert marker_count == 1
        assert _index_sql(connection) == EXPECTED_INDEX_SQL
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_pre077_database_rebuilds_stale_index_without_row_mutation(
    tmp_path: Path,
) -> None:
    _migration_077_sql()
    database_path = tmp_path / "upgrade.db"
    _apply_migrations(database_path, through=76)

    connection = _connect(database_path)
    try:
        _insert_ranking_fixture(connection)
        before = _row_fingerprint(connection)
        assert _index_sql(connection) != EXPECTED_INDEX_SQL
    finally:
        connection.close()

    DATABASE_CLASS(database_path).migrate()

    connection = _connect(database_path)
    try:
        assert _row_fingerprint(connection) == before
        assert _index_sql(connection) == EXPECTED_INDEX_SQL
        ordered = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT title FROM research_candidates
                WHERE scope = 'topic:1'
                  AND status IN ('candidate', 'active')
                ORDER BY llm_score DESC,
                    CASE confidence_level
                        WHEN 'high' THEN 0
                        WHEN 'normal' THEN 1
                        WHEN 'low' THEN 2
                        ELSE 3
                    END,
                    id ASC
                """
            ).fetchall()
        ]
        assert ordered == [
            "open-low-10",
            "dense-high-9",
            "tie-high",
            "tie-normal",
            "tie-low",
            "same-dense",
            "same-open",
        ]
    finally:
        connection.close()


def test_077_is_three_run_idempotent(tmp_path: Path) -> None:
    _migration_077_sql()
    database_path = tmp_path / "idempotent.db"
    database = DATABASE_CLASS(database_path)
    database.migrate()

    connection = _connect(database_path)
    try:
        _insert_ranking_fixture(connection)
        expected_index = _index_sql(connection)
        expected_rows = _row_fingerprint(connection)
    finally:
        connection.close()

    database.migrate()
    database.migrate()

    connection = _connect(database_path)
    try:
        assert _index_sql(connection) == expected_index == EXPECTED_INDEX_SQL
        assert _row_fingerprint(connection) == expected_rows
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 77"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_077_failure_is_atomic_and_backup_restore_is_exact(tmp_path: Path) -> None:
    migration_sql = _migration_077_sql()
    database_path = tmp_path / "rollback.db"
    backup_path = tmp_path / "rollback.pre077.db"
    _apply_migrations(database_path, through=76)

    connection = _connect(database_path)
    try:
        _insert_ranking_fixture(connection)
        old_index = _index_sql(connection)
        old_rows = _row_fingerprint(connection)
        old_ledger = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()
    shutil.copy2(database_path, backup_path)
    backup_checksum = hashlib.sha256(backup_path.read_bytes()).hexdigest()

    broken_sql = migration_sql.replace(
        "ON research_candidates(", "ON missing_research_candidates(", 1
    )
    assert broken_sql != migration_sql
    connection = _connect(database_path)
    with pytest.raises(sqlite3.OperationalError):
        connection.executescript(broken_sql)
    connection.close()

    connection = _connect(database_path)
    try:
        assert _index_sql(connection) == old_index
        assert _row_fingerprint(connection) == old_rows
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 77"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    DATABASE_CLASS(database_path).migrate()
    connection = _connect(database_path)
    try:
        assert _index_sql(connection) == EXPECTED_INDEX_SQL
    finally:
        connection.close()

    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == backup_checksum
    shutil.copy2(backup_path, database_path)
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == backup_checksum
    connection = _connect(database_path)
    try:
        restored_ledger = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert _index_sql(connection) == old_index
        assert _row_fingerprint(connection) == old_rows
        assert [tuple(row) for row in restored_ledger] == [
            tuple(row) for row in old_ledger
        ]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_077_contract_uses_explicit_transaction_and_no_density_lane() -> None:
    sql = _migration_077_sql()
    normalized = _normalize_sql(sql).upper()

    assert "BEGIN IMMEDIATE" in normalized
    assert "DROP INDEX IF EXISTS IDX_RC_SCOPE_SORT" in normalized
    assert "CREATE INDEX IDX_RC_SCOPE_SORT" in normalized
    assert "COMMIT" in normalized
    assert "LLM_SCORE DESC" in normalized
    assert "CASE CONFIDENCE_LEVEL" in normalized
    assert "AREA_RED_OCEAN" not in normalized
    assert "TASK_RED_OCEAN" not in normalized
    assert "METHOD_RED_OCEAN" not in normalized
