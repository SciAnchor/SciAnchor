from __future__ import annotations

import tomllib
from pathlib import Path


def test_core_storage_is_canonical_and_public_path_reexports() -> None:
    from research_harness._core.storage.db import Database, MIGRATIONS_DIR
    from research_harness._core.storage.models import Paper
    from research_harness.storage.db import Database as PublicDatabase
    from research_harness.storage.models import Paper as PublicPaper

    assert PublicDatabase is Database
    assert PublicPaper is Paper
    assert MIGRATIONS_DIR.name == "migrations"
    assert (MIGRATIONS_DIR / "001_initial_schema.sql").is_file()


def test_research_harness_wheel_includes_migrations_as_package_data() -> None:
    package_root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))

    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    force_include = wheel["force-include"]

    assert wheel["packages"] == ["research_harness"]
    assert force_include["migrations"] == "research_harness/migrations"


def test_migration_replay_applies_all_available_migrations(tmp_path) -> None:
    from research_harness._core.storage.db import Database, MIGRATIONS_DIR

    expected_versions = {
        int(path.name.split("_", 1)[0]) for path in MIGRATIONS_DIR.glob("*.sql")
    }
    assert expected_versions

    db = Database(tmp_path / "migration-replay.db")
    db.migrate()

    conn = db.connect()
    try:
        applied_versions = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
    finally:
        conn.close()

    assert applied_versions == expected_versions


def test_duplicate_column_migration_does_not_duplicate_marker(
    tmp_path, monkeypatch
) -> None:
    from research_harness._core.storage import db as db_module

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_initial.sql").write_text(
        """
        CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT);
        """,
        encoding="utf-8",
    )
    (migrations_dir / "002_duplicate_column.sql").write_text(
        """
        ALTER TABLE sample ADD COLUMN name TEXT;
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations_dir)

    database = db_module.Database(tmp_path / "duplicate-column.db")
    database.migrate()
    database.migrate()

    conn = database.connect()
    try:
        applied_versions = [
            row["version"]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
    finally:
        conn.close()

    assert applied_versions == [1, 2]
