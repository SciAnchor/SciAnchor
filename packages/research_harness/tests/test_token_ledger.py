"""Tests for token_accounting: ledger recording, budget enforcement, WAL mode."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_harness.storage.db import MIGRATIONS_DIR, Database


def _migrate_through(db_path: Path, version: int) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "applied_at TEXT DEFAULT (datetime('now')))"
        )
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            migration_version = int(migration.name.split("_", 1)[0])
            if migration_version > version:
                continue
            try:
                connection.executescript(migration.read_text(encoding="utf-8"))
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
            connection.execute(
                "INSERT INTO schema_migrations(version,name) VALUES (?,?)",
                (migration_version, migration.stem),
            )
            connection.commit()
    finally:
        connection.close()


@pytest.fixture()
def ledger_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh DB with migrations applied; patches env so token_accounting uses it."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.migrate()
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))

    conn = db.connect()
    conn.execute(
        """
        INSERT INTO agent_registry (nickname, provider, provider_family, model, api_key_env, role_prefs)
        VALUES ('test-agent', 'anthropic', 'anthropic', 'claude-opus-4-7', 'KEY', '{}')
        """
    )
    conn.commit()
    agent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    return db_path, agent_id


def test_record_usage_inserts_row(ledger_db):
    db_path, agent_id = ledger_db
    from research_harness.token_accounting import record_usage

    cost = record_usage(
        "claude-opus-4-7",
        prompt_tokens=1000,
        completion_tokens=500,
        agent_id=agent_id,
        stage="analyze",
        role="generator",
    )

    assert cost > 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM token_ledger").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["agent_id"] == agent_id
    assert rows[0]["prompt_tokens"] == 1000
    assert rows[0]["completion_tokens"] == 500
    assert rows[0]["cost_usd"] == pytest.approx(cost)


def test_record_usage_idempotency(ledger_db):
    db_path, agent_id = ledger_db
    from research_harness.token_accounting import record_usage

    record_usage(
        "claude-opus-4-7",
        prompt_tokens=100,
        completion_tokens=50,
        agent_id=agent_id,
        idempotency_key="dedup-key-1",
    )
    record_usage(
        "claude-opus-4-7",
        prompt_tokens=100,
        completion_tokens=50,
        agent_id=agent_id,
        idempotency_key="dedup-key-1",
    )

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM token_ledger").fetchone()[0]
    conn.close()

    assert count == 1


def test_provider_accounting_migrations_preserve_existing_ledger_row(tmp_path):
    db_path = tmp_path / "provider-receipt-upgrade.db"
    _migrate_through(db_path, 78)
    connection = sqlite3.connect(db_path)
    try:
        agent_id = connection.execute(
            "INSERT INTO agent_registry "
            "(nickname,provider,provider_family,model,api_key_env,role_prefs) "
            "VALUES ('pre-079','synthetic','synthetic','model-v1','AUTO','{}')"
        ).lastrowid
        connection.execute("INSERT INTO topics(name) VALUES ('pre-079 topic')")
        topic_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute(
            "INSERT INTO token_ledger "
            "(agent_id,topic_id,stage,primitive,role,prompt_tokens,"
            "completion_tokens,cost_usd,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                agent_id,
                topic_id,
                "write",
                "section_revise",
                "provider",
                13,
                5,
                0.23,
                "pre-079-attempt",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    Database(db_path).migrate()

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(token_ledger)")
        }
        assert {
            "provider_receipt_sha256",
            "prompt_tokens_known",
            "completion_tokens_known",
        } <= columns
        row = connection.execute(
            "SELECT role,provider_receipt_sha256,prompt_tokens_known,"
            "completion_tokens_known,cost_usd,idempotency_key "
            "FROM token_ledger WHERE idempotency_key='pre-079-attempt'"
        ).fetchone()
        assert dict(row) == {
            "role": "provider",
            "provider_receipt_sha256": None,
            "prompt_tokens_known": 1,
            "completion_tokens_known": 1,
            "cost_usd": pytest.approx(0.23),
            "idempotency_key": "pre-079-attempt",
        }
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=79"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=80"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_provider_usage_distinguishes_unknown_tokens_from_known_zero(ledger_db):
    db_path, _ = ledger_db
    from research_harness.token_accounting import record_provider_usage_once

    db = Database(db_path)
    for suffix, tokens in (("unknown", None), ("known-zero", 0)):
        receipt = SimpleNamespace(
            cost_usd=0.23,
            prompt_tokens=tokens,
            completion_tokens=tokens,
            receipt_sha256=("a" if tokens is None else "b") * 64,
            provider="synthetic",
            model="accounted-v1",
        )
        record_provider_usage_once(
            db=db,
            receipt=receipt,
            topic_id=None,
            stage="write",
            primitive="section_revise",
            idempotency_key=f"tokens-{suffix}",
        )

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = {
            row["idempotency_key"]: dict(row)
            for row in connection.execute(
                "SELECT idempotency_key,prompt_tokens,completion_tokens,"
                "prompt_tokens_known,completion_tokens_known FROM token_ledger "
                "WHERE idempotency_key LIKE 'tokens-%'"
            )
        }
    finally:
        connection.close()
    assert rows == {
        "tokens-unknown": {
            "idempotency_key": "tokens-unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_tokens_known": 0,
            "completion_tokens_known": 0,
        },
        "tokens-known-zero": {
            "idempotency_key": "tokens-known-zero",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_tokens_known": 1,
            "completion_tokens_known": 1,
        },
    }


def test_provider_usage_records_prompt_and_completion_known_flags_independently(
    ledger_db,
):
    db_path, _ = ledger_db
    from research_harness.token_accounting import record_provider_usage_once

    db = Database(db_path)
    for suffix, prompt_tokens, completion_tokens in (
        ("prompt-unknown", None, 0),
        ("completion-unknown", 0, None),
    ):
        record_provider_usage_once(
            db=db,
            receipt=SimpleNamespace(
                cost_usd=0.23,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                receipt_sha256=suffix.encode().hex().ljust(64, "0"),
                provider="synthetic",
                model="accounted-v1",
            ),
            topic_id=None,
            stage="write",
            primitive="section_revise",
            idempotency_key=f"mixed-{suffix}",
        )

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = {
            row["idempotency_key"]: dict(row)
            for row in connection.execute(
                "SELECT idempotency_key,prompt_tokens,completion_tokens,"
                "prompt_tokens_known,completion_tokens_known FROM token_ledger "
                "WHERE idempotency_key LIKE 'mixed-%'"
            )
        }
    finally:
        connection.close()
    assert rows == {
        "mixed-prompt-unknown": {
            "idempotency_key": "mixed-prompt-unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_tokens_known": 0,
            "completion_tokens_known": 1,
        },
        "mixed-completion-unknown": {
            "idempotency_key": "mixed-completion-unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_tokens_known": 1,
            "completion_tokens_known": 0,
        },
    }


def test_provider_usage_rejects_idempotency_conflict_only_in_known_flag(ledger_db):
    db_path, _ = ledger_db
    from research_harness.token_accounting import record_provider_usage_once

    db = Database(db_path)
    common = {
        "cost_usd": 0.23,
        "completion_tokens": 0,
        "receipt_sha256": "c" * 64,
        "provider": "synthetic",
        "model": "accounted-v1",
    }
    record_provider_usage_once(
        db=db,
        receipt=SimpleNamespace(prompt_tokens=None, **common),
        topic_id=None,
        stage="write",
        primitive="section_revise",
        idempotency_key="known-flag-conflict",
    )

    with pytest.raises(
        ValueError,
        match="idempotency key has conflicting accounting",
    ):
        record_provider_usage_once(
            db=db,
            receipt=SimpleNamespace(prompt_tokens=0, **common),
            topic_id=None,
            stage="write",
            primitive="section_revise",
            idempotency_key="known-flag-conflict",
        )


def test_budget_exceeded_on_zero_cap(ledger_db):
    db_path, agent_id = ledger_db
    from research_harness.token_accounting import BudgetExceeded, check_budget

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO budgets (scope, scope_id, monthly_cap_usd, hard_stop) VALUES ('global', NULL, 0.0, 1)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(BudgetExceeded) as exc_info:
        check_budget(estimated_cost=0.01)

    assert exc_info.value.scope == "global"
    assert exc_info.value.cap == 0.0


def test_budget_soft_cap_does_not_raise(ledger_db):
    db_path, agent_id = ledger_db
    from research_harness.token_accounting import check_budget

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO budgets (scope, scope_id, monthly_cap_usd, hard_stop) VALUES ('global', NULL, 0.0, 0)"
    )
    conn.commit()
    conn.close()

    check_budget(estimated_cost=100.0)


def test_wal_mode(ledger_db):
    db_path, _ = ledger_db
    conn = sqlite3.connect(str(db_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert mode == "wal"


def test_cost_usd_calculation():
    from research_harness.pricing.models import cost_usd

    cost = cost_usd("claude-opus-4-7", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == pytest.approx(15.0)

    cost2 = cost_usd("claude-opus-4-7", prompt_tokens=0, completion_tokens=1_000_000)
    assert cost2 == pytest.approx(75.0)

    cost3 = cost_usd(
        "unknown-model", prompt_tokens=1_000_000, completion_tokens=1_000_000
    )
    assert cost3 == pytest.approx(3.0 + 15.0)
