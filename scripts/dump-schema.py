#!/usr/bin/env python3
"""Generate storage/SCHEMA.md from Research Harness SQLite migrations."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "packages" / "research_harness" / "migrations"
SCHEMA_PATH = (
    ROOT
    / "packages"
    / "research_harness"
    / "research_harness"
    / "storage"
    / "SCHEMA.md"
)


@dataclass(frozen=True)
class Migration:
    name: str
    path: Path
    sql: str


def _load_migrations() -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        migrations.append(Migration(name=path.stem, path=path, sql=path.read_text()))
    return migrations


def _split_columns(body: str) -> list[str]:
    columns: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            value = "".join(current).strip()
            if value:
                columns.append(value)
            current = []
            continue
        current.append(char)
    value = "".join(current).strip()
    if value:
        columns.append(value)
    return columns


def _clean_identifier(value: str) -> str:
    return value.strip().strip('"`[]')


def _migration_sources(
    migrations: list[Migration],
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    table_sources: dict[str, str] = {}
    column_sources: dict[tuple[str, str], str] = {}
    create_re = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"[\"`\[]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)[\"`\]]?\s*"
        r"\((?P<body>.*?)\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    add_column_re = re.compile(
        r"ALTER\s+TABLE\s+[\"`\[]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)[\"`\]]?"
        r"\s+ADD\s+COLUMN\s+[\"`\[]?(?P<column>[A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE,
    )
    skip_prefixes = {
        "CONSTRAINT",
        "PRIMARY",
        "FOREIGN",
        "UNIQUE",
        "CHECK",
        "KEY",
    }

    for migration in migrations:
        for match in create_re.finditer(migration.sql):
            table = _clean_identifier(match.group("table"))
            table_sources.setdefault(table, migration.name)
            for entry in _split_columns(match.group("body")):
                first = entry.split(None, 1)[0] if entry.split(None, 1) else ""
                if not first or _clean_identifier(first).upper() in skip_prefixes:
                    continue
                column = _clean_identifier(first)
                column_sources.setdefault((table, column), migration.name)
        for match in add_column_re.finditer(migration.sql):
            table = _clean_identifier(match.group("table"))
            column = _clean_identifier(match.group("column"))
            table_sources.setdefault(table, migration.name)
            column_sources.setdefault((table, column), migration.name)

    table_sources.setdefault("schema_migrations", "storage.db runtime")
    column_sources.setdefault(("schema_migrations", "version"), "storage.db runtime")
    column_sources.setdefault(("schema_migrations", "name"), "storage.db runtime")
    column_sources.setdefault(("schema_migrations", "applied_at"), "storage.db runtime")
    return table_sources, column_sources


def _migrate_temp_db(
    migrations: list[Migration],
) -> tuple[sqlite3.Connection, tempfile.TemporaryDirectory[str]]:
    tmp = tempfile.TemporaryDirectory(prefix="rh-schema-")
    db_path = Path(tmp.name) / "schema.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    for migration in migrations:
        version = int(migration.name.split("_", 1)[0])
        try:
            conn.executescript(migration.sql)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, migration.name),
        )
        conn.commit()
    return conn, tmp


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _indexes(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA index_list({table})").fetchall()


def _foreign_keys(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _md(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if text == "":
        return ""
    return text.replace("|", "\\|").replace("\n", " ")


def render_schema() -> str:
    migrations = _load_migrations()
    table_sources, column_sources = _migration_sources(migrations)
    conn, tmp = _migrate_temp_db(migrations)
    try:
        tables = _table_names(conn)
        latest = migrations[-1].name if migrations else "none"
        lines: list[str] = [
            "# Research Harness SQLite Schema",
            "",
            "Generated by `scripts/dump-schema.py` from the migration history.",
            "Do not edit this file by hand; run `python scripts/dump-schema.py --write`.",
            "",
            f"- Migration directory: `packages/research_harness/migrations/`",
            f"- Migration files: {len(migrations)}",
            f"- Latest migration: `{latest}`",
            f"- Tables: {len(tables)}",
            "",
            "## Tables",
            "",
            "| Table | Columns | Primary key columns | Source migration |",
            "|---|---:|---|---|",
        ]
        table_columns: dict[str, list[sqlite3.Row]] = {}
        for table in tables:
            columns = _columns(conn, table)
            table_columns[table] = columns
            primary = [str(col["name"]) for col in columns if int(col["pk"])]
            lines.append(
                f"| `{table}` | {len(columns)} | `{', '.join(primary)}` | `{_md(table_sources.get(table, 'unknown'))}` |"
            )

        lines.extend(["", "## Table Details", ""])
        for table in tables:
            lines.extend(
                [
                    f"### `{table}`",
                    "",
                    f"Source migration: `{_md(table_sources.get(table, 'unknown'))}`",
                    "",
                    "| Column | Type | Nullable | Default | PK order | Source migration |",
                    "|---|---|---|---|---:|---|",
                ]
            )
            for col in table_columns[table]:
                name = str(col["name"])
                nullable = "no" if int(col["notnull"]) or int(col["pk"]) else "yes"
                source = column_sources.get((table, name), table_sources.get(table, "unknown"))
                lines.append(
                    "| "
                    f"`{_md(name)}` | `{_md(col['type'])}` | {nullable} | "
                    f"`{_md(col['dflt_value'])}` | {int(col['pk'])} | `{_md(source)}` |"
                )

            fks = _foreign_keys(conn, table)
            if fks:
                lines.extend(
                    [
                        "",
                        "Foreign keys:",
                        "",
                        "| From | References | On update | On delete |",
                        "|---|---|---|---|",
                    ]
                )
                for fk in fks:
                    lines.append(
                        f"| `{_md(fk['from'])}` | `{_md(fk['table'])}({_md(fk['to'])})` | "
                        f"{_md(fk['on_update'])} | {_md(fk['on_delete'])} |"
                    )

            indexes = _indexes(conn, table)
            if indexes:
                lines.extend(
                    [
                        "",
                        "Indexes:",
                        "",
                        "| Name | Unique | Origin | Partial |",
                        "|---|---:|---|---:|",
                    ]
                )
                for index in indexes:
                    lines.append(
                        f"| `{_md(index['name'])}` | {int(index['unique'])} | "
                        f"{_md(index['origin'])} | {int(index['partial'])} |"
                    )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
    finally:
        conn.close()
        tmp.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write storage/SCHEMA.md")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if storage/SCHEMA.md differs from generated output",
    )
    args = parser.parse_args(argv)

    rendered = render_schema()
    if args.write:
        SCHEMA_PATH.write_text(rendered, encoding="utf-8")
        print(f"Wrote {SCHEMA_PATH.relative_to(ROOT)}")
        return 0
    if args.check:
        try:
            existing = SCHEMA_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"FAIL: {SCHEMA_PATH.relative_to(ROOT)} is missing", file=sys.stderr)
            return 1
        if existing != rendered:
            print(
                f"FAIL: {SCHEMA_PATH.relative_to(ROOT)} is stale; run scripts/dump-schema.py --write",
                file=sys.stderr,
            )
            return 1
        print("Schema documentation is up to date")
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
