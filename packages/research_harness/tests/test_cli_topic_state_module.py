"""CLI shape tests for `rh topic state`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from research_harness.cli import main
from research_harness.storage.db import Database


def test_topic_state_missing_topic(runner, tmp_path):
    result = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "state",
            "--topic",
            "999",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "rh.topic_state.v1"
    assert payload["next_action"]["code"] == "missing_topic"


def test_topic_state_existing_topic(runner, tmp_path):
    db_path = Path(os.environ["RESEARCH_HARNESS_DB_PATH"])
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("cli-topic-state", "cli-topic-state"),
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "state",
            "--topic",
            "cli-topic-state",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic"]["name"] == "cli-topic-state"
    assert payload["next_action"]["code"] == "not_started"

    text = runner.invoke(
        main,
        [
            "topic",
            "state",
            "--topic",
            "cli-topic-state",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert text.exit_code == 0, text.output
    assert "next [not_started]" in text.output
